#!/usr/bin/env python3
"""
NN Proxy Server - Creates MIDI files for midigpt server to load
"""

import os
import sys
import json
import re
import requests
import tempfile
import uuid
from xmlrpc.server import SimpleXMLRPCServer
from typing import Dict, List, Tuple

print('NN Proxy Server starting...')

# Configuration
XMLRPC_PORT = 3456
MIDIGPT_SERVER_URL = 'http://127.0.0.1:3457'
DEBUG = True

# Shared directory for MIDI files (both proxy and midigpt server can access)
SHARED_MIDI_DIR = os.path.join(os.path.dirname(__file__), 'temp_midi')
if not os.path.exists(SHARED_MIDI_DIR):
    os.makedirs(SHARED_MIDI_DIR)

# Import MIDI library for file creation
try:
    import mido
    print('mido library loaded for MIDI file creation')
    MIDI_LIB_AVAILABLE = True
    USE_MIDO = True
except ImportError:
    try:
        # Fallback to miditoolkit if available
        import miditoolkit
        print('miditoolkit library loaded for MIDI file creation')
        MIDI_LIB_AVAILABLE = True
        USE_MIDO = False
    except ImportError:
        print('No MIDI library available - install mido or miditoolkit')
        MIDI_LIB_AVAILABLE = False

# Simple cache
LAST_CALL = ''
LAST_OUTPUTS = set()

def normalize_requests(input_s: str) -> str:
    """Normalize input for caching"""
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

def parse_legacy_notes(legacy_input: str) -> List[Dict]:
    """Parse legacy REAPER format into note list"""
    note_pattern = r'N:(\d+);d:(\d+)(?:;w:(\d+))?'
    notes = re.findall(note_pattern, legacy_input)
    
    parsed_notes = []
    current_time = 0
    
    for pitch_str, duration_str, wait_str in notes:
        pitch = int(pitch_str)
        duration = int(duration_str)
        wait = int(wait_str) if wait_str else 0
        
        note = {
            'pitch': pitch,
            'velocity': 80,
            'start_time': current_time,
            'duration': duration
        }
        parsed_notes.append(note)
        current_time += duration + wait
    
    return parsed_notes

def create_midi_file(notes: List[Dict], filename: str) -> bool:
    """Create MIDI file using available library"""
    if not MIDI_LIB_AVAILABLE:
        return False
    
    if USE_MIDO:
        return create_midi_file_mido(notes, filename)
    else:
        return create_midi_file_miditoolkit(notes, filename)

def create_midi_file_mido(notes: List[Dict], filename: str) -> bool:
    """Create MIDI file using mido library"""
    try:
        import mido
        
        # Create a new MIDI file
        mid = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        
        # Set tempo (120 BPM)
        track.append(mido.MetaMessage('set_tempo', tempo=500000))
        
        # Convert notes to MIDI events
        events = []
        for note in notes:
            # Note on
            events.append({
                'time': note['start_time'],
                'type': 'note_on',
                'pitch': note['pitch'],
                'velocity': note['velocity']
            })
            # Note off
            events.append({
                'time': note['start_time'] + note['duration'],
                'type': 'note_off', 
                'pitch': note['pitch'],
                'velocity': 0
            })
        
        # Sort events by time
        events.sort(key=lambda x: (x['time'], x['type'] == 'note_off'))
        
        # Convert to delta time and add to track
        last_time = 0
        for event in events:
            delta_time = max(0, event['time'] - last_time)
            
            if event['type'] == 'note_on':
                track.append(mido.Message('note_on', 
                                        channel=0, 
                                        note=event['pitch'], 
                                        velocity=event['velocity'], 
                                        time=delta_time))
            else:  # note_off
                track.append(mido.Message('note_off', 
                                        channel=0, 
                                        note=event['pitch'], 
                                        velocity=0, 
                                        time=delta_time))
            
            last_time = event['time']
        
        # Save the file
        mid.save(filename)
        return True
        
    except Exception as e:
        if DEBUG:
            print(f"Error creating MIDI file with mido: {e}")
        return False

def create_midi_file_miditoolkit(notes: List[Dict], filename: str) -> bool:
    """Create MIDI file using miditoolkit library"""
    try:
        import miditoolkit
        
        # Create new MIDI file
        midi_obj = miditoolkit.MidiFile(ticks_per_beat=480)
        
        # Create instrument track
        instrument = miditoolkit.Instrument(program=0, is_drum=False, name='Piano')
        
        # Add notes
        for note in notes:
            midi_note = miditoolkit.Note(
                velocity=note['velocity'],
                pitch=note['pitch'],
                start=note['start_time'],
                end=note['start_time'] + note['duration']
            )
            instrument.notes.append(midi_note)
        
        midi_obj.instruments.append(instrument)
        midi_obj.dump(filename)
        return True
        
    except Exception as e:
        if DEBUG:
            print(f"Error creating MIDI file with miditoolkit: {e}")
        return False

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, has_fully_masked_inst=False, temperature=1.0):
    """Main function called by REAPER via XMLRPC"""
    global LAST_CALL, LAST_OUTPUTS
    
    if DEBUG:
        print(f"\n{'='*60}")
        print('LEGACY CALL_NN_INFILL RECEIVED')
        print(f"Input: {s[:100]}...")
        print(f"Temperature: {temperature}")
    
    try:
        # Check cache
        s_normalized = normalize_requests(s)
        if s_normalized == LAST_CALL or s_normalized in LAST_OUTPUTS:
            if DEBUG:
                print("Using cached result")
            return "<extra_id_0>N:60;d:240;w:240;N:64;d:240;w:240"
        
        if not MIDI_LIB_AVAILABLE:
            raise Exception("No MIDI library available - install mido or miditoolkit")
        
        # Parse legacy format
        notes = parse_legacy_notes(s)
        
        if not notes:
            raise Exception("No notes found in legacy input")
        
        # Create unique MIDI file
        midi_filename = f"input_{uuid.uuid4().hex[:8]}.mid"
        midi_path = os.path.join(SHARED_MIDI_DIR, midi_filename)
        
        # Create MIDI file
        midi_created = create_midi_file(notes, midi_path)
        
        if not midi_created:
            raise Exception("Failed to create MIDI file")
        
        if DEBUG:
            print(f"Created MIDI file: {midi_path}")
            print(f"Notes converted: {len(notes)}")
        
        # Send MIDI file path to midigpt server
        request_data = {
            'midi_file': midi_path,  # Send file path instead of protobuf
            'legacy_params': {
                'temperature': temperature,
                'use_sampling': use_sampling,
                'min_length': min_length,
                'enc_no_repeat_ngram_size': enc_no_repeat_ngram_size,
                'has_fully_masked_inst': has_fully_masked_inst
            }
        }
        
        response = requests.post(
            f'{MIDIGPT_SERVER_URL}/generate_from_midi',  # New endpoint
            json=request_data,
            timeout=120
        )
        
        if response.status_code != 200:
            raise Exception(f"midigpt server returned {response.status_code}: {response.text}")
        
        result_data = response.json()
        
        if not result_data.get('success', False):
            raise Exception(f"Generation failed: {result_data.get('error')}")
        
        # Get result and convert back to legacy format
        legacy_result = result_data.get('legacy_result', "<extra_id_0>N:60;d:240;w:240;N:64;d:240;w:240")
        
        # Clean up MIDI file
        try:
            os.unlink(midi_path)
        except:
            pass
        
        # Update cache
        LAST_CALL = s_normalized
        LAST_OUTPUTS.add(normalize_requests(legacy_result))
        
        if DEBUG:
            print(f"✅ Successfully generated via MIDI file approach!")
        
        return legacy_result
        
    except Exception as e:
        if DEBUG:
            print(f'Error in MIDI file approach: {e}')
            import traceback
            traceback.print_exc()
        
        # Return fallback
        return "<extra_id_0>N:60;d:240;w:240;N:64;d:240;w:240"

def start_xmlrpc_server():
    """Start the XMLRPC server"""
    try:
        server = SimpleXMLRPCServer(('127.0.0.1', XMLRPC_PORT), logRequests=DEBUG)
        server.register_function(call_nn_infill, 'call_nn_infill')
        
        print(f"NN Proxy Server running on http://127.0.0.1:{XMLRPC_PORT}")
        print(f"MIDI file directory: {SHARED_MIDI_DIR}")
        
        if MIDI_LIB_AVAILABLE:
            lib_name = "mido" if USE_MIDO else "miditoolkit"
            print(f"Using {lib_name} for MIDI file creation")
        else:
            print("⚠️ WARNING: No MIDI library available - install mido or miditoolkit")
        
        server.serve_forever()
        
    except KeyboardInterrupt:
        print("NN server stopped")
    except Exception as e:
        print(f"Server error: {e}")

if __name__ == "__main__":
    start_xmlrpc_server()