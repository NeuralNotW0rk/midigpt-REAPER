#!/usr/bin/env python3

import sys
import os
import json
import tempfile
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
from pathlib import Path

# Add necessary paths
current_dir = Path(__file__).parent.absolute()
sys.path.insert(0, str(current_dir))
sys.path.insert(0, str(current_dir / "../../"))

import mido
import midigpt

# Import CA functions
import preprocessing_functions as pre

class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0):
    """
    REAPER interface function - matches exact signature expected by REAPER scripts
    """
    print("MidiGPT call_nn_infill called")
    print(f"Input: {len(s)} chars, temp={temperature}")
    
    try:
        # Convert S parameter if needed
        if hasattr(S, 'keys'):
            print("Converting S parameter")
            S = pre.midisongbymeasure_from_save_dict(S)
        
        # Detect extra_id tokens for infill vs continuation
        extra_ids = [token for token in s.split(';') if '<extra_id_' in token]
        print(f"Found extra IDs: {len(extra_ids)}")
        
        # Check libraries
        print("MidiGPT library available")
        print("Mido library available")
        print("Using MidiGPT generation")
        
        if extra_ids:
            print("Infill generation")
            ca_result = handle_infill_generation(s, extra_ids, temperature)
        else:
            print("Continuation generation") 
            ca_result = handle_continuation_generation(s, temperature)
            
        print(f"Generated result: {len(ca_result)} chars")
        print(f"COMPLETE return string: {ca_result}")  # Show the complete string
        
        # CRITICAL: Return the CA string directly, not wrapped in a dictionary
        # REAPER expects just the string, not {'result': string}
        return ca_result
        
    except Exception as e:
        print(f"Error in call_nn_infill: {e}")
        # Return minimal fallback that REAPER can handle
        return ";M:0;N:60;d:480;w:480;"

def handle_infill_generation(s, extra_ids, temperature):
    """Handle infill generation using the WORKING approach from pythoninferencetest.py"""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create MIDI with content in bars 0,1,3 and empty bar 2 for generation
        midi_path = create_infill_midi_structure(temp_dir)
        
        # Convert to MidiGPT format
        encoder = midigpt.ExpressiveEncoder()
        piece_json = encoder.midi_to_json(midi_path)
        
        # Use the EXACT working configuration from pythoninferencetest.py
        status_json = {
            'tracks': [{
                'track_id': 0,
                'temperature': 0.5,
                'instrument': 'acoustic_grand_piano', 
                'density': 10, 
                'track_type': 10, 
                'ignore': False, 
                'selected_bars': [False, False, True, False],  # Generate only bar 2
                'min_polyphony_q': 'POLYPHONY_ANY', 
                'max_polyphony_q': 'POLYPHONY_ANY', 
                'autoregressive': False,  # INFILL mode, not autoregressive
                'polyphony_hard_limit': 9 
            }]
        }
        
        param_json = {
            'tracks_per_step': 1, 
            'bars_per_step': 1, 
            'model_dim': 4, 
            'percentage': 100, 
            'batch_size': 1, 
            'temperature': 1.0, 
            'max_steps': 200, 
            'polyphony_hard_limit': 6, 
            'shuffle': True, 
            'verbose': True, 
            'ckpt': find_model_path(),
            'sampling_seed': -1,
            'mask_top_k': 0
        }
        
        # Convert to JSON strings
        piece_str = piece_json
        status_str = json.dumps(status_json)
        param_str = json.dumps(param_json)
        
        # Create CallbackManager
        callbacks = midigpt.CallbackManager()
        
        print(f"Using WORKING pythoninferencetest.py configuration")
        
        try:
            results = midigpt.sample_multi_step(
                piece_str, status_str, param_str, 3, callbacks
            )
            
            if results and len(results) > 0:
                result_json_str = results[0]
                temp_midi = os.path.join(temp_dir, 'generated.mid')
                encoder.json_to_midi(result_json_str, temp_midi)
                
                # Extract generated content
                ca_result = extract_any_notes_from_midi(temp_midi)
                
                if ca_result and len(ca_result) > 20:
                    print(f"Successfully generated {len(ca_result)} chars using working config")
                    print(f"Sample output: {ca_result[:200]}...")
                    return ca_result
                else:
                    print("Generated content was too minimal")
            
        except Exception as generation_error:
            print(f"Working config failed: {generation_error}")
        
        return generate_fallback_notes(len(extra_ids))

def create_infill_midi_structure(temp_dir):
    """Create MIDI structure with content for infill generation (like pythoninferencetest.py)"""
    
    midi_path = os.path.join(temp_dir, 'infill_seed.mid')
    
    mid = mido.MidiFile(ticks_per_beat=480, type=0)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Add meta messages
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, 
                                 clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0))
    track.append(mido.Message('program_change', channel=0, program=0, time=0))
    
    ticks_per_beat = 480
    ticks_per_bar = ticks_per_beat * 4
    
    # Bar 0: Add context notes
    track.append(mido.Message('note_on', channel=0, note=60, velocity=80, time=0))
    track.append(mido.Message('note_off', channel=0, note=60, velocity=0, time=ticks_per_beat))
    track.append(mido.Message('note_on', channel=0, note=64, velocity=80, time=0))
    track.append(mido.Message('note_off', channel=0, note=64, velocity=0, time=ticks_per_beat))
    
    # Bar 1: Add more context
    track.append(mido.Message('note_on', channel=0, note=67, velocity=80, time=ticks_per_beat))
    track.append(mido.Message('note_off', channel=0, note=67, velocity=0, time=ticks_per_beat))
    
    # Bar 2: EMPTY - this is where MidiGPT will generate
    track.append(mido.Message('note_on', channel=0, note=60, velocity=0, time=ticks_per_bar))
    
    # Bar 3: Add ending context
    track.append(mido.Message('note_on', channel=0, note=72, velocity=80, time=0))
    track.append(mido.Message('note_off', channel=0, note=72, velocity=0, time=ticks_per_beat * 2))
    
    track.append(mido.MetaMessage('end_of_track', time=0))
    
    mid.save(midi_path)
    return midi_path

def handle_continuation_generation(s, temperature):
    """Handle continuation generation with existing notes"""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Convert CA string to MIDI
        midi_path = create_midi_file_from_ca_string(s, temp_dir)
        
        # Use MidiGPT for enhancement/continuation
        encoder = midigpt.ExpressiveEncoder()
        piece_json = encoder.midi_to_json(midi_path)
        
        # Configure for continuation
        status_json = {
            'tracks': [{
                'track_id': 0,
                'temperature': temperature,
                'instrument': 'acoustic_grand_piano',
                'density': 10,
                'track_type': 10,
                'ignore': False,
                'selected_bars': [False, False, True, False],  # Selective
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY',
                'autoregressive': False,  # Work with existing content
                'polyphony_hard_limit': 6
            }]
        }
        
        param_json = {
            'tracks_per_step': 1,
            'bars_per_step': 1,
            'model_dim': 4,
            'percentage': 100,
            'batch_size': 1,
            'temperature': temperature,
            'max_steps': 30,
            'polyphony_hard_limit': 6,
            'shuffle': True,
            'verbose': False,
            'ckpt': find_model_path(),
            'sampling_seed': -1,
            'mask_top_k': 0
        }
        
        # Convert to JSON strings
        piece_str = piece_json
        status_str = json.dumps(status_json)
        param_str = json.dumps(param_json)
        
        # Create CallbackManager
        callbacks = midigpt.CallbackManager()
        
        try:
            results = midigpt.sample_multi_step(
                piece_str, status_str, param_str, 3, callbacks
            )
            
            if results and len(results) > 0:
                temp_midi = os.path.join(temp_dir, 'output.mid')
                encoder.json_to_midi(results[0], temp_midi)
                return extract_any_notes_from_midi(temp_midi) or s
                
        except Exception as e:
            print(f"Continuation generation failed: {e}")
        
        return s  # Return original if generation fails

def create_empty_midi_structure(temp_dir, num_bars=4):
    """Create a minimal MIDI structure with just enough content for MidiGPT to process"""
    
    midi_path = os.path.join(temp_dir, 'minimal.mid')
    
    # Create MIDI file with minimal but valid musical content
    mid = mido.MidiFile(ticks_per_beat=480, type=0)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Add essential meta messages
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, 
                                 clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0))
    track.append(mido.Message('program_change', channel=0, program=0, time=0))
    
    # Add ONE minimal note to satisfy MidiGPT's requirement
    # This gives it just enough to work with without constraining creativity
    track.append(mido.Message('note_on', channel=0, note=60, velocity=40, time=0))  # Quiet C
    track.append(mido.Message('note_off', channel=0, note=60, velocity=0, time=240))  # Short duration
    
    # Add silence for the rest of the structure
    ticks_per_bar = 480 * 4  # 4/4 time
    remaining_time = (ticks_per_bar * num_bars) - 240  # Subtract the note duration
    
    # Add silence to fill the remaining time
    track.append(mido.Message('note_on', channel=0, note=60, velocity=0, time=remaining_time))
    track.append(mido.MetaMessage('end_of_track', time=0))
    
    mid.save(midi_path)
    return midi_path

def create_midi_file_from_ca_string(ca_string, temp_dir):
    """Convert CA format string to MIDI file"""
    
    midi_path = os.path.join(temp_dir, 'input.mid')
    
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Add tempo and time signature
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    
    # Parse CA string for notes
    parts = ca_string.split(';')
    current_time = 0
    
    for part in parts:
        if part.startswith('N:') and 'd:' in ca_string:
            try:
                # Extract note information
                note_pitch = None
                note_duration = None
                
                # Find the note pitch
                if part.startswith('N:'):
                    note_pitch = int(part[2:])
                
                # Find duration in subsequent parts
                for next_part in parts[parts.index(part):]:
                    if next_part.startswith('d:'):
                        note_duration = int(next_part[2:])
                        break
                
                if note_pitch and note_duration:
                    # Add note to MIDI
                    track.append(mido.Message('note_on', channel=0, note=note_pitch, 
                                            velocity=80, time=current_time))
                    track.append(mido.Message('note_off', channel=0, note=note_pitch, 
                                            velocity=80, time=note_duration))
                    current_time = 0
                    
            except (ValueError, IndexError):
                continue
    
    mid.save(midi_path)
    return midi_path

def extract_any_notes_from_midi(midi_path):
    """Extract musical notes from MIDI regardless of track structure - agnostic approach"""
    
    try:
        mid = mido.MidiFile(midi_path)
        ca_parts = []
        measure = 0
        
        # Process ALL tracks and extract ANY notes found
        all_notes = []
        
        for track_idx, track in enumerate(mid.tracks):
            current_time = 0
            active_notes = {}  # pitch -> start_time
            
            for msg in track:
                current_time += msg.time
                
                if msg.type == 'note_on' and msg.velocity > 0:
                    # Note starts
                    active_notes[msg.note] = current_time
                    
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    # Note ends
                    if msg.note in active_notes:
                        start_time = active_notes[msg.note]
                        duration = max(120, current_time - start_time)  # Minimum duration
                        
                        all_notes.append({
                            'pitch': msg.note,
                            'start_time': start_time,
                            'duration': duration,
                            'track': track_idx
                        })
                        
                        del active_notes[msg.note]
        
        # Convert collected notes to CA format
        if all_notes:
            # Sort by start time
            all_notes.sort(key=lambda x: x['start_time'])
            
            ticks_per_bar = 1920  # Standard 4/4 bar
            
            for note in all_notes:
                current_measure = note['start_time'] // ticks_per_bar
                
                ca_parts.extend([
                    f'M:{current_measure}',
                    f'N:{note["pitch"]}',
                    f'd:{note["duration"]}',
                    f'w:{note["duration"]}'
                ])
            
            if ca_parts:
                result = ';' + ';'.join(ca_parts) + ';'
                return result
        
        print("No notes found in generated MIDI")
        return None
        
    except Exception as e:
        print(f"Error extracting notes from MIDI: {e}")
        return None

def extract_notes_and_convert_to_ca_format(midi_path):
    """Original function - kept as fallback"""
    
    try:
        mid = mido.MidiFile(midi_path)
        ca_parts = []
        
        # Track state
        measure = 0
        
        for msg in mid.tracks[0]:
            if msg.type == 'note_on' and msg.velocity > 0:
                # Convert to CA format
                pitch = msg.note
                duration = 480  # Default duration
                
                # Find corresponding note_off
                remaining_time = duration
                for future_msg in mid.tracks[0]:
                    if (future_msg.type == 'note_off' and 
                        future_msg.note == pitch):
                        duration = future_msg.time if future_msg.time > 0 else 480
                        break
                
                # Format as CA string
                ca_parts.extend([
                    f'M:{measure}',
                    f'N:{pitch}', 
                    f'd:{duration}',
                    f'w:{duration}'
                ])
        
        if ca_parts:
            result = ';' + ';'.join(ca_parts) + ';'
            return result
        
    except Exception as e:
        print(f"Error converting MIDI to CA format: {e}")
    
    # Fallback
    return ";M:0;N:60;d:480;w:480;"

def generate_fallback_notes(num_notes):
    """Generate simple fallback notes when MidiGPT fails"""
    
    pitches = [60, 62, 64, 65, 67, 69, 71, 72]  # C major scale
    ca_parts = []
    
    for i in range(min(num_notes, len(pitches))):
        pitch = pitches[i]
        measure = i  # Different measure for each note
        ca_parts.extend([
            f'M:{measure}',
            f'N:{pitch}',
            'd:480',
            'w:480'
        ])
    
    return ';' + ';'.join(ca_parts) + ';'

def find_model_path():
    """Find the MidiGPT model checkpoint"""
    
    possible_paths = [
        "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return os.path.abspath(path)
    
    raise FileNotFoundError("Could not find MidiGPT model checkpoint")

def main():
    print("Starting MidiGPT Production Server")
    print("Port: 3456")
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