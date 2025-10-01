#!/usr/bin/env python3
"""
MidiGPT Server with correct 9-parameter signature
Matches rpr_midigpt_functions.py exactly
"""

import os
import sys
from xmlrpc.server import SimpleXMLRPCServer
import tempfile
import json

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
    """Find MidiGPT checkpoint file"""
    possible_paths = [
        "MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        os.path.expanduser("~/Documents/GitHub/midigpt-REAPER/MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt")
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return os.path.abspath(path)
    print("WARNING: No checkpoint found, generation may fail")
    return possible_paths[0]  # Return default, will fail but with clear error

CHECKPOINT_PATH = find_checkpoint()
print(f"Using checkpoint: {CHECKPOINT_PATH}")

# Caching
LAST_CALL = None
LAST_OUTPUTS = set()


def convert_midi_to_ca_format(midi_path):
    """Convert a MIDI file back to CA format string (simple version without timing preservation)"""
    if DEBUG:
        print(f"  Converting MIDI to CA format: {midi_path}")
    
    midi_file = mido.MidiFile(midi_path)
    
    # Extract notes from all tracks
    all_notes = []
    ticks_per_beat = midi_file.ticks_per_beat
    
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
                    duration = current_time - note_info['start']
                    all_notes.append({
                        'pitch': msg.note,
                        'start': note_info['start'],
                        'duration': duration,
                        'velocity': note_info['velocity']
                    })
    
    if not all_notes:
        if DEBUG:
            print("  WARNING: No notes found in MIDI file")
        return "<extra_id_0>N:60;d:240;w:240"
    
    # Sort by start time
    all_notes.sort(key=lambda n: n['start'])
    
    # Convert to CA format
    ca_parts = []
    last_time = 0
    measure_length = ticks_per_beat * 4
    current_measure = 0
    
    for note in all_notes:
        note_measure = note['start'] // measure_length
        
        if note_measure != current_measure:
            current_measure = note_measure
            ca_parts.append(f"M:{current_measure}")
        
        wait = note['start'] - last_time
        
        if wait > 0:
            ca_parts.append(f"w:{int(wait)}")
        ca_parts.append(f"N:{note['pitch']}")
        ca_parts.append(f"d:{int(note['duration'])}")
        
        last_time = note['start']
    
    result = ';'.join([''] + ca_parts)
    
    if DEBUG:
        print(f"  Converted {len(all_notes)} notes to CA format: {len(result)} chars")
    
    return result


def convert_midi_to_ca_format_with_timing(midi_path, project_measures, actual_extra_id=0):
    """
    TIMING PRESERVATION: Convert MIDI back to CA format with extra_id grouping
    Returns format like: ;<extra_id_191>N:60;d:480;w:240;N:64;d:480
    Uses the actual extra_id from the input so REAPER can match it
    """
    if DEBUG:
        print(f"\n=== TIMING PRESERVATION CONVERSION ===")
        print(f"  MIDI file: {midi_path}")
        print(f"  Target project measures: {project_measures}")
    
    midi_file = mido.MidiFile(midi_path)
    ticks_per_beat = midi_file.ticks_per_beat
    measure_length = ticks_per_beat * 4  # 4/4 time
    
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
                    duration = current_time - note_info['start']
                    
                    # Calculate AI-generated measure number
                    ai_measure = current_time // measure_length
                    
                    all_notes.append({
                        'pitch': msg.note,
                        'start': current_time,
                        'duration': duration,
                        'velocity': note_info['velocity'],
                        'ai_measure': int(ai_measure)
                    })
    
    if not all_notes:
        if DEBUG:
            print("  No notes found - returning empty for extra_id_0")
        return ";<extra_id_0>"
    
    if DEBUG:
        print(f"  Extracted {len(all_notes)} notes")
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
    
    # Group notes by mapped project measure
    notes_by_measure = {}
    for note in all_notes:
        project_measure = measure_map.get(note['ai_measure'], project_measures[0])
        if project_measure not in notes_by_measure:
            notes_by_measure[project_measure] = []
        notes_by_measure[project_measure].append(note)
    
    # Build CA format string with extra_id grouping
    # Format: ;<extra_id_X>N:pitch;d:duration;w:wait;N:pitch;d:duration;...
    ca_parts = []
    
    # Use the actual extra_id from the input (e.g., 191) so REAPER can match it
    # Group all generated notes under this single extra_id
    if notes_by_measure:
        ca_parts.append(f"<extra_id_{actual_extra_id}>")
        
        # Combine all measures' notes into one instruction list
        all_measure_notes = []
        for measure in sorted(notes_by_measure.keys()):
            all_measure_notes.extend(sorted(notes_by_measure[measure], key=lambda n: n['start']))
        
        if all_measure_notes:
            last_time = 0  # Start from beginning
            
            for note in all_measure_notes:
                # Calculate wait time from last event
                wait = note['start'] - last_time
                
                if wait > 0:
                    ca_parts.append(f"w:{int(wait)}")
                
                ca_parts.append(f"N:{note['pitch']}")
                ca_parts.append(f"d:{int(note['duration'])}")
                
                last_time = note['start']
    
    result = ';'.join([''] + ca_parts)
    
    if DEBUG:
        print(f"  Mapped to measures: {sorted(notes_by_measure.keys())}")
        print(f"  Final CA: {len(result)} chars")
        print(f"  Preview: {result[:200]}")
        print("=== END TIMING PRESERVATION ===\n")
    
    return result


def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0,
                   has_fully_masked_inst=False, temperature=1.0, start_measure=None, end_measure=None):
    """
    Main inference function with TIMING PRESERVATION
    Maps AI-generated content back to original project measure range
    """
    global LAST_CALL, LAST_OUTPUTS
    
    if DEBUG:
        print(f"\nMidiGPT call_nn_infill called")
        print(f"  Input length: {len(s)} chars")
        print(f"  Sampling: {use_sampling}, Temp: {temperature}")
        print(f"  Measures: {start_measure} to {end_measure}")
        print(f"  Raw input string:")
        print(f"  {s}")
        print()
        
        # Check for extra_id tokens
        import re
        extra_ids = re.findall(r'<extra_id_(\d+)>', s)
        if extra_ids:
            print(f"  Found extra IDs: {extra_ids}")
        
        # Store the actual extra_id number for use in the response
        actual_extra_id = int(extra_ids[0]) if extra_ids else 0
    
    if not MIDIGPT_AVAILABLE:
        print("MidiGPT not available, returning fallback")
        return "<extra_id_0>N:60;d:240;w:240;N:64;d:240;w:240"
    
    # TIMING PRESERVATION: Use explicit measure range from REAPER
    # The start_measure and end_measure parameters define the selection to be modified
    # The s parameter may include additional context measures
    if start_measure is not None and end_measure is not None:
        project_measures = list(range(start_measure, end_measure + 1))
    else:
        # Fallback: extract from s parameter
        measure_numbers = []
        for segment in s.split(';'):
            if segment.startswith('M:'):
                try:
                    measure_numbers.append(int(segment[2:]))
                except ValueError:
                    pass
        project_measures = sorted(set(measure_numbers)) if measure_numbers else [0, 1, 2, 3]
    
    if DEBUG:
        print(f"  Target selection: measures {project_measures[0]} to {project_measures[-1]}")
        print(f"  S parameter type: {type(S)}")
        if isinstance(S, dict):
            print(f"  S keys: {list(S.keys())[:10]}")
            if 'tracks' in S and 'MEs' in S:
                print(f"  S has {len(S.get('tracks', []))} track(s)")
                print(f"  S MEs (measure endpoints): {S.get('MEs', [])}")
                if S['tracks']:
                    track0 = S['tracks'][0]
                    if isinstance(track0, list):
                        print(f"  Track 0 has {len(track0)} measures")
                        for i, measure_data in enumerate(track0[:8]):
                            note_ons = measure_data[0] if measure_data else ''
                            note_count = len(note_ons.split()) if note_ons else 0
                            print(f"    S Measure {i}: {note_count} notes")
    
    # CRITICAL FIX: Use S parameter to find which measures are actually empty
    # The M: markers in the s string are NOT the same as S measure indices
    actual_empty_measures = []
    if isinstance(S, dict) and 'tracks' in S and S['tracks']:
        track0 = S['tracks'][0]
        if isinstance(track0, list):
            for measure_idx in project_measures:
                if measure_idx < len(track0):
                    measure_data = track0[measure_idx]
                    note_ons = measure_data[0] if measure_data else ''
                    if not note_ons or note_ons.strip() == '':
                        actual_empty_measures.append(measure_idx)
    
    if DEBUG:
        print(f"  Empty measures in selection: {actual_empty_measures}")
    
    # Use actual empty measures instead of parsing the s string
    if actual_empty_measures:
        measures_to_generate = set(actual_empty_measures)
        if DEBUG:
            print(f"  Will generate for empty measures: {sorted(measures_to_generate)}")
    
    try:
        # Convert S dictionary back to MidiSongByMeasure object
        midi_song = pre.midisongbymeasure_from_save_dict(S)
        
        if DEBUG:
            print(f"  Converted S to MidiSongByMeasure: {len(midi_song.tracks)} tracks")
        
        # Create temporary MIDI file for MidiGPT
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            temp_midi_path = tmp.name
        
        # Export to MIDI file using correct method
        midi_song.dump(filename=temp_midi_path)
        
        if DEBUG:
            print(f"  Created temp MIDI: {temp_midi_path}")
        
        # Load with MidiGPT - use ExpressiveEncoder
        encoder = midigpt.ExpressiveEncoder()
        
        # Convert MIDI to JSON using correct API
        protobuf_json = encoder.midi_to_json(temp_midi_path)
        midi_json_input = json.loads(protobuf_json)
        
        if DEBUG:
            print(f"  Converted to MidiGPT JSON: {len(protobuf_json)} chars")
        
        # Determine if this is infill or continuation
        import re
        has_extra_ids = '<extra_id_' in s
        
        # Use actual empty measures from S parameter analysis
        if not actual_empty_measures:
            # Fallback: parse from string if S parameter analysis failed
            segments = s.split(';')
            current_measure = None
            
            if DEBUG:
                print(f"  Fallback: Parsing segments to find extra_id locations:")
            
            for i, segment in enumerate(segments):
                if segment.startswith('M:'):
                    try:
                        current_measure = int(segment[2:])
                        if DEBUG and i < 20:
                            print(f"    Segment {i}: Set current_measure to {current_measure}")
                    except ValueError:
                        pass
                elif '<extra_id_' in segment:
                    if current_measure is not None and current_measure in project_measures:
                        measures_to_generate.add(current_measure)
                        if DEBUG:
                            print(f"    Segment {i}: Found extra_id in measure {current_measure}")
        
        if DEBUG:
            print(f"  Has extra_ids: {has_extra_ids}")
            if has_extra_ids:
                print(f"  Measures needing generation: {sorted(measures_to_generate)}")
        
        # Build status configuration (matching pythoninferencetest.py)
        status = {
            "tracks": []
        }
        
        # For each track in the piece, configure generation
        num_tracks = len(midi_json_input.get('tracks', []))
        
        # Determine selected_bars based on which measures need generation
        # selected_bars should match the number of bars in the MIDI (typically 4)
        num_bars = 4
        if has_extra_ids and measures_to_generate:
            # Only select bars that need generation
            # Map project measures to MIDI bar indices
            selected_bars = []
            for bar_idx in range(num_bars):
                # Check if this bar index corresponds to a measure that needs generation
                if bar_idx < len(project_measures):
                    project_measure = project_measures[bar_idx]
                    selected_bars.append(project_measure in measures_to_generate)
                else:
                    selected_bars.append(False)
        else:
            # No infill - generate for all bars
            selected_bars = [True] * num_bars
        
        if DEBUG:
            print(f"  Selected bars: {selected_bars}")
        
        for track_idx in range(max(1, num_tracks)):
            track_config = {
                "track_id": track_idx,
                "temperature": temperature,
                "instrument": "acoustic_grand_piano",
                "density": 10,
                "track_type": 10,
                "ignore": False,
                "selected_bars": selected_bars,
                "min_polyphony_q": "POLYPHONY_ANY",
                "max_polyphony_q": "POLYPHONY_ANY",
                "autoregressive": all(selected_bars),  # CRITICAL: Only True if ALL bars selected
                "polyphony_hard_limit": 9
            }
            status["tracks"].append(track_config)
        
        # Parameter configuration (matching pythoninferencetest.py)
        # CRITICAL: shuffle must be False when not all bars are selected
        use_shuffle = all(selected_bars) if has_extra_ids else True
        
        param = {
            "tracks_per_step": 1,
            "bars_per_step": 1,
            "model_dim": 4,
            "percentage": 100,
            "batch_size": 1,
            "temperature": temperature,
            "max_steps": 200,
            "polyphony_hard_limit": 6,
            "shuffle": use_shuffle,
            "verbose": False,
            "ckpt": CHECKPOINT_PATH,
            "sampling_seed": -1,
            "mask_top_k": 0
        }
        
        if DEBUG:
            print(f"  Shuffle: {use_shuffle}")
        
        # Call MidiGPT generation (exact pattern from pythoninferencetest.py)
        if DEBUG:
            print(f"  Calling MidiGPT generation...")
        
        piece = json.dumps(midi_json_input)
        status_str = json.dumps(status)
        param_str = json.dumps(param)
        callbacks = midigpt.CallbackManager()
        max_attempts = 3
        
        midi_str = midigpt.sample_multi_step(piece, status_str, param_str, max_attempts, callbacks)
        
        if not midi_str or len(midi_str) == 0:
            raise Exception("MidiGPT returned no results")
        
        # Parse result (first element is the result string)
        result_json_str = midi_str[0]
        
        if DEBUG:
            print(f"  Generated: {len(result_json_str)} chars")
        
        # Convert result back to MIDI file
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            result_midi_path = tmp.name
        
        encoder.json_to_midi(result_json_str, result_midi_path)
        
        if DEBUG:
            print(f"  Saved result MIDI: {result_midi_path}")
        
        # TIMING PRESERVATION: Convert MIDI back to CA format with proper measure mapping
        result_str = convert_midi_to_ca_format_with_timing(result_midi_path, project_measures)
        
        if DEBUG:
            print(f"  Result CA format: {len(result_str)} chars")
        
        # Cleanup temp files
        try:
            os.unlink(temp_midi_path)
            os.unlink(result_midi_path)
        except:
            pass
        
        return result_str
        
    except Exception as e:
        if DEBUG:
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()
        
        # Return fallback
        return "<extra_id_0>N:60;d:240;w:240;N:64;d:240;w:240"


def start_server():
    """Start the XML-RPC server"""
    print("="*60)
    print("MidiGPT Server Starting")
    print("="*60)
    print(f"Port: {PORT}")
    print(f"MidiGPT Available: {MIDIGPT_AVAILABLE}")
    print(f"Debug Mode: {DEBUG}")
    print("="*60)
    
    try:
        server = SimpleXMLRPCServer(('127.0.0.1', PORT), logRequests=DEBUG)
        server.register_function(call_nn_infill, 'call_nn_infill')
        
        print(f"\nServer ready and listening on port {PORT}")
        print("Press Ctrl+C to stop\n")
        
        server.serve_forever()
        
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Server error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    start_server()