#!/usr/bin/env python3
"""
MidiGPT Server - Patched with proper timing conversion
ONLY CHANGE: Fixed convert_midi_to_ca_format_with_timing to read actual MIDI timing
instead of assuming ticks_per_beat=480 and time_signature=4/4
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

try:
    import midigpt
    import preprocessing_functions as pre
    import mido
    MIDIGPT_AVAILABLE = True
    print("MidiGPT library loaded successfully")
except ImportError as e:
    MIDIGPT_AVAILABLE = False
    print(f"MidiGPT not available: {e}")

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


def convert_midi_to_ca_format_with_timing(midi_path, project_measures, actual_extra_id=0, 
                                          measures_to_generate=None, input_ticks_per_beat=None, 
                                          input_time_signature=None):
    """
    TIMING PRESERVATION: Convert MIDI back to CA format with extra_id grouping
    
    PATCHED: Now reads actual ticks_per_beat and time_signature from MIDI file
    instead of hardcoding ticks_per_beat=480 and assuming 4/4 time.
    
    ENHANCED: Can optionally use input_ticks_per_beat and input_time_signature
    if the output MIDI timing differs from input (e.g., MidiGPT changes resolution)
    
    Returns format like: ;<extra_id_191>N:60;d:480;w:240;N:64;d:480
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
        return f";<extra_id_{actual_extra_id}>"
    
    if DEBUG:
        print(f"  Extracted {len(all_notes)} total notes")
        ai_measures = sorted(set(n['ai_measure'] for n in all_notes))
        print(f"  AI measures: {ai_measures}")
        # Debug: Show first few notes with their timings
        print(f"  First 5 notes:")
        for i, note in enumerate(sorted(all_notes, key=lambda n: n['start'])[:5]):
            print(f"    Note {i}: pitch={note['pitch']}, start={note['start']}, duration={note['duration']}, measure={note['ai_measure']}")
    
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
        return f";<extra_id_{actual_extra_id}>"
    
    if DEBUG:
        print(f"  Notes in generated measures only: {sum(len(notes) for notes in notes_by_measure.values())} notes")
        # Debug: Show distribution across measures
        for measure in sorted(notes_by_measure.keys()):
            print(f"    Measure {measure}: {len(notes_by_measure[measure])} notes")
    
    # TIMING RESET: Get all notes from generated measures and reset timing to first note
    all_generated_notes = []
    for measure in sorted(notes_by_measure.keys()):
        all_generated_notes.extend(notes_by_measure[measure])
    
    all_generated_notes.sort(key=lambda n: n['start'])
    
    # Reset timing anchor to first generated note
    first_note_start = all_generated_notes[0]['start']
    last_time = first_note_start
    
    # Build CA format string with relative timing from first note
    ca_parts = [f"<extra_id_{actual_extra_id}>"]
    
    if DEBUG:
        print(f"  Building CA format from {len(all_generated_notes)} notes")
        print(f"  First note starts at tick: {first_note_start}")
    
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
        print(f"  Preview: {result[:150]}...")
        # Show structure breakdown
        note_count = result.count('N:')
        wait_count = result.count('w:')
        duration_count = result.count('d:')
        print(f"  Structure: {note_count} notes, {wait_count} waits, {duration_count} durations")
    
    return result


def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0, start_measure=None, end_measure=None):
    """
    Main function called by REAPER via XMLRPC
    Signature matches rpr_midigpt_functions.py (9 parameters)
    """
    global LAST_CALL, LAST_OUTPUTS
    
    if DEBUG:
        print(f"\n{'='*60}")
        print('MIDIGPT CALL_NN_INFILL RECEIVED')
        print(f"Input length: {len(s)} chars")
        print(f"Temperature: {temperature}")
        if start_measure is not None and end_measure is not None:
            print(f"Selection bounds: measures {start_measure}-{end_measure}")
    
    try:
        if not MIDIGPT_AVAILABLE:
            if DEBUG:
                print("MidiGPT not available - returning fallback")
            return "<extra_id_0>N:60;d:240;w:240"
        
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
            print(f"  Found extra_ids: {extra_ids}")
            print(f"  Project measures: {project_measures}")
        
        # Determine which measures to generate
        if start_measure is not None and end_measure is not None:
            measures_to_generate = set(range(start_measure, end_measure + 1))
        else:
            measures_to_generate = {actual_extra_id % len(project_measures)} if extra_ids else set(project_measures)
        
        if DEBUG:
            print(f"  Measures to generate: {measures_to_generate}")
        
        # Create temporary MIDI file from S
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            temp_midi_path = tmp.name
        
        # Convert S to MIDI using dump method
        S.dump(filename=temp_midi_path)
        
        # CRITICAL: Capture the input MIDI timing parameters for later conversion
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
            print(f"  Created input MIDI: {temp_midi_path}")
            print(f"  Input MIDI timing: {input_ticks_per_beat} ticks/beat, {input_time_sig_num}/{input_time_sig_denom} time sig")
        
        # Load encoder
        encoder = midigpt.ExpressiveEncoder()
        
        # Convert MIDI to JSON
        piece_json_str = encoder.midi_to_json(temp_midi_path)
        piece_json = json.loads(piece_json_str)
        
        # Setup generation parameters (from pythoninferencetest.py)
        status = {
            'tracks': [{
                'track_id': 0,
                'temperature': temperature,
                'instrument': 'acoustic_grand_piano',
                'density': 10,
                'track_type': 10,
                'ignore': False,
                'selected_bars': [True if i in measures_to_generate else False for i in project_measures],
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY',
                'autoregressive': False,  # MUST be False for selective bars (infill mode)
                'polyphony_hard_limit': 9
            }]
        }
        
        params = {
            'tracks_per_step': 1,
            'bars_per_step': 1,
            'model_dim': 4,
            'percentage': 100,
            'batch_size': 1,
            'temperature': temperature,
            'max_steps': 200,
            'polyphony_hard_limit': 6,
            'shuffle': True,
            'verbose': False,
            'ckpt': CHECKPOINT_PATH,
            'sampling_seed': -1,
            'mask_top_k': 0
        }
        
        if DEBUG:
            print(f"  Running MidiGPT generation...")
        
        # Convert to JSON strings
        status_str = json.dumps(status)
        params_str = json.dumps(params)
        
        # Run MidiGPT generation
        callbacks = midigpt.CallbackManager()
        midi_results = midigpt.sample_multi_step(piece_json_str, status_str, params_str, 3, callbacks)
        
        if not midi_results or len(midi_results) == 0:
            if DEBUG:
                print("  MidiGPT returned empty result")
            return f";<extra_id_{actual_extra_id}>N:60;d:240;w:240"
        
        # Parse first result
        midi_result_str = midi_results[0]
        result_json = json.loads(midi_result_str)
        
        if DEBUG:
            print(f"  Generated: {len(midi_result_str)} chars")
        
        # Convert result back to MIDI file
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            result_midi_path = tmp.name
        
        # Use encoder.json_to_midi to convert back
        encoder.json_to_midi(midi_result_str, result_midi_path)
        
        if DEBUG:
            print(f"  Saved result MIDI: {result_midi_path}")
        
        # Convert MIDI to CA format with proper timing
        # Pass the input timing parameters we captured earlier
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
            print(f"  Result CA format: {len(ca_result)} chars")
        
        return ca_result
        
    except Exception as e:
        if DEBUG:
            print(f'Error in MidiGPT processing: {e}')
            import traceback
            traceback.print_exc()
        
        return f";<extra_id_{actual_extra_id if 'actual_extra_id' in locals() else 0}>N:60;d:240;w:240"


def start_server():
    print("="*60)
    print("MidiGPT Server Starting (Patched with Timing Fixes)")
    print("="*60)
    print(f"Port: {PORT}")
    print(f"MidiGPT Available: {MIDIGPT_AVAILABLE}")
    print(f"Debug Mode: {DEBUG}")
    print("="*60)
    print()
    
    server = SimpleXMLRPCServer(('127.0.0.1', PORT), logRequests=DEBUG, allow_none=True)
    server.register_function(call_nn_infill, 'call_nn_infill')
    
    print(f"Server ready and listening on port {PORT}")
    print("Press Ctrl+C to stop")
    print()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")


if __name__ == "__main__":
    start_server()