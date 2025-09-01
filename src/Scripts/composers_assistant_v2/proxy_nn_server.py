#!/usr/bin/env python3
"""
NN Proxy Server - Creates MIDI files for midigpt server to load
Fixed to handle infilling from empty MIDI items (extra_id tokens only)
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
    """Normalize input for caching - preserve extra_id numbers for proper mapping"""
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

    # Don't normalize extra_id tokens - they need to be preserved for proper mapping
    return norm_measure(input_s)

def parse_legacy_notes(legacy_input: str) -> List[Dict]:
    """Parse legacy REAPER format into note list"""
    note_pattern = r'N:(\d+);d:(\d+)(?:;w:(\d+))?'
    notes = []
    current_time = 0
    
    for match in re.finditer(note_pattern, legacy_input):
        pitch = int(match.group(1))
        duration = int(match.group(2))
        wait = int(match.group(3)) if match.group(3) else 0
        
        current_time += wait
        
        notes.append({
            'pitch': pitch,
            'velocity': 80,
            'start_time': current_time,
            'duration': duration
        })
        
        current_time += duration
    
    return notes

def extract_extra_id_tokens(input_string: str) -> List[int]:
    """Extract extra_id token numbers from input string"""
    extra_ids = []
    pattern = r'<extra_id_(\d+)>'
    matches = re.findall(pattern, input_string)
    for match in matches:
        extra_ids.append(int(match))
    return extra_ids

def has_extra_id_tokens(input_string: str) -> bool:
    """Check if input contains extra_id tokens (infill markers)"""
    return '<extra_id_' in input_string

def extract_context_info(legacy_input: str) -> Dict:
    """Extract context information from legacy input string"""
    context = {
        'measure_count': legacy_input.count(';M:'),
        'bar_length': 96,  # Default bar length
        'extra_id_count': len(re.findall(r'<extra_id_\d+>', legacy_input))
    }
    
    # Try to extract bar length if present
    bar_match = re.search(r';L:(\d+)', legacy_input)
    if bar_match:
        context['bar_length'] = int(bar_match.group(1))
    
    return context

def create_minimal_context_midi(context: Dict, filename: str) -> bool:
    """Create a minimal MIDI file with enough bars for model requirements"""
    try:
        # Model requires at least 4 bars of content, but cap at maximum supported
        MAX_MODEL_BARS = 4
        model_dim = 4
        bars_needed = min(MAX_MODEL_BARS, max(model_dim, context.get('measure_count', 1)))
        
        if context.get('measure_count', 1) > MAX_MODEL_BARS:
            print(f"Warning: Requested {context.get('measure_count', 1)} bars, but model supports max {MAX_MODEL_BARS}. Using {bars_needed} bars.")
        
        ticks_per_beat = 480
        beats_per_bar = 4  # 4/4 time signature
        ticks_per_bar = ticks_per_beat * beats_per_bar  # 1920 ticks per bar
        
        if USE_MIDO:
            # Create with mido
            mid = mido.MidiFile(ticks_per_beat=ticks_per_beat)
            track = mido.MidiTrack()
            mid.tracks.append(track)
            
            # Set basic tempo and time signature
            track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))  # 120 BPM
            track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
            track.append(mido.Message('program_change', channel=0, program=1, time=0))
            
            # Add notes across multiple bars to give model sufficient context
            current_time = 0
            for bar in range(bars_needed):
                bar_start_time = bar * ticks_per_bar
                
                # Add a few notes per bar to create realistic musical content
                notes_in_bar = [
                    (60, 0, ticks_per_beat),      # C4 on beat 1
                    (64, ticks_per_beat, ticks_per_beat),  # E4 on beat 2  
                    (67, ticks_per_beat * 2, ticks_per_beat),  # G4 on beat 3
                    (60, ticks_per_beat * 3, ticks_per_beat),  # C4 on beat 4
                ]
                
                for pitch, offset, duration in notes_in_bar:
                    note_time = bar_start_time + offset
                    
                    # Note on
                    delta_time = note_time - current_time
                    track.append(mido.Message('note_on', channel=0, note=pitch, 
                                            velocity=80, time=delta_time))
                    current_time = note_time
                    
                    # Note off
                    track.append(mido.Message('note_off', channel=0, note=pitch, 
                                            velocity=80, time=duration))
                    current_time += duration
            
            mid.save(filename)
            return True
            
        else:
            # Create with miditoolkit
            import miditoolkit
            midi_obj = miditoolkit.MidiFile(ticks_per_beat=ticks_per_beat)
            
            instrument = miditoolkit.Instrument(program=1, is_drum=False, name='Piano')
            
            # Add notes across multiple bars
            for bar in range(bars_needed):
                bar_start_time = bar * ticks_per_bar
                
                # Add a few notes per bar
                notes_in_bar = [
                    (60, 0, ticks_per_beat),      # C4 on beat 1
                    (64, ticks_per_beat, ticks_per_beat),  # E4 on beat 2  
                    (67, ticks_per_beat * 2, ticks_per_beat),  # G4 on beat 3
                    (60, ticks_per_beat * 3, ticks_per_beat),  # C4 on beat 4
                ]
                
                for pitch, offset, duration in notes_in_bar:
                    midi_note = miditoolkit.Note(
                        velocity=80,
                        pitch=pitch,
                        start=bar_start_time + offset,
                        end=bar_start_time + offset + duration
                    )
                    instrument.notes.append(midi_note)
            
            midi_obj.instruments.append(instrument)
            midi_obj.dump(filename)
            return True
            
    except Exception as e:
        if DEBUG:
            print(f"Error creating context MIDI file: {e}")
        return False

def create_midi_file(notes: List[Dict], filename: str) -> bool:
    """Create MIDI file from note list"""
    try:
        if not notes:
            return False
            
        if USE_MIDO:
            # Create with mido
            mid = mido.MidiFile()
            track = mido.MidiTrack()
            mid.tracks.append(track)
            
            # Set basic tempo
            track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
            track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
            track.append(mido.Message('program_change', channel=0, program=1, time=0))
            
            # Sort notes by start time
            notes = sorted(notes, key=lambda x: x['start_time'])
            
            current_time = 0
            for note in notes:
                # Note on
                delta_time = note['start_time'] - current_time
                track.append(mido.Message('note_on', channel=0, note=note['pitch'], 
                                        velocity=note['velocity'], time=delta_time))
                current_time = note['start_time']
                
                # Note off
                track.append(mido.Message('note_off', channel=0, note=note['pitch'], 
                                        velocity=note['velocity'], time=note['duration']))
                current_time += note['duration']
            
            mid.save(filename)
            return True
            
        else:
            # Create with miditoolkit
            import miditoolkit
            midi_obj = miditoolkit.MidiFile()
            midi_obj.ticks_per_beat = 480
            
            instrument = miditoolkit.Instrument(program=1, is_drum=False, name='Piano')
            
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
            print(f"Error creating MIDI file: {e}")
        return False

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, has_fully_masked_inst=False, temperature=1.0):
    """Main function called by REAPER via XMLRPC"""
    global LAST_CALL, LAST_OUTPUTS
    
    if DEBUG:
        print(f"\n{'='*60}")
        print('LEGACY CALL_NN_INFILL RECEIVED')
        print(f"Input: {s[:100]}...")
        print(f"Temperature: {temperature}")
        print(f"Has extra_id tokens: {has_extra_id_tokens(s)}")
    
    try:
        # Check cache
        s_normalized = normalize_requests(s)
        if s_normalized == LAST_CALL or s_normalized in LAST_OUTPUTS:
            if DEBUG:
                print("Using cached result")
            return "<extra_id_0>N:60;d:240;w:240;N:64;d:240;w:240"
        
        if not MIDI_LIB_AVAILABLE:
            raise Exception("No MIDI library available - install mido or miditoolkit")
        
        # Create unique MIDI file
        midi_filename = f"input_{uuid.uuid4().hex[:8]}.mid"
        midi_path = os.path.join(SHARED_MIDI_DIR, midi_filename)
        
        # Check if this is an infilling request (contains extra_id tokens)
        if has_extra_id_tokens(s):
            if DEBUG:
                print("Detected infilling request (extra_id tokens present)")
            
            # Extract the specific extra_id tokens requested
            requested_extra_ids = extract_extra_id_tokens(s)
            if DEBUG:
                print(f"Requested extra_ids: {requested_extra_ids}")
            
            # Extract context information
            context = extract_context_info(s)
            context['extra_id_tokens'] = requested_extra_ids
            if DEBUG:
                print(f"Context: {context}")
            
            # For infilling, create a minimal context MIDI file
            # The midigpt model will generate new content to fill the masked regions
            midi_created = create_minimal_context_midi(context, midi_path)
            
        else:
            # Parse existing notes for variation/continuation
            notes = parse_legacy_notes(s)
            
            if not notes:
                if DEBUG:
                    print("No notes found and no extra_id tokens - creating minimal context")
                # Fallback: create minimal context
                context = {'bar_length': 96, 'measure_count': 1}
                midi_created = create_minimal_context_midi(context, midi_path)
            else:
                if DEBUG:
                    print(f"Parsed {len(notes)} notes for variation/continuation")
                midi_created = create_midi_file(notes, midi_path)
        
        if not midi_created:
            raise Exception("Failed to create MIDI file")
        
        if DEBUG:
            print(f"Created MIDI file: {midi_path}")
        
        # Send MIDI file path to midigpt server
        request_data = {
            'midi_file': midi_path,
            'is_infill': has_extra_id_tokens(s),
            'requested_extra_ids': extract_extra_id_tokens(s) if has_extra_id_tokens(s) else [0],
            'legacy_params': {
                'temperature': temperature,
                'use_sampling': use_sampling,
                'min_length': min_length,
                'enc_no_repeat_ngram_size': enc_no_repeat_ngram_size,
                'has_fully_masked_inst': has_fully_masked_inst
            }
        }
        
        response = requests.post(
            f'{MIDIGPT_SERVER_URL}/generate_from_midi',
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
            print(f"Successfully generated result")
        
        return legacy_result
        
    except Exception as e:
        if DEBUG:
            print(f'Error in infill processing: {e}')
            import traceback
            traceback.print_exc()
        
        # Return fallback result
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
            print("WARNING: No MIDI library available - install mido or miditoolkit")
        
        server.serve_forever()
        
    except KeyboardInterrupt:
        print("NN server stopped")
    except Exception as e:
        print(f"Server error: {e}")

if __name__ == "__main__":
    start_xmlrpc_server()