#!/usr/bin/env python3
"""
Updated midigpt Server with proper infilling support
"""

import os
import sys
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import time

# Add midigpt path
midigpt_path = os.path.join(os.path.dirname(__file__), "midigpt_workspace", "MIDI-GPT", "python_lib")
if midigpt_path and os.path.exists(midigpt_path):
    abs_path = os.path.abspath(midigpt_path)
    if abs_path not in sys.path:
        sys.path.insert(0, abs_path)

print('midigpt AI Server starting...')

# Import midigpt
try:
    import midigpt
    print('midigpt module loaded')
    MIDIGPT_AVAILABLE = True
except Exception as e:
    print(f'midigpt not available: {e}')
    MIDIGPT_AVAILABLE = False

# Configuration
SERVER_PORT = 3457
DEBUG = True

# Default checkpoint path
DEFAULT_CKPT = "midigpt_workspace/MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"

class MidiGPTHandler(BaseHTTPRequestHandler):
    """HTTP handler for midigpt requests with MIDI file support"""
    
    def log_message(self, format, *args):
        if DEBUG:
            super().log_message(format, *args)
    
    def do_GET(self):
        if self.path == '/health':
            self._handle_health()
        else:
            self._send_error(404, "Not found")
    
    def do_POST(self):
        if self.path == '/generate':
            self._handle_generate()
        elif self.path == '/generate_from_midi':
            self._handle_generate_from_midi()
        else:
            self._send_error(404, "Not found")
    
    def _handle_health(self):
        """Health check endpoint"""
        response = {
            'status': 'healthy',
            'midigpt_available': MIDIGPT_AVAILABLE,
            'python_version': sys.version
        }
        self._send_json_response(200, response)
    
    def _handle_generate_from_midi(self):
        """New endpoint: Generate from MIDI file with proper infilling support"""
        try:
            # Read request data
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            request_data = json.loads(post_data.decode('utf-8'))
            
            if not MIDIGPT_AVAILABLE:
                # Return mock legacy result
                mock_legacy_result = "<extra_id_0>N:60;d:240;w:240;N:64;d:240;w:240;N:67;d:240;w:240"
                response = {'success': True, 'legacy_result': mock_legacy_result}
                self._send_json_response(200, response)
                return
            
            midi_file_path = request_data.get('midi_file')
            legacy_params = request_data.get('legacy_params', {})
            is_infill = request_data.get('is_infill', False)
            requested_extra_ids = request_data.get('requested_extra_ids', [0])
            
            if not midi_file_path or not os.path.exists(midi_file_path):
                raise Exception(f"MIDI file not found: {midi_file_path}")
            
            print(f"Processing MIDI file: {midi_file_path}")
            print(f"Infill mode: {is_infill}")
            print(f"Requested extra_ids: {requested_extra_ids}")
            
            # Use ExpressiveEncoder to convert MIDI to protobuf
            encoder = midigpt.ExpressiveEncoder()
            piece_json_str = encoder.midi_to_json(midi_file_path)
            piece_json = json.loads(piece_json_str)
            
            print(f"✅ Converted MIDI to protobuf format")
            print(f"Piece structure: {list(piece_json.keys())}")
            
            # Check how many bars we actually have in the piece
            if 'tracks' in piece_json and piece_json['tracks']:
                actual_bars = len(piece_json['tracks'][0].get('bars', []))
                print(f"Actual bars in MIDI: {actual_bars}")
            else:
                actual_bars = 4  # Default fallback
                print("Could not determine bar count, using default: 4")
            
            # Configure status based on infilling requirements
            # Cap model_dim to maximum supported by the model (typically 4)
            MAX_MODEL_DIM = 4
            model_dim = min(MAX_MODEL_DIM, max(4, actual_bars))
            
            if actual_bars > MAX_MODEL_DIM:
                print(f"Warning: Input has {actual_bars} bars, but model maximum is {MAX_MODEL_DIM}. Using {MAX_MODEL_DIM} bars.")
            
            if is_infill:
                # For infilling: provide context in first bars, generate in middle/later bars
                # Following pythoninferencetest.py pattern: [False, False, True, False]
                selected_bars = [False] * model_dim
                # Select middle bars for generation (infilling)
                start_fill = max(1, model_dim // 4)  # Start filling after some context
                end_fill = min(model_dim - 1, model_dim * 3 // 4)  # Leave some context at end
                for i in range(start_fill, end_fill):
                    selected_bars[i] = True
                print(f"Infill configuration - selected_bars: {selected_bars}")
            else:
                # For variation/continuation: generate new content in all bars
                selected_bars = [True] * model_dim
                print(f"Variation configuration - selected_bars: {selected_bars}")
            
            # Create status configuration
            status_json = {
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
                    'polyphony_hard_limit': 6,
                    'bars': [{
                        'ts_numerator': 4,
                        'ts_denominator': 4
                    }] * model_dim
                }]
            }
            
            # Create params
            params = {
                'tracks_per_step': 1,
                'bars_per_step': 1,
                'model_dim': model_dim,
                'percentage': 100,
                'batch_size': 1,
                'temperature': legacy_params.get('temperature', 1.0),
                'max_steps': 50,
                'polyphony_hard_limit': 6,
                'shuffle': True,
                'verbose': True,
                'sampling_seed': -1,
                'mask_top_k': 0,
                'ckpt': DEFAULT_CKPT
            }
            
            # Run midigpt inference
            print("Running midigpt inference...")
            result = self._run_midigpt_inference(piece_json, status_json, params)
            
            # Convert result back to legacy format
            legacy_result = self._convert_to_legacy_format(result, requested_extra_ids)
            
            response = {'success': True, 'result': result, 'legacy_result': legacy_result}
            self._send_json_response(200, response)
            
        except Exception as e:
            print(f'Error in generate_from_midi: {e}')
            import traceback
            traceback.print_exc()
            
            error_response = {'success': False, 'error': str(e)}
            self._send_json_response(500, error_response)
    
    def _handle_generate(self):
        """Original generation endpoint"""
        try:
            # Read request data
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            request_data = json.loads(post_data.decode('utf-8'))
            
            if not MIDIGPT_AVAILABLE:
                # Mock response for testing
                mock_result = {
                    'tracks': [{
                        'notes': [
                            {'pitch': 60, 'start': 0, 'duration': 480, 'velocity': 80},
                            {'pitch': 64, 'start': 480, 'duration': 480, 'velocity': 80},
                            {'pitch': 67, 'start': 960, 'duration': 480, 'velocity': 80}
                        ]
                    }]
                }
                response = {'success': True, 'result': mock_result}
                self._send_json_response(200, response)
                return
            
            # Extract request components
            piece_json = request_data.get('piece', {})
            status_json = request_data.get('status', {})
            params = request_data.get('params', {})
            
            # Add checkpoint path if not provided
            if 'ckpt' not in params:
                params['ckpt'] = DEFAULT_CKPT
            
            # Perform midigpt inference
            result = self._run_midigpt_inference(piece_json, status_json, params)
            
            response = {'success': True, 'result': result}
            self._send_json_response(200, response)
            
        except Exception as e:
            if DEBUG:
                print(f"Generation error: {e}")
                import traceback
                traceback.print_exc()
      
            error_response = {'success': False, 'error': str(e)}
            self._send_json_response(500, error_response)
    
    def _run_midigpt_inference(self, piece_json, status_json, params):
        """Run midigpt inference with proper error handling"""
        if DEBUG:
            print(f"Piece: {list(piece_json.keys())}")
            print(f"Status tracks: {len(status_json.get('tracks', []))}")
            print(f"Model dim: {params.get('model_dim', 4)}")
        
        # Convert to JSON strings as required by midigpt API
        piece_str = json.dumps(piece_json)
        status_str = json.dumps(status_json)
        params_str = json.dumps(params)
        
        # Create callback manager
        callbacks = midigpt.CallbackManager()
        
        # Run inference
        max_attempts = 3
        midi_results = midigpt.sample_multi_step(piece_str, status_str, params_str, max_attempts, callbacks)
        
        if not midi_results:
            raise Exception("midigpt returned no results")
        
        # Parse first result
        midi_result_str = midi_results[0]
        result_json = json.loads(midi_result_str)
        
        return result_json
    
    def _convert_to_legacy_format(self, result_json, requested_extra_ids=None):
        """Convert midigpt result to CAv2 legacy format with correct extra_id tokens"""
        if not requested_extra_ids:
            requested_extra_ids = [0]  # Fallback
        
        # Model has limitations - if we have more extra_ids than we can process,
        # we'll provide fallback content for the excess ones
        MAX_PROCESSABLE_SECTIONS = 4
        
        legacy_parts = []
        
        try:
            if 'tracks' in result_json and result_json['tracks']:
                track = result_json['tracks'][0]
                
                # Extract all notes from the generated result
                all_notes = []
                
                if 'bars' in track:
                    for bar in track['bars']:
                        if 'events' in bar:
                            # Handle event indices
                            event_indices = bar['events']
                            if 'events' in result_json:
                                events = result_json['events']
                                for idx in event_indices:
                                    if idx < len(events):
                                        event = events[idx]
                                        pitch = event.get('pitch', 60)
                                        start = event.get('start', 0)
                                        end = event.get('end', 240)
                                        duration = max(1, end - start)
                                        all_notes.append({'pitch': pitch, 'start': start, 'duration': duration})
                
                # Fallback to direct notes if available
                if 'notes' in track and not all_notes:
                    for note in track['notes']:
                        pitch = note.get('pitch', 60)
                        start = note.get('start', 0)
                        duration = note.get('duration', 240)
                        all_notes.append({'pitch': pitch, 'start': start, 'duration': duration})
                
                # Sort notes by start time
                all_notes.sort(key=lambda x: x['start'])
                
                # Distribute notes among the requested extra_id sections
                if all_notes and len(requested_extra_ids) <= MAX_PROCESSABLE_SECTIONS:
                    # Normal case - distribute generated notes
                    notes_per_section = max(1, len(all_notes) // len(requested_extra_ids))
                    
                    for i, extra_id in enumerate(requested_extra_ids):
                        legacy_parts.append(f"<extra_id_{extra_id}>")
                        
                        # Get notes for this section
                        start_idx = i * notes_per_section
                        end_idx = start_idx + notes_per_section
                        if i == len(requested_extra_ids) - 1:  # Last section gets remaining notes
                            end_idx = len(all_notes)
                        
                        section_notes = all_notes[start_idx:end_idx]
                        
                        # Add notes with proper timing
                        current_time = 0
                        for note in section_notes:
                            wait_time = max(0, note['start'] - current_time)
                            if wait_time > 0:
                                legacy_parts.append(f"w:{wait_time}")
                                current_time += wait_time
                            
                            legacy_parts.append(f"N:{note['pitch']};d:{note['duration']}")
                            current_time += note['duration']
                
                else:
                    # Fallback case - provide basic content for all extra_ids
                    fallback_notes = [
                        {'pitch': 60, 'duration': 240},
                        {'pitch': 64, 'duration': 240}, 
                        {'pitch': 67, 'duration': 240}
                    ]
                    
                    for i, extra_id in enumerate(requested_extra_ids):
                        legacy_parts.append(f"<extra_id_{extra_id}>")
                        
                        # Use different base pitches for variety
                        base_pitch = 60 + (i % 12)  # Cycle through octave
                        
                        for j, note in enumerate(fallback_notes):
                            if j > 0:
                                legacy_parts.append("w:240")
                            pitch = base_pitch + (note['pitch'] - 60)
                            legacy_parts.append(f"N:{pitch};d:{note['duration']}")
        
        except Exception as e:
            if DEBUG:
                print(f"Legacy conversion error: {e}")
            
            # Error fallback - provide basic notes for each requested extra_id
            for i, extra_id in enumerate(requested_extra_ids):
                legacy_parts.append(f"<extra_id_{extra_id}>")
                base_pitch = 60 + (i % 12)
                legacy_parts.append(f"N:{base_pitch};d:240")
        
        result = ";".join(legacy_parts) if legacy_parts else "<extra_id_0>N:60;d:240"
        return result
    
    def _send_json_response(self, status_code, data):
        """Send JSON response"""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response_data = json.dumps(data).encode('utf-8')
        self.wfile.write(response_data)
    
    def _send_error(self, status_code, message):
        """Send error response"""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        error_data = json.dumps({'error': message}).encode('utf-8')
        self.wfile.write(error_data)

def run_server():
    """Start the midigpt server"""
    try:
        server = HTTPServer(('127.0.0.1', SERVER_PORT), MidiGPTHandler)
        
        print(f'midigpt Server running on http://127.0.0.1:{SERVER_PORT}')
        print('Endpoints:')
        print('  /health - Health check')
        print('  /generate - Original protobuf generation')
        print('  /generate_from_midi - New MIDI file generation')
        
        server.serve_forever()
        
    except KeyboardInterrupt:
        print("midigpt server stopped")
    except Exception as e:
        print(f"Server error: {e}")

if __name__ == "__main__":
    run_server()