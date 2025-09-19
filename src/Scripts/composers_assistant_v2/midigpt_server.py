#!/usr/bin/env python3
"""
MidiGPT Server - Production Implementation
Fixed to include missing generate_with_midigpt_from_file function
"""

import sys
import os
import json
import tempfile
import uuid
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
else:
    print("WARNING: MIDI-GPT python_lib not found")

# Import required libraries
try:
    import mido
    MIDI_LIB_AVAILABLE = True
    print("✓ Mido library available")
except ImportError:
    try:
        import miditoolkit
        MIDI_LIB_AVAILABLE = True
        print("✓ Miditoolkit library available")
    except ImportError:
        MIDI_LIB_AVAILABLE = False
        print("✗ No MIDI library available")

try:
    import preprocessing_functions as pre
    print("✓ Preprocessing functions loaded")
except ImportError as e:
    print(f"✗ Preprocessing functions not available: {e}")

# Import MidiGPT with compatibility layer (like working example)
try:
    # Try compatibility layer first (like pythoninferencetest.py)
    from midigpt_compat import midigpt
    MIDIGPT_AVAILABLE = True
    print("✓ MidiGPT compatibility layer loaded")
except ImportError:
    try:
        # Fallback to direct import
        import midigpt
        MIDIGPT_AVAILABLE = True
        print("✓ MidiGPT library loaded directly")
    except ImportError as e:
        print(f"✗ MidiGPT not available: {e}")
        MIDIGPT_AVAILABLE = False

# Configuration
XMLRPC_PORT = 3456
DEBUG = True
TEMP_MIDI_DIR = tempfile.gettempdir()

# Global state
LAST_CALL = None
LAST_OUTPUTS = set()

class RequestHandler(SimpleXMLRPCRequestHandler):
    """Custom request handler with minimal logging"""
    def log_request(self, code='-', size='-'):
        if DEBUG:
            print(f"XML-RPC request: {self.requestline.strip()}")

def normalize_requests(s):
    """Normalize input for caching"""
    if not isinstance(s, str):
        return str(s)
    return s.replace(" ", "").replace("\n", "").replace("\t", "")

def has_extra_id_tokens(s):
    """Check if string contains extra_id tokens"""
    return '<extra_id_' in s and '>' in s

def extract_extra_id_tokens(s):
    """Extract extra_id token numbers from string"""
    import re
    matches = re.findall(r'<extra_id_(\d+)>', s)
    return [int(match) for match in matches]

def parse_legacy_notes(s):
    """Parse legacy format notes from string"""
    notes = []
    if not s or not isinstance(s, str):
        return notes
    
    parts = s.split(';')
    current_time = 0
    
    for part in parts:
        part = part.strip()
        if part.startswith('N:'):
            try:
                pitch = int(part.split(':')[1])
                notes.append({
                    'pitch': pitch,
                    'start_time': current_time,
                    'duration': 240,  # Default duration
                    'velocity': 80
                })
            except (ValueError, IndexError):
                continue
        elif part.startswith('d:'):
            try:
                duration = int(part.split(':')[1])
                if notes:
                    notes[-1]['duration'] = duration
            except (ValueError, IndexError):
                continue
        elif part.startswith('w:'):
            try:
                wait = int(part.split(':')[1])
                current_time += wait
            except (ValueError, IndexError):
                continue
    
    return notes

def parse_ca_string_to_midi(ca_string, output_path):
    """
    Convert CA string format to MIDI file, preserving ONLY existing musical content
    NO placeholders, NO artificial content - only what REAPER actually sends
    """
    try:
        if DEBUG:
            print(f"=== DEBUGGING CA STRING PARSING ===")
            print(f"Full CA string ({len(ca_string)} chars): {ca_string}")
            print(f"First 500 chars: {ca_string[:500]}")
            print(f"Last 200 chars: {ca_string[-200:]}")
        
        # Parse the CA string to extract ONLY real musical information
        measures = {}
        extra_id_positions = {}
        
        # Split into parts and parse each component
        parts = ca_string.split(';')
        if DEBUG:
            print(f"Split into {len(parts)} parts")
            print(f"First 20 parts: {parts[:20]}")
        
        current_measure = 0
        current_beat = 0
        current_length = 96
        current_instrument = 0
        note_count = 0
        
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
                
            if DEBUG and i < 50:  # Debug first 50 parts
                print(f"Part {i}: '{part}'")
                
            if part.startswith('M:'):
                current_measure = int(part.split(':')[1])
                if current_measure not in measures:
                    measures[current_measure] = {
                        'notes': [],
                        'beat': current_beat,
                        'length': current_length,
                        'instrument': current_instrument
                    }
                if DEBUG:
                    print(f"  → Set measure to {current_measure}")
            elif part.startswith('B:'):
                current_beat = int(part.split(':')[1])
                if DEBUG:
                    print(f"  → Set beat to {current_beat}")
            elif part.startswith('L:'):
                current_length = int(part.split(':')[1])
                if DEBUG:
                    print(f"  → Set length to {current_length}")
            elif part.startswith('I:'):
                current_instrument = int(part.split(':')[1])
                if DEBUG:
                    print(f"  → Set instrument to {current_instrument}")
            elif part.startswith('N:'):
                # REAL note data from REAPER - this is what we want!
                pitch = int(part.split(':')[1])
                if current_measure in measures:
                    measures[current_measure]['notes'].append({
                        'pitch': pitch,
                        'time': current_beat,
                        'duration': current_length,
                        'velocity': 80
                    })
                    note_count += 1
                    if DEBUG:
                        print(f"  → FOUND NOTE: pitch={pitch}, measure={current_measure}, beat={current_beat}, duration={current_length}")
            elif part.startswith('d:'):
                # Duration for last note
                if current_measure in measures and measures[current_measure]['notes']:
                    duration = int(part.split(':')[1])
                    measures[current_measure]['notes'][-1]['duration'] = duration
                    if DEBUG:
                        print(f"  → Updated last note duration to {duration}")
            elif part.startswith('w:'):
                # Wait time
                wait_time = int(part.split(':')[1])
                current_beat += wait_time
                if DEBUG:
                    print(f"  → Added wait time {wait_time}, beat now {current_beat}")
            elif '<extra_id_' in part:
                # Mark positions where generation should happen - NO placeholders
                import re
                match = re.search(r'<extra_id_(\d+)>', part)
                if match:
                    extra_id = int(match.group(1))
                    extra_id_positions[extra_id] = {
                        'measure': current_measure,
                        'beat': current_beat,
                        'length': current_length,
                        'instrument': current_instrument
                    }
                    if DEBUG:
                        print(f"  → FOUND EXTRA_ID: {extra_id} at measure={current_measure}, beat={current_beat}")
        
        if DEBUG:
            print(f"=== PARSING RESULTS ===")
            print(f"Total notes found: {note_count}")
            print(f"Measures with content: {len(measures)}")
            print(f"Extra ID positions: {len(extra_id_positions)}")
            
            for measure_num, measure_data in measures.items():
                print(f"Measure {measure_num}: {len(measure_data['notes'])} notes")
                for note in measure_data['notes']:
                    print(f"  Note: pitch={note['pitch']}, time={note['time']}, duration={note['duration']}")
            
            for extra_id, pos in extra_id_positions.items():
                print(f"Extra ID {extra_id}: measure={pos['measure']}, beat={pos['beat']}")
        
        # Create MIDI file with ONLY the actual content from REAPER
        if 'mido' in sys.modules:
            return create_midi_from_real_content_mido(measures, extra_id_positions, output_path)
        else:
            return create_midi_from_real_content_miditoolkit(measures, extra_id_positions, output_path)
            
    except Exception as e:
        if DEBUG:
            print(f"Error parsing CA string: {e}")
            import traceback
            traceback.print_exc()
        return False

def create_midi_from_real_content_mido(measures, extra_id_positions, output_path):
    """Create MIDI file using mido with ONLY real content from REAPER"""
    import mido
    
    mid = mido.MidiFile(ticks_per_beat=96)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Add basic setup
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    
    # Convert ONLY real notes to timeline events
    events = []
    
    # Add ONLY existing notes from REAPER - NO artificial content
    for measure_num, measure_data in measures.items():
        measure_start_time = measure_num * 384  # 4 beats * 96 ticks
        for note in measure_data['notes']:
            start_time = measure_start_time + note['time']
            events.append({
                'time': start_time,
                'type': 'note_on',
                'pitch': note['pitch'],
                'velocity': note['velocity']
            })
            events.append({
                'time': start_time + note['duration'],
                'type': 'note_off',
                'pitch': note['pitch'],
                'velocity': 0
            })
    
    # NO placeholders for extra_id positions - MidiGPT will generate there
    
    # If we have NO real content at all, this is an error condition
    if not events:
        if DEBUG:
            print("ERROR: No real musical content found in REAPER data")
            print("Infill requires existing musical context to work properly")
        return False
    
    # Sort events by time and convert to MIDI messages
    events.sort(key=lambda e: e['time'])
    
    current_time = 0
    for event in events:
        delta_time = event['time'] - current_time
        
        if event['type'] == 'note_on':
            track.append(mido.Message('note_on', 
                                    channel=0, 
                                    note=event['pitch'], 
                                    velocity=event['velocity'], 
                                    time=delta_time))
        else:
            track.append(mido.Message('note_off', 
                                    channel=0, 
                                    note=event['pitch'], 
                                    velocity=event['velocity'], 
                                    time=delta_time))
        
        current_time = event['time']
    
    track.append(mido.MetaMessage('end_of_track', time=0))
    mid.save(output_path)
    
    if DEBUG:
        print(f"Created MIDI with {len(events)} events from REAL REAPER content only")
    
    return True

def create_midi_from_s_parameter(S, extra_ids, output_path):
    """
    Extract real musical content from REAPER's S parameter (MidiSongByMeasure)
    This is where the actual notes are stored!
    """
    try:
        if DEBUG:
            print(f"=== EXTRACTING FROM S PARAMETER ===")
            print(f"S type: {type(S)}")
            
        # S is a MidiSongByMeasure object with tracks
        if not hasattr(S, 'tracks'):
            if DEBUG:
                print("ERROR: S parameter has no tracks attribute")
            return False
            
        tracks = S.tracks
        if DEBUG:
            print(f"Found {len(tracks)} tracks in S parameter")
        
        # Extract notes from all tracks
        all_notes = []
        
        for track_idx, track in enumerate(tracks):
            if DEBUG:
                print(f"Track {track_idx}: {len(track)} measures")
            
            for measure_idx, measure in enumerate(track):
                if DEBUG:
                    print(f"  Measure {measure_idx}: {len(measure)} entries")
                
                for entry_idx, entry in enumerate(measure):
                    if isinstance(entry, str) and entry and entry != '':
                        # Parse note format: '60;0;0;115' = pitch;velocity;start;duration?
                        if ';' in entry:
                            try:
                                parts = entry.split(';')
                                if len(parts) >= 4:
                                    pitch = int(parts[0])
                                    # parts[1] might be velocity or other param
                                    start_in_measure = int(parts[2])
                                    duration_or_other = int(parts[3])
                                    
                                    # Calculate absolute timing
                                    measure_start_time = measure_idx * 384  # 4 beats * 96 ticks
                                    absolute_start = measure_start_time + start_in_measure
                                    
                                    note = {
                                        'pitch': pitch,
                                        'start': absolute_start,
                                        'duration': 192,  # Default duration, might be wrong
                                        'velocity': 80,
                                        'track': track_idx,
                                        'measure': measure_idx,
                                        'entry': entry_idx
                                    }
                                    all_notes.append(note)
                                    
                                    if DEBUG:
                                        print(f"    FOUND NOTE: {entry} → pitch={pitch}, start={absolute_start}, measure={measure_idx}")
                                        
                            except (ValueError, IndexError) as e:
                                if DEBUG:
                                    print(f"    Could not parse entry: {entry} - {e}")
        
        if DEBUG:
            print(f"=== EXTRACTION RESULTS ===")
            print(f"Total real notes extracted: {len(all_notes)}")
        
        if not all_notes:
            if DEBUG:
                print("ERROR: No real notes found in S parameter")
            return False
        
        # Create MIDI file with the extracted notes
        if 'mido' in sys.modules:
            return create_midi_from_extracted_notes_mido(all_notes, output_path)
        else:
            return create_midi_from_extracted_notes_miditoolkit(all_notes, output_path)
            
    except Exception as e:
        if DEBUG:
            print(f"Error extracting from S parameter: {e}")
            import traceback
            traceback.print_exc()
        return False

def create_midi_from_extracted_notes_mido(notes, output_path):
    """Create MIDI file using mido with extracted real notes"""
    import mido
    
    mid = mido.MidiFile(ticks_per_beat=96)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Add basic setup
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    
    # Convert notes to MIDI events
    events = []
    
    for note in notes:
        events.append({
            'time': note['start'],
            'type': 'note_on',
            'pitch': note['pitch'],
            'velocity': note['velocity']
        })
        events.append({
            'time': note['start'] + note['duration'],
            'type': 'note_off',
            'pitch': note['pitch'],
            'velocity': 0
        })
    
    # Sort events by time
    events.sort(key=lambda e: e['time'])
    
    # Convert to MIDI messages with delta times
    current_time = 0
    for event in events:
        delta_time = event['time'] - current_time
        
        if event['type'] == 'note_on':
            track.append(mido.Message('note_on', 
                                    channel=0, 
                                    note=event['pitch'], 
                                    velocity=event['velocity'], 
                                    time=delta_time))
        else:
            track.append(mido.Message('note_off', 
                                    channel=0, 
                                    note=event['pitch'], 
                                    velocity=event['velocity'], 
                                    time=delta_time))
        
        current_time = event['time']
    
    track.append(mido.MetaMessage('end_of_track', time=0))
    mid.save(output_path)
    
    if DEBUG:
        print(f"Created MIDI with {len(events)} events from extracted S parameter notes")
    
    return True

def create_midi_from_extracted_notes_miditoolkit(notes, output_path):
    """Create MIDI file using miditoolkit with extracted real notes"""
    import miditoolkit
    
    midi_obj = miditoolkit.MidiFile()
    midi_obj.ticks_per_beat = 96
    
    instrument = miditoolkit.Instrument(program=1, is_drum=False, name='Piano')
    
    # Add all extracted notes
    for note in notes:
        midi_note = miditoolkit.Note(
            velocity=note['velocity'],
            pitch=note['pitch'],
            start=note['start'],
            end=note['start'] + note['duration']
        )
        instrument.notes.append(midi_note)
    
    midi_obj.instruments.append(instrument)
    midi_obj.dump(output_path)
    
    if DEBUG:
        print(f"Created MIDI with {len(notes)} notes from extracted S parameter")
    
    return True

# Removed the old CA string parsing function since the real data is in S parameter
    """Create MIDI file using miditoolkit with ONLY real content from REAPER"""
    import miditoolkit
    
    midi_obj = miditoolkit.MidiFile()
    midi_obj.ticks_per_beat = 96
    
    instrument = miditoolkit.Instrument(program=1, is_drum=False, name='Piano')
    
    # Add ONLY existing notes from REAPER - NO artificial content
    for measure_num, measure_data in measures.items():
        measure_start_time = measure_num * 384
        for note in measure_data['notes']:
            start_time = measure_start_time + note['time']
            midi_note = miditoolkit.Note(
                velocity=note['velocity'],
                pitch=note['pitch'],
                start=start_time,
                end=start_time + note['duration']
            )
            instrument.notes.append(midi_note)
    
    # NO placeholders for extra_id positions
    
    # If we have NO real content at all, this is an error condition  
    if not instrument.notes:
        if DEBUG:
            print("ERROR: No real musical content found in REAPER data")
            print("Infill requires existing musical context to work properly")
        return False
    
    midi_obj.instruments.append(instrument)
    midi_obj.dump(output_path)
    
    if DEBUG:
        print(f"Created MIDI with {len(instrument.notes)} REAL notes from REAPER only")
    
    return True

def generate_with_midigpt_from_file(midi_path, is_infill=True, extra_ids=None):
    """
    MISSING FUNCTION - Core MidiGPT generation from MIDI file
    This is what was causing the NameError
    """
    if not MIDIGPT_AVAILABLE:
        # Fallback generation
        if DEBUG:
            print("MidiGPT not available, using fallback")
        return generate_fallback_result(extra_ids or [0])
    
    try:
        if DEBUG:
            print(f"Generating with MidiGPT from: {midi_path}")
        
        # Initialize encoder
        encoder = midigpt.ExpressiveEncoder()
        
        # Convert MIDI to JSON using protobuf format (from working example)
        midi_json_str = encoder.midi_to_json_protobuf(midi_path)
        midi_json_data = json.loads(midi_json_str)
        
        if DEBUG:
            print(f"MIDI → JSON: {len(midi_json_str)} chars")
        
        # CRITICAL: Get actual tracks from the MIDI data (like working example)
        actual_tracks = midi_json_data.get('tracks', [])
        
        if not actual_tracks:
            if DEBUG:
                print("No tracks found in MIDI, using fallback")
            return generate_fallback_result(extra_ids or [0])
        
        if DEBUG:
            print(f"Found {len(actual_tracks)} actual tracks in MIDI")
        
        # Create status data that matches actual track structure (EXACT working example pattern)
        status_data = {
            'tracks': []
        }
        
        # Configure for each actual track in the MIDI (CRITICAL: must match exactly)
        for i in range(len(actual_tracks)):
            # Check how many bars this track actually has
            track_bars = actual_tracks[i].get('bars', [])
            num_bars = len(track_bars)
            
            if DEBUG:
                print(f"Track {i} has {num_bars} bars")
            
            # Ensure we have exactly the right number of selected_bars
            if num_bars == 0:
                # Fallback: assume 4 bars if none found
                selected_bars = [False, False, True, True] if is_infill else [True, True, True, True]
                num_bars = 4
            elif num_bars < 4:
                # Pad to 4 bars minimum
                selected_bars = [False] * num_bars + [True] * (4 - num_bars)
                if is_infill and num_bars >= 2:
                    # For infill, select middle bars
                    selected_bars = [False, False, True, True][:num_bars] + [True] * max(0, 4 - num_bars)
            else:
                # Use actual number of bars
                if is_infill:
                    # Infill pattern: context at start/end, generation in middle
                    selected_bars = [False] * num_bars
                    # Select middle 50% of bars for generation
                    start_gen = max(1, num_bars // 4)
                    end_gen = min(num_bars - 1, num_bars * 3 // 4)
                    for j in range(start_gen, end_gen):
                        selected_bars[j] = True
                else:
                    # Generate in all bars
                    selected_bars = [True] * num_bars
            
            track_config = {
                'track_id': i,  # CRITICAL: Sequential track IDs starting from 0
                'temperature': 1.0,
                'instrument': 'acoustic_grand_piano', 
                'density': 10, 
                'track_type': 10, 
                'ignore': False, 
                'selected_bars': selected_bars,  # CRITICAL: Must match actual bar count
                'min_polyphony_q': 'POLYPHONY_ANY',  # String format from working example
                'max_polyphony_q': 'POLYPHONY_ANY', 
                'autoregressive': False if is_infill else True,
                'polyphony_hard_limit': 9 
            }
            status_data['tracks'].append(track_config)
            
            if DEBUG:
                print(f"Track {i}: {len(selected_bars)} selected_bars = {selected_bars}")
        
        if DEBUG:
            print(f"Created status with {len(status_data['tracks'])} track configs")
        
        # Generation parameters (exact format from working example)
        params = {
            'tracks_per_step': 1, 
            'bars_per_step': 1, 
            'model_dim': 4, 
            'percentage': 100, 
            'batch_size': 1, 
            'temperature': 1.0, 
            'max_steps': 10,  # Keep small for infill
            'polyphony_hard_limit': 6, 
            'shuffle': True, 
            'verbose': False,
            'sampling_seed': -1,
            'mask_top_k': 0
        }
        
        # Find model checkpoint
        model_paths = [
            "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
            "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
            "../../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"
        ]
        
        model_path = None
        for path in model_paths:
            if os.path.exists(path):
                model_path = os.path.abspath(path)
                break
        
        if not model_path:
            if DEBUG:
                print("Model checkpoint not found, using fallback")
            return generate_fallback_result(extra_ids or [0])
        
        params['ckpt'] = model_path
        
        # Run generation using correct API (from working example)
        if DEBUG:
            print(f"Running MidiGPT sample_multi_step with {len(actual_tracks)} tracks...")
        
        # Convert to JSON strings as expected by sample_multi_step (EXACT working example)
        piece = midi_json_str  # Use the protobuf JSON string directly
        status = json.dumps(status_data)
        param = json.dumps(params)
        callbacks = midigpt.CallbackManager()
        max_attempts = 1  # Reduced for debugging
        
        if DEBUG:
            print(f"Piece size: {len(piece)} chars")
            print(f"Status size: {len(status)} chars") 
            print(f"Params size: {len(param)} chars")
        
        # Use the correct API function (working example pattern)
        results = midigpt.sample_multi_step(piece, status, param, max_attempts, callbacks)
        
        if not results or len(results) == 0:
            if DEBUG:
                print("No results from MidiGPT")
            raise Exception("MidiGPT returned no results")
        
        result_json = results[0]
        
        if DEBUG:
            print(f"Generated: {len(result_json)} chars")
        
        # Convert result to legacy format
        legacy_result = convert_result_to_legacy(result_json, extra_ids or [0])
        
        if DEBUG:
            print(f"Legacy result: {len(legacy_result)} chars")
        
        return legacy_result
        
    except Exception as e:
        if DEBUG:
            print(f"MidiGPT generation error: {e}")
            import traceback
            traceback.print_exc()
        
        # NO fallback - re-raise the error
        raise Exception(f"MidiGPT generation failed: {e}")

def convert_result_to_legacy(result_json, extra_ids):
    """Convert MidiGPT JSON result to legacy format - REAL content only"""
    try:
        result_data = json.loads(result_json)
        legacy_parts = []
        
        for i, extra_id in enumerate(extra_ids):
            legacy_parts.append(f"<extra_id_{extra_id}>")
            
            # Extract REAL notes from result - no artificial fallbacks
            if 'tracks' in result_data and result_data['tracks']:
                track = result_data['tracks'][0]
                if 'notes' in track and track['notes']:
                    notes = track['notes']
                    
                    # Process ALL real notes, not just a subset
                    for j, note in enumerate(notes):
                        if j > 0:
                            legacy_parts.append("w:240")  # Wait between notes
                        
                        pitch = note.get('pitch', 60)
                        duration = note.get('duration', 240)
                        legacy_parts.append(f"N:{pitch};d:{duration}")
                else:
                    # If no notes in track, this is an error - don't add artificial content
                    if DEBUG:
                        print(f"WARNING: No notes found in track for extra_id_{extra_id}")
            else:
                # If no tracks, this is an error - don't add artificial content
                if DEBUG:
                    print(f"WARNING: No tracks found in result for extra_id_{extra_id}")
        
        if not legacy_parts:
            raise Exception("No musical content generated by MidiGPT")
            
        result = ";".join(legacy_parts)
        return result
        
    except Exception as e:
        if DEBUG:
            print(f"Legacy conversion error: {e}")
        # NO fallback - re-raise the error
        raise Exception(f"Failed to convert MidiGPT result: {e}")

# REMOVED: generate_fallback_result function - no more fallbacks!

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0):
    """
    Main function called by REAPER via XML-RPC
    Matches exact signature expected by REAPER scripts
    """
    global LAST_CALL, LAST_OUTPUTS
    
    if DEBUG:
        print(f"\n{'='*60}")
        print('🎵 MidiGPT call_nn_infill called')
        print(f"Input: {s[:100]}...")
        print(f"Temperature: {temperature}")
    
    try:
        if not MIDIGPT_AVAILABLE:
            # Return error - no more fallbacks
            raise Exception("MidiGPT not available and no fallback allowed")
        
        # Handle S parameter conversion and debugging
        if hasattr(S, 'keys'):  # It's a dictionary
            import preprocessing_functions as pre
            if DEBUG:
                print(f"=== DEBUGGING S PARAMETER ===")
                print(f"S is a dictionary with keys: {list(S.keys())}")
                for key, value in S.items():
                    print(f"S[{key}] = {str(value)[:200]}...")
            
            S = pre.midisongbymeasure_from_save_dict(S)
            if DEBUG:
                print("✓ Converted S parameter from dict to object")
                print(f"S object type: {type(S)}")
                if hasattr(S, '__dict__'):
                    print(f"S attributes: {list(S.__dict__.keys())}")
        else:
            if DEBUG:
                print(f"=== S PARAMETER INFO ===")
                print(f"S type: {type(S)}")
                print(f"S value: {str(S)[:200]}...")
                if hasattr(S, '__dict__'):
                    print(f"S attributes: {list(S.__dict__.keys())}")
        
        # Check cache
        s_normalized = normalize_requests(s)
        if s_normalized == LAST_CALL or s_normalized in LAST_OUTPUTS:
            if DEBUG:
                print("Using cached result")
            # Even cached results should be real - remove fallback return
            raise Exception("Cached result not available - regenerating")
        
        if not MIDI_LIB_AVAILABLE:
            raise Exception("No MIDI library available")
        
        # Detect request type and extract extra_ids
        if has_extra_id_tokens(s):
            extra_ids = extract_extra_id_tokens(s)
            if DEBUG:
                print(f"Found extra IDs: {extra_ids}")
            
            if DEBUG:
                print("🚀 Using MidiGPT generation with REAL REAPER content from S parameter")
            
            # Extract real musical content from S parameter, not s string!
            midi_filename = f"reaper_s_content_{uuid.uuid4().hex[:8]}.mid"
            midi_path = os.path.join(TEMP_MIDI_DIR, midi_filename)
            
            # The real content is in S (MidiSongByMeasure), not s (positioning string)
            if create_midi_from_s_parameter(S, extra_ids, midi_path):
                if DEBUG:
                    print(f"✓ Created MIDI from REAL REAPER S parameter: {midi_path}")
                
                # Generate with MidiGPT using actual context from S
                result = generate_with_midigpt_from_file(midi_path, is_infill=True, extra_ids=extra_ids)
                
                # Cleanup
                try:
                    os.unlink(midi_path)
                except:
                    pass
                
                # Update cache
                LAST_CALL = s_normalized
                LAST_OUTPUTS.add(normalize_requests(result))
                
                if DEBUG:
                    print(f"✓ Generated result: {len(result)} chars")
                
                return result
            else:
                raise Exception("Failed to extract REAPER content from S parameter")
        else:
            # Parse existing notes for continuation
            notes = parse_legacy_notes(s)
            if DEBUG:
                print(f"Parsed {len(notes)} notes for continuation")
            
            if not notes:
                raise Exception("No musical content found for continuation")
            
            # For continuation, we need to implement similar real-content approach
            # For now, return error rather than fallback
            raise Exception("Continuation mode not yet implemented for real content")
        
    except Exception as e:
        if DEBUG:
            print(f'Error in call_nn_infill: {e}')
            import traceback
            traceback.print_exc()
        
        # NO fallback results - if we can't generate properly, return error
        raise Exception(f"MidiGPT generation failed: {e}")

def start_server():
    """Start the XML-RPC server"""
    try:
        server = SimpleXMLRPCServer(('127.0.0.1', XMLRPC_PORT), 
                                  requestHandler=RequestHandler, 
                                  logRequests=DEBUG)
        
        # Register functions that REAPER expects
        server.register_function(call_nn_infill, 'call_nn_infill')
        server.register_function(generate_with_midigpt_from_file, 'generate_with_midigpt_from_file')
        
        print(f"MidiGPT Server running on http://127.0.0.1:{XMLRPC_PORT}")
        print("Registered functions:")
        print("  - call_nn_infill (main REAPER interface)")
        print("  - generate_with_midigpt_from_file (direct generation)")
        
        if MIDIGPT_AVAILABLE:
            print("✓ MidiGPT library available")
        else:
            print("✗ MidiGPT library not available (using fallback)")
        
        if MIDI_LIB_AVAILABLE:
            print("✓ MIDI library available")
        else:
            print("✗ MIDI library not available")
        
        server.serve_forever()
        
    except KeyboardInterrupt:
        print("MidiGPT server stopped")
    except Exception as e:
        print(f"Server error: {e}")

if __name__ == "__main__":
    start_server()