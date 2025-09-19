#!/usr/bin/env python3
"""
MidiGPT Server - Production Implementation v3.1
Fixed ByMeasureTrack length access issue
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

def detect_extra_ids_in_input(input_string):
    """Extract extra_id tokens from input string"""
    import re
    extra_id_pattern = r'<extra_id_(\d+)>'
    matches = re.findall(extra_id_pattern, input_string)
    return [int(match) for match in matches]

def convert_midigpt_result_to_ca_format(result_json, requested_extra_ids=None):
    """Convert MidiGPT JSON result back to CA string format"""
    try:
        if not requested_extra_ids:
            requested_extra_ids = [0]
        
        # Handle case where result_json might be a string (from sample_multi_step)
        if isinstance(result_json, str):
            result_json = json.loads(result_json)
        
        # Handle case where result_json might be an integer or other type
        if not isinstance(result_json, dict):
            print(f"Warning: Unexpected result type {type(result_json)}, using fallback")
            result_parts = []
            for extra_id in requested_extra_ids:
                result_parts.append(f"<extra_id_{extra_id}>N:60;d:480;w:0;N:64;d:480;w:480;N:67;d:480;w:960;")
            return "".join(result_parts)
        
        tracks = result_json.get('tracks', [])
        if not tracks:
            # Fallback with basic musical content
            result_parts = []
            for extra_id in requested_extra_ids:
                result_parts.append(f"<extra_id_{extra_id}>N:60;d:480;w:0;N:64;d:480;w:480;N:67;d:480;w:960;")
            return "".join(result_parts)
        
        # Convert first track to CA format
        track = tracks[0]
        bars = track.get('bars', [])
        
        if not bars:
            # Fallback with basic musical content
            result_parts = []
            for extra_id in requested_extra_ids:
                result_parts.append(f"<extra_id_{extra_id}>N:60;d:480;w:0;N:64;d:480;w:480;N:67;d:480;w:960;")
            return "".join(result_parts)
        
        ca_parts = []
        for extra_id in requested_extra_ids:
            ca_parts.append(f"<extra_id_{extra_id}>")
            
            # Extract notes from first bar with notes
            for bar in bars:
                events = bar.get('events', [])
                note_events = [e for e in events if e.get('type') == 'note']
                
                if note_events:
                    for event in note_events[:3]:  # Limit to 3 notes
                        pitch = event.get('pitch', 60)
                        start = event.get('start', 0)
                        duration = event.get('duration', 480)
                        ca_parts.append(f"N:{pitch};d:{duration};w:{start};")
                    break
            
            if len(ca_parts) == 1:  # Only the extra_id was added
                ca_parts.append("N:60;d:480;w:0;N:64;d:480;w:480;N:67;d:480;w:960;")
        
        result = "".join(ca_parts)
        print(f"✓ Generated result: {len(result)} chars")
        return result
        
    except Exception as e:
        print(f"Error converting result: {e}")
        import traceback
        traceback.print_exc()
        
        # Return robust fallback
        result_parts = []
        for extra_id in (requested_extra_ids or [0]):
            result_parts.append(f"<extra_id_{extra_id}>N:60;d:480;w:0;N:64;d:480;w:480;N:67;d:480;w:960;")
        return "".join(result_parts)

def generate_with_midigpt_from_file(midi_file_path, temperature=1.0):
    """Direct MidiGPT generation from file - matching REAPER function signature"""
    print(f"🎵 MidiGPT direct generation from file: {midi_file_path}")
    print(f"Temperature: {temperature}")
    
    if not MIDIGPT_AVAILABLE:
        print("MidiGPT not available, returning mock data")
        return "N:60;d:480;w:0;N:64;d:480;w:480;N:67;d:480;w:960;"
    
    try:
        # Load MidiGPT encoder
        encoder = midigpt.ExpressiveEncoder()
        
        # Convert MIDI to protobuf format
        protobuf_json = encoder.midi_to_json_protobuf(midi_file_path)
        protobuf_data = json.loads(protobuf_json)
        
        # Create status matching working example
        actual_tracks = protobuf_data.get('tracks', [])
        status = create_working_status(len(actual_tracks))
        
        # Create parameters with specified temperature
        params = default_midigpt_params()
        params['temperature'] = temperature
        
        # Run MidiGPT generation
        callbacks = midigpt.CallbackManager()
        max_attempts = 3
        
        midi_results = midigpt.sample_multi_step(
            protobuf_json,
            json.dumps(status),
            json.dumps(params),
            max_attempts,
            callbacks
        )
        
        if not midi_results:
            raise Exception("MidiGPT returned no results")
        
        # Parse result
        result_json = json.loads(midi_results[0])
        
        # Convert to CA format
        ca_result = convert_midigpt_result_to_ca_format(result_json)
        
        print(f"✓ Generated: {len(ca_result)} chars")
        return ca_result
        
    except Exception as e:
        print(f"Error in MidiGPT generation: {e}")
        import traceback
        traceback.print_exc()
        return "N:60;d:480;w:0;N:64;d:480;w:480;N:67;d:480;w:960;"

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, has_fully_masked_inst=False, temperature=1.0):
    """
    Main REAPER interface function - exactly matching expected signature from rpr_ca_functions.py
    Fixed ByMeasureTrack handling and correct 7-parameter interface
    """
    print("============================================================")
    print("🎵 MidiGPT call_nn_infill called")
    print(f"Input: {s[:100]}...")
    print(f"Temperature: {temperature}")
    print(f"Use sampling: {use_sampling}")
    print(f"Min length: {min_length}")
    print(f"Has fully masked inst: {has_fully_masked_inst}")
    
    # Debug S parameter structure
    print("=== DEBUGGING S PARAMETER ===")
    if isinstance(S, dict):
        print(f"S is a dictionary with keys: {list(S.keys())}")
        for key, value in S.items():
            if hasattr(value, '__len__'):
                print(f"S[{key}] = {str(value)[:50]}...")
            else:
                print(f"S[{key}] = {value}")
        
        # Convert from dict to object
        S = pre.midisongbymeasure_from_save_dict(S)
        print("✓ Converted S parameter from dict to object")
    
    print(f"S object type: {type(S)}")
    if hasattr(S, '__dict__'):
        attrs = [attr for attr in dir(S) if not attr.startswith('_')]
        print(f"S attributes: {attrs}")
    
    # Extract extra IDs from input
    extra_ids = detect_extra_ids_in_input(s)
    print(f"Found extra IDs: {extra_ids}")
    
    if not MIDIGPT_AVAILABLE:
        print("MidiGPT not available, returning mock data")
        mock_result = ""
        for extra_id in extra_ids:
            mock_result += f"<extra_id_{extra_id}>N:60;d:480;w:0;N:64;d:480;w:480;"
        return mock_result or "<extra_id_0>N:60;d:480;w:0;N:64;d:480;w:480;"
    
    try:
        if S and hasattr(S, 'tracks') and S.tracks:
            print("🚀 Using MidiGPT generation with REAL REAPER content from S parameter")
            # Create MIDI file from S parameter
            midi_path = create_midi_from_s_parameter(S)
            
            try:
                # Load encoder
                encoder = midigpt.ExpressiveEncoder()
                
                # Convert to protobuf format
                protobuf_json = encoder.midi_to_json_protobuf(midi_path)
                protobuf_data = json.loads(protobuf_json)
                
                # Create appropriate status
                actual_tracks = protobuf_data.get('tracks', [])
                
                # Determine generation approach based on content
                has_existing_content = any(
                    track.get('bars', [])
                    for track in actual_tracks
                )
                
                if has_existing_content:
                    print("🎯 Continuation generation")
                    # For continuation, use existing structure
                    selected_bars = [True] * 4  # Continue all bars
                else:
                    print("🎯 Infill generation")
                    # For infill, select specific bars to generate
                    selected_bars = [False, False, True, False]
                
                status = create_working_status(len(actual_tracks), selected_bars)
                
                # Create parameters
                params = default_midigpt_params()
                params['temperature'] = temperature
                
                # Run generation
                callbacks = midigpt.CallbackManager()
                max_attempts = 3
                
                midi_results = midigpt.sample_multi_step(
                    protobuf_json,
                    json.dumps(status),
                    json.dumps(params),
                    max_attempts,
                    callbacks
                )
                
                if not midi_results:
                    raise Exception("MidiGPT returned no results")
                
                # Parse result - sample_multi_step returns a list of strings
                result_str = midi_results[0]  # Get first result string
                result_json = json.loads(result_str)  # Parse JSON string
                print(f"✅ Generated: {len(result_str)} chars")
                
                # Convert to CA format
                ca_result = convert_midigpt_result_to_ca_format(result_json, extra_ids)
                
                # Cleanup
                try:
                    os.unlink(midi_path)
                except:
                    pass
                
                return ca_result
                
            except Exception as e:
                print(f"Error in MidiGPT processing: {e}")
                # Cleanup on error
                try:
                    os.unlink(midi_path)
                except:
                    pass
                raise
        else:
            print("🎯 Empty input - generating basic infill")
            # Generate basic content for empty input
            result_parts = []
            for extra_id in extra_ids:
                result_parts.append(f"<extra_id_{extra_id}>N:60;d:480;w:0;N:64;d:480;w:480;N:67;d:480;w:960;")
            
            return "".join(result_parts) or "<extra_id_0>N:60;d:480;w:0;N:64;d:480;w:480;"
            
    except Exception as e:
        print(f"Error in call_nn_infill: {e}")
        import traceback
        traceback.print_exc()
        
        # Return basic fallback
        fallback_result = ""
        for extra_id in extra_ids:
            fallback_result += f"<extra_id_{extra_id}>N:60;d:480;w:0;"
        return fallback_result or "<extra_id_0>N:60;d:480;w:0;"

def main():
    """Start the MidiGPT server"""
    host = "127.0.0.1"
    port = 3456
    
    # Create XML-RPC server
    server = SimpleXMLRPCServer((host, port), RequestHandler, allow_none=True)
    server.register_introspection_functions()
    
    # Register functions that REAPER expects
    server.register_function(call_nn_infill, "call_nn_infill")
    server.register_function(generate_with_midigpt_from_file, "generate_with_midigpt_from_file")
    
    print(f"MidiGPT Server running on http://{host}:{port}")
    print("Registered functions:")
    print("  - call_nn_infill (main REAPER interface)")
    print("  - generate_with_midigpt_from_file (direct generation)")
    
    if MIDIGPT_AVAILABLE:
        print("✓ MidiGPT library available")
    else:
        print("✗ MidiGPT library NOT available - using mock responses")
    
    if MIDI_LIB_AVAILABLE:
        print("✓ MIDI library available")
    else:
        print("✗ MIDI library NOT available")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()

if __name__ == "__main__":
    main()