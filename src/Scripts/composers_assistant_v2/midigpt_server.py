#!/usr/bin/env python3
"""
Production MidiGPT Server for REAPER Integration
Converts REAPER CA format to MidiGPT and back for AI music generation
"""

import os
import re
from xmlrpc.server import SimpleXMLRPCServer
import socketserver
from pathlib import Path

DEBUG = True

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0):
    """
    MidiGPT inference function - matches REAPER script signature exactly
    """
    
    if DEBUG:
        print(f"\n🎵 MidiGPT call_nn_infill called")
        print(f"Input: {len(s)} chars, temp={temperature}")
    
    try:
        # Step 1: Handle S parameter conversion
        if hasattr(S, 'keys'):  # It's a dictionary
            try:
                import preprocessing_functions as pre
                S_converted = pre.midisongbymeasure_from_save_dict(S)
                S = S_converted
                if DEBUG:
                    print("✅ Converted S parameter")
            except Exception as e:
                print(f"Warning: Could not convert S parameter: {e}")
        
        # Step 2: Extract extra IDs from input string
        extra_id_matches = re.findall(r'<extra_id_(\d+)>', s)
        extra_ids = [int(match) for match in extra_id_matches]
        
        if len(extra_ids) == 0:
            extra_ids = [0]  # Default fallback
        
        if DEBUG:
            print(f"Found extra IDs: {extra_ids}")
        
        # Step 3: Check for MidiGPT availability
        midigpt_available = False
        try:
            import sys
            sys.path.append('MIDI-GPT/python_lib')
            import midigpt
            midigpt_available = True
            if DEBUG:
                print("✅ MidiGPT library available")
        except ImportError as e:
            print(f"MidiGPT library not available: {e}")
        
        # Step 4: Check for MIDI library
        midi_lib_available = False
        try:
            import mido
            midi_lib_available = True
            if DEBUG:
                print("✅ Mido library available")
        except ImportError:
            try:
                import miditoolkit
                midi_lib_available = True
                if DEBUG:
                    print("✅ Miditoolkit library available")
            except ImportError:
                print("No MIDI library available")
        
        # Step 5: Generate response
        if midigpt_available and midi_lib_available:
            if DEBUG:
                print("🚀 Using MidiGPT generation")
            result = attempt_midigpt_generation(s, S, extra_ids, temperature, min_length)
        else:
            if DEBUG:
                print("🔄 Using fallback generation")
            result = generate_enhanced_fallback(s, extra_ids, temperature)
        
        if DEBUG:
            print(f"✅ Generated result: {len(result)} chars")
        
        return result
        
    except Exception as e:
        print(f"❌ Error in call_nn_infill: {e}")
        import traceback
        traceback.print_exc()
        
        # Emergency fallback
        try:
            return generate_simple_fallback(s, extra_ids)
        except:
            return "<extra_id_0>N:60;d:240;w:240"

def attempt_midigpt_generation(input_string, S, extra_ids, temperature, min_length):
    """Attempt actual MidiGPT generation"""
    
    try:
        import midigpt
        import json
        import tempfile
        import uuid
        from pathlib import Path
        
        # Create temp directory
        temp_dir = Path(tempfile.gettempdir()) / "midigpt_temp"
        temp_dir.mkdir(exist_ok=True)
        
        # Check if this is an infill request (no existing notes)
        has_actual_notes = bool(re.search(r'N:\d+', input_string))
        
        if not has_actual_notes:
            if DEBUG:
                print("🎯 Infill generation")
            return handle_infill_generation(input_string, S, extra_ids, temperature, min_length, temp_dir)
        else:
            if DEBUG:
                print("🎵 Continuation generation")
            return handle_continuation_generation(input_string, S, extra_ids, temperature, min_length, temp_dir)
            
    except Exception as e:
        print(f"Error in MidiGPT generation: {e}")
        return generate_enhanced_fallback(input_string, extra_ids, temperature)

def handle_infill_generation(input_string, S, extra_ids, temperature, min_length, temp_dir):
    """Handle infill generation where we need to create content from scratch"""
    
    try:
        import midigpt
        import json
        import uuid
        
        # Step 1: Create minimal MIDI structure for infill
        midi_file_path = create_minimal_midi_structure(temp_dir, len(extra_ids))
        
        # Step 2: Find model
        model_path = find_midigpt_model()
        if not model_path:
            return generate_enhanced_fallback(input_string, extra_ids, temperature)
        
        # Step 3: Convert to JSON
        encoder = midigpt.ExpressiveEncoder()
        midi_json_str = encoder.midi_to_json(midi_file_path)
        midi_data = json.loads(midi_json_str)
        
        # Step 4: Configure for infill generation
        num_bars = max(4, len(extra_ids))
        selected_bars = [True] * num_bars  # Generate all bars for infill
        
        status_config = {
            'tracks': [{
                'track_id': 0,
                'temperature': temperature,
                'instrument': 'acoustic_grand_piano',
                'density': min(10, 6 + len(extra_ids)),
                'track_type': 10,
                'ignore': False,
                'selected_bars': selected_bars,
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY',
                'autoregressive': True,
                'polyphony_hard_limit': min(12, 6 + len(extra_ids))
            }]
        }
        
        param_config = {
            'tracks_per_step': 1,
            'bars_per_step': min(4, num_bars),
            'model_dim': 4,
            'percentage': 100,
            'batch_size': 1,
            'temperature': temperature,
            'max_steps': max(200, min_length * 50),
            'polyphony_hard_limit': min(12, 6 + len(extra_ids)),
            'shuffle': False,
            'verbose': False,
            'ckpt': os.path.abspath(model_path),
            'sampling_seed': -1,
            'mask_top_k': 0
        }
        
        # Step 5: Generate
        piece_json = json.dumps(midi_data)
        status_json = json.dumps(status_config)
        param_json = json.dumps(param_config)
        
        callbacks = midigpt.CallbackManager()
        max_attempts = 3
        
        result = midigpt.sample_multi_step(piece_json, status_json, param_json, 
                                         max_attempts, callbacks)
        
        if result and len(result) > 0:
            result_json = result[0]
            
            # Convert back and map to extra_ids
            temp_output_file = temp_dir / f"infill_output_{uuid.uuid4().hex[:8]}.mid"
            encoder.json_to_midi(result_json, str(temp_output_file))
            
            ca_result = map_generated_notes_to_extra_ids(
                str(temp_output_file), input_string, extra_ids
            )
            
            # Clean up
            try:
                os.unlink(midi_file_path)
                os.unlink(temp_output_file)
            except:
                pass
            
            return ca_result
        else:
            return generate_enhanced_fallback(input_string, extra_ids, temperature)
            
    except Exception as e:
        print(f"Error in infill generation: {e}")
        return generate_enhanced_fallback(input_string, extra_ids, temperature)

def create_minimal_midi_structure(temp_dir, num_extra_ids):
    """Create a minimal MIDI file with basic structure for infill"""
    import mido
    import uuid
    
    filename = f"minimal_structure_{uuid.uuid4().hex[:8]}.mid"
    filepath = temp_dir / filename
    
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Add tempo
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    
    # Add seed notes
    seed_notes = [60, 64, 67]  # C major triad
    
    for i, pitch in enumerate(seed_notes):
        track.append(mido.Message('note_on', channel=0, note=pitch, 
                                velocity=64, time=0 if i == 0 else 0))
        track.append(mido.Message('note_off', channel=0, note=pitch, 
                                velocity=0, time=480))
    
    # Add silence for generation
    bars_to_generate = max(4, num_extra_ids)
    silence_duration = bars_to_generate * 4 * 480
    track.append(mido.Message('note_on', channel=0, note=60, velocity=0, time=silence_duration))
    
    mid.save(str(filepath))
    return str(filepath)

def map_generated_notes_to_extra_ids(midi_path, original_input, extra_ids):
    """Convert generated MIDI back to CA format and map to extra_ids"""
    import mido
    
    # Extract notes from generated MIDI
    notes = []
    mid = mido.MidiFile(midi_path)
    current_time = 0
    
    for track in mid.tracks:
        for msg in track:
            current_time += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                notes.append({
                    'pitch': msg.note,
                    'start': current_time,
                    'velocity': msg.velocity
                })
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                for note in reversed(notes):
                    if note['pitch'] == msg.note and 'duration' not in note:
                        note['duration'] = current_time - note['start']
                        break
    
    # Filter generated content (after seed notes)
    generated_notes = [n for n in notes if n.get('start', 0) > 1440]
    
    if not generated_notes:
        return generate_enhanced_fallback(original_input, extra_ids, 1.0)
    
    # Sort and distribute notes to extra_ids
    generated_notes.sort(key=lambda x: x['start'])
    notes_per_extra_id = max(1, len(generated_notes) // len(extra_ids))
    
    result = original_input
    
    for i, extra_id in enumerate(extra_ids):
        start_idx = i * notes_per_extra_id
        end_idx = min(start_idx + notes_per_extra_id, len(generated_notes))
        notes_for_this_id = generated_notes[start_idx:end_idx]
        
        # Convert notes to CA format
        ca_notes = []
        last_end = 0
        
        for note in notes_for_this_id:
            if 'duration' not in note:
                note['duration'] = 240
            
            wait = max(0, note['start'] - note.get('start', 0) - last_end) if last_end > 0 else 0
            ca_notes.append(f"N:{note['pitch']};d:{note['duration']};w:{wait}")
            last_end = note['start'] + note['duration']
        
        # Replace extra_id token
        token = f"<extra_id_{extra_id}>"
        replacement = "".join(ca_notes) if ca_notes else "N:60;d:240;w:0"
        result = result.replace(token, replacement, 1)
    
    return result

def handle_continuation_generation(input_string, S, extra_ids, temperature, min_length, temp_dir):
    """Handle continuation generation - placeholder for now"""
    return generate_enhanced_fallback(input_string, extra_ids, temperature)

def generate_enhanced_fallback(input_string, extra_ids, temperature):
    """Generate enhanced fallback based on temperature"""
    
    # Base notes - vary by temperature
    if temperature < 0.7:
        base_notes = [60, 64, 67]  # Conservative
    elif temperature > 1.3:
        base_notes = [60, 63, 66, 70, 73]  # Adventurous
    else:
        base_notes = [60, 64, 67, 72]  # Standard
    
    result = input_string
    
    for i, extra_id in enumerate(extra_ids):
        note = base_notes[i % len(base_notes)]
        duration = int(240 * (0.5 + temperature))
        wait = duration if i > 0 else 0
        
        token = f"<extra_id_{extra_id}>"
        replacement = f"N:{note};d:{duration};w:{wait}"
        if i < len(extra_ids) - 1:
            replacement += f"N:{note + 4};d:{duration};w:0"
        result = result.replace(token, replacement, 1)
    
    return result

def generate_simple_fallback(input_string, extra_ids):
    """Simple fallback - just replace tokens"""
    result = input_string
    for extra_id in extra_ids:
        token = f"<extra_id_{extra_id}>"
        replacement = "N:60;d:240;w:240;N:64;d:240;w:240"
        result = result.replace(token, replacement, 1)
    return result

def find_midigpt_model():
    """Find MidiGPT model checkpoint file"""
    possible_paths = [
        "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

if __name__ == "__main__":
    class ThreadedXMLRPCServer(socketserver.ThreadingMixIn, SimpleXMLRPCServer):
        allow_reuse_address = True
    
    print("🎵 Starting MidiGPT Production Server")
    print("Port: 3456")
    print("Ready for REAPER connections...")
    
    try:
        server = ThreadedXMLRPCServer(("localhost", 3456), allow_none=True)
        server.register_function(call_nn_infill)
        server.serve_forever()
        
    except KeyboardInterrupt:
        print("\n🛑 Stopping MidiGPT server...")
        server.shutdown()
    except Exception as e:
        print(f"❌ Server error: {e}")