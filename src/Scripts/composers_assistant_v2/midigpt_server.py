#!/usr/bin/env python3
"""
Unified MidiGPT-REAPER Server
Combines proxy and AI server functionality into single Python 3.9 server
"""

import os
import sys
import json
import re
import tempfile
import uuid
from xmlrpc.server import SimpleXMLRPCServer
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
from typing import Dict, List, Tuple

print('Unified MidiGPT-REAPER Server starting...')

# Configuration
XMLRPC_PORT = 3456
DEBUG = True

# MIDI file handling
TEMP_MIDI_DIR = os.path.join(os.path.dirname(__file__), 'temp_midi')
if not os.path.exists(TEMP_MIDI_DIR):
    os.makedirs(TEMP_MIDI_DIR)

# Import required libraries
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

# Import midigpt (now works with Python 3.9)
try:
    # Add midigpt path if needed
    midigpt_path = os.path.join(os.path.dirname(__file__), "midigpt_workspace", "MIDI-GPT", "python_lib")
    if midigpt_path and os.path.exists(midigpt_path):
        abs_path = os.path.abspath(midigpt_path)
        if abs_path not in sys.path:
            sys.path.insert(0, abs_path)
    
    import midigpt
    print('midigpt module loaded')
    MIDIGPT_AVAILABLE = True
except Exception as e:
    print(f'midigpt not available: {e}')
    MIDIGPT_AVAILABLE = False

# Cache
LAST_CALL = ''
LAST_OUTPUTS = set()

# Default checkpoint path - simplified structure
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
    return DEFAULT_CKPT_PATHS[0]  # Return first path as fallback

DEFAULT_CKPT = get_default_checkpoint()

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
        
        notes.append({
            'pitch': pitch,
            'start': current_time,
            'end': current_time + duration,
            'velocity': 80
        })
        
        current_time += duration + wait
    
    return notes

def create_midi_file_mido(notes: List[Dict], filename: str) -> str:
    """Create MIDI file using mido library"""
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Sort notes by start time
    notes_sorted = sorted(notes, key=lambda n: n['start'])
    
    current_time = 0
    for note in notes_sorted:
        # Note on
        delta_time = note['start'] - current_time
        track.append(mido.Message('note_on', 
                                channel=0, 
                                note=note['pitch'], 
                                velocity=note['velocity'], 
                                time=delta_time))
        
        # Note off
        track.append(mido.Message('note_off', 
                                channel=0, 
                                note=note['pitch'], 
                                velocity=0, 
                                time=note['end'] - note['start']))
        
        current_time = note['end']
    
    mid.save(filename)
    return filename

def create_midi_file_miditoolkit(notes: List[Dict], filename: str) -> str:
    """Create MIDI file using miditoolkit library"""
    import miditoolkit
    
    midi_obj = miditoolkit.MidiFile()
    track = miditoolkit.Instrument(program=0, is_drum=False)
    
    for note in notes:
        midi_note = miditoolkit.Note(
            velocity=note['velocity'],
            pitch=note['pitch'],
            start=note['start'],
            end=note['end']
        )
        track.notes.append(midi_note)
    
    midi_obj.instruments.append(track)
    midi_obj.dump(filename)
    return filename

def create_midi_file(notes: List[Dict]) -> str:
    """Create MIDI file from note list"""
    if not MIDI_LIB_AVAILABLE:
        raise Exception("No MIDI library available")
    
    filename = os.path.join(TEMP_MIDI_DIR, f"input_{uuid.uuid4().hex[:8]}.mid")
    
    if USE_MIDO:
        return create_midi_file_mido(notes, filename)
    else:
        return create_midi_file_miditoolkit(notes, filename)

def extract_extra_ids_from_input(legacy_input: str) -> List[int]:
    """Extract extra_id numbers from input string"""
    extra_id_pattern = r'<extra_id_(\d+)>'
    matches = re.findall(extra_id_pattern, legacy_input)
    return [int(match) for match in matches]

def generate_fallback_content(extra_ids: List[int], bar_count: int = 1) -> str:
    """Generate fallback content when AI is unavailable"""
    result_parts = []
    
    base_pitches = [60, 64, 67, 72, 55]  # C, E, G, C, G
    
    for i, extra_id in enumerate(extra_ids):
        base_pitch = base_pitches[i % len(base_pitches)]
        
        notes = []
        for bar in range(bar_count):
            bar_offset = bar * 960  # 1 bar = 960 ticks
            notes.extend([
                f"N:{base_pitch};d:240;w:240",
                f"N:{base_pitch + 4};d:240;w:240", 
                f"N:{base_pitch + 7};d:240;w:240"
            ])
        
        content = ";".join(notes)
        result_parts.append(f"<extra_id_{extra_id}>{content}")
    
    return ";".join(result_parts)

def process_with_midigpt(midi_file_path: str, extra_ids: List[int], legacy_params: Dict) -> str:
    """Process MIDI file with midigpt and return legacy format result"""
    if not MIDIGPT_AVAILABLE:
        print("midigpt not available, using fallback")
        return generate_fallback_content(extra_ids)
    
    try:
        encoder = midigpt.ExpressiveEncoder()
        piece_json_str = encoder.midi_to_json(midi_file_path)
        piece_json = json.loads(piece_json_str)
        
        print(f"Converted MIDI to protobuf format")
        
        # Determine bars in piece
        actual_bars = 4  # Default
        if 'tracks' in piece_json and piece_json['tracks']:
            actual_bars = len(piece_json['tracks'][0].get('bars', []))
        
        MAX_MODEL_DIM = 4
        model_dim = min(MAX_MODEL_DIM, max(4, actual_bars))
        
        if actual_bars > MAX_MODEL_DIM:
            print(f"Warning: {actual_bars} bars detected, capping to {MAX_MODEL_DIM}")
        
        # Configure for infill mode with context
        selected_bars = [False, True, True, False] if model_dim == 4 else [True] * model_dim
        
        # Setup status for infill generation
        status = {
            'tracks': [{
                'track_id': 0,
                'temperature': legacy_params.get('temperature', 1.0),
                'instrument': 'acoustic_grand_piano',
                'density': 10,
                'track_type': 10,
                'ignore': False,
                'selected_bars': selected_bars,
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY',
                'autoregressive': False,
                'polyphony_hard_limit': legacy_params.get('polyphony_hard_limit', 6)
            }]
        }
        
        # Setup parameters
        params = {
            'tracks_per_step': 1,
            'bars_per_step': 1,
            'model_dim': model_dim,
            'percentage': 100,
            'batch_size': 1,
            'temperature': legacy_params.get('temperature', 1.0),
            'max_steps': 200,
            'polyphony_hard_limit': legacy_params.get('polyphony_hard_limit', 6),
            'shuffle': True,
            'verbose': False,
            'ckpt': DEFAULT_CKPT,
            'sampling_seed': -1,
            'mask_top_k': 0
        }
        
        # Generate with midigpt
        callbacks = midigpt.CallbackManager()
        max_attempts = 3
        
        print("Calling midigpt.sample_multi_step...")
        result = midigpt.sample_multi_step(
            json.dumps(piece_json),
            json.dumps(status), 
            json.dumps(params),
            max_attempts,
            callbacks
        )
        
        if result and len(result) > 0:
            result_json = json.loads(result[0])
            print("AI generation successful")
            
            # Convert result back to legacy format
            # Extract notes from generated MIDI and format with original extra_ids
            legacy_result = convert_midigpt_result_to_legacy(result_json, extra_ids)
            return legacy_result
        else:
            print("AI generation failed, using fallback")
            return generate_fallback_content(extra_ids)
            
    except Exception as e:
        print(f"midigpt processing error: {e}")
        return generate_fallback_content(extra_ids)

def convert_midigpt_result_to_legacy(result_json: Dict, extra_ids: List[int]) -> str:
    """Convert midigpt JSON result back to legacy format with proper extra_id mapping"""
    try:
        result_parts = []
        
        # Extract notes from first track
        if 'tracks' in result_json and result_json['tracks']:
            track = result_json['tracks'][0]
            
            if 'bars' in track:
                all_notes = []
                
                # Collect all notes from all bars
                for bar_idx, bar in enumerate(track['bars']):
                    if 'events' in bar:
                        for event_idx in bar['events']:
                            if event_idx < len(result_json.get('events', [])):
                                event = result_json['events'][event_idx]
                                if 'pitch' in event:
                                    all_notes.append({
                                        'pitch': event['pitch'],
                                        'start': event.get('start', 0),
                                        'end': event.get('end', 240),
                                        'bar': bar_idx
                                    })
                
                # Sort notes by start time
                all_notes.sort(key=lambda n: n['start'])
                
                # Distribute notes across extra_ids
                notes_per_id = max(1, len(all_notes) // len(extra_ids))
                
                for i, extra_id in enumerate(extra_ids):
                    start_idx = i * notes_per_id
                    end_idx = start_idx + notes_per_id if i < len(extra_ids) - 1 else len(all_notes)
                    notes_subset = all_notes[start_idx:end_idx]
                    
                    if notes_subset:
                        legacy_notes = []
                        current_time = 0
                        
                        for note in notes_subset:
                            duration = max(120, note['end'] - note['start'])
                            wait = max(0, note['start'] - current_time)
                            
                            if wait > 0:
                                legacy_notes.append(f"w:{wait}")
                            
                            legacy_notes.append(f"N:{note['pitch']};d:{duration}")
                            current_time = note['start'] + duration
                        
                        content = ";".join(legacy_notes)
                        result_parts.append(f"<extra_id_{extra_id}>{content}")
                    else:
                        # Fallback for this extra_id
                        fallback = generate_fallback_content([extra_id])
                        result_parts.append(fallback)
            
        if not result_parts:
            # Complete fallback
            return generate_fallback_content(extra_ids)
        
        return ";".join(result_parts)
        
    except Exception as e:
        print(f"Legacy conversion error: {e}")
        return generate_fallback_content(extra_ids)

def call_nn_infill(nn_input_string: str, S_dict: Dict, use_sampling: bool = True, 
                  min_length: int = 10, enc_no_repeat_ngram_size: int = 0,
                  has_fully_masked_inst: bool = False, temperature: float = 1.0) -> str:
    """Main XML-RPC endpoint - unified processing"""
    
    try:
        print(f"Processing request: {nn_input_string[:100]}...")
        
        # Check cache
        normalized_input = normalize_requests(nn_input_string)
        global LAST_CALL, LAST_OUTPUTS
        
        if normalized_input == LAST_CALL and LAST_OUTPUTS:
            cached_result = next(iter(LAST_OUTPUTS))
            print("Using cached result")
            return cached_result
        
        # Extract extra_ids from input
        extra_ids = extract_extra_ids_from_input(nn_input_string)
        if not extra_ids:
            extra_ids = [0]  # Default fallback
        
        print(f"Extracted extra_ids: {extra_ids}")
        
        # Parse any existing musical content
        notes = parse_legacy_notes(nn_input_string)
        
        # If no notes, create minimal context
        if not notes:
            notes = [{'pitch': 60, 'start': 0, 'end': 240, 'velocity': 80}]
        
        # Create MIDI file
        midi_file_path = create_midi_file(notes)
        print(f"Created MIDI file: {midi_file_path}")
        
        # Prepare legacy parameters
        legacy_params = {
            'temperature': temperature,
            'polyphony_hard_limit': 6
        }
        
        # Process with midigpt
        result = process_with_midigpt(midi_file_path, extra_ids, legacy_params)
        
        # Cleanup
        try:
            os.remove(midi_file_path)
        except:
            pass
        
        # Update cache
        LAST_CALL = normalized_input
        LAST_OUTPUTS = {result}
        
        print(f"Returning result: {result[:100]}...")
        return result
        
    except Exception as e:
        print(f"Error in call_nn_infill: {e}")
        # Return safe fallback
        extra_ids = extract_extra_ids_from_input(nn_input_string)
        if not extra_ids:
            extra_ids = [0]
        return generate_fallback_content(extra_ids)

class XMLRPCRequestHandler:
    """XML-RPC request handler"""
    
    def call_nn_infill(self, *args):
        """Handle XML-RPC call with flexible argument handling"""
        return call_nn_infill(*args)

def start_xmlrpc_server():
    """Start the XML-RPC server"""
    print(f"Starting XML-RPC server on port {XMLRPC_PORT}")
    
    server = SimpleXMLRPCServer(('127.0.0.1', XMLRPC_PORT), 
                               logRequests=DEBUG, 
                               allow_none=True)
    
    handler = XMLRPCRequestHandler()
    server.register_instance(handler)
    
    try:
        print(f"✅ XML-RPC server ready on port {XMLRPC_PORT}")
        server.serve_forever()
    except KeyboardInterrupt:
        print("XML-RPC server stopped")
    except Exception as e:
        print(f"XML-RPC server error: {e}")

def cleanup_temp_files():
    """Cleanup old temporary files"""
    try:
        if os.path.exists(TEMP_MIDI_DIR):
            for filename in os.listdir(TEMP_MIDI_DIR):
                if filename.endswith('.mid'):
                    filepath = os.path.join(TEMP_MIDI_DIR, filename)
                    if os.path.isfile(filepath):
                        try:
                            os.remove(filepath)
                        except:
                            pass
    except:
        pass

def main():
    """Main entry point"""
    print("MidiGPT-REAPER Server")
    print(f"Python version: {sys.version}")
    print(f"MIDI library available: {MIDI_LIB_AVAILABLE}")
    print(f"midigpt available: {MIDIGPT_AVAILABLE}")
    
    # Cleanup old files
    cleanup_temp_files()
    
    # Start XML-RPC server
    try:
        start_xmlrpc_server()
    except KeyboardInterrupt:
        print("\nShutting down...")
        cleanup_temp_files()

if __name__ == "__main__":
    main()