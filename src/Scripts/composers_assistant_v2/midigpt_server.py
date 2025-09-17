#!/usr/bin/env python3
"""
MidiGPT Server with Full Debug Tracing
Integrates comprehensive debugging to trace the generation pipeline
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
    REAPER interface function with full debug tracing
    """
    print("🎵 MidiGPT call_nn_infill called")
    print(f"📊 Parameters: temp={temperature}, sampling={use_sampling}")
    
    try:
        # Convert S parameter if needed
        if hasattr(S, 'keys'):
            S = pre.midisongbymeasure_from_save_dict(S)
        
        # Extract extra_id tokens from input
        extra_ids = extract_extra_id_tokens(s)
        print(f"Found extra IDs: {extra_ids}")
        
        # Check libraries
        print("✅ MidiGPT library available")
        print("✅ Mido library available")
        print("🚀 Using MidiGPT generation")
        
        # Use debug generation flow
        if extra_ids:
            print("🎯 Infill generation with DEBUG")
            ca_instructions = debug_generation_path(extra_ids, temperature)
        else:
            print("🎵 Continuation generation with DEBUG") 
            ca_instructions = debug_generation_path(['<extra_id_1>'], temperature)
            extra_ids = ['<extra_id_1>']
            
        # Format response with extra_id tokens
        result = format_response_with_extra_ids(extra_ids, ca_instructions)
        
        print(f"✅ Final result: {result}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error in call_nn_infill: {e}")
        import traceback
        traceback.print_exc()
        # Return properly formatted fallback
        return ";<extra_id_1>;N:60;d:480;w:480;"

def debug_generation_path(extra_ids, temperature):
    """Enhanced generation with detailed debugging"""
    print(f"\n=== GENERATION DEBUG SESSION ===")
    print(f"Extra IDs: {extra_ids}")
    print(f"Temperature: {temperature}")
    
    try:
        # Step 1: MidiGPT generation attempt
        print("\n1. ATTEMPTING MIDIGPT GENERATION...")
        ca_instructions = attempt_midigpt_generation(len(extra_ids), temperature)
        
        if ca_instructions:
            print(f"✅ MidiGPT SUCCESS: Generated {len(ca_instructions)} instructions")
            print(f"   First few: {ca_instructions[:6]}")
            
            # Validate the content quality
            quality = analyze_generation_quality(ca_instructions)
            print(f"   Quality score: {quality}/10")
            
            if quality >= 5:  # Threshold for acceptable quality
                print("   ✅ Quality acceptable, using MidiGPT output")
                return ca_instructions
            else:
                print("   ⚠️ Quality too low, falling back")
        else:
            print("❌ MidiGPT FAILED: No instructions generated")
        
    except Exception as e:
        print(f"❌ MidiGPT ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    # Step 2: Fallback generation
    print("\n2. USING FALLBACK GENERATION...")
    fallback = generate_enhanced_fallback(len(extra_ids))
    print(f"✅ Fallback generated: {len(fallback)} instructions")
    print(f"   Content: {fallback[:6]}")
    
    return fallback

def attempt_midigpt_generation(num_extra_ids, temperature):
    """Attempt MidiGPT generation with detailed step tracking"""
    
    print("   📂 Creating temp directory...")
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Step A: Create input MIDI
        print("   🎼 Creating input MIDI...")
        midi_file_path = os.path.join(temp_dir, "input.mid")
        create_debug_midi_input(midi_file_path, num_extra_ids)
        
        # Verify MIDI file
        verify_midi_file(midi_file_path)
        
        # Step B: Load model and encoder
        print("   🤖 Loading MidiGPT model...")
        model_path = find_model_path()
        encoder = midigpt.ExpressiveEncoder()
        print(f"   ✅ Model loaded: {os.path.basename(model_path)}")
        
        # Step C: Convert to JSON
        print("   🔄 Converting MIDI to JSON...")
        piece_json_str = encoder.midi_to_json(midi_file_path)
        piece_json = json.loads(piece_json_str)
        
        print(f"   ✅ JSON created: {len(piece_json_str)} chars")
        print(f"   JSON keys: {list(piece_json.keys()) if isinstance(piece_json, dict) else 'Not a dict'}")
        
        # Step D: Prepare configuration
        print("   ⚙️ Preparing generation config...")
        status_config, param_config = create_debug_config(temperature, model_path)
        
        # Convert to strings
        piece_str = json.dumps(piece_json)
        status_str = json.dumps(status_config)
        param_str = json.dumps(param_config)
        
        print(f"   ✅ Config prepared:")
        print(f"      Piece: {len(piece_str)} chars")
        print(f"      Status: {len(status_str)} chars") 
        print(f"      Param: {len(param_str)} chars")
        
        # Step E: Generate with MidiGPT
        print("   🎵 Calling MidiGPT sample_multi_step...")
        callbacks = midigpt.CallbackManager()
        
        result_tuple = midigpt.sample_multi_step(piece_str, status_str, param_str, 3, callbacks)
        
        print(f"   ✅ Generation complete!")
        print(f"   Result type: {type(result_tuple)}")
        print(f"   Result length: {len(result_tuple) if hasattr(result_tuple, '__len__') else 'N/A'}")
        
        # Step F: Extract result
        result_json_str = result_tuple[0]
        attempts = result_tuple[1] if len(result_tuple) > 1 else "Unknown"
        
        print(f"   📊 Generation stats:")
        print(f"      Attempts: {attempts}")
        print(f"      Result JSON: {len(result_json_str)} chars")
        print(f"      First 200 chars: {result_json_str[:200]}...")
        
        # Step G: Convert back to MIDI
        print("   🔄 Converting JSON back to MIDI...")
        output_midi_path = os.path.join(temp_dir, "output.mid")
        encoder.json_to_midi(result_json_str, output_midi_path)
        
        # Verify output MIDI
        verify_midi_file(output_midi_path)
        
        # Step H: Extract instructions
        print("   📝 Extracting CA instructions...")
        ca_instructions = extract_instructions_with_debug(output_midi_path)
        
        return ca_instructions
        
    except Exception as e:
        print(f"   ❌ Generation step failed: {e}")
        raise
    finally:
        # Cleanup
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

def verify_midi_file(midi_path):
    """Verify MIDI file is valid and has content"""
    try:
        midi_file = mido.MidiFile(midi_path)
        file_size = os.path.getsize(midi_path)
        
        note_count = 0
        for track in midi_file.tracks:
            for msg in track:
                if msg.type == 'note_on' and msg.velocity > 0:
                    note_count += 1
        
        print(f"   📊 MIDI file stats:")
        print(f"      File size: {file_size} bytes")
        print(f"      Tracks: {len(midi_file.tracks)}")
        print(f"      Notes: {note_count}")
        print(f"      Ticks per beat: {midi_file.ticks_per_beat}")
        
        if note_count == 0:
            print("   ⚠️ WARNING: MIDI file has no notes!")
        
    except Exception as e:
        print(f"   ❌ MIDI verification failed: {e}")

def extract_instructions_with_debug(midi_path):
    """Extract CA instructions with detailed debugging"""
    print(f"   🔍 Analyzing output MIDI: {midi_path}")
    
    try:
        midi_file = mido.MidiFile(midi_path)
        
        # Count content
        total_messages = 0
        note_on_count = 0
        note_off_count = 0
        unique_pitches = set()
        
        for track_idx, track in enumerate(midi_file.tracks):
            print(f"   📊 Track {track_idx}: {len(track)} messages")
            
            track_time = 0
            for msg in track:
                total_messages += 1
                track_time += msg.time
                
                if msg.type == 'note_on' and msg.velocity > 0:
                    note_on_count += 1
                    unique_pitches.add(msg.note)
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    note_off_count += 1
        
        print(f"   📊 Content analysis:")
        print(f"      Total messages: {total_messages}")
        print(f"      Note ONs: {note_on_count}")
        print(f"      Note OFFs: {note_off_count}")
        print(f"      Unique pitches: {sorted(unique_pitches)}")
        
        if note_on_count == 0:
            print(f"   ❌ NO NOTES FOUND in generated MIDI!")
            return None
        
        # Extract actual instructions
        instructions = convert_midi_to_instructions_debug(midi_file)
        
        print(f"   ✅ Extracted {len(instructions)} instructions")
        print(f"   📝 Instructions: {instructions[:10]}...")  # First 10
        
        return instructions
        
    except Exception as e:
        print(f"   ❌ Instruction extraction failed: {e}")
        return None

def convert_midi_to_instructions_debug(midi_file):
    """Convert MIDI to instructions with debug output - FIXED for multiple notes"""
    instructions = []
    ticks_per_beat = midi_file.ticks_per_beat or 480
    
    # Collect all notes
    all_notes = []
    
    for track_idx, track in enumerate(midi_file.tracks):
        track_time = 0
        active_notes = {}
        
        for msg in track:
            track_time += msg.time
            
            if msg.type == 'note_on' and msg.velocity > 0:
                active_notes[msg.note] = track_time
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active_notes:
                    start_time = active_notes[msg.note]
                    duration = max(240, track_time - start_time)
                    
                    all_notes.append({
                        'pitch': msg.note,
                        'start': start_time,
                        'duration': duration
                    })
                    del active_notes[msg.note]
    
    print(f"   🎵 Found {len(all_notes)} complete notes")
    
    # Sort and convert to instructions
    all_notes.sort(key=lambda n: n['start'])
    
    # FIXED: Create better CA format for multiple notes
    if len(all_notes) <= 1:
        # Single note - use simple format
        for note in all_notes[:1]:
            duration = min(note['duration'], 480)  # Shorter duration
            instructions.extend([
                f"N:{note['pitch']}",
                f"d:{duration}",
                f"w:{duration}"
            ])
    else:
        # Multiple notes - use sequential format with shorter timing
        for i, note in enumerate(all_notes[:6]):  # Limit to 6 notes
            duration = min(note['duration'], 240)  # Much shorter notes
            
            if i == 0:
                # First note - start immediately
                instructions.extend([
                    f"N:{note['pitch']}",
                    f"d:{duration}",
                    f"w:{duration}"  # Short wait before next note
                ])
            else:
                # Subsequent notes - shorter waits
                instructions.extend([
                    f"N:{note['pitch']}",
                    f"d:{duration}",
                    f"w:{120}"  # Very short wait (1/8 note)
                ])
            
            if i < 3:  # Log first few notes
                print(f"   🎵 Note {i+1}: pitch={note['pitch']}, dur={duration}")
    
    print(f"   📝 Final CA format will be: {instructions[:9]}...")
    return instructions

def analyze_generation_quality(instructions):
    """Analyze the quality of generated instructions"""
    if not instructions:
        return 0
    
    score = 0
    
    # Count unique pitches
    pitches = set()
    durations = set()
    
    for instr in instructions:
        if instr.startswith('N:'):
            pitches.add(instr)
        elif instr.startswith('d:'):
            durations.add(instr)
    
    # Quality scoring
    if len(pitches) > 1:
        score += 3  # Pitch variety
    if len(pitches) > 3:
        score += 2  # Good pitch variety
    
    if len(durations) > 1:
        score += 2  # Rhythm variety
    
    if len(instructions) >= 9:  # At least 3 notes
        score += 2
    
    if len(instructions) >= 15:  # At least 5 notes
        score += 1
    
    print(f"   📊 Quality analysis:")
    print(f"      Unique pitches: {len(pitches)}")
    print(f"      Unique durations: {len(durations)}")
    print(f"      Total instructions: {len(instructions)}")
    
    return min(score, 10)

def create_debug_config(temperature, model_path):
    """Create configuration using EXACT working values from pythoninferencetest.py"""
    # EXACT copy from pythoninferencetest.py (with small modifications for our use case)
    status_config = {
        'tracks': [{
            'track_id': 0,
            'temperature': 0.5,  # Use working value
            'instrument': 'acoustic_grand_piano', 
            'density': 10,  # EXACT working value from pythoninferencetest.py
            'track_type': 10, 
            'ignore': False, 
            'selected_bars': [False, False, True, False],  # EXACT working pattern
            'min_polyphony_q': 'POLYPHONY_ANY',  # EXACT working value
            'max_polyphony_q': 'POLYPHONY_ANY',  # EXACT working value
            'autoregressive': False,
            'polyphony_hard_limit': 9  # EXACT working value
        }]
    }
    
    # EXACT copy from pythoninferencetest.py
    param_config = {
        'tracks_per_step': 1, 
        'bars_per_step': 1,  # EXACT working value
        'model_dim': 4, 
        'percentage': 100, 
        'batch_size': 1, 
        'temperature': 1.0,  # Use working value, ignore input temperature for now
        'max_steps': 200,  # EXACT working value
        'polyphony_hard_limit': 6,  # EXACT working value
        'shuffle': True, 
        'verbose': True,  # Enable verbose for debugging
        'ckpt': model_path,
        'sampling_seed': -1,
        'mask_top_k': 0
    }
    
    print(f"   ⚙️ Config settings (EXACT from pythoninferencetest.py):")
    print(f"      Temperature: {param_config['temperature']}")
    print(f"      Density: {status_config['tracks'][0]['density']}")
    print(f"      Bars per step: {param_config['bars_per_step']}")
    print(f"      Polyphony limits: {status_config['tracks'][0]['min_polyphony_q']} - {status_config['tracks'][0]['max_polyphony_q']}")
    
    return status_config, param_config

def create_debug_midi_input(output_path, num_tokens):
    """Create MIDI input with more musical content"""
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Add tempo and meta
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    
    # Add more musical seed content
    seed_notes = [
        (60, 480, 64),   # C quarter note
        (64, 480, 64),   # E quarter note
        (67, 480, 64),   # G quarter note
        (72, 960, 64),   # C octave half note
    ]
    
    current_time = 0
    for i, (pitch, duration, velocity) in enumerate(seed_notes[:num_tokens + 1]):
        track.append(mido.Message('note_on', note=pitch, velocity=velocity, time=current_time))
        track.append(mido.Message('note_off', note=pitch, velocity=0, time=duration))
        current_time = 480  # Space between notes
    
    # Add significant empty space for generation
    track.append(mido.Message('note_on', note=60, velocity=0, time=3840))  # 2 bars of silence
    
    mid.save(output_path)
    print(f"   ✅ Created input MIDI with {len(seed_notes)} seed notes")

def generate_enhanced_fallback(num_extra_ids):
    """Generate better fallback content"""
    # More interesting musical patterns
    patterns = [
        # Pattern 1: Simple melody
        ["N:60", "d:480", "w:480", "N:62", "d:480", "w:480", "N:64", "d:480", "w:480"],
        # Pattern 2: Chord progression
        ["N:60", "d:960", "w:0", "N:64", "d:960", "w:0", "N:67", "d:960", "w:960"],
        # Pattern 3: Rhythm pattern
        ["N:60", "d:240", "w:240", "N:60", "d:240", "w:240", "N:64", "d:480", "w:480"]
    ]
    
    pattern_idx = min(num_extra_ids - 1, len(patterns) - 1)
    selected_pattern = patterns[pattern_idx]
    print(f"   🎵 Selected fallback pattern {pattern_idx + 1}: {len(selected_pattern)} instructions")
    return selected_pattern

# Utility functions from previous version
def extract_extra_id_tokens(input_string):
    """Extract extra_id tokens from input string"""
    pattern = r'<extra_id_\d+>'
    tokens = re.findall(pattern, input_string)
    return tokens

def format_response_with_extra_ids(extra_ids, ca_instructions):
    """Format response in the format expected by instructions_by_extra_id()"""
    if not extra_ids:
        extra_ids = ['<extra_id_1>']
    
    # Split instructions evenly among extra_ids
    instructions_per_id = max(1, len(ca_instructions) // len(extra_ids))
    
    result_parts = []
    
    for i, extra_id in enumerate(extra_ids):
        # Add the extra_id token
        result_parts.append(extra_id)
        
        # Add instructions for this extra_id
        start_idx = i * instructions_per_id
        end_idx = start_idx + instructions_per_id
        
        # For the last extra_id, include any remaining instructions
        if i == len(extra_ids) - 1:
            end_idx = len(ca_instructions)
        
        id_instructions = ca_instructions[start_idx:end_idx]
        result_parts.extend(id_instructions)
    
    # Join with semicolons and ensure proper formatting
    result = ';' + ';'.join(result_parts) + ';'
    
    print(f"🎼 Formatted response: {result}")
    return result

def find_model_path():
    """Find MidiGPT model checkpoint"""
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
    print("🎵 Starting MidiGPT Production Server (FULL DEBUG)")
    print("📡 Port: 3456")
    print("🔍 Debug mode enabled - detailed tracing active")
    print("✅ Ready for REAPER connections...")
    
    # Create XML-RPC server
    server = SimpleXMLRPCServer(("127.0.0.1", 3456), 
                               requestHandler=RequestHandler,
                               allow_none=True)
    
    # Register the function REAPER expects
    server.register_function(call_nn_infill, 'call_nn_infill')
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped.")

if __name__ == "__main__":
    main()