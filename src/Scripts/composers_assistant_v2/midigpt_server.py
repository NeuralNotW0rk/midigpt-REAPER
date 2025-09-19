#!/usr/bin/env python3
"""
MidiGPT Server - Direct Integration Only
Based exactly on pythoninferencetest.py working example
No fallbacks - expose actual MidiGPT issues directly
"""

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

# Add MIDI-GPT path - find where it actually exists
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
else:
    print("CRITICAL ERROR: MIDI-GPT python_lib not found")
    print("Expected locations:")
    for path in midigpt_paths:
        print(f"  {path}")
    sys.exit(1)

# Import required libraries - fail fast if not available
try:
    import mido
    import preprocessing_functions as pre
    print("Base libraries loaded")
except ImportError as e:
    print(f"CRITICAL ERROR: Missing dependency: {e}")
    print("Install: pip install mido miditoolkit")
    sys.exit(1)

# Import MidiGPT with compatibility layer - handles Python 3.9 format issues
try:
    # Try compatibility layer first (recommended for refactored version)
    from midigpt_compat import midigpt
    print("✅ MidiGPT compatibility layer loaded (recommended)")
except ImportError:
    try:
        # Fallback to direct import
        import midigpt
        print("✅ MidiGPT library loaded directly")
    except ImportError as e:
        print(f"CRITICAL ERROR: MidiGPT not available: {e}")
        print("This server requires working MidiGPT installation")
        print("Run: python complete_setup.py")
        sys.exit(1)

class RequestHandler(SimpleXMLRPCRequestHandler):
    """Log all requests for debugging"""
    def log_request(self, code='-', size='-'):
        print(f"XML-RPC request: {self.requestline.strip()}")

def find_model_checkpoint():
    """Find MidiGPT model checkpoint - fail if not found"""
    possible_paths = [
        "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"
    ]
    
    for path in possible_paths:
        full_path = Path(current_dir / path)
        if full_path.exists():
            print(f"Found model: {full_path}")
            return str(full_path)
    
    print("CRITICAL ERROR: Model checkpoint not found")
    print("Expected locations:")
    for path in possible_paths:
        print(f"  {Path(current_dir / path)}")
    raise Exception("MidiGPT model not available")

def parse_ca_string_to_notes(ca_input):
    """Parse CA string into notes with proper timing (from old proxy_nn_server.py)"""
    notes = []
    
    # Extract note patterns: N:pitch;d:duration with optional w:wait
    note_pattern = r'N:(\d+);d:(\d+)(?:;w:(\d+))?'
    wait_pattern = r'w:(\d+)'
    
    current_time = 0
    
    # Split by semicolon and process instructions in order
    instructions = ca_input.split(';')
    
    for instruction in instructions:
        instruction = instruction.strip()
        if not instruction:
            continue
            
        # Check for wait instruction
        if instruction.startswith('w:'):
            wait_time = int(instruction[2:])
            current_time += wait_time
            
        # Check for note instruction
        elif instruction.startswith('N:'):
            # Look for following duration
            note_match = re.match(r'N:(\d+)', instruction)
            if note_match:
                pitch = int(note_match.group(1))
                # Default duration if not specified
                duration = 480  # Default quarter note
                
                notes.append({
                    'pitch': pitch,
                    'start': current_time,
                    'duration': duration,
                    'velocity': 80
                })
                
        # Check for duration instruction (modifies last note)
        elif instruction.startswith('d:') and notes:
            duration = int(instruction[2:])
            notes[-1]['duration'] = duration
    
    return notes

def create_midi_from_ca_input(ca_input, temp_dir):
    """Create MIDI file from CA input with proper timing (like old system)"""
    midi_path = os.path.join(temp_dir, "ca_input.mid")
    
    # Parse CA string to get notes with timing
    notes = parse_ca_string_to_notes(ca_input)
    
    print(f"Parsed CA input: {len(notes)} notes from CA string")
    for note in notes:
        print(f"  Note {note['pitch']}: start={note['start']}, dur={note['duration']}")
    
    # Create MIDI file with proper timing
    mid = mido.MidiFile(ticks_per_beat=96)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Add metadata
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))  # 120 BPM
    track.append(mido.Message('program_change', channel=0, program=0, time=0))
    
    # Sort notes by start time
    notes.sort(key=lambda n: n['start'])
    
    # Convert to MIDI messages with proper timing
    events = []
    
    # Create note on/off events
    for note in notes:
        events.append({
            'time': note['start'],
            'type': 'note_on',
            'note': note['pitch'],
            'velocity': note['velocity']
        })
        events.append({
            'time': note['start'] + note['duration'],
            'type': 'note_off', 
            'note': note['pitch'],
            'velocity': 0
        })
    
    # Sort all events by time
    events.sort(key=lambda e: e['time'])
    
    # Convert to MIDI messages with delta times
    current_time = 0
    for event in events:
        delta_time = event['time'] - current_time
        
        if event['type'] == 'note_on':
            track.append(mido.Message('note_on', 
                                    channel=0, 
                                    note=event['note'], 
                                    velocity=event['velocity'], 
                                    time=delta_time))
        else:
            track.append(mido.Message('note_off', 
                                    channel=0, 
                                    note=event['note'], 
                                    velocity=event['velocity'], 
                                    time=delta_time))
        
        current_time = event['time']
    
    mid.save(midi_path)
    print(f"Created MIDI file from CA input: {midi_path}")
    return midi_path

def generate_with_midigpt(num_tokens, temperature=1.0):
    """Generate using MidiGPT with compatibility layer - handles format conversion"""
    print(f"Starting MidiGPT generation for {num_tokens} tokens")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Initialize encoder - compatibility layer handles format differences
            encoder = midigpt.ExpressiveEncoder()
            
            # Find and load model
            ckpt = find_model_checkpoint()
            
            # Create infill MIDI structure with proper multi-bar content
            input_midi_path = create_infill_midi_structure(temp_dir, num_tokens)
            
            # Convert to JSON - use protobuf format directly for sample_multi_step
            print("Converting MIDI to JSON using protobuf format...")
            midi_json_input = encoder.midi_to_json_protobuf(input_midi_path)
            
            # Debug: Check the converted JSON structure
            try:
                json_data = json.loads(midi_json_input) if isinstance(midi_json_input, str) else midi_json_input
                if isinstance(json_data, dict) and "tracks" in json_data:
                    print(f"✅ Protobuf JSON successful: {len(json_data['tracks'])} tracks found")
                    print(f"   Track 0 has {len(json_data['tracks'][0].get('bars', []))} bars")
                    print(f"   Total events: {len(json_data.get('events', []))}")
                else:
                    print(f"⚠️  Still unexpected JSON structure: {type(json_data)}")
                    print(f"   Data preview: {str(json_data)[:200]}...")
            except Exception as e:
                print(f"⚠️  JSON parsing for debug failed: {e}")
            
            # Create status that matches actual track structure (like pythoninferencetest.py)
            json_data = json.loads(midi_json_input) if isinstance(midi_json_input, str) else midi_json_input
            actual_tracks = json_data.get('tracks', [])
            
            print(f"Configuring status for {len(actual_tracks)} actual tracks in JSON")
            
            valid_status = {
                'tracks': []
            }
            
            # Configure for each actual track in the MIDI (exact pythoninferencetest.py pattern)
            for i in range(len(actual_tracks)):
                track_config = {
                    'track_id': i,  # Use actual track index from JSON
                    'temperature': temperature,
                    'instrument': 'acoustic_grand_piano',
                    'density': 10,
                    'track_type': 10,
                    'ignore': False,
                    'selected_bars': [False, False, True, False],  # Generate only bar 2
                    'min_polyphony_q': 'POLYPHONY_ANY',  # STRING not int
                    'max_polyphony_q': 'POLYPHONY_ANY',  # STRING not int
                    'autoregressive': False,  # CRITICAL: Use infill mode
                    'polyphony_hard_limit': 9
                }
                valid_status['tracks'].append(track_config)
            
            print(f"Created status config with {len(valid_status['tracks'])} track configs")
            
            # Parameters - ensure model_dim matches selected_bars length
            parami = {
                'tracks_per_step': 1,
                'bars_per_step': 1,
                'model_dim': 4,  # Must match selected_bars length (4 bars)
                'percentage': 100,
                'batch_size': 1,
                'temperature': temperature,
                'max_steps': 200,
                'polyphony_hard_limit': 6,
                'shuffle': True,
                'verbose': False,  # Reduce noise
                'ckpt': ckpt,
                'sampling_seed': -1,
                'mask_top_k': 0
            }
            
            # Use protobuf format directly for sampling (exact pythoninferencetest.py pattern)
            piece = midi_json_input  # Use JSON string directly, not re-dumped
            status = json.dumps(valid_status)
            param = json.dumps(parami)
            
            print(f"Calling sample_multi_step with piece={len(piece)} chars, {len(actual_tracks)} tracks")
            
            print("Calling midigpt.sample_multi_step with compatibility layer...")
            
            # Create callback manager and sample - compatibility layer ensures proper format
            callbacks = midigpt.CallbackManager()
            max_attempts = 3
            
            midi_results = midigpt.sample_multi_step(piece, status, param, max_attempts, callbacks)
            
            if not midi_results or len(midi_results) == 0:
                raise Exception("MidiGPT returned empty results")
            
            # Get first result and parse JSON
            midi_str = midi_results[0]
            midi_json = json.loads(midi_str)
            
            print(f"✅ MidiGPT generated {len(midi_str)} chars of JSON")
            
            # Convert back to MIDI file - compatibility layer handles format properly
            output_midi_path = os.path.join(temp_dir, "output.mid")
            encoder.json_to_midi(midi_str, output_midi_path)
            
            if not os.path.exists(output_midi_path):
                raise Exception("MidiGPT failed to create output MIDI file")
            
            # Extract notes from generated MIDI
            notes = extract_notes_from_midi(output_midi_path)
            
            if not notes:
                raise Exception("MidiGPT generated MIDI with no extractable notes")
            
            print(f"✅ Extracted {len(notes)} notes from MidiGPT output")
            return notes
            
        except Exception as e:
            print(f"❌ MidiGPT generation failed: {e}")
            # Print additional debugging info for format-related issues
            if "track_id not on range" in str(e):
                print("   This may be a format compatibility issue")
                print("   Verify midigpt_compat.py is available and working")
            raise  # Don't mask errors

def extract_notes_from_midi(midi_path):
    """Extract notes from MidiGPT output - focus on actual content"""
    notes = []
    
    try:
        mid = mido.MidiFile(midi_path)
        ticks_per_beat = mid.ticks_per_beat or 96
        
        print(f"Analyzing output: {len(mid.tracks)} tracks, {ticks_per_beat} tpb")
        
        # Process all tracks - MidiGPT may put content anywhere
        for track_idx, track in enumerate(mid.tracks):
            track_time = 0
            active_notes = {}
            
            for msg in track:
                track_time += msg.time
                
                if msg.type == 'note_on' and msg.velocity > 0:
                    active_notes[msg.note] = track_time
                
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    if msg.note in active_notes:
                        start_time = active_notes[msg.note]
                        duration = track_time - start_time
                        
                        if duration > 0:  # Valid note
                            notes.append({
                                'track': track_idx,
                                'note': msg.note,
                                'start': start_time,
                                'duration': duration,
                                'velocity': 80  # Default velocity
                            })
                        
                        del active_notes[msg.note]
        
        print(f"Extracted {len(notes)} valid notes")
        return notes
        
    except Exception as e:
        print(f"❌ MIDI extraction failed: {e}")
        raise

def format_ca_response(notes):
    """Convert notes to CA format - only w, d, N, D instructions (no measure markers)"""
    if not notes:
        raise Exception("No notes to format")
    
    # Sort notes by start time
    notes.sort(key=lambda n: n['start'])
    
    ca_parts = []
    current_time = 0
    
    for note in notes:
        # Add wait to reach note position
        wait_time = note['start'] - current_time
        if wait_time > 0:
            ca_parts.append(f"w:{wait_time}")
        
        # Add note and duration (only N and d instructions)
        ca_parts.append(f"N:{note['note']}")
        ca_parts.append(f"d:{note['duration']}")
        
        # Update current time to end of note
        current_time = note['start'] + note['duration']
    
    # Build final CA string with leading semicolon
    result = ";" + ";".join(ca_parts)
    
    print(f"Formatted CA response: {len(result)} chars")
    print(f"   CA content: {result}")
    print(f"   Uses only w/d/N instructions (no measure markers)")
    return result

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0,
                  has_fully_masked_inst=False, temperature=1.0):
    """
    MidiGPT REAPER interface - direct integration using old dual-server approach
    Matches exact signature expected by REAPER
    """
    print(f"\n🎵 MidiGPT call_nn_infill")
    print(f"   Input: {len(s)} chars")
    print(f"   Parameters: temp={temperature}, sampling={use_sampling}")
    print(f"   Input content: {s}")
    
    try:
        # Convert S parameter if needed
        if hasattr(S, 'keys'):
            S = pre.midisongbymeasure_from_save_dict(S)
        
        # Use old dual-server approach: parse CA input and create proper MIDI
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create MIDI file from CA input (like old proxy_nn_server.py)
            input_midi_path = create_midi_from_ca_input(s, temp_dir)
            
            # Process with MidiGPT using the real input
            notes = generate_with_midigpt_from_file(input_midi_path, temperature)
            
            # Format response using old approach
            result = format_ca_response(notes)
            
            print(f"✅ Generated {len(result)} chars")
            return result
        
    except Exception as e:
        print(f"❌ MidiGPT call failed: {e}")
        import traceback
        traceback.print_exc()
        # Return actual error, don't mask
        raise Exception(f"MidiGPT generation failed: {str(e)}")

def main():
    print("🎹 MidiGPT Server - Direct Integration Only")
    print("=" * 50)
    print("Port: 3456")
    print("No fallbacks - actual MidiGPT required")
    
    # Verify MidiGPT setup immediately with detailed error handling
    try:
        print("Testing MidiGPT encoder...")
        encoder = midigpt.ExpressiveEncoder()
        print("✅ MidiGPT encoder created")
        
        print("Testing model checkpoint...")
        model_path = find_model_checkpoint()
        print(f"✅ Model found: {model_path}")
        
        print("✅ All systems operational")
    except Exception as e:
        print(f"❌ CRITICAL: MidiGPT setup failed: {e}")
        import traceback
        traceback.print_exc()
        print("❌ Fix MidiGPT integration before continuing")
        sys.exit(1)
    
    print("\n🚀 Starting XML-RPC server...")
    
    # Create XML-RPC server with detailed error handling
    try:
        server = SimpleXMLRPCServer(("127.0.0.1", 3456), 
                                   requestHandler=RequestHandler,
                                   allow_none=True)
        print("✅ XML-RPC server created on port 3456")
        
        # Register the function REAPER expects
        server.register_function(call_nn_infill, 'call_nn_infill')
        print("✅ Function 'call_nn_infill' registered")
        
    except Exception as e:
        print(f"❌ Server creation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("✅ Ready for REAPER connections...")
    print("Press Ctrl+C to stop")
    
    try:
        print("Starting server.serve_forever()...")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()