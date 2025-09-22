#!/usr/bin/env python3

import json
import os
import sys
import tempfile
from xmlrpc.server import SimpleXMLRPCServer
import traceback

# Add MidiGPT path
midigpt_path = os.path.join(os.path.dirname(__file__), "../../../MIDI-GPT/python_lib")
if os.path.exists(midigpt_path):
    sys.path.insert(0, os.path.abspath(midigpt_path))

try:
    import mido
    print("✓ Mido library available")
except ImportError:
    print("✗ Mido library not available")
    sys.exit(1)

try:
    from rpr_midigpt_functions import *
    import preprocessing_functions as pf
    print("✓ Preprocessing functions loaded")
except ImportError as e:
    print(f"✗ Failed to load preprocessing functions: {e}")
    sys.exit(1)

try:
    import midigpt
    print("✓ MidiGPT library available")
    MIDIGPT_AVAILABLE = True
except ImportError as e:
    print(f"✗ MidiGPT library not available: {e}")
    MIDIGPT_AVAILABLE = False

try:
    from midisong import MidiSongByMeasure
    print("✓ MIDI library available")
    MIDI_AVAILABLE = True
except ImportError as e:
    print(f"✗ MIDI library not available: {e}")
    MIDI_AVAILABLE = False

def create_infill_midi_structure(input_string):
    """Create MIDI structure from CA string format with timing validation"""
    print(f"Processing input string: {len(input_string)} characters")
    print(f"Input preview: {input_string[:200]}...")
    
    # Check if this is an infill request (contains only <extra_id_XXX> tokens)
    import re
    extra_ids = re.findall(r'<extra_id_(\d+)>', input_string)
    has_notes = ';N:' in input_string  # Check for actual notes
    
    print(f"Found extra IDs: {extra_ids}")
    print(f"Contains notes: {has_notes}")
    
    # Extract existing notes from CA format if they exist
    notes = []
    if has_notes:
        # Parse CA format: ;M:0;N:60;d:240;w:240;
        segments = input_string.split(';')
        current_measure = 0
        current_note = None
        
        for segment in segments:
            if segment.startswith('M:'):
                current_measure = int(segment[2:])
            elif segment.startswith('N:'):
                pitch = int(segment[2:])
                current_note = {'measure': current_measure, 'pitch': pitch}
            elif segment.startswith('d:') and current_note:
                duration = int(segment[2:])
                current_note['duration'] = duration
                notes.append(current_note)
                current_note = None
    
    print(f"Extracted {len(notes)} context notes from input")
    
    # Create MIDI file with basic structure for infilling
    midi_file = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    
    # Add time signature and tempo
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))  # 120 BPM
    
    current_time = 0
    measure_length = 480 * 4  # 4 beats per measure at 480 ticks per beat
    
    if notes:
        # Use existing notes for context with proper timing
        notes.sort(key=lambda x: x['measure'])  # Sort by measure
        
        for note in notes:
            measure_start = note['measure'] * measure_length
            note_time = max(0, measure_start - current_time)  # Ensure non-negative
            
            # Add note on
            track.append(mido.Message('note_on', 
                                    channel=0, 
                                    note=note['pitch'], 
                                    velocity=64, 
                                    time=note_time))
            current_time += note_time
            
            # Add note off
            duration = note.get('duration', 480)
            track.append(mido.Message('note_off',
                                    channel=0,
                                    note=note['pitch'],
                                    velocity=0,
                                    time=duration))
            current_time += duration
    else:
        # Create minimal structure for pure infill (no existing notes)
        # Add a few seed notes to give MidiGPT something to work with
        seed_notes = [60, 64, 67]  # C major triad
        for i, pitch in enumerate(seed_notes):
            measure_start = i * measure_length
            note_time = max(0, measure_start - current_time)  # Ensure non-negative
            
            track.append(mido.Message('note_on', 
                                    channel=0, 
                                    note=pitch, 
                                    velocity=64, 
                                    time=note_time))
            current_time += note_time
            
            track.append(mido.Message('note_off',
                                    channel=0,
                                    note=pitch,
                                    velocity=0,
                                    time=480))  # Quarter note duration
            current_time += 480
    
    # Ensure minimum length for generation
    min_total = 4 * measure_length  # At least 4 measures
    if current_time < min_total:
        # Add silent time to reach minimum - ensure non-negative
        remaining_time = max(0, min_total - current_time)
        if remaining_time > 0:
            track.append(mido.Message('note_on', channel=0, note=60, velocity=0, 
                                    time=remaining_time))
            current_time += remaining_time
    
    print(f"MIDI structure created: {current_time} ticks, {len(notes) if notes else 'seed'} notes")
    
    # Save to temporary file
    temp_fd, temp_path = tempfile.mkstemp(suffix='.mid')
    os.close(temp_fd)
    
    try:
        midi_file.save(temp_path)
        print(f"Created infill MIDI structure: {temp_path} ({current_time} ticks)")
        return temp_path
    except Exception as e:
        os.unlink(temp_path)
        raise RuntimeError(f"Failed to save MIDI file: {e}")

def process_midigpt_for_reaper(s, S_dict):
    """Process MidiGPT generation with S parameter containing REAPER content"""
    if not MIDIGPT_AVAILABLE:
        raise RuntimeError("MidiGPT library not available")
    
    # Check if this is infill or continuation based on s parameter
    import re
    extra_ids = re.findall(r'<extra_id_(\d+)>', s)
    has_notes = ';N:' in s
    
    print(f"Found extra IDs: {extra_ids}")
    print(f"Contains notes in s: {has_notes}")
    
    # Convert S parameter to MIDI file - this contains the actual REAPER content
    try:
        # Convert S_dict to MidiSongByMeasure if needed
        if isinstance(S_dict, dict):
            print(f"Converting S dict with keys: {list(S_dict.keys())}")
            S = pf.midisongbymeasure_from_save_dict(S_dict)
        else:
            S = S_dict
            
        # Create MIDI file from S parameter (actual REAPER content)
        temp_midi_path = create_midi_from_s_parameter(S)
        print(f"✓ Created MIDI file from S parameter: {temp_midi_path}")
        
    except Exception as e:
        print(f"Failed to create MIDI from S parameter: {e}")
        print(f"S_dict type: {type(S_dict)}")
        if isinstance(S_dict, dict):
            print(f"S_dict keys: {list(S_dict.keys())}")
        # Fallback: create minimal MIDI structure from s parameter  
        temp_midi_path = create_infill_midi_structure(s)
    
    try:
        # Convert MIDI to MidiGPT protobuf JSON format using ExpressiveEncoder
        encoder = midigpt.ExpressiveEncoder()
        piece_json_str = encoder.midi_to_json(temp_midi_path)
        
        print(f"Generated piece JSON: {len(piece_json_str)} characters")
        
        # Parse to verify it's valid JSON
        piece_json = json.loads(piece_json_str)
        print(f"Piece structure: {list(piece_json.keys())}")
        
        # Determine generation strategy based on content
        if extra_ids and not has_notes:
            print("🎯 Infill generation (no existing notes)")
            selected_bars = [True, True, True, True]  # Generate in all bars
            autoregressive = True
        else:
            print("🎯 Continuation generation")
            selected_bars = [False, False, True, False]  # Generate only in specific bars
            autoregressive = False
        
        # Prepare status configuration
        status_data = {
            'tracks': [{
                'track_id': 0,
                'temperature': 0.7,
                'instrument': 'acoustic_grand_piano',
                'density': 10,
                'track_type': 10,
                'ignore': False,
                'selected_bars': selected_bars,
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY',
                'autoregressive': autoregressive,
                'polyphony_hard_limit': 9
            }]
        }
        
        # Find model checkpoint
        model_paths = [
            "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
            "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
            os.path.join(os.path.dirname(__file__), "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt")
        ]
        
        model_path = None
        for path in model_paths:
            if os.path.exists(path):
                model_path = os.path.abspath(path)
                break
        
        if not model_path:
            raise FileNotFoundError("Model checkpoint not found in expected locations")
        
        # Prepare parameters
        param_data = {
            'tracks_per_step': 1,
            'bars_per_step': 1,
            'model_dim': 4,
            'percentage': 100,
            'batch_size': 1,
            'temperature': 1.0,
            'max_steps': 200,
            'polyphony_hard_limit': 6,
            'shuffle': True,
            'verbose': False,
            'ckpt': model_path,
            'sampling_seed': -1,
            'mask_top_k': 0
        }
        
        print("Calling MidiGPT sample_multi_step...")
        
        # Convert to JSON strings as required by MidiGPT
        status_json_str = json.dumps(status_data)
        param_json_str = json.dumps(param_data)
        
        # Create callback manager
        callbacks = midigpt.CallbackManager()
        
        # Call MidiGPT with correct signature: (str, str, str, int, CallbackManager)
        result_tuple = midigpt.sample_multi_step(
            piece_json_str,     # arg0: piece JSON string (already a string)
            status_json_str,    # arg1: status JSON string  
            param_json_str,     # arg2: param JSON string
            3,                  # arg3: max_attempts (int)
            callbacks           # arg4: CallbackManager
        )
        
        # Extract result from tuple
        result_json_str = result_tuple[0]  # First element is the result string
        attempts_used = result_tuple[1]    # Second element is attempts count
        
        print(f"MidiGPT generation completed in {attempts_used} attempts")
        print(f"Result length: {len(result_json_str)} characters")
        
        # Parse the result JSON
        result_data = json.loads(result_json_str)
        
        # Convert result back to MIDI file first, then extract notes
        temp_result_fd, temp_result_path = tempfile.mkstemp(suffix='.mid')
        os.close(temp_result_fd)
        
        try:
            # Use encoder to convert JSON back to MIDI
            encoder.json_to_midi(result_json_str, temp_result_path)
            print(f"Converted result to MIDI: {temp_result_path}")
            
            # Extract notes from the generated MIDI file
            output_notes = extract_notes_from_midi(temp_result_path)
            
        finally:
            # Clean up temporary result file
            if os.path.exists(temp_result_path):
                os.unlink(temp_result_path)
        
        # Format as CA string
        result_lines = []
        for note in output_notes:
            # Convert to CA format: ;M:measure;N:pitch;d:duration;w:duration;
            measure = note.get('measure', 0)
            pitch = note.get('pitch', 60)
            duration = note.get('duration', 480)
            result_lines.append(f";M:{measure};N:{pitch};d:{duration};w:{duration};")
        
        result_string = ''.join(result_lines)
        print(f"Generated {len(output_notes)} notes for REAPER")
        
        return result_string
        
    finally:
        # Clean up temporary file
        if os.path.exists(temp_midi_path):
            os.unlink(temp_midi_path)

def create_midi_from_s_parameter(S):
    """Create MIDI file from S parameter (MidiSongByMeasure object)"""
    print("Creating MIDI from S parameter")
    print(f"S type: {type(S)}")
    
    try:
        # Create temporary MIDI file
        temp_fd, temp_path = tempfile.mkstemp(suffix='.mid')
        os.close(temp_fd)
        
        # Use the dump method to export to MIDI file
        S.dump(filename=temp_path)
        print(f"Created MIDI file from S parameter: {temp_path}")
        
        # Debug info about tracks
        if hasattr(S, 'tracks'):
            for track_idx, track in enumerate(S.tracks):
                if hasattr(track, 'tracks_by_measure'):
                    num_measures = len(track.tracks_by_measure)
                    print(f"Track {track_idx}: {num_measures} measures")
        
        return temp_path
        
    except Exception as e:
        print(f"Error creating MIDI from S parameter: {e}")
        import traceback
        traceback.print_exc()
        raise RuntimeError(f"Failed to create MIDI from S parameter: {e}")

def extract_notes_from_midi(midi_path):
    """Extract notes from MIDI file in a format suitable for CA conversion"""
    notes = []
    
    try:
        midi_file = mido.MidiFile(midi_path)
        print(f"Extracting notes from MIDI: {len(midi_file.tracks)} tracks")
        
        for track_idx, track in enumerate(midi_file.tracks):
            current_time = 0
            active_notes = {}  # Track note-on events to match with note-offs
            
            for msg in track:
                current_time += msg.time
                
                if msg.type == 'note_on' and msg.velocity > 0:
                    # Store note-on event
                    active_notes[msg.note] = {
                        'start_time': current_time,
                        'velocity': msg.velocity
                    }
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    # Note-off event
                    if msg.note in active_notes:
                        note_on = active_notes.pop(msg.note)
                        duration = current_time - note_on['start_time']
                        
                        # Convert to measure-based timing (assuming 1920 ticks per measure)
                        measure = note_on['start_time'] // 1920
                        
                        note = {
                            'measure': measure,
                            'pitch': msg.note,
                            'duration': max(480, duration),  # Minimum quarter note
                            'velocity': note_on['velocity'],
                            'start_time': note_on['start_time']
                        }
                        notes.append(note)
        
        print(f"Extracted {len(notes)} notes from MIDI")
        return notes
        
    except Exception as e:
        print(f"Error extracting notes from MIDI: {e}")
        return []

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0):
    """
    REAPER-compatible function signature for neural network infill generation
    """
    print("🎵 MidiGPT call_nn_infill called")
    print(f"  s: {type(s)} ({len(s) if isinstance(s, str) else 'N/A'} chars)")
    print(f"  S: {type(S)}")
    print(f"  use_sampling: {use_sampling}")
    print(f"  temperature: {temperature}")
    
    try:
        # Convert S to dict if it's a string
        if isinstance(S, str):
            S_dict = json.loads(S)
        else:
            S_dict = S
            
        print("Converted S parameter from dict to MidiSongByMeasure")
        
        # Process with MidiGPT
        result = process_midigpt_for_reaper(s, {
            'use_sampling': use_sampling,
            'min_length': min_length,
            'enc_no_repeat_ngram_size': enc_no_repeat_ngram_size,
            'has_fully_masked_inst': has_fully_masked_inst,
            'temperature': temperature
        })
        
        return result
        
    except Exception as e:
        error_msg = f"MidiGPT sample_multi_step failed: {e}"
        print(f"ERROR in call_nn_infill: {error_msg}")
        print("Full traceback:")
        traceback.print_exc()
        raise RuntimeError(error_msg) from e

def check_libraries():
    """Check status of required libraries"""
    return {
        'midigpt_available': MIDIGPT_AVAILABLE,
        'midi_available': MIDI_AVAILABLE
    }

def main():
    """Start the MidiGPT server"""
    print("MidiGPT Server running on http://127.0.0.1:3456")
    print("Ready to process REAPER requests with fail-fast debugging")
    print(f"MidiGPT Available: {MIDIGPT_AVAILABLE}")
    print(f"MIDI Library Available: {MIDI_AVAILABLE}")
    
    server = SimpleXMLRPCServer(("127.0.0.1", 3456), allow_none=True)
    server.register_function(call_nn_infill, "call_nn_infill")
    server.register_function(check_libraries, "check_libraries")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer shutdown requested")
    except Exception as e:
        print(f"Server error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()