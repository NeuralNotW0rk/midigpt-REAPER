#!/usr/bin/env python3
"""
Updated midigpt Server with MIDI file support
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
DEBUG = False

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
            self._handle_generate_from_midi()  # New endpoint
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
    
    def _handle_generate_from_midi(self):
        """New endpoint: Generate from MIDI file"""
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
            
            if not midi_file_path or not os.path.exists(midi_file_path):
                raise Exception(f"MIDI file not found: {midi_file_path}")
            
            print(f"Processing MIDI file: {midi_file_path}")
            
            # Use ExpressiveEncoder to convert MIDI to protobuf
            encoder = midigpt.ExpressiveEncoder()
            piece_json_str = encoder.midi_to_json(midi_file_path)
            piece_json = json.loads(piece_json_str)
            
            print(f"✅ Converted MIDI to protobuf format")
            print(f"Piece structure: {list(piece_json.keys())}")
            
            # Create status from legacy params
            status_json = {
                'tracks': [{
                    'track_id': 0,
                    'temperature': legacy_params.get('temperature', 1.0),
                    'instrument': 'acoustic_grand_piano',
                    'density': 10,
                    'track_type': 10,
                    'ignore': False,
                    'selected_bars': [True],  # Generate first bar
                    'min_polyphony_q': 'POLYPHONY_ANY',
                    'max_polyphony_q': 'POLYPHONY_ANY',
                    'autoregressive': False,
                    'polyphony_hard_limit': 6,
                    'bars': [{
                        'ts_numerator': 4,
                        'ts_denominator': 4
                    }]
                }]
            }
            
            # Create params
            params = {
                'tracks_per_step': 1,
                'bars_per_step': 1,
                'model_dim': 4,
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
            result = self._run_midigpt_inference(piece_json, status_json, params)
            
            # Convert result back to legacy format (simplified for now)
            legacy_result = self._convert_to_legacy_format(result)
            
            response = {'success': True, 'result': result, 'legacy_result': legacy_result}
            self._send_json_response(200, response)
            
        except Exception as e:
            print(f"MIDI generation error: {e}")
            import traceback
            traceback.print_exc()
            
            error_response = {'success': False, 'error': str(e)}
            self._send_json_response(500, error_response)
    
    def _run_midigpt_inference(self, piece_json, status_json, params):
        """Run midigpt inference with the provided parameters"""
        try:
            # Convert to JSON strings as expected by midigpt
            piece_str = json.dumps(piece_json)
            status_str = json.dumps(status_json)
            param_str = json.dumps(params)
            
            print("Running midigpt inference...")
            
            # Create callback manager
            callbacks = midigpt.CallbackManager()
            
            # Run multi-step sampling
            max_attempts = params.get('max_attempts', 3)
            
            # Multiple attempts to handle potential generation issues
            for attempt in range(max_attempts):
                try:
                    midi_result = midigpt.sample_multi_step(
                        piece_str, status_str, param_str, max_attempts, callbacks
                    )
                    
                    if midi_result and len(midi_result) > 0:
                        midi_str = midi_result[0]
                        break
                        
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    continue
            else:
                raise Exception("All generation attempts failed")
            
            # Parse the result back to JSON
            midi_json = json.loads(midi_str)
            
            print("✅ Generation successful!")
            
            return midi_json
            
        except Exception as e:
            print(f"midigpt inference error: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _convert_to_legacy_format(self, result):
        """Convert midigpt result back to legacy REAPER format"""
        # Simplified conversion - you can enhance this
        # For now, return a basic pattern
        return "<extra_id_0>N:60;d:240;w:240;N:64;d:240;w:240;N:67;d:240;w:240"
    
    def _send_json_response(self, status_code, data):
        """Send JSON response"""
        response_bytes = json.dumps(data).encode('utf-8')
        
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_bytes)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(response_bytes)
    
    def _send_error(self, status_code, message):
        """Send error response"""
        error_data = {'error': message}
        self._send_json_response(status_code, error_data)

def start_server():
    """Start the HTTP server"""
    try:
        server = HTTPServer(('127.0.0.1', SERVER_PORT), MidiGPTHandler)
        print(f"midigpt Server running on http://127.0.0.1:{SERVER_PORT}")
        print("Endpoints:")
        print("  /health - Health check")
        print("  /generate - Original protobuf generation")
        print("  /generate_from_midi - New MIDI file generation")
        server.serve_forever()
        
    except KeyboardInterrupt:
        print("midigpt server stopped")
    except Exception as e:
        print(f"Server error: {e}")

if __name__ == "__main__":
    start_server()