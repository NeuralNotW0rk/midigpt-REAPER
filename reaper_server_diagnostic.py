#!/usr/bin/env python3
"""
REAPER-Server Connection Diagnostic
Traces the exact path from REAPER script to server to identify where queries are lost
"""

import sys
import time
from xmlrpc.server import SimpleXMLRPCServer
from xmlrpc.client import ServerProxy
import threading
import json
from datetime import datetime

class DiagnosticXMLRPCServer(SimpleXMLRPCServer):
    """Enhanced XML-RPC Server with detailed request tracing"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_count = 0
        self.start_time = datetime.now()
        
    def _dispatch(self, method, params):
        self.request_count += 1
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        print(f"\n{'='*60}")
        print(f"[{timestamp}] REQUEST #{self.request_count}: {method}")
        print(f"{'='*60}")
        
        # Log all parameters with detailed analysis
        print(f"Parameter count: {len(params)}")
        for i, param in enumerate(params):
            param_type = type(param).__name__
            
            if isinstance(param, str):
                print(f"  [{i}] {param_type}: '{param[:100]}{'...' if len(param) > 100 else ''}' (len={len(param)})")
                
                # Analyze the input string for REAPER patterns
                if i == 0 and method == 'call_nn_infill':  # First param should be input string
                    self._analyze_input_string(param)
                    
            elif isinstance(param, dict):
                print(f"  [{i}] {param_type}: {len(param)} keys")
                if param:
                    keys = list(param.keys())[:5]
                    print(f"       Sample keys: {keys}{'...' if len(param) > 5 else ''}")
                    
                    # Analyze song dict structure
                    if i == 1 and method == 'call_nn_infill':  # Second param should be song dict
                        self._analyze_song_dict(param)
                        
            elif isinstance(param, (int, float, bool)):
                print(f"  [{i}] {param_type}: {param}")
            else:
                print(f"  [{i}] {param_type}: {str(param)[:50]}{'...' if len(str(param)) > 50 else ''}")
        
        # Call the actual method and trace response
        try:
            start_time = time.time()
            result = super()._dispatch(method, params)
            end_time = time.time()
            
            print(f"\n✅ METHOD EXECUTED SUCCESSFULLY")
            print(f"   Execution time: {(end_time - start_time)*1000:.1f}ms")
            
            if isinstance(result, str):
                print(f"   Result type: string (len={len(result)})")
                print(f"   Result preview: '{result[:100]}{'...' if len(result) > 100 else ''}'")
                
                # Analyze result for MIDI patterns
                self._analyze_result_string(result)
            else:
                print(f"   Result type: {type(result).__name__}")
                print(f"   Result: {str(result)[:100]}{'...' if len(str(result)) > 100 else ''}")
            
            return result
            
        except Exception as e:
            print(f"\n❌ METHOD EXECUTION FAILED")
            print(f"   Error type: {type(e).__name__}")
            print(f"   Error message: {e}")
            print(f"   This error will be returned to REAPER")
            raise
    
    def _analyze_input_string(self, input_str):
        """Analyze the input string for REAPER/CA patterns"""
        print(f"\n📝 INPUT STRING ANALYSIS:")
        
        # Count extra_id tokens
        extra_ids = []
        import re
        for match in re.finditer(r'<extra_id_(\d+)>', input_str):
            extra_ids.append(int(match.group(1)))
        
        if extra_ids:
            print(f"   Extra ID tokens found: {sorted(set(extra_ids))} (count: {len(extra_ids)})")
        else:
            print(f"   No extra_id tokens found")
        
        # Count note instructions
        note_count = len(re.findall(r'N:\d+', input_str))
        wait_count = len(re.findall(r'w:\d+', input_str))
        duration_count = len(re.findall(r'd:\d+', input_str))
        
        print(f"   Note instructions (N:): {note_count}")
        print(f"   Wait instructions (w:): {wait_count}")
        print(f"   Duration instructions (d:): {duration_count}")
        
        # Check for measure markers
        measure_count = len(re.findall(r';M:\d+', input_str))
        if measure_count > 0:
            print(f"   Measure markers found: {measure_count}")
        
        # Determine input type
        if not extra_ids and note_count == 0:
            print(f"   ⚠️  INPUT TYPE: Empty/invalid - no tokens or notes")
        elif extra_ids and note_count == 0:
            print(f"   ✅ INPUT TYPE: Infill request (tokens only)")
        elif note_count > 0:
            print(f"   ✅ INPUT TYPE: Continuation/variation (has existing notes)")
        else:
            print(f"   ❓ INPUT TYPE: Unknown pattern")
    
    def _analyze_song_dict(self, song_dict):
        """Analyze the song dictionary structure"""
        print(f"\n🎵 SONG DICT ANALYSIS:")
        
        if 'tracks' in song_dict:
            tracks = song_dict['tracks']
            print(f"   Track count: {len(tracks) if isinstance(tracks, list) else 'invalid'}")
            
            if isinstance(tracks, list) and tracks:
                # Analyze first track
                first_track = tracks[0]
                if isinstance(first_track, dict):
                    print(f"   First track keys: {list(first_track.keys())}")
        
        if 'metadata' in song_dict:
            metadata = song_dict['metadata']
            print(f"   Metadata: {type(metadata).__name__} with {len(metadata) if isinstance(metadata, dict) else 0} keys")
        
        print(f"   All keys: {list(song_dict.keys())}")
    
    def _analyze_result_string(self, result_str):
        """Analyze the result string to verify it's valid MIDI output"""
        print(f"\n🎼 RESULT ANALYSIS:")
        
        # Count output instructions
        import re
        note_count = len(re.findall(r'N:\d+', result_str))
        wait_count = len(re.findall(r'w:\d+', result_str))
        duration_count = len(re.findall(r'd:\d+', result_str))
        
        print(f"   Output notes (N:): {note_count}")
        print(f"   Output waits (w:): {wait_count}")
        print(f"   Output durations (d:): {duration_count}")
        
        # Check for extra_id tokens in output
        extra_ids = []
        for match in re.finditer(r'<extra_id_(\d+)>', result_str):
            extra_ids.append(int(match.group(1)))
        
        if extra_ids:
            print(f"   Extra ID tokens in output: {sorted(set(extra_ids))}")
        
        # Validate output format
        if note_count > 0 and duration_count > 0:
            print(f"   ✅ OUTPUT TYPE: Valid MIDI instructions")
        elif extra_ids:
            print(f"   ✅ OUTPUT TYPE: Contains extra_id tokens (may be partial)")
        else:
            print(f"   ⚠️  OUTPUT TYPE: No recognizable MIDI content")

def mock_call_nn_infill(s, S, use_sampling=True, min_length=10, 
                       enc_no_repeat_ngram_size=0, has_fully_masked_inst=False, 
                       temperature=1.0):
    """Enhanced mock implementation that generates realistic responses"""
    
    print(f"\n🤖 GENERATING RESPONSE:")
    print(f"   Input analysis: {len(s)} chars, {len(S.get('tracks', []))} tracks")
    print(f"   Parameters: sampling={use_sampling}, temp={temperature}, min_len={min_length}")
    
    # Simulate processing time
    time.sleep(0.1)
    
    # Generate contextually appropriate response
    import re
    extra_ids = re.findall(r'<extra_id_(\d+)>', s)
    
    if extra_ids:
        # Infill response - replace tokens with notes
        result = s
        for match in re.finditer(r'<extra_id_(\d+)>', s):
            token = match.group(0)
            # Generate some notes for this token
            replacement = "N:60;d:240;w:240;N:64;d:240;w:240;N:67;d:240;w:240"
            result = result.replace(token, replacement, 1)
        
        print(f"   Generated infill response: replaced {len(extra_ids)} tokens")
    else:
        # Continuation response - add more notes
        result = s + ";w:240;N:60;d:240;w:240;N:64;d:240;w:240"
        print(f"   Generated continuation response")
    
    return result

def start_diagnostic_server():
    """Start the diagnostic server"""
    print("🔍 STARTING DIAGNOSTIC XML-RPC SERVER")
    print("="*60)
    print("This server will log ALL communication with REAPER")
    print("Port: 3456 (same as production server)")
    print("Press Ctrl+C to stop")
    print("="*60)
    
    try:
        server = DiagnosticXMLRPCServer(('127.0.0.1', 3456), logRequests=True)
        server.register_function(mock_call_nn_infill, 'call_nn_infill')
        
        print("\n🟢 Diagnostic server ready!")
        print("📊 Waiting for REAPER connections...")
        print("\nTo test:")
        print("1. Run your REAPER script")
        print("2. Watch this console for detailed logs")
        print("3. Any issues will be clearly identified")
        
        # Auto-test the server
        def auto_test():
            time.sleep(2)
            print(f"\n🧪 RUNNING AUTO-TEST...")
            try:
                proxy = ServerProxy('http://127.0.0.1:3456', timeout=5)
                result = proxy.call_nn_infill(
                    "<extra_id_0>N:60;d:240", 
                    {"tracks": [], "metadata": {}}, 
                    True, 10, 0, False, 1.0
                )
                print(f"✅ Auto-test successful!")
            except Exception as e:
                print(f"❌ Auto-test failed: {e}")
        
        test_thread = threading.Thread(target=auto_test)
        test_thread.daemon = True
        test_thread.start()
        
        server.serve_forever()
        
    except KeyboardInterrupt:
        print(f"\n\n📊 DIAGNOSTIC SUMMARY:")
        print(f"   Total requests received: {server.request_count}")
        print(f"   Server uptime: {datetime.now() - server.start_time}")
        print(f"   Diagnostic complete!")
    except Exception as e:
        print(f"\n❌ Server error: {e}")

if __name__ == "__main__":
    start_diagnostic_server()
