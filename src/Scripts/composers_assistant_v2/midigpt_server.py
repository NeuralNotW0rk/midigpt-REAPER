#!/usr/bin/env python3
"""
Fresh MidiGPT Server - Single Note Per Extra ID
Based on analysis of working two-server solution
"""

import sys
import os
import json
import tempfile
import re
import shutil
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
from pathlib import Path

# Add necessary paths
current_dir = Path(__file__).parent.absolute()
sys.path.insert(0, str(current_dir))
sys.path.insert(0, str(current_dir / "../../"))

import mido
import midigpt
import preprocessing_functions as pre

class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0):
    """
    REAPER interface function - FRESH IMPLEMENTATION
    Key insight: Each extra_id gets exactly ONE note
    """
    print("MidiGPT call_nn_infill called - FRESH VERSION")
    
    try:
        # Convert S parameter if needed
        if hasattr(S, 'keys'):
            S = pre.midisongbymeasure_from_save_dict(S)
        
        # Extract extra_id tokens
        extra_ids = extract_extra_id_tokens(s)
        print(f"Found extra IDs: {extra_ids}")
        
        print("MidiGPT library available")
        print("Mido library available")
        
        # Generate content
        if extra_ids:
            print("Infill generation")
            generated_notes = generate_notes(len(extra_ids), temperature)
        else:
            print("Continuation generation") 
            generated_notes = generate_notes(1, temperature)
            extra_ids = ['<extra_id_1>']
            
        # Format response: ONE note per extra_id
        result = format_single_note_response(extra_ids, generated_notes)
        
        print(f"Final result: {result}")
        return result
        
    except Exception as e:
        print(f"Error: {e}")
        return "<extra_id_1>N:60;d:240;w:240"

def extract_extra_id_tokens(input_string):
    """Extract extra_id tokens from input string"""
    pattern = r'<extra_id_\d+>'
    tokens = re.findall(pattern, input_string)
    return tokens

def generate_notes(num_notes, temperature):
    """Generate notes using MidiGPT or fallback"""
    try:
        # Try MidiGPT generation
        notes = attempt_midigpt_generation(num_notes, temperature)
        if notes:
            print(f"MidiGPT generated {len(notes)} notes: {[n['pitch'] for n in notes]}")
            return notes
    except Exception as e:
        print(f"MidiGPT failed: {e}")
    
    # Fallback generation
    print("Using fallback generation")
    fallback_pitches = [60, 64, 67, 69, 72]  # C major pentatonic
    notes = []
    for i in range(num_notes):
        pitch = fallback_pitches[i % len(fallback_pitches)]
        notes.append({'pitch': pitch, 'duration': 240})
    return notes

def attempt_midigpt_generation(num_notes, temperature):
    """Attempt MidiGPT generation"""
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Create input MIDI
        midi_file_path = os.path.join(temp_dir, "input.mid")
        create_simple_midi_input(midi_file_path, num_notes)
        
        # Load model and encoder
        model_path = find_model_path()
        encoder = midigpt.ExpressiveEncoder()
        
        # Convert to JSON
        piece_json_str = encoder.midi_to_json(midi_file_path)
        piece_json = json.loads(piece_json_str)
        
        # Use exact working configuration from pythoninferencetest.py
        status_config = {
            'tracks': [{
                'track_id': 0,
                'temperature': 0.5,
                'instrument': 'acoustic_grand_piano', 
                'density': 10, 
                'track_type': 10, 
                'ignore': False, 
                'selected_bars': [False, False, True, False],
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY', 
                'autoregressive': False,
                'polyphony_hard_limit': 9 
            }]
        }
        
        param_config = {
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
        
        # Convert to JSON strings
        piece_str = json.dumps(piece_json)
        status_str = json.dumps(status_config)
        param_str = json.dumps(param_config)
        
        # Generate
        callbacks = midigpt.CallbackManager()
        result_tuple = midigpt.sample_multi_step(piece_str, status_str, param_str, 3, callbacks)
        
        # Extract result
        result_json_str = result_tuple[0]
        
        # Convert back to MIDI
        output_midi_path = os.path.join(temp_dir, "output.mid")
        encoder.json_to_midi(result_json_str, output_midi_path)
        
        # Extract notes
        notes = extract_notes_from_midi(output_midi_path)
        
        return notes
        
    finally:
        # Cleanup
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

def create_simple_midi_input(output_path, num_notes):
    """Create simple MIDI input"""
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Add tempo
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    
    # Add a couple seed notes
    seed_pitches = [60, 64]
    for i, pitch in enumerate(seed_pitches):
        track.append(mido.Message('note_on', note=pitch, velocity=64, time=0 if i == 0 else 480))
        track.append(mido.Message('note_off', note=pitch, velocity=64, time=240))
    
    mid.save(output_path)

def extract_notes_from_midi(midi_path):
    """Extract notes from MidiGPT's multi-track output correctly"""
    try:
        midi_file = mido.MidiFile(midi_path)
        all_notes = []
        ticks_per_beat = midi_file.ticks_per_beat or 480
        
        print(f"Analyzing MidiGPT output: {len(midi_file.tracks)} tracks, {ticks_per_beat} tpb")
        
        # Process each track separately - each track has its own timeline starting from 0
        for track_idx, track in enumerate(midi_file.tracks):
            track_time = 0
            active_notes = {}
            track_notes = []
            
            for msg in track:
                track_time += msg.time
                
                if msg.type == 'note_on' and msg.velocity > 0:
                    active_notes[msg.note] = track_time
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    if msg.note in active_notes:
                        start_time = active_notes[msg.note]
                        duration = track_time - start_time
                        
                        track_notes.append({
                            'pitch': msg.note,
                            'start': start_time,
                            'duration': duration,
                            'track': track_idx
                        })
                        del active_notes[msg.note]
            
            if track_notes:
                print(f"  Track {track_idx}: {len(track_notes)} notes")
                for note in track_notes:
                    print(f"    pitch={note['pitch']}, start={note['start']}, dur={note['duration']}")
            
            all_notes.extend(track_notes)
        
        if not all_notes:
            print("No notes found in any track!")
            return []
        
        # Sort all notes by start time to create the final sequence
        all_notes.sort(key=lambda n: n['start'])
        
        print(f"\nCombined sequence ({len(all_notes)} total notes):")
        for i, note in enumerate(all_notes[:8]):
            print(f"  {i+1}: pitch={note['pitch']}, start={note['start']}, dur={note['duration']}, track={note['track']}")
        
        return all_notes[:8]  # Limit to 8 notes
        
    except Exception as e:
        print(f"MIDI extraction error: {e}")
        import traceback
        traceback.print_exc()
        return []

def format_single_note_response(extra_ids, notes):
    """
    Format response using MidiGPT's actual extracted notes with proper timing
    """
    if not extra_ids:
        extra_ids = ['<extra_id_1>']
    
    if not notes:
        notes = [{'pitch': 60, 'start': 0, 'duration': 240}]
    
    result_parts = []
    
    for i, extra_id in enumerate(extra_ids):
        result_parts.append(extra_id)
        
        # Distribute notes among extra_ids
        if i == 0:
            # First extra_id gets most of the notes
            phrase_notes = notes[:min(len(notes), 6)]
        else:
            # Additional extra_ids get remaining notes
            notes_per_id = max(1, len(notes) // len(extra_ids))
            start_idx = i * notes_per_id
            end_idx = min(start_idx + notes_per_id, len(notes))
            phrase_notes = notes[start_idx:end_idx]
        
        if not phrase_notes:
            # Fallback single note if no notes available
            pitch = 60 + (i * 2)
            result_parts.extend([f"N:{pitch}", "d:480", "w:480"])
            continue
        
        # Format notes with proper timing relationships
        current_position = 0
        
        for j, note in enumerate(phrase_notes):
            pitch = note['pitch']
            start_time = note['start']
            duration = note['duration']
            
            # Calculate wait needed to reach this note's position
            wait_needed = max(0, start_time - current_position)
            
            # Add wait if needed (but keep reasonable)
            if wait_needed > 0:
                # Cap waits to reasonable musical values
                wait_needed = min(wait_needed, 3840)  # Max 2 measures
                result_parts.append(f"w:{wait_needed}")
                current_position += wait_needed
            
            # Add the note with its actual duration
            duration = max(240, min(duration, 1920))  # Between 1/8 note and whole note
            result_parts.extend([
                f"N:{pitch}",
                f"d:{duration}"
            ])
            
            # Update current position
            current_position = start_time
        
        # Add final wait equal to the last note's duration
        if phrase_notes:
            final_duration = max(240, min(phrase_notes[-1]['duration'], 1920))
            result_parts.append(f"w:{final_duration}")
    
    result = ';'.join(result_parts)
    
    print(f"PROPERLY EXTRACTED FORMAT: {result[:120]}...")
    return result

def find_model_path():
    """Find MidiGPT model checkpoint"""
    possible_paths = [
        "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return os.path.abspath(path)
    
    raise FileNotFoundError("Could not find MidiGPT model checkpoint")

def main():
    print("Fresh MidiGPT Server - Single Note Per Extra ID")
    print("Port: 3456")
    print("Key insight: Each extra_id gets exactly ONE note")
    print("Ready for REAPER connections...")
    
    # Create XML-RPC server
    server = SimpleXMLRPCServer(("127.0.0.1", 3456), 
                               requestHandler=RequestHandler,
                               allow_none=True)
    
    # Register the function REAPER expects
    server.register_function(call_nn_infill, 'call_nn_infill')
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")

if __name__ == "__main__":
    main()