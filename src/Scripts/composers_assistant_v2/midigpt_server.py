#!/usr/bin/env python3
"""
MidiGPT Server - Production Implementation with Fail-Fast Post-Processing
Integrates the fail-fast functions into the existing server architecture
"""

import sys
import os
import json
import tempfile
import uuid
import re
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

# Import MidiGPT with compatibility layer
try:
    from midigpt_compat import midigpt
    MIDIGPT_AVAILABLE = True
    print("✓ MidiGPT compatibility layer loaded")
except ImportError:
    try:
        import midigpt
        MIDIGPT_AVAILABLE = True
        print("✓ MidiGPT library available")
    except ImportError as e:
        MIDIGPT_AVAILABLE = False
        print(f"✗ MidiGPT not available: {e}")

# Import MIDI library
try:
    import midisong as ms
    print("✓ MIDI library available")
except ImportError as e:
    print(f"✗ MIDI library not available: {e}")

class RequestHandler(SimpleXMLRPCRequestHandler):
    """Custom request handler for better debugging"""
    rpc_paths = ('/RPC2',)
    
    def log_message(self, format, *args):
        print(f"Request: {format % args}")

# =============================================================================
# FAIL-FAST POST-PROCESSING FUNCTIONS
# =============================================================================

def extract_any_notes_from_midi(midi_path):
    """
    Track-agnostic extraction: Process ALL tracks, extract ALL notes
    Convert to CA format based on timing, not track indices
    FAILS FAST - no fallbacks, exposes issues immediately
    """
    if not os.path.exists(midi_path):
        raise FileNotFoundError(f"MIDI file not found: {midi_path}")
    
    midi_file = mido.MidiFile(midi_path)
    all_notes = []
    
    print(f"Processing MIDI file with {len(midi_file.tracks)} tracks")
    
    if len(midi_file.tracks) == 0:
        raise ValueError("MIDI file contains no tracks")
    
    # Extract notes from ALL tracks (bypasses 17-track issue)
    notes_found = False
    for track_idx, track in enumerate(midi_file.tracks):
        track_time = 0
        active_notes = {}  # note_number -> start_time
        track_note_count = 0
        
        for msg in track:
            track_time += msg.time
            
            if msg.type == 'note_on' and msg.velocity > 0:
                active_notes[msg.note] = track_time
                track_note_count += 1
                
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active_notes:
                    start_time = active_notes[msg.note]
                    duration = track_time - start_time
                    
                    if duration <= 0:
                        raise ValueError(f"Invalid note duration {duration} for note {msg.note} in track {track_idx}")
                    
                    all_notes.append({
                        'pitch': msg.note,
                        'start': start_time,
                        'duration': duration,
                        'velocity': getattr(msg, 'velocity', 64),
                        'track': track_idx
                    })
                    del active_notes[msg.note]
                    notes_found = True
        
        print(f"Track {track_idx}: {track_note_count} note_on messages, {len(all_notes)} completed notes")
    
    # Handle any remaining active notes (incomplete notes)
    if active_notes:
        print(f"Warning: {len(active_notes)} notes never received note_off messages")
        for note, start_time in active_notes.items():
            all_notes.append({
                'pitch': note,
                'start': start_time,
                'duration': 480,  # Standard quarter note
                'velocity': 64,
                'track': -1  # Mark as incomplete
            })
            notes_found = True
    
    if not notes_found:
        raise ValueError("No musical notes found in any track of the MIDI file")
    
    # Sort by start time
    all_notes.sort(key=lambda x: x['start'])
    
    print(f"Successfully extracted {len(all_notes)} notes from {len(midi_file.tracks)} tracks")
    return convert_notes_to_ca_format(all_notes)

def convert_notes_to_ca_format(notes):
    """
    Convert extracted notes to Composer's Assistant format
    FAILS FAST - validates all data
    """
    if not notes:
        raise ValueError("No notes provided for CA format conversion")
    
    # Validate note data
    for i, note in enumerate(notes):
        required_keys = ['pitch', 'start', 'duration']
        for key in required_keys:
            if key not in note:
                raise KeyError(f"Note {i} missing required key '{key}': {note}")
        
        if not (0 <= note['pitch'] <= 127):
            raise ValueError(f"Invalid MIDI pitch {note['pitch']} in note {i}")
        
        if note['duration'] <= 0:
            raise ValueError(f"Invalid duration {note['duration']} in note {i}")
    
    # Group notes by measure (assuming 1920 ticks per measure)
    ticks_per_measure = 1920
    measures = {}
    
    for note in notes:
        measure = note['start'] // ticks_per_measure
        if measure not in measures:
            measures[measure] = []
        
        # Convert to CA format with proper timing
        measures[measure].append({
            'pitch': note['pitch'],
            'duration': note['duration'],
            'offset': note['start'] % ticks_per_measure
        })
    
    if not measures:
        raise ValueError("No measures created from note data")
    
    # Build CA string
    ca_parts = []
    total_notes = 0
    
    for measure in sorted(measures.keys()):
        measure_notes = sorted(measures[measure], key=lambda x: x['offset'])
        
        for note in measure_notes:
            ca_parts.extend([
                f"M:{measure}",
                f"N:{note['pitch']}", 
                f"d:{note['duration']}",
                f"w:{note['offset']}"
            ])
            total_notes += 1
    
    if total_notes == 0:
        raise ValueError("No notes converted to CA format")
    
    result = ";" + ";".join(ca_parts) + ";"
    print(f"Generated CA string: {len(result)} chars, {total_notes} notes, {len(measures)} measures")
    
    # Validate CA string format
    if not result.startswith(';') or not result.endswith(';'):
        raise ValueError("CA string format invalid - missing semicolon delimiters")
    
    return result

def create_infill_midi_structure(input_string, num_measures=4):
    """
    Create minimal MIDI structure for MidiGPT infill mode
    FAILS FAST - validates all inputs and outputs
    """
    if input_string is None:
        raise ValueError("Input string cannot be None")
    
    midi_file = mido.MidiFile()
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    
    # Add required tempo message
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    
    # Parse input for any existing context
    context_notes = parse_ca_string_for_context(input_string)
    print(f"Extracted {len(context_notes)} context notes from input")
    
    # Create minimal context structure for infill
    ticks_per_measure = 1920
    note_duration = 480
    
    # Bar 0: Context note (C)
    track.append(mido.Message('note_on', channel=0, note=60, velocity=64, time=0))
    track.append(mido.Message('note_off', channel=0, note=60, velocity=0, time=note_duration))
    
    # Bar 1: Context note (E) - full measure gap from previous note
    track.append(mido.Message('note_on', channel=0, note=64, velocity=64, time=ticks_per_measure-note_duration))
    track.append(mido.Message('note_off', channel=0, note=64, velocity=0, time=note_duration))
    
    # Bar 2: Empty space for generation target (full measure)
    empty_measure_time = ticks_per_measure - note_duration
    
    # Bar 3: Final context note (G) - after empty bar 2
    track.append(mido.Message('note_on', channel=0, note=67, velocity=64, time=empty_measure_time))
    track.append(mido.Message('note_off', channel=0, note=67, velocity=0, time=note_duration))
    
    print(f"MIDI structure: Bar 0 ({note_duration}), gap ({ticks_per_measure-note_duration}), Bar 1 ({note_duration}), gap ({empty_measure_time}), Bar 3 ({note_duration})")
    
    # Validate MIDI structure - calculate actual expected time correctly
    # We have: note_on + note_off + wait + note_on + note_off + wait + note_on + note_off
    # Total: 4320 ticks (note_duration=480, ticks_per_measure=1920, wait_time=1440)
    total_time = sum(msg.time for msg in track if hasattr(msg, 'time'))
    expected_minimum = ticks_per_measure * 2  # At least 2 measures worth
    
    print(f"MIDI timing validation: {total_time} ticks generated, minimum expected: {expected_minimum}")
    
    if total_time < expected_minimum:
        raise ValueError(f"MIDI structure timing invalid: {total_time} < minimum expected {expected_minimum}")
    
    # Save to temp file
    temp_path = tempfile.mktemp(suffix='.mid')
    midi_file.save(temp_path)
    
    # Verify file was created and is readable
    if not os.path.exists(temp_path):
        raise FileNotFoundError(f"Failed to create temporary MIDI file: {temp_path}")
    
    # Test readability
    test_midi = mido.MidiFile(temp_path)
    if len(test_midi.tracks) == 0:
        raise ValueError(f"Created MIDI file has no tracks: {temp_path}")
    
    print(f"Created infill MIDI structure: {temp_path} ({total_time} ticks)")
    return temp_path

def parse_ca_string_for_context(ca_string):
    """Extract existing musical content from CA string - FAILS FAST"""
    if not ca_string:
        return []
    
    if not isinstance(ca_string, str):
        raise TypeError(f"CA string must be string, got {type(ca_string)}")
    
    # Extract notes using regex
    note_pattern = r'N:(\d+)'
    matches = re.findall(note_pattern, ca_string)
    
    notes = []
    for match in matches:
        try:
            pitch = int(match)
            if not (0 <= pitch <= 127):
                raise ValueError(f"Invalid MIDI pitch in CA string: {pitch}")
            notes.append(pitch)
        except ValueError as e:
            raise ValueError(f"Invalid note data in CA string: {match}") from e
    
    return notes[:3]  # Limit context notes

def handle_midigpt_result_conversion(result_json, temp_midi_path):
    """
    Convert MidiGPT JSON result to MIDI file, then extract notes
    FAILS FAST - no error masking
    """
    if result_json is None:
        raise ValueError("MidiGPT result is None")
    
    if not isinstance(result_json, (dict, str)):
        raise TypeError(f"Invalid result type from MidiGPT: {type(result_json)}")
    
    # Import and validate MidiGPT availability
    try:
        import midigpt
    except ImportError as e:
        raise ImportError("MidiGPT module not available") from e
    
    # Create encoder
    try:
        encoder = midigpt.ExpressiveEncoder()
    except Exception as e:
        raise RuntimeError("Failed to create MidiGPT encoder") from e
    
    # Convert JSON to MIDI using MidiGPT's tools
    try:
        encoder.json_to_midi(result_json, temp_midi_path)
    except Exception as e:
        raise RuntimeError(f"MidiGPT json_to_midi conversion failed: {e}") from e
    
    # Verify MIDI file was created
    if not os.path.exists(temp_midi_path):
        raise FileNotFoundError(f"MidiGPT failed to create output file: {temp_midi_path}")
    
    # Verify file is valid MIDI
    try:
        test_midi = mido.MidiFile(temp_midi_path)
        print(f"MidiGPT output: {len(test_midi.tracks)} tracks")
    except Exception as e:
        raise ValueError(f"MidiGPT created invalid MIDI file: {e}") from e
    
    # Extract notes using track-agnostic method
    ca_result = extract_any_notes_from_midi(temp_midi_path)
    
    # Cleanup
    try:
        os.remove(temp_midi_path)
    except OSError:
        print(f"Warning: Could not remove temp file {temp_midi_path}")
    
    return ca_result

def process_midigpt_for_reaper(input_string, midigpt_params=None):
    """
    Complete pipeline: REAPER input -> MidiGPT processing -> REAPER output
    FAILS FAST - exposes all issues immediately
    """
    if input_string is None:
        raise ValueError("Input string cannot be None")
    
    print(f"Processing input string: {len(input_string)} characters")
    
    # Step 1: Create infill MIDI structure
    midi_input_path = create_infill_midi_structure(input_string)
    
    try:
        # Step 2: Import and validate MidiGPT
        try:
            import midigpt
        except ImportError as e:
            raise ImportError("MidiGPT module not available for import") from e
        
        # Step 3: Create encoder and convert to MidiGPT format
        try:
            encoder = midigpt.ExpressiveEncoder()
            piece_json = encoder.midi_to_json(midi_input_path)
        except Exception as e:
            raise RuntimeError(f"Failed to convert MIDI to MidiGPT JSON: {e}") from e
        
        if piece_json is None:
            raise ValueError("MidiGPT encoder returned None for piece_json")
        
        # Step 4: Prepare generation parameters (infill mode)
        status_json = {
            'tracks': [{
                'track_id': 0,
                'temperature': 0.7,
                'instrument': 'acoustic_grand_piano', 
                'density': 10, 
                'track_type': 10, 
                'ignore': False, 
                'selected_bars': [False, False, True, False],  # Generate bar 2
                'min_polyphony_q': 'POLYPHONY_ANY', 
                'max_polyphony_q': 'POLYPHONY_ANY', 
                'autoregressive': False,  # CRITICAL: Use infill mode
                'polyphony_hard_limit': 9 
            }]
        }
        
        param_json = {
            'max_steps_per_bar': 1024,
            'temperature': 0.7,
            'top_p': 0.9
        }
        
        # Step 5: Generate using MidiGPT
        print("Calling MidiGPT sample_multi_step...")
        try:
            result_json = midigpt.sample_multi_step(
                piece_json, status_json, param_json, 
                max_attempts=3, callbacks=[]
            )
        except Exception as e:
            raise RuntimeError(f"MidiGPT sample_multi_step failed: {e}") from e
        
        if not result_json:
            raise ValueError("MidiGPT returned empty result")
        
        if not isinstance(result_json, list) or len(result_json) == 0:
            raise ValueError(f"Invalid MidiGPT result format: {type(result_json)}")
        
        # Step 6: Convert result back to CA format
        temp_output_path = tempfile.mktemp(suffix='.mid')
        ca_result = handle_midigpt_result_conversion(result_json[0], temp_output_path)
        
        return ca_result
        
    finally:
        # Cleanup input file
        try:
            if os.path.exists(midi_input_path):
                os.remove(midi_input_path)
        except OSError:
            print(f"Warning: Could not remove temp input file {midi_input_path}")

# =============================================================================
# LEGACY SERVER FUNCTIONS (PRESERVED)
# =============================================================================

def default_midigpt_params():
    """Return working parameters based on pythoninferencetest.py"""
    return {
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
        'sampling_seed': -1,
        'mask_top_k': 0,
        'ckpt': find_midigpt_checkpoint()
    }

def find_midigpt_checkpoint():
    """Find available MidiGPT checkpoint"""
    possible_paths = [
        "MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    return "MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"

def create_working_status(num_tracks, selected_bars=None):
    """Create status based on working pythoninferencetest.py example"""
    if selected_bars is None:
        selected_bars = [False, False, True, False]
    
    status = {'tracks': []}
    
    for track_id in range(num_tracks):
        track_config = {
            'track_id': track_id,
            'temperature': 0.5,
            'instrument': 'acoustic_grand_piano',
            'density': 10,
            'track_type': 10,
            'ignore': False,
            'selected_bars': selected_bars,
            'min_polyphony_q': 'POLYPHONY_ANY',  # String value from working example
            'max_polyphony_q': 'POLYPHONY_ANY',  # String value from working example
            'autoregressive': False,
            'polyphony_hard_limit': 9
        }
        status['tracks'].append(track_config)
    
    return status

def create_midi_from_s_parameter(S):
    """
    Create MIDI file from S parameter (MidiSongByMeasure object)
    Fixed to use correct dump method instead of to_midi_file
    """
    print("=== EXTRACTING FROM S PARAMETER ===")
    print(f"S type: {type(S)}")
    print(f"Found {len(S.tracks)} tracks in S parameter")
    
    try:
        # Convert S parameter to regular MidiSong first
        midi_song = ms.MidiSong.from_MidiSongByMeasure(S, consume_calling_song=False)
        
        # Create temporary MIDI file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mid')
        temp_path = temp_file.name
        temp_file.close()
        
        # Export to MIDI file using dump method (not to_midi_file)
        midi_song.dump(filename=temp_path)
        print(f"✓ Created MIDI file from S parameter: {temp_path}")
        
        # Debug info about tracks - FIXED: Use correct length access
        for track_idx, track in enumerate(S.tracks):
            num_measures = len(track.tracks_by_measure)  # FIXED: Access tracks_by_measure length
            print(f"Track {track_idx}: {num_measures} measures")
            if hasattr(track, 'inst'):
                print(f"  Instrument: {track.inst}")
        
        return temp_path
        
    except Exception as e:
        print(f"Error extracting from S parameter: {e}")
        import traceback
        traceback.print_exc()
        raise Exception("Failed to extract REAPER content from S parameter")

# =============================================================================
# MAIN REAPER INTERFACE FUNCTION (UPDATED WITH FAIL-FAST)
# =============================================================================

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0):
    """
    Main function called by REAPER - FAIL FAST version with integrated post-processing
    Matches exact signature expected by REAPER scripts
    """
    print(f"🎵 MidiGPT call_nn_infill called")
    print(f"  s: {type(s)} ({len(s) if isinstance(s, str) else 'N/A'} chars)")
    print(f"  S: {type(S)}")
    print(f"  use_sampling: {use_sampling}")
    print(f"  temperature: {temperature}")
    
    # FAIL FAST validation
    if s is None:
        raise ValueError("Input string 's' cannot be None")
    
    if not isinstance(s, str):
        raise TypeError(f"Input 's' must be string, got {type(s)}")
    
    if len(s) == 0:
        raise ValueError("Input string 's' cannot be empty")
    
    # Convert S parameter if needed
    try:
        import preprocessing_functions as pre
    except ImportError as e:
        raise ImportError("preprocessing_functions module not available") from e
    
    if isinstance(S, dict):
        try:
            S = pre.midisongbymeasure_from_save_dict(S)
            print(f"Converted S parameter from dict to MidiSongByMeasure")
        except Exception as e:
            raise ValueError(f"Failed to convert S parameter: {e}") from e
    
    if not MIDIGPT_AVAILABLE:
        raise RuntimeError("MidiGPT not available - cannot process request")
    
    try:
        # Use the fail-fast post-processing pipeline
        result = process_midigpt_for_reaper(s, {
            'temperature': temperature,
            'use_sampling': use_sampling
        })
        
        if not isinstance(result, str):
            raise TypeError(f"Pipeline returned invalid type: {type(result)}")
        
        if len(result) == 0:
            raise ValueError("Pipeline returned empty result")
        
        print(f"Successfully returning {len(result)} characters to REAPER")
        return result
        
    except Exception as e:
        print(f"ERROR in call_nn_infill: {e}")
        import traceback
        traceback.print_exc()
        # Re-raise the exception to expose the issue
        raise

# =============================================================================
# SERVER STARTUP
# =============================================================================

def run_server():
    """Start the XML-RPC server"""
    try:
        server = SimpleXMLRPCServer(('127.0.0.1', 3456), RequestHandler)
        server.register_function(call_nn_infill, 'call_nn_infill')
        
        print(f"MidiGPT Server running on http://127.0.0.1:3456")
        print("Ready to process REAPER requests with fail-fast debugging")
        print(f"MidiGPT Available: {MIDIGPT_AVAILABLE}")
        print(f"MIDI Library Available: {MIDI_LIB_AVAILABLE}")
        
        server.serve_forever()
        
    except KeyboardInterrupt:
        print("MidiGPT server stopped")
    except Exception as e:
        print(f"Server error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_server()