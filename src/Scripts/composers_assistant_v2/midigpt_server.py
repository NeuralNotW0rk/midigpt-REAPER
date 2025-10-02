#!/usr/bin/env python3
"""
MidiGPT Server - Patched to fix measures_to_generate parameter passing
Critical fix: Pass measures_to_generate to convert_midi_to_ca_format_with_timing
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


def convert_midi_to_ca_format_with_timing(midi_path, project_measures, actual_extra_id=0, measures_to_generate=None):
    """
    TIMING PRESERVATION: Convert MIDI back to CA format with extra_id grouping
    Returns format like: ;<extra_id_191>N:60;d:480;w:240;N:64;d:480
    Only returns notes for measures that were actually generated (not context)
    """
    if DEBUG:
        print(f"\n=== TIMING PRESERVATION CONVERSION ===")
        print(f"  MIDI file: {midi_path}")
        print(f"  Target project measures: {project_measures}")
        print(f"  Measures to generate: {measures_to_generate}")
    
    if measures_to_generate is None:
        measures_to_generate = set(project_measures)
    
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
            print("  No notes found - returning empty for extra_id")
        return f";<extra_id_{actual_extra_id}>"
    
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
    
    # Group notes by mapped project measure, but ONLY keep notes from measures_to_generate
    notes_by_measure = {}
    for note in all_notes:
        project_measure = measure_map.get(note['ai_measure'], project_measures[0])
        
        # CRITICAL: Only include notes from measures that were actually generated
        if project_measure in measures_to_generate:
            if project_measure not in notes_by_measure:
                notes_by_measure[project_measure] = []
            notes_by_measure[project_measure].append(note)
    
    if DEBUG:
        print(f"  Notes in generated measures only: {sum(len(notes) for notes in notes_by_measure.values())} notes")
    
    # Build CA format string with extra_id grouping
    ca_parts = []
    
    # Use the actual extra_id from the input so REAPER can match it
    if notes_by_measure:
        ca_parts.append(f"<extra_id_{actual_extra_id}>")
        
        # CRITICAL: We need to track timing relative to the FIRST note in the generated content
        # REAPER expects times relative to the extra_id marker, not absolute MIDI times
        all_generated_notes = []
        for measure in sorted(notes_by_measure.keys()):
            all_generated_notes.extend(notes_by_measure[measure])
        
        # Sort by start time
        all_generated_notes.sort(key=lambda n: n['start'])
        
        if all_generated_notes:
            # Start timing from the first generated note
            first_note_start = all_generated_notes[0]['start']
            last_time = first_note_start
            
            for note in all_generated_notes:
                # Calculate wait from last event
                wait = note['start'] - last_time
                
                if wait > 0:
                    ca_parts.append(f"w:{int(wait)}")
                
                ca_parts.append(f"N:{note['pitch']}")
                ca_parts.append(f"d:{int(note['duration'])}")
                
                last_time = note['start']
    
    result = ';'.join([''] + ca_parts) if ca_parts else f";<extra_id_{actual_extra_id}>"
    
    if DEBUG:
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
    
    # Check for extra_id tokens and extract actual_extra_id early
    extra_ids = re.findall(r'<extra_id_(\d+)>', s)
    actual_extra_id = int(extra_ids[0]) if extra_ids else 0
    
    if DEBUG:
        print(f"\nMidiGPT call_nn_infill called")
        print(f"  Input length: {len(s)} chars")
        print(f"  Sampling: {use_sampling}, Temp: {temperature}")
        print(f"  Measures: {start_measure} to {end_measure}")
        print(f"  Raw input string:")
        print(f"  {s}")
        print()
        
        if extra_ids:
            print(f"  Found extra IDs: {extra_ids}")
    
    if not MIDIGPT_AVAILABLE:
        print("MidiGPT not available, returning fallback")
        return f";<extra_id_{actual_extra_id}>N:60;d:240;w:240"
    
    # TIMING PRESERVATION: Determine project measure range
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
    
    # CRITICAL: Store which measures need generation
    measures_to_generate = set()
    if actual_empty_measures:
        measures_to_generate = set(actual_empty_measures)
        if DEBUG:
            print(f"  Will generate for empty measures: {sorted(measures_to_generate)}")
    else:
        # Fallback: use all project measures if detection failed
        measures_to_generate = set(project_measures)
    
    try:
        # Convert S dictionary to MidiSongByMeasure object
        midi_song = pre.midisongbymeasure_from_save_dict(S)
        
        if DEBUG:
            print(f"  Converted S to MidiSongByMeasure: {len(midi_song.tracks)} tracks")
        
        # Create temporary MIDI file for MidiGPT
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            temp_midi_path = tmp.name
        
        # Export to MIDI file
        midi_song.dump(filename=temp_midi_path)
        
        if DEBUG:
            print(f"  Created temp MIDI: {temp_midi_path}")
        
        # Load with MidiGPT - use ExpressiveEncoder
        encoder = midigpt.ExpressiveEncoder()
        
        # Convert MIDI to JSON
        protobuf_json = encoder.midi_to_json(temp_midi_path)
        midi_json_input = json.loads(protobuf_json)
        
        if DEBUG:
            print(f"  Converted to MidiGPT JSON: {len(protobuf_json)} chars")
        
        # Determine if this is infill or continuation
        has_extra_ids = '<extra_id_' in s
        
        if DEBUG:
            print(f"  Has extra_ids: {has_extra_ids}")
            if has_extra_ids:
                print(f"  Measures needing generation: {sorted(measures_to_generate)}")
        
        # Build status configuration (matching pythoninferencetest.py)
        status = {
            "tracks": []
        }
        
        # Configure selected bars for generation
        num_measures = len(project_measures)
        selected_bars = [measure_idx in measures_to_generate for measure_idx in project_measures]
        
        for track_idx in range(len(midi_song.tracks)):
            track_config = {
                "track_id": track_idx,
                "track_type": "STANDARD_TRACK",
                "selected_bars": selected_bars,
                "ignore": False,
                "temperature": temperature,
                "polyphony_hard_limit": 10
            }
            # Only add autoregressive if needed for infill with all bars selected
            if has_extra_ids and all(selected_bars):
                track_config["autoregressive"] = True
            status["tracks"].append(track_config)
        
        if DEBUG:
            print(f"  Selected bars: {selected_bars}")
            print(f"  Shuffle: {not has_extra_ids}")
        
        # Build generation parameters - ONLY valid HyperParam fields
        # Both HyperParam and StatusTrack have temperature fields
        params = {
            'tracks_per_step': 1,
            'bars_per_step': 1,
            'model_dim': 4,
            'percentage': 100,
            'batch_size': 1,
            'temperature': temperature,  # HyperParam also has temperature field
            'max_steps': 200,
            'shuffle': not has_extra_ids,
            'verbose': DEBUG,
            'ckpt': CHECKPOINT_PATH
        }
        
        # Convert to JSON strings
        piece_str = json.dumps(midi_json_input)
        status_str = json.dumps(status)
        params_str = json.dumps(params)
        
        if DEBUG:
            print(f"  Status JSON: {status_str[:500]}")
            print(f"  Params JSON: {params_str}")
            print(f"  Calling MidiGPT generation...")
        
        # Create callback manager
        callbacks = midigpt.CallbackManager()
        
        # Call MidiGPT generation
        max_attempts = 1
        midi_results = midigpt.sample_multi_step(piece_str, status_str, params_str, max_attempts, callbacks)
        
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
        
        # CRITICAL FIX: Pass measures_to_generate parameter
        ca_result = convert_midi_to_ca_format_with_timing(
            result_midi_path,
            project_measures,
            actual_extra_id=actual_extra_id,
            measures_to_generate=measures_to_generate  # ADDED THIS PARAMETER
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
        
        return f";<extra_id_{actual_extra_id}>N:60;d:240;w:240"


def start_server():
    print("="*60)
    print("MidiGPT Server Starting")
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