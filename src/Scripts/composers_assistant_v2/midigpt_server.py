#!/usr/bin/env python3
"""
MidiGPT Server - Direct Implementation
Based exactly on pythoninferencetest.py working example
No fallbacks - fix the actual MidiGPT integration
"""

import sys
import os
import json
import tempfile
import re
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
from pathlib import Path

# Add necessary paths
current_dir = Path(__file__).parent.absolute()
sys.path.insert(0, str(current_dir))
sys.path.insert(0, str(current_dir / "../../"))

# Add MIDI-GPT path
midigpt_paths = [
    str(current_dir / "../../../MIDI-GPT/python_lib"),
    str(current_dir / "../../MIDI-GPT/python_lib"),
    str(current_dir / "../../../../MIDI-GPT/python_lib")
]

for path in midigpt_paths:
    if os.path.exists(path):
        sys.path.insert(0, path)
        print(f"Added MidiGPT path: {path}")
        break

# Import required libraries
try:
    import mido
    import preprocessing_functions as pre
    print("Base libraries loaded")
except ImportError as e:
    print(f"Critical error: {e}")
    sys.exit(1)

# Import MidiGPT (required - no fallback)
try:
    import midigpt
    print("MidiGPT library loaded successfully")
except ImportError as e:
    print(f"CRITICAL ERROR: MidiGPT not available: {e}")
    print("Server cannot function without MidiGPT. Check installation.")
    sys.exit(1)

class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)

def extract_extra_id_tokens(input_string):
    """Extract extra_id tokens from input string"""
    if not input_string:
        return []
    
    pattern = r'<extra_id_(\d+)>'
    matches = re.findall(pattern, str(input_string))
    return [f'<extra_id_{match}>' for match in matches]

def find_model_checkpoint():
    """Find MidiGPT model checkpoint"""
    possible_paths = [
        "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../MIDI-GPT/models/model.pt",
        "../../../MIDI-GPT/models/model.pt"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            abs_path = os.path.abspath(path)
            print(f"Found model: {abs_path}")
            return abs_path
    
    raise FileNotFoundError("Could not find MidiGPT model checkpoint")

def create_seed_midi(temp_dir, num_bars=4):
    """Create seed MIDI file following pythoninferencetest.py approach"""
    midi_path = os.path.join(temp_dir, "seed.mid")
    
    # Create MIDI with proper structure for MidiGPT
    mid = mido.MidiFile(ticks_per_beat=96)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Add meta messages
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    
    # Add some seed content across multiple bars like pythoninferencetest.py expects
    # This gives MidiGPT context to work with
    current_time = 0
    
    for bar in range(num_bars):
        if bar < 2:  # First 2 bars have some content
            # Add a simple chord progression
            pitches = [60, 64, 67] if bar == 0 else [62, 65, 69]  # C major, D minor
            
            for i, pitch in enumerate(pitches):
                track.append(mido.Message('note_on', channel=0, note=pitch, velocity=80, time=current_time))
                track.append(mido.Message('note_off', channel=0, note=pitch, velocity=0, time=48))  # Half beat
                current_time = 0 if i < len(pitches) - 1 else 48  # Last note in chord
        
        # Fill rest of bar with silence  
        remaining_ticks = 96 * 4 - (48 * 3 if bar < 2 else 0)  # 4 beats per bar, minus notes
        if remaining_ticks > 0:
            current_time = remaining_ticks
    
    # End of track
    track.append(mido.MetaMessage('end_of_track', time=current_time))
    mid.save(midi_path)
    
    return midi_path

def generate_with_midigpt(num_tokens, temperature=1.0):
    """Generate using MidiGPT - exact copy of pythoninferencetest.py approach"""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create seed MIDI
            seed_midi_path = create_seed_midi(temp_dir, num_bars=4)
            
            # Use ExpressiveEncoder exactly like pythoninferencetest.py
            encoder = midigpt.ExpressiveEncoder()
            midi_json_str = encoder.midi_to_json(seed_midi_path)
            midi_json_input = json.loads(midi_json_str)
            
            print(f"Created piece JSON with {len(midi_json_str)} chars")
            
            # Status configuration - EXACT copy from pythoninferencetest.py
            valid_status = {
                'tracks': [{
                    'track_id': 0,
                    'temperature': temperature,
                    'instrument': 'acoustic_grand_piano', 
                    'density': 10, 
                    'track_type': 10, 
                    'ignore': False, 
                    'selected_bars': [False, False, True, True],  # Generate bars 2 and 3
                    'min_polyphony_q': 'POLYPHONY_ANY',  # STRING not integer
                    'max_polyphony_q': 'POLYPHONY_ANY', 
                    'autoregressive': False,  # Use infill mode
                    'polyphony_hard_limit': 9 
                }]
            }
            
            # Parameters - EXACT copy from pythoninferencetest.py
            model_path = find_model_checkpoint()
            parami = {
                'tracks_per_step': 1, 
                'bars_per_step': 1, 
                'model_dim': 4, 
                'percentage': 100, 
                'batch_size': 1, 
                'temperature': temperature, 
                'max_steps': 50,  # Reduced for faster response
                'polyphony_hard_limit': 6, 
                'shuffle': True, 
                'verbose': False,  # Reduce spam
                'ckpt': model_path,
                'sampling_seed': -1,
                'mask_top_k': 0
            }
            
            # Convert to JSON strings - EXACT like pythoninferencetest.py
            piece = json.dumps(midi_json_input)
            status = json.dumps(valid_status)
            param = json.dumps(parami)
            
            # Create callback manager and sample - EXACT like pythoninferencetest.py
            callbacks = midigpt.CallbackManager()
            max_attempts = 3
            
            print("Calling midigpt.sample_multi_step...")
            midi_results = midigpt.sample_multi_step(piece, status, param, max_attempts, callbacks)
            
            if not midi_results or len(midi_results) == 0:
                raise Exception("MidiGPT returned no results")
            
            # Get first result and parse JSON - like pythoninferencetest.py
            midi_str = midi_results[0]
            midi_json = json.loads(midi_str)
            
            print(f"MidiGPT generated {len(midi_str)} chars")
            
            # Convert back to MIDI and extract notes - like pythoninferencetest.py
            output_midi_path = os.path.join(temp_dir, "output.mid")
            encoder.json_to_midi(midi_str, output_midi_path)
            
            # Extract notes from generated MIDI
            return extract_notes_from_midi(output_midi_path)
            
    except Exception as e:
        print(f"MidiGPT generation failed: {e}")
        import traceback
        traceback.print_exc()
        raise  # Don't mask the error with fallback

def extract_notes_from_midi(midi_path):
    """Extract notes from MidiGPT output - focus on Track 0 where content lives"""
    all_notes = []
    
    try:
        mid = mido.MidiFile(midi_path)
        ticks_per_beat = mid.ticks_per_beat or 96
        print(f"Analyzing MidiGPT output: {len(mid.tracks)} tracks, {ticks_per_beat} tpb")
        
        # Based on diagnostic: Track 0 has all the content, others are empty
        # Focus extraction on Track 0 only
        if len(mid.tracks) > 0:
            track = mid.tracks[0]  # Only process Track 0
            track_time = 0
            active_notes = {}
            
            print(f"Processing Track 0 with {len(track)} messages")
            
            for msg in track:
                track_time += msg.time
                
                if msg.type == 'note_on' and msg.velocity > 0:
                    active_notes[msg.note] = {
                        'start': track_time,
                        'velocity': msg.velocity
                    }
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    if msg.note in active_notes:
                        note_info = active_notes.pop(msg.note)
                        duration = max(48, track_time - note_info['start'])
                        
                        all_notes.append({
                            'pitch': msg.note,
                            'start': note_info['start'],
                            'duration': duration,
                            'velocity': note_info['velocity']
                        })
            
            # Sort by start time
            all_notes.sort(key=lambda x: x['start'])
            
            print(f"Extracted {len(all_notes)} notes from Track 0:")
            for i, note in enumerate(all_notes):
                print(f"  Note {i+1}: pitch={note['pitch']}, start={note['start']}, dur={note['duration']}")
        
        return all_notes
        
    except Exception as e:
        print(f"MIDI extraction error: {e}")
        import traceback
        traceback.print_exc()
        raise

def format_ca_response(extra_ids, notes):
    """Format response in CA string format"""
    if not extra_ids or not notes:
        raise Exception("No extra_ids or notes to format")
    
    result_parts = []
    
    # Distribute notes across extra_ids
    notes_per_token = max(1, len(notes) // len(extra_ids))
    
    for i, extra_id in enumerate(extra_ids):
        result_parts.append(extra_id)
        
        # Get notes for this token
        start_idx = i * notes_per_token
        end_idx = min(start_idx + notes_per_token, len(notes))
        token_notes = notes[start_idx:end_idx] if start_idx < len(notes) else notes[:1]
        
        # Add notes for this token
        for j, note in enumerate(token_notes):
            result_parts.append(f"N:{note['pitch']}")
            result_parts.append(f"d:{note['duration']}")
            # Add wait between notes (except last note in token)
            if j < len(token_notes) - 1:
                result_parts.append(f"w:{note['duration'] // 2}")
    
    return ';'.join(result_parts)

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0):
    """
    MidiGPT REAPER interface - no fallbacks, direct MidiGPT integration only
    """
    print("MidiGPT call_nn_infill called")
    
    try:
        # Convert S parameter if needed
        if hasattr(S, 'keys'):
            S = pre.midisongbymeasure_from_save_dict(S)
        
        # Extract extra_id tokens
        extra_ids = extract_extra_id_tokens(s)
        print(f"Found extra IDs: {extra_ids}")
        
        if not extra_ids:
            extra_ids = ['<extra_id_1>']
        
        # Limit to reasonable number
        num_tokens = min(len(extra_ids), 4)
        extra_ids = extra_ids[:num_tokens]
        
        print(f"Generating content for {num_tokens} tokens using MidiGPT")
        
        # Generate using MidiGPT - no fallbacks
        notes = generate_with_midigpt(num_tokens, temperature)
        
        if not notes:
            raise Exception("MidiGPT generation produced no notes")
        
        # Format response
        result = format_ca_response(extra_ids, notes)
        
        print(f"Final result: {result}")
        return result
        
    except Exception as e:
        print(f"CRITICAL ERROR in call_nn_infill: {e}")
        import traceback
        traceback.print_exc()
        # Return error instead of hiding it
        raise Exception(f"MidiGPT generation failed: {e}")

def main():
    print("MidiGPT Server - Direct Integration Only")
    print("Port: 3456")
    print("No fallbacks - MidiGPT must work or server reports error")
    
    # Test MidiGPT availability immediately
    try:
        encoder = midigpt.ExpressiveEncoder()
        model_path = find_model_checkpoint()
        print(f"MidiGPT ready with model: {model_path}")
    except Exception as e:
        print(f"CRITICAL: MidiGPT setup failed: {e}")
        print("Fix MidiGPT integration before continuing")
        sys.exit(1)
    
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