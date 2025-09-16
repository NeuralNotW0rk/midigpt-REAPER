#!/usr/bin/env python3
"""
Complete MidiGPT Server with MIDI File Conversion
Converts REAPER string data to MIDI files for MidiGPT processing
"""

import os
import re
import uuid
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Optional
import json

# Server setup
DEBUG = True
MAX_NN_LENGTH = 1024
DEVICE = "cpu"  # or "cuda" if available

# Check for MIDI library availability
try:
    import mido
    USE_MIDO = True
    MIDI_LIB_AVAILABLE = True
    print("Using mido for MIDI file creation")
except ImportError:
    try:
        import miditoolkit
        USE_MIDO = False
        MIDI_LIB_AVAILABLE = True
        print("Using miditoolkit for MIDI file creation")
    except ImportError:
        MIDI_LIB_AVAILABLE = False
        print("WARNING: No MIDI library available - install mido or miditoolkit")

# Check for MidiGPT availability
try:
    import sys
    sys.path.append('MIDI-GPT/python_lib')
    import midigpt
    MIDIGPT_AVAILABLE = True
    print("MidiGPT library available")
except ImportError:
    MIDIGPT_AVAILABLE = False
    print("MidiGPT library not available - using fallback mode")

# Create temp directory for MIDI files
TEMP_MIDI_DIR = Path(tempfile.gettempdir()) / "midigpt_temp"
TEMP_MIDI_DIR.mkdir(exist_ok=True)

# Cache for avoiding repeated requests
LAST_CALL = ''
LAST_OUTPUTS = set()

def normalize_requests(input_s: str) -> str:
    """Normalize input for caching - same as CA server"""
    def norm_extra_id(s):
        first_loc = s.find('<extra_id_')
        if first_loc != -1:
            second_loc = s.find('>', first_loc)
            s = s[:first_loc] + '<e>' + s[second_loc + 1:]
            return norm_extra_id(s)
        return s

    def norm_measure(s):
        first_loc = s.find(';M:')
        if first_loc != -1:
            second_loc = s.find(';', first_loc + 1)
            if second_loc == -1:
                s = s[:first_loc] + '<M>'
            else:
                s = s[:first_loc] + '<M>' + s[second_loc:]
            return norm_measure(s)
        return s

    return norm_measure(norm_extra_id(input_s))

def extract_extra_ids_from_input(s: str) -> List[int]:
    """Extract extra_id tokens from input string"""
    extra_ids = []
    pattern = r'<extra_id_(\d+)>'
    
    for match in re.finditer(pattern, s):
        extra_id = int(match.group(1))
        extra_ids.append(extra_id)
    
    return sorted(list(set(extra_ids)))

def parse_ca_notes_to_midi_events(input_string: str) -> List[Dict]:
    """Parse CA-format string to MIDI events with timing"""
    events = []
    current_time = 0
    current_duration = 480  # Default duration in ticks
    
    # Parse the input string token by token
    tokens = input_string.split(';')
    
    for token in tokens:
        token = token.strip()
        if not token:
            continue
            
        if token.startswith('N:'):
            # Note instruction: N:pitch
            try:
                pitch = int(token.split(':')[1])
                events.append({
                    'type': 'note_on',
                    'time': current_time,
                    'pitch': pitch,
                    'velocity': 80
                })
                events.append({
                    'type': 'note_off',
                    'time': current_time + current_duration,
                    'pitch': pitch,
                    'velocity': 0
                })
            except (ValueError, IndexError):
                continue
                
        elif token.startswith('d:'):
            # Duration instruction: d:duration_in_ticks
            try:
                current_duration = int(token.split(':')[1])
            except (ValueError, IndexError):
                continue
                
        elif token.startswith('w:'):
            # Wait instruction: w:wait_time_in_ticks
            try:
                wait_time = int(token.split(':')[1])
                current_time += wait_time
            except (ValueError, IndexError):
                continue
                
        elif token.startswith('M:'):
            # Measure marker - can be used for timing
            continue
            
        elif token.startswith('<extra_id_'):
            # Extra ID token - skip for now
            continue
    
    return events

def create_midi_file_from_ca_string(input_string: str) -> Optional[str]:
    """Create a MIDI file from CA-format string data"""
    if not MIDI_LIB_AVAILABLE:
        print("ERROR: No MIDI library available")
        return None
    
    # Generate unique filename
    file_id = str(uuid.uuid4())[:8]
    midi_file_path = TEMP_MIDI_DIR / f"ca_input_{file_id}.mid"
    
    try:
        # Parse events from CA string
        events = parse_ca_notes_to_midi_events(input_string)
        
        if not events:
            # Create minimal context MIDI if no notes found
            print("No notes found in input, creating minimal context MIDI")
            return create_minimal_context_midi(str(midi_file_path))
        
        if USE_MIDO:
            # Create MIDI file using mido
            mid = mido.MidiFile(ticks_per_beat=480)
            track = mido.MidiTrack()
            mid.tracks.append(track)
            
            # Sort events by time
            events.sort(key=lambda x: x['time'])
            
            last_time = 0
            for event in events:
                delta_time = event['time'] - last_time
                
                if event['type'] == 'note_on':
                    msg = mido.Message('note_on',
                                     channel=0,
                                     note=event['pitch'],
                                     velocity=event['velocity'],
                                     time=delta_time)
                elif event['type'] == 'note_off':
                    msg = mido.Message('note_off',
                                     channel=0,
                                     note=event['pitch'],
                                     velocity=0,
                                     time=delta_time)
                else:
                    continue
                
                track.append(msg)
                last_time = event['time']
            
            mid.save(str(midi_file_path))
            
        else:
            # Create MIDI file using miditoolkit
            mid = miditoolkit.MidiFile(ticks_per_beat=480)
            instrument = miditoolkit.Instrument(program=0, is_drum=False)
            
            # Convert events to notes
            note_ons = {}
            for event in events:
                if event['type'] == 'note_on':
                    note_ons[event['pitch']] = event
                elif event['type'] == 'note_off' and event['pitch'] in note_ons:
                    note_on = note_ons.pop(event['pitch'])
                    note = miditoolkit.Note(
                        velocity=note_on['velocity'],
                        pitch=event['pitch'],
                        start=note_on['time'],
                        end=event['time']
                    )
                    instrument.notes.append(note)
            
            mid.instruments.append(instrument)
            mid.dump(str(midi_file_path))
        
        print(f"Created MIDI file: {midi_file_path} ({len(events)} events)")
        return str(midi_file_path)
        
    except Exception as e:
        print(f"Error creating MIDI file: {e}")
        return None

def create_minimal_context_midi(output_path: str) -> str:
    """Create a minimal context MIDI file for infilling"""
    if not MIDI_LIB_AVAILABLE:
        return None
    
    try:
        if USE_MIDO:
            mid = mido.MidiFile(ticks_per_beat=480)
            track = mido.MidiTrack()
            mid.tracks.append(track)
            
            # Add a simple note for context
            track.append(mido.Message('note_on', channel=0, note=60, velocity=80, time=0))
            track.append(mido.Message('note_off', channel=0, note=60, velocity=0, time=480))
            
            mid.save(output_path)
        else:
            mid = miditoolkit.MidiFile(ticks_per_beat=480)
            instrument = miditoolkit.Instrument(program=0, is_drum=False)
            
            note = miditoolkit.Note(velocity=80, pitch=60, start=0, end=480)
            instrument.notes.append(note)
            
            mid.instruments.append(instrument)
            mid.dump(output_path)
        
        print(f"Created minimal context MIDI: {output_path}")
        return output_path
        
    except Exception as e:
        print(f"Error creating minimal MIDI: {e}")
        return None

def process_with_midigpt(midi_file_path: str, extra_ids: List[int], params: Dict) -> str:
    """Process MIDI file with MidiGPT using correct API"""
    if not MIDIGPT_AVAILABLE:
        print("MidiGPT not available, using fallback")
        return generate_fallback_content(extra_ids)
    
    try:
        print(f"Processing with MidiGPT: {midi_file_path}")
        
        # Check for model checkpoint - paths relative to Scripts/composers_assistant_v2
        possible_model_paths = [
            "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
            "../../MIDI-GPT/models/model.pt",
            "../../MIDI-GPT/models/model.zip",
            "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
            "MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",  # In case run from project root
            "./EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"  # In case copied to current dir
        ]
        
        model_path = None
        print("Searching for model checkpoint...")
        for path in possible_model_paths:
            abs_path = os.path.abspath(path)
            exists = os.path.exists(path)
            print(f"  Checking: {path} -> {abs_path} {'✅' if exists else '❌'}")
            if exists:
                model_path = path
                print(f"Found model at: {model_path}")
                break
        
        if not model_path:
            print(f"❌ No model found at any of the checked locations.")
            print(f"Current working directory: {os.getcwd()}")
            print("Using fallback mode")
            return generate_fallback_content(extra_ids)
        
        # Create MidiGPT encoder
        encoder = midigpt.ExpressiveEncoder()
        
        # Convert MIDI to JSON format
        midi_json_str = encoder.midi_to_json(midi_file_path)
        midi_data = json.loads(midi_json_str)
        
        print(f"Converted MIDI to JSON: {len(midi_json_str)} chars")
        
        # Configure sampling parameters for infilling
        temperature = params.get('temperature', 1.0)
        
        # Create status configuration for infilling
        status_config = {
            'tracks': [{
                'track_id': 0,
                'temperature': temperature,
                'instrument': 'acoustic_grand_piano',
                'density': 10,
                'track_type': 10,
                'ignore': False,
                'selected_bars': [True] * 4,  # Enable infilling for bars
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY',
                'autoregressive': False,  # Use conditional generation
                'polyphony_hard_limit': 6
            }]
        }
        
        # Create parameter configuration
        param_config = {
            'tracks_per_step': 1,
            'bars_per_step': 1,
            'model_dim': 4,
            'percentage': 100,
            'batch_size': 1,
            'temperature': temperature,
            'max_steps': 50,  # Shorter for faster response
            'polyphony_hard_limit': 6,
            'shuffle': True,
            'verbose': False,  # Reduce output noise
            'ckpt': os.path.abspath(model_path),  # Use absolute path for model
            'sampling_seed': -1,
            'mask_top_k': 0
        }
        
        # Convert to JSON strings
        piece_json = json.dumps(midi_data)
        status_json = json.dumps(status_config)
        param_json = json.dumps(param_config)
        
        print("Calling MidiGPT sample_multi_step...")
        print(f"Model checkpoint: {os.path.abspath(model_path)}")
        
        # Create callback manager
        callbacks = midigpt.CallbackManager()
        
        # Call MidiGPT sampling
        max_attempts = 1  # Single attempt for speed
        result_list = midigpt.sample_multi_step(
            piece_json, status_json, param_json, max_attempts, callbacks
        )
        
        if result_list and len(result_list) > 0:
            result_json = result_list[0]
            print(f"✅ MidiGPT returned: {len(result_json)} chars")
            
            # Convert result back to CA format
            return convert_midigpt_result_to_ca_format(result_json, extra_ids)
        else:
            print("❌ MidiGPT returned empty result")
            return generate_fallback_content(extra_ids)
            
    except Exception as e:
        print(f"❌ MidiGPT processing error: {e}")
        import traceback
        traceback.print_exc()
        return generate_fallback_content(extra_ids)

def convert_midigpt_result_to_ca_format(midigpt_result_json: str, extra_ids: List[int]) -> str:
    """Convert MidiGPT JSON result back to CA string format"""
    try:
        # Parse the JSON result from MidiGPT
        result_data = json.loads(midigpt_result_json)
        
        print(f"Converting MidiGPT result: {len(midigpt_result_json)} chars JSON")
        
        # MidiGPT returns JSON in the same format as input - let's convert it back to MIDI and parse
        # This follows the pattern from pythoninferencetest.py
        
        # Create a temporary MIDI file from the MidiGPT result
        temp_id = str(uuid.uuid4())[:8]
        temp_result_midi = TEMP_MIDI_DIR / f"midigpt_result_{temp_id}.mid"
        
        try:
            # Use MidiGPT's encoder to convert JSON back to MIDI
            encoder = midigpt.ExpressiveEncoder()
            encoder.json_to_midi(midigpt_result_json, str(temp_result_midi))
            
            print(f"Converted MidiGPT JSON to MIDI file: {temp_result_midi}")
            
            # Now read the MIDI file and extract notes for CA format
            if USE_MIDO:
                mid = mido.MidiFile(str(temp_result_midi))
                notes = []
                current_time = 0
                
                for track in mid.tracks:
                    track_time = 0
                    active_notes = {}  # pitch -> start_time
                    
                    for msg in track:
                        track_time += msg.time
                        
                        if msg.type == 'note_on' and msg.velocity > 0:
                            active_notes[msg.note] = track_time
                        elif (msg.type == 'note_off' or 
                              (msg.type == 'note_on' and msg.velocity == 0)):
                            if msg.note in active_notes:
                                start_time = active_notes.pop(msg.note)
                                duration = track_time - start_time
                                notes.append({
                                    'pitch': msg.note,
                                    'start': start_time,
                                    'duration': max(120, duration),  # Minimum duration
                                    'velocity': 80
                                })
                
                print(f"Extracted {len(notes)} notes from MidiGPT result")
                
            else:
                # Use miditoolkit
                mid = miditoolkit.MidiFile(str(temp_result_midi))
                notes = []
                
                for instrument in mid.instruments:
                    if not instrument.is_drum:
                        for note in instrument.notes:
                            notes.append({
                                'pitch': note.pitch,
                                'start': note.start,
                                'duration': max(120, note.end - note.start),
                                'velocity': note.velocity
                            })
                
                print(f"Extracted {len(notes)} notes from MidiGPT result")
            
            # Clean up temp file
            try:
                temp_result_midi.unlink()
            except:
                pass
            
            if notes:
                # Sort notes by start time
                notes.sort(key=lambda x: x['start'])
                
                # Convert to CA format instructions
                ca_instructions = []
                last_end_time = 0
                
                for note in notes:
                    # Add wait if there's a gap
                    if note['start'] > last_end_time:
                        wait_time = note['start'] - last_end_time
                        ca_instructions.append(f"w:{int(wait_time)}")
                    
                    # Add note and duration
                    ca_instructions.append(f"N:{int(note['pitch'])}")
                    ca_instructions.append(f"d:{int(note['duration'])}")
                    
                    last_end_time = note['start'] + note['duration']
                
                # Distribute across extra_ids
                if ca_instructions:
                    instructions_per_id = max(1, len(ca_instructions) // len(extra_ids))
                    result_parts = []
                    
                    for i, extra_id in enumerate(extra_ids):
                        start_idx = i * instructions_per_id
                        end_idx = start_idx + instructions_per_id
                        if i == len(extra_ids) - 1:
                            end_idx = len(ca_instructions)
                        
                        id_instructions = ca_instructions[start_idx:end_idx]
                        if id_instructions:
                            instruction_str = ';'.join(id_instructions)
                            result_parts.append(f"<extra_id_{extra_id}>{instruction_str}")
                    
                    result = ''.join(result_parts)
                    print(f"✅ Converted to CA format: {len(result)} chars")
                    print(f"CA result preview: {result[:100]}...")
                    return result
            
            print("No notes found in converted MIDI, using fallback")
            return generate_fallback_content(extra_ids)
            
        except Exception as e:
            print(f"Error converting MidiGPT JSON to MIDI: {e}")
            # Clean up temp file
            try:
                temp_result_midi.unlink()
            except:
                pass
            return generate_fallback_content(extra_ids)
        
    except Exception as e:
        print(f"Error parsing MidiGPT result: {e}")
        import traceback
        traceback.print_exc()
        return generate_fallback_content(extra_ids)

def generate_fallback_content(extra_ids: List[int]) -> str:
    """Generate fallback content when MidiGPT is unavailable"""
    if not extra_ids:
        extra_ids = [0]
    
    fallback_patterns = [
        "N:60;d:480;w:240;N:64;d:480;w:240;N:67;d:480",
        "N:69;d:240;w:120;N:65;d:240;w:120;N:62;d:480",
        "N:72;d:960;w:480;N:69;d:480;w:240;N:65;d:240",
        "N:57;d:480;w:240;N:60;d:480;w:240;N:64;d:480"
    ]
    
    result_parts = []
    for i, extra_id in enumerate(extra_ids):
        pattern = fallback_patterns[i % len(fallback_patterns)]
        result_parts.append(f"<extra_id_{extra_id}>{pattern}")
    
    return ''.join(result_parts)

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0,
                   has_fully_masked_inst=False, temperature=1.0) -> str:
    """Main inference function - mirrors CA server signature with MIDI file conversion"""
    global LAST_CALL, LAST_OUTPUTS
    
    # CRITICAL: Convert S from dict to object (same as CA server)
    try:
        import preprocessing_functions as pre
        S = pre.midisongbymeasure_from_save_dict(S)
        print(f"Converted song dict to object: {len(S.tracks)} tracks")
    except Exception as e:
        print(f"Warning: Could not convert S parameter: {e}")
        # Continue with S as-is for fallback processing
    
    s_request_normalized = normalize_requests(s)
    
    if DEBUG:
        print(f"\n=== MIDIGPT SERVER REQUEST ===")
        print(f"Input string length: {len(s)} chars")
        print(f"Input preview: {s[:100]}...")
        print(f"Temperature: {temperature}")
        print(f"Use sampling: {use_sampling}")
    
    if s_request_normalized != LAST_CALL:
        LAST_OUTPUTS = set()
    
    if len(s) > MAX_NN_LENGTH:
        print('WARNING: neural net input is too long')
    
    # Extract extra_ids from input
    extra_ids = extract_extra_ids_from_input(s)
    if not extra_ids:
        extra_ids = [0]
    
    print(f"Found extra_ids: {extra_ids}")
    
    # Create MIDI file from CA string data
    midi_file_path = create_midi_file_from_ca_string(s)
    
    if not midi_file_path:
        print("Failed to create MIDI file, using fallback")
        result = generate_fallback_content(extra_ids)
    else:
        # Prepare parameters for MidiGPT
        params = {
            'temperature': temperature,
            'use_sampling': use_sampling,
            'min_length': min_length
        }
        
        # Process with MidiGPT or fallback
        result = process_with_midigpt(midi_file_path, extra_ids, params)
        
        # Clean up temporary MIDI file
        try:
            os.remove(midi_file_path)
            print(f"Cleaned up temp file: {midi_file_path}")
        except:
            pass
    
    # Update cache
    LAST_CALL = s_request_normalized
    result_normalized = normalize_requests(result)
    LAST_OUTPUTS.add(result_normalized)
    
    if DEBUG:
        print(f"Generated result length: {len(result)} chars")
        print(f"Result preview: {result[:100]}...")
        print(f"=== REQUEST COMPLETE ===\n")
    
    return result

if __name__ == '__main__':
    # Start the XML-RPC server
    from xmlrpc.server import SimpleXMLRPCServer
    
    print("="*60)
    print("MidiGPT-REAPER Server with MIDI File Conversion")
    print("="*60)
    print(f"MIDI library: {'✅' if MIDI_LIB_AVAILABLE else '❌'}")
    print(f"MidiGPT library: {'✅' if MIDIGPT_AVAILABLE else '❌ (fallback mode)'}")
    print(f"Temp MIDI directory: {TEMP_MIDI_DIR}")
    print(f"Device: {DEVICE}")
    
    SERVER = SimpleXMLRPCServer(('127.0.0.1', 3456), logRequests=DEBUG)
    SERVER.register_function(call_nn_infill)
    
    print(f"\n🚀 Server running on http://127.0.0.1:3456")
    print("Ready to receive REAPER requests!")
    print("Press Ctrl+C to stop")
    
    try:
        SERVER.serve_forever()
    except KeyboardInterrupt:
        print('\n👋 MidiGPT server shutting down...')
        
        # Clean up temp files
        try:
            for temp_file in TEMP_MIDI_DIR.glob("*.mid"):
                temp_file.unlink()
            print("Cleaned up temporary MIDI files")
        except:
            pass