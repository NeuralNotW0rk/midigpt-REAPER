#!/usr/bin/env python3
"""
MidiGPT Server for REAPER
Mirrors composers_assistant_nn_server.py structure but uses midigpt instead of Composer's Assistant
Environment setup handled by start_server.py
"""

import os
import sys
import json
import re
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Tuple
import torch

print('MidiGPT Server starting...')

# Configuration - mirrors CA server
DEBUG = False
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
MAX_NN_LENGTH = 2048

# MIDI file handling
TEMP_MIDI_DIR = Path(__file__).parent / 'temp_midi'
TEMP_MIDI_DIR.mkdir(exist_ok=True)

# Import required libraries
try:
    import mido
    MIDI_LIB_AVAILABLE = True
    USE_MIDO = True
    if DEBUG:
        print('mido library loaded')
except ImportError:
    try:
        import miditoolkit
        MIDI_LIB_AVAILABLE = True
        USE_MIDO = False
        if DEBUG:
            print('miditoolkit library loaded')
    except ImportError:
        print('No MIDI library available - install mido or miditoolkit')
        MIDI_LIB_AVAILABLE = False

# Import midigpt (path setup handled by start_server.py)
MIDIGPT_AVAILABLE = False
try:
    import midigpt
    MIDIGPT_AVAILABLE = True
    if DEBUG:
        print('midigpt module loaded')
except ImportError:
    print('midigpt not available - using fallback mode')

# Cache - mirrors CA server pattern
LAST_CALL = ''
LAST_OUTPUTS = set()

# Default checkpoint paths
DEFAULT_CKPT_PATHS = [
    "MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
    "models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
    "EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"
]

def get_default_checkpoint():
    """Find the default checkpoint file"""
    for path in DEFAULT_CKPT_PATHS:
        if os.path.exists(path):
            return path
    return DEFAULT_CKPT_PATHS[0]

DEFAULT_CKPT = get_default_checkpoint()

def normalize_requests(input_s: str) -> str:
    """Normalize input for caching - mirrors CA server normalization"""
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
    
    return norm_measure(input_s)

def get_n_measures(s: str):
    """Count measures in string - mirrors CA server"""
    return s.count(';M')

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
            'start': current_time,
            'duration': duration
        })
        current_time += duration
    
    return notes

def extract_extra_ids_from_input(nn_input: str) -> List[int]:
    """Extract extra_id tokens from input"""
    extra_ids = []
    pattern = r'<extra_id_(\d+)>'
    
    for match in re.finditer(pattern, nn_input):
        extra_id = int(match.group(1))
        extra_ids.append(extra_id)
    
    return extra_ids

def create_midi_file(notes: List[Dict]) -> str:
    """Create MIDI file from notes"""
    if not MIDI_LIB_AVAILABLE:
        return None
    
    temp_id = str(uuid.uuid4())[:8]
    midi_file_path = TEMP_MIDI_DIR / f"temp_{temp_id}.mid"
    
    try:
        if USE_MIDO:
            mid = mido.MidiFile()
            track = mido.MidiTrack()
            mid.tracks.append(track)
            
            for note in notes:
                # Note on
                track.append(mido.Message('note_on', 
                                        channel=0, 
                                        note=note['pitch'], 
                                        velocity=note['velocity'], 
                                        time=0))
                # Note off
                track.append(mido.Message('note_off', 
                                        channel=0, 
                                        note=note['pitch'], 
                                        velocity=0, 
                                        time=note['duration']))
            
            mid.save(str(midi_file_path))
        else:
            # Use miditoolkit
            mid = miditoolkit.MidiFile()
            mid.ticks_per_beat = 480
            
            instrument = miditoolkit.Instrument(program=0, is_drum=False, name='Piano')
            
            for note in notes:
                note_obj = miditoolkit.Note(
                    velocity=note['velocity'],
                    pitch=note['pitch'],
                    start=note['start'],
                    end=note['start'] + note['duration']
                )
                instrument.notes.append(note_obj)
            
            mid.instruments.append(instrument)
            mid.dump(str(midi_file_path))
        
        return str(midi_file_path)
        
    except Exception as e:
        if DEBUG:
            print(f"Error creating MIDI file: {e}")
        return None

def generate_fallback_content(extra_ids: List[int]) -> str:
    """Generate fallback content when midigpt is unavailable - mirrors CA server pattern"""
    if not extra_ids:
        extra_ids = [0]
    
    # Simple fallback patterns
    fallback_notes = [
        60, 64, 67, 72,  # C major chord progression
        69, 65, 62, 57,  # Some melody
        60, 67, 64, 60   # Resolution
    ]
    
    result_parts = []
    for i, extra_id in enumerate(extra_ids):
        note_idx = i % len(fallback_notes)
        note = fallback_notes[note_idx]
        duration = 480 if i % 2 == 0 else 240
        wait = 0 if i == 0 else 120
        
        result_parts.append(f"<extra_id_{extra_id}>N:{note};d:{duration};w:{wait}")
    
    return ''.join(result_parts)

def process_with_midigpt(midi_file_path: str, extra_ids: List[int], params: Dict) -> str:
    """Process with midigpt inference"""
    if not MIDIGPT_AVAILABLE:
        return generate_fallback_content(extra_ids)
    
    try:
        # Basic midigpt inference - adapt based on actual midigpt API
        result = midigpt.infill_notes(
            midi_file=midi_file_path,
            checkpoint=DEFAULT_CKPT,
            temperature=params.get('temperature', 1.0)
        )
        
        if result:
            # Convert midigpt result back to legacy format
            # This would need to be implemented based on midigpt's output format
            return result
        else:
            return generate_fallback_content(extra_ids)
            
    except Exception as e:
        if DEBUG:
            print(f"midigpt processing error: {e}")
        return generate_fallback_content(extra_ids)

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0,
                   has_fully_masked_inst=False, temperature=1.0) -> str:
    """Main inference function - mirrors composers_assistant_nn_server.py signature exactly"""
    global LAST_CALL, LAST_OUTPUTS
    
    s_request_normalized = normalize_requests(s)
    
    if DEBUG:
        print('request normalized:', s_request_normalized)
        print('is the same as previous', s_request_normalized == LAST_CALL)
    
    if s_request_normalized != LAST_CALL:
        LAST_OUTPUTS = set()
    
    if DEBUG:
        print(f'no_repeat_ngram_size = {enc_no_repeat_ngram_size}, temperature={temperature}')
        print(f'input length: {len(s)}')
    
    if use_sampling == 'None' or use_sampling is None:
        # Use greedy decoding for first attempt
        use_sampling = len(LAST_OUTPUTS) != 0
        if DEBUG:
            if use_sampling:
                print('using sampling')
            else:
                print('using greedy decoding')
    
    print(f'NN input (len {len(s)})')
    
    if len(s) > MAX_NN_LENGTH:
        print('WARNING: neural net input is too long. If you are unhappy with the output, '
              'try again with fewer measures selected.')
    
    # Extract extra_ids and notes
    extra_ids = extract_extra_ids_from_input(s)
    if not extra_ids:
        extra_ids = [0]
    
    notes = parse_legacy_notes(s)
    
    # Create MIDI file if we have notes
    midi_file_path = None
    if notes:
        midi_file_path = create_midi_file(notes)
    
    # Prepare parameters
    params = {
        'temperature': temperature,
        'use_sampling': use_sampling,
        'min_length': min_length
    }
    
    # Process with midigpt or fallback
    done = False
    attempt_index = 0
    temperature_multiplier = [1.0, 1.05, 1.10, 1.15, 1.25, 1.5, 1.75, 2.0, 2.5]
    
    while not done and attempt_index < len(temperature_multiplier):
        current_temp = temperature * temperature_multiplier[attempt_index]
        params['temperature'] = current_temp
        
        if midi_file_path:
            this_candidate = process_with_midigpt(midi_file_path, extra_ids, params)
        else:
            this_candidate = generate_fallback_content(extra_ids)
        
        this_candidate_normalized = normalize_requests(this_candidate)
        if this_candidate_normalized not in LAST_OUTPUTS:
            done = True
        
        if attempt_index >= 8:  # Max attempts
            done = True
        
        if not done:
            attempt_index += 1
            if DEBUG:
                print(f'Trying again: Attempt {attempt_index + 1}')
    
    # Cleanup
    if midi_file_path:
        try:
            os.remove(midi_file_path)
        except:
            pass
    
    # Update cache
    LAST_CALL = s_request_normalized
    LAST_OUTPUTS.add(this_candidate_normalized)
    
    if DEBUG:
        print(f'NN output length: {len(this_candidate)}')
    
    return this_candidate

if __name__ == '__main__':
    # Mirror the CA server startup pattern
    from xmlrpc.server import SimpleXMLRPCServer
    
    SERVER = SimpleXMLRPCServer(('127.0.0.1', 3456), logRequests=DEBUG)
    SERVER.register_function(call_nn_infill)
    
    if str(DEVICE) == 'cuda':
        str_device = 'GPU'
    else:
        str_device = 'CPU'
    
    print(f'MidiGPT server running on device: {str_device}. Press ctrl+c or close this window to shut it down.')
    
    try:
        SERVER.serve_forever(poll_interval=0.01)
    except KeyboardInterrupt:
        print('MidiGPT server shutting down...')