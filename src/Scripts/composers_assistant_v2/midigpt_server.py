#!/usr/bin/env python3
"""
MidiGPT Server - Complete with streamlined parameter support
- Reads parameters from REAPER FX (Global and Track Options)
- Applies them to MidiGPT generation
- Includes timing conversion fixes
- ARCHITECTURE: Uses S structure and selection bounds, not CA string parsing
  (M: markers in CA strings represent LOUDNESS levels, not measure indices)

CRITICAL CA FORMAT UNDERSTANDING:
-------------------------------
The CA (Composer's Assistant) string format encodes musical data for neural networks.
Key markers in CA strings:

  M:X - Loudness level (0-7), NOT measure index
  B:X - Tempo level (0-7)
  L:X - Measure length in clicks
  I:X - Instrument index
  N:X - Note pitch
  d:X - Note duration
  w:X - Wait time
  <extra_id_X> - Mask token indicating generation position

DO NOT parse M: markers as measure indices. The authoritative sources are:
  1. S structure (MidiSongByMeasure) - contains actual measure content
  2. start_measure/end_measure parameters - define time selection from REAPER
  3. extra_id presence - indicates REAPER selected items for generation

The CA string is an encoding artifact for the neural network, not an interface format.
"""

import os
import sys
from xmlrpc.server import SimpleXMLRPCServer
import tempfile
import json
import re

# Add MIDI-GPT python_lib to path
midi_gpt_path = os.path.join(os.path.dirname(__file__), "../../../MIDI-GPT/python_lib")
if os.path.exists(midi_gpt_path):
    sys.path.insert(0, os.path.abspath(midi_gpt_path))

# Add composers_assistant path for preprocessing
ca_path = os.path.join(os.path.dirname(__file__), "src/Scripts/composers_assistant_v2")
if os.path.exists(ca_path):
    sys.path.insert(0, os.path.abspath(ca_path))

try:
    import midigpt
    import preprocessing_functions as pre
    import mido
    MIDIGPT_AVAILABLE = True
    print("MidiGPT library loaded successfully")
except ImportError as e:
    MIDIGPT_AVAILABLE = False
    print(f"MidiGPT not available: {e}")

# Try to import midigpt functions for parameter reading
try:
    import rpr_midigpt_functions as midigpt_fn
    PARAM_FUNCTIONS_AVAILABLE = True
    print("Parameter reading functions loaded")
except ImportError as e:
    PARAM_FUNCTIONS_AVAILABLE = False
    print(f"Parameter functions not available (will use defaults): {e}")

# Configuration
DEBUG = True
PORT = 3456

# Find checkpoint dynamically
def find_checkpoint():
    possible_paths = [
        "MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        os.path.expanduser("~/Documents/GitHub/midigpt-REAPER/MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt")
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return os.path.abspath(path)
    print("WARNING: No checkpoint found")
    return possible_paths[0]

CHECKPOINT_PATH = find_checkpoint()
print(f"Using checkpoint: {CHECKPOINT_PATH}")

# Caching
LAST_CALL = None
LAST_OUTPUTS = set()


def detect_measures_to_generate(S, start_measure, end_measure, extra_ids_present, debug=False):
    """
    Detect which measures need generation based on S structure and selection.
    
    Architecture:
    - M: markers in CA strings represent LOUDNESS (0-7), not measure indices
    - S structure is the authoritative source for measure content
    - start_measure/end_measure define the time range from REAPER
    - extra_ids indicate REAPER has selected items, but we must check S to find empty measures
    
    Returns:
        set: Measure indices that need generation
    """
    measures_to_generate = set()
    
    if start_measure is None or end_measure is None:
        return measures_to_generate
    
    # Always detect empty measures within the selection
    # The presence of extra_ids just confirms REAPER has items selected
    if debug:
        print(f"  Strategy: detect empty measures within selection {start_measure}-{end_measure}")
    
    for measure_idx in range(start_measure, end_measure + 1):
        is_empty = True
        for track in S.tracks:
            if measure_idx < len(track.tracks_by_measure):
                measure_track = track.tracks_by_measure[measure_idx]
                if hasattr(measure_track, 'note_ons') and measure_track.note_ons:
                    is_empty = False
                    break
        if is_empty:
            measures_to_generate.add(measure_idx)
            if debug:
                print(f"    Measure {measure_idx}: empty (will generate)")
        elif debug:
            print(f"    Measure {measure_idx}: has content (skip)")
    
    return measures_to_generate


def apply_track_options_to_status(status_json, track_options_by_idx, global_options):
    """
    Apply track-specific options from REAPER FX to MidiGPT status configuration.
    
    Args:
        status_json: The status dict with tracks list
        track_options_by_idx: Dict mapping track index to MidigptTrackOptionsObj
        global_options: MidigptGlobalOptionsObj with global settings
    """
    
    for track_idx, track_config in enumerate(status_json.get('tracks', [])):
        # Check if this track has specific options
        if track_idx in track_options_by_idx:
            options = track_options_by_idx[track_idx]
            
            # Apply temperature (use track-specific if set, otherwise global)
            if options.track_temperature >= 0:
                track_config['temperature'] = options.track_temperature
            else:
                track_config['temperature'] = global_options.temperature
            
            # Apply instrument
            track_config['instrument'] = options.instrument
            
            # Apply density
            track_config['density'] = options.density
            
            # Apply track type
            track_config['track_type'] = options.track_type
            
            # Apply polyphony constraints
            track_config['min_polyphony_q'] = options.min_polyphony_q
            track_config['max_polyphony_q'] = options.max_polyphony_q
            
            # Apply polyphony hard limit (use track-specific if set, otherwise global)
            if options.polyphony_hard_limit > 0:
                track_config['polyphony_hard_limit'] = options.polyphony_hard_limit
            else:
                track_config['polyphony_hard_limit'] = global_options.polyphony_hard_limit
        else:
            # Use global defaults for tracks without specific options
            track_config['temperature'] = global_options.temperature
            track_config['instrument'] = 'acoustic_grand_piano'
            track_config['density'] = 10
            track_config['track_type'] = 'STANDARD_TRACK'
            track_config['min_polyphony_q'] = 'POLYPHONY_ANY'
            track_config['max_polyphony_q'] = 'POLYPHONY_ANY'
            track_config['polyphony_hard_limit'] = global_options.polyphony_hard_limit


def convert_midi_to_ca_format_with_timing(midi_path, project_measures, actual_extra_id=0, 
                                          measures_to_generate=None, input_ticks_per_beat=None, 
                                          input_time_signature=None):
    """
    TIMING PRESERVATION: Convert MIDI back to CA format with extra_id grouping
    
    Reads actual ticks_per_beat and time_signature from MIDI file
    Can optionally use input_ticks_per_beat and input_time_signature
    if the output MIDI timing differs from input (e.g., MidiGPT changes resolution)
    
    Returns format like: M:3;<extra_id_191>N:60;d:480;w:240;N:64;d:480
    Only returns notes for measures that were actually generated (not context)
    """
    if DEBUG:
        print(f"\n=== TIMING PRESERVATION CONVERSION ===")
        print(f"  MIDI file: {midi_path}")
        print(f"  Target project measures: {project_measures}")
        print(f"  Measures to generate: {measures_to_generate}")
        if input_ticks_per_beat:
            print(f"  Using input timing: {input_ticks_per_beat} ticks/beat, {input_time_signature}")
    
    if measures_to_generate is None:
        measures_to_generate = set(project_measures)
    
    # Read MIDI file and extract timing information
    midi_file = mido.MidiFile(midi_path)
    output_ticks_per_beat = midi_file.ticks_per_beat
    
    # Read actual time signature from MIDI file
    output_time_sig_numerator = 4
    output_time_sig_denominator = 4
    for track in midi_file.tracks:
        for msg in track:
            if msg.type == 'time_signature':
                output_time_sig_numerator = msg.numerator
                output_time_sig_denominator = msg.denominator
                break
        if output_time_sig_numerator != 4 or output_time_sig_denominator != 4:
            break
    
    # Use input timing if provided, otherwise use output timing
    if input_ticks_per_beat is not None and input_time_signature is not None:
        ticks_per_beat = input_ticks_per_beat
        time_sig_numerator, time_sig_denominator = input_time_signature
        timing_source = "input (original project)"
    else:
        ticks_per_beat = output_ticks_per_beat
        time_sig_numerator = output_time_sig_numerator
        time_sig_denominator = output_time_sig_denominator
        timing_source = "output MIDI"
    
    # Calculate timing conversion ratio if output differs from input
    timing_ratio = 1.0
    if input_ticks_per_beat is not None and output_ticks_per_beat != input_ticks_per_beat:
        timing_ratio = input_ticks_per_beat / output_ticks_per_beat
        if DEBUG:
            print(f"  Timing mismatch detected!")
            print(f"    Input: {input_ticks_per_beat} ticks/beat")
            print(f"    Output: {output_ticks_per_beat} ticks/beat")
            print(f"    Conversion ratio: {timing_ratio}")
    
    # Calculate beats per measure based on actual time signature
    beats_per_measure = time_sig_numerator * (4.0 / time_sig_denominator)
    measure_length = int(ticks_per_beat * beats_per_measure)
    
    if DEBUG:
        print(f"  Using timing from: {timing_source}")
        print(f"  MIDI timing metadata:")
        print(f"    ticks_per_beat: {ticks_per_beat}")
        print(f"    time_signature: {time_sig_numerator}/{time_sig_denominator}")
        print(f"    beats_per_measure: {beats_per_measure}")
        print(f"    measure_length (ticks): {measure_length}")
    
    # Extract all notes from all tracks
    all_notes = []
    for track_idx, track in enumerate(midi_file.tracks):
        current_time = 0
        active_notes = {}
        
        for msg in track:
            current_time += msg.time
            
            if msg.type == 'note_on' and msg.velocity > 0:
                active_notes[msg.note] = {
                    'start': current_time,
                    'velocity': msg.velocity
                }
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active_notes:
                    note_info = active_notes.pop(msg.note)
                    
                    # Apply timing ratio if needed (convert output ticks to input ticks)
                    actual_start = int(note_info['start'] * timing_ratio)
                    duration = int((current_time - note_info['start']) * timing_ratio)
                    
                    # Calculate AI-generated measure number using actual measure_length
                    ai_measure = actual_start // measure_length
                    
                    all_notes.append({
                        'pitch': msg.note,
                        'start': actual_start,
                        'duration': duration,
                        'velocity': note_info['velocity'],
                        'ai_measure': int(ai_measure)
                    })
    
    if not all_notes:
        if DEBUG:
            print("  No notes found - returning empty for extra_id")
        target_measure = min(measures_to_generate) if measures_to_generate else 0
        return f";M:{target_measure};<extra_id_{actual_extra_id}>"
    
    if DEBUG:
        print(f"  Extracted {len(all_notes)} total notes")
        ai_measures = sorted(set(n['ai_measure'] for n in all_notes))
        print(f"  AI measures: {ai_measures}")
    
    # MAP AI MEASURES TO PROJECT MEASURES
    ai_measures_sorted = sorted(set(n['ai_measure'] for n in all_notes))
    
    if len(project_measures) >= len(ai_measures_sorted):
        measure_map = {ai_m: project_measures[i] for i, ai_m in enumerate(ai_measures_sorted)}
    else:
        measure_map = {}
        for i, ai_m in enumerate(ai_measures_sorted):
            project_idx = int((i / len(ai_measures_sorted)) * len(project_measures))
            project_idx = min(project_idx, len(project_measures) - 1)
            measure_map[ai_m] = project_measures[project_idx]
    
    if DEBUG:
        print(f"  Measure mapping: {measure_map}")
    
    # Group notes by mapped project measure, ONLY keep notes from measures_to_generate
    notes_by_measure = {}
    for note in all_notes:
        project_measure = measure_map.get(note['ai_measure'], project_measures[0])
        if project_measure in measures_to_generate:
            if project_measure not in notes_by_measure:
                notes_by_measure[project_measure] = []
            notes_by_measure[project_measure].append(note)
    
    if not notes_by_measure:
        if DEBUG:
            print("  No notes in target measures after filtering")
        target_measure = min(measures_to_generate) if measures_to_generate else 0
        return f";M:{target_measure};<extra_id_{actual_extra_id}>"
    
    if DEBUG:
        print(f"  Notes in generated measures: {sum(len(notes) for notes in notes_by_measure.values())} notes")
    
    # TIMING RESET: Get all notes from generated measures and reset timing to first note
    all_generated_notes = []
    for measure in sorted(notes_by_measure.keys()):
        all_generated_notes.extend(notes_by_measure[measure])
    
    all_generated_notes.sort(key=lambda n: n['start'])
    
    # Reset timing anchor to first generated note
    first_note_start = all_generated_notes[0]['start']
    last_time = first_note_start
    
    # Build CA format string with MEASURE MARKER, then extra_id, then relative timing
    target_measure = min(measures_to_generate) if measures_to_generate else 0
    ca_parts = [f"M:{target_measure}", f"<extra_id_{actual_extra_id}>"]
    
    if DEBUG:
        print(f"  Building CA format from {len(all_generated_notes)} notes at measure {target_measure}")
    
    for note in all_generated_notes:
        wait = note['start'] - last_time
        if wait > 0:
            ca_parts.append(f"w:{int(wait)}")
        
        ca_parts.append(f"N:{note['pitch']}")
        ca_parts.append(f"d:{int(note['duration'])}")
        
        last_time = note['start']
    
    result = ';'.join(ca_parts)
    
    if DEBUG:
        print(f"  Final CA: {len(result)} chars")
        note_count = result.count('N:')
        print(f"  Structure: {note_count} notes at M:{target_measure}")
    
    return result


def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0, start_measure=None, end_measure=None):
    """
    Main function called by REAPER via XMLRPC
    Now with parameter support from REAPER FX
    """
    global LAST_CALL, LAST_OUTPUTS
    
    # Validate temperature - MidiGPT requires [0.5, 2.0]
    if temperature < 0.5:
        if DEBUG:
            print(f"Warning: Temperature {temperature} below minimum 0.5, clamping to 0.5")
        temperature = 0.5
    elif temperature > 2.0:
        if DEBUG:
            print(f"Warning: Temperature {temperature} above maximum 2.0, clamping to 2.0")
        temperature = 2.0
    
    if DEBUG:
        print(f"\n{'='*60}")
        print('MIDIGPT CALL_NN_INFILL RECEIVED')
        print(f"Input length: {len(s)} chars")
        print(f"Temperature (validated): {temperature}")
        if start_measure is not None and end_measure is not None:
            print(f"Selection bounds: measures {start_measure}-{end_measure}")
    
    try:
        if not MIDIGPT_AVAILABLE:
            if DEBUG:
                print("MidiGPT not available - returning fallback")
            return "<extra_id_0>N:60;d:240;w:240"
        
        # Read parameters from REAPER FX (if available)
        if PARAM_FUNCTIONS_AVAILABLE:
            try:
                global_options = midigpt_fn.get_midigpt_global_options()
                track_options = midigpt_fn.get_midigpt_track_options_by_track_idx()
                
                if DEBUG:
                    print(f"\nGlobal Options:")
                    print(f"  Temperature: {global_options.temperature}")
                    print(f"  Model Dim: {global_options.model_dim}")
                    print(f"  Max Steps: {global_options.max_steps}")
                    print(f"  Shuffle: {global_options.shuffle}")
                    print(f"  Polyphony Hard Limit: {global_options.polyphony_hard_limit}")
                    
                    if track_options:
                        print(f"\nTrack Options ({len(track_options)} tracks):")
                        for idx, opts in track_options.items():
                            print(f"  Track {idx}:")
                            print(f"    Instrument: {opts.instrument}")
                            print(f"    Density: {opts.density}")
                            print(f"    Track Type: {opts.track_type}")
                            print(f"    Min Polyphony: {opts.min_polyphony_q}")
                            print(f"    Max Polyphony: {opts.max_polyphony_q}")
            except Exception as e:
                if DEBUG:
                    print(f"Could not read parameters from REAPER: {e}")
                # Create defaults
                temp_val = temperature
                
                class DefaultGlobalOptions:
                    pass
                
                global_options = DefaultGlobalOptions()
                global_options.temperature = temp_val
                global_options.tracks_per_step = 1
                global_options.bars_per_step = 1
                global_options.model_dim = 4
                global_options.percentage = 100
                global_options.max_steps = 200
                global_options.batch_size = 1
                global_options.shuffle = True
                global_options.sampling_seed = -1
                global_options.mask_top_k = 0
                global_options.polyphony_hard_limit = 6
                
                track_options = {}
        else:
            # Create defaults if parameter functions not available
            temp_val = temperature
            
            class DefaultGlobalOptions:
                pass
            
            global_options = DefaultGlobalOptions()
            global_options.temperature = temp_val
            global_options.tracks_per_step = 1
            global_options.bars_per_step = 1
            global_options.model_dim = 4
            global_options.percentage = 100
            global_options.max_steps = 200
            global_options.batch_size = 1
            global_options.shuffle = True
            global_options.sampling_seed = -1
            global_options.mask_top_k = 0
            global_options.polyphony_hard_limit = 6
            
            track_options = {}
        
        # Normalize request for caching
        s_normalized = re.sub(r'<extra_id_\d+>', '<extra_id_0>', s)
        if s_normalized == LAST_CALL or s_normalized in LAST_OUTPUTS:
            if DEBUG:
                print("Using cached result")
            return "<extra_id_0>N:60;d:240;w:240"
        
        # Extract extra_id tokens
        extra_id_pattern = r'<extra_id_(\d+)>'
        extra_ids = [int(m) for m in re.findall(extra_id_pattern, s)]
        
        if not extra_ids:
            extra_ids = [0]
        
        actual_extra_id = extra_ids[0]
        
        # Extract project measures from S parameter
        project_measures = list(range(8))  # Default
        if isinstance(S, dict):
            S = pre.midisongbymeasure_from_save_dict(S)
            project_measures = list(range(S.get_n_measures()))

        if DEBUG:
            print(f"\n=== S STRUCTURE DEBUG ===")
            for track_idx, track in enumerate(S.tracks):
                print(f"Track {track_idx}:")
                for measure_idx, m_track in enumerate(track.tracks_by_measure):
                    note_count = len(m_track.note_ons) if hasattr(m_track, 'note_ons') else 0
                    print(f"  Measure {measure_idx}: {note_count} notes")

        
        if DEBUG:
            print(f"\nData Processing:")
            print(f"  Found extra_ids: {extra_ids}")
            print(f"  Project measures: {project_measures}")
            print(f"  CA string (first 500 chars):")
            print(f"  {s[:500]}")
        
        # Detect which measures need generation using S structure
        measures_to_generate = detect_measures_to_generate(
            S, start_measure, end_measure, bool(extra_ids), debug=DEBUG
        )
        
        if DEBUG:
            print(f"  Selection bounds: measures {start_measure}-{end_measure}")
            print(f"  Detected measures to generate: {sorted(measures_to_generate) if measures_to_generate else 'none'}")
        
        # If we have extra_ids but found no empty measures,
        # this means selected non-empty items need replacement
        # Generate anyway - REAPER will map correctly via extra_id
        if not measures_to_generate and extra_ids:
            measures_to_generate = {end_measure}
            if DEBUG:
                print(f"  No empty measures, but extra_ids present - selected item replacement")
        
        # Create temporary MIDI file from S
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            temp_midi_path = tmp.name
        
        S.dump(filename=temp_midi_path)
        
        # Capture input MIDI timing
        input_midi = mido.MidiFile(temp_midi_path)
        input_ticks_per_beat = input_midi.ticks_per_beat
        input_time_sig_num = 4
        input_time_sig_denom = 4
        for track in input_midi.tracks:
            for msg in track:
                if msg.type == 'time_signature':
                    input_time_sig_num = msg.numerator
                    input_time_sig_denom = msg.denominator
                    break
            if input_time_sig_num != 4 or input_time_sig_denom != 4:
                break
        
        if DEBUG:
            print(f"\nMIDI Conversion:")
            print(f"  Input MIDI: {temp_midi_path}")
            print(f"  Timing: {input_ticks_per_beat} ticks/beat, {input_time_sig_num}/{input_time_sig_denom}")
        
        # Load encoder
        encoder = midigpt.ExpressiveEncoder()
        
        # Convert MIDI to JSON
        piece_json_str = encoder.midi_to_json(temp_midi_path)
        piece_json = json.loads(piece_json_str)
        
        # Determine number of tracks for status configuration
        num_tracks = len(piece_json.get('tracks', []))
        if num_tracks == 0:
            num_tracks = 1
        
        # Build status configuration with defaults
        status = {'tracks': []}
        
        for track_idx in range(num_tracks):
            track_config = {
                'track_id': track_idx,
                'temperature': global_options.temperature,
                'instrument': 'acoustic_grand_piano',
                'density': 10,
                'track_type': 'STANDARD_TRACK',
                'ignore': False,
                'selected_bars': [True if i in measures_to_generate else False for i in project_measures],
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY',
                'autoregressive': False,
                'polyphony_hard_limit': global_options.polyphony_hard_limit
            }
            status['tracks'].append(track_config)
        
        # Apply track-specific options if available
        if track_options:
            apply_track_options_to_status(status, track_options, global_options)
        
        # Build params from global options
        params = {
            'tracks_per_step': global_options.tracks_per_step,
            'bars_per_step': global_options.bars_per_step,
            'model_dim': global_options.model_dim,
            'percentage': global_options.percentage,
            'batch_size': global_options.batch_size,
            'temperature': global_options.temperature,
            'max_steps': global_options.max_steps,
            'polyphony_hard_limit': global_options.polyphony_hard_limit,
            'shuffle': global_options.shuffle,
            'verbose': False,
            'ckpt': CHECKPOINT_PATH,
            'sampling_seed': global_options.sampling_seed,
            'mask_top_k': global_options.mask_top_k
        }
        
        if DEBUG:
            print(f"\nMidiGPT Generation:")
            print(f"  Status: {num_tracks} tracks configured")
            print(f"  Project has {len(project_measures)} measures")
            print(f"  Measures to generate: {sorted(measures_to_generate)}")
            print(f"  Selected bars: {status['tracks'][0]['selected_bars']}")
            print(f"  Running generation...")
        
        # Convert to JSON strings
        status_str = json.dumps(status)
        params_str = json.dumps(params)
        
        # Run MidiGPT generation
        callbacks = midigpt.CallbackManager()
        midi_results = midigpt.sample_multi_step(piece_json_str, status_str, params_str, 3, callbacks)
        
        if not midi_results or len(midi_results) == 0:
            if DEBUG:
                print("  MidiGPT returned empty result")
            target_measure = min(measures_to_generate) if measures_to_generate else 0
            return f";M:{target_measure};<extra_id_{actual_extra_id}>N:60;d:240;w:240"
        
        # Parse first result
        midi_result_str = midi_results[0]
        result_json = json.loads(midi_result_str)
        
        if DEBUG:
            print(f"  Generated: {len(midi_result_str)} chars")
        
        # Convert result back to MIDI file
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            result_midi_path = tmp.name
        
        encoder.json_to_midi(midi_result_str, result_midi_path)
        
        if DEBUG:
            print(f"  Saved result MIDI: {result_midi_path}")
        
        # Convert MIDI to CA format with proper timing
        ca_result = convert_midi_to_ca_format_with_timing(
            result_midi_path,
            project_measures,
            actual_extra_id=actual_extra_id,
            measures_to_generate=measures_to_generate,
            input_ticks_per_beat=input_ticks_per_beat,
            input_time_signature=(input_time_sig_num, input_time_sig_denom)
        )
        
        # Clean up temp files
        try:
            os.unlink(temp_midi_path)
            os.unlink(result_midi_path)
        except:
            pass
        
        # Update cache
        LAST_CALL = s
        LAST_OUTPUTS.add(ca_result)
        
        if DEBUG:
            print(f"\nResult:")
            print(f"  CA format: {len(ca_result)} chars")
            print(f"  Preview: {ca_result[:100]}...")
        
        return ca_result
        
    except Exception as e:
        if DEBUG:
            print(f'\nError in MidiGPT processing: {e}')
            import traceback
            traceback.print_exc()
        
        # Use first generated measure or 0 as fallback
        target_measure = min(measures_to_generate) if 'measures_to_generate' in locals() and measures_to_generate else 0
        fallback_extra_id = actual_extra_id if 'actual_extra_id' in locals() else 0
        
        return f";M:{target_measure};<extra_id_{fallback_extra_id}>N:60;d:240;w:240"


def start_server():
    print("="*60)
    print("MidiGPT Server - With Parameter Support")
    print("="*60)
    print(f"Port: {PORT}")
    print(f"MidiGPT Available: {MIDIGPT_AVAILABLE}")
    print(f"Parameter Functions Available: {PARAM_FUNCTIONS_AVAILABLE}")
    print(f"Debug Mode: {DEBUG}")
    print("="*60)
    print()
    
    server = SimpleXMLRPCServer(('127.0.0.1', PORT), logRequests=DEBUG, allow_none=True)
    server.register_function(call_nn_infill, 'call_nn_infill')
    
    print(f"Server ready and listening on port {PORT}")
    if PARAM_FUNCTIONS_AVAILABLE:
        print("Will read parameters from REAPER FX:")
        print("  - midigpt Global Options (temperature, model_dim, etc.)")
        print("  - midigpt Track Options (instrument, density, polyphony)")
    else:
        print("Parameter functions not available - using defaults")
    print("\nPress Ctrl+C to stop")
    print()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")


if __name__ == "__main__":
    start_server()