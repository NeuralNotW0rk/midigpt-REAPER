#!/usr/bin/env python3
"""
Test model path and discover working protobuf format
"""

import requests
import json
import os

def test_model_paths():
    """Test different model paths to see which one works"""
    
    # Based on the constants.py and working examples, try these paths:
    model_paths = [
        # Default from midigpt_server.py 
        None,  # Let server use default
        
        # From constants.py
        "../../../midigpt_workspace/MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        
        # Relative to current directory
        "midigpt_workspace/MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        
        # Alternative paths
        "models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        
        # Empty string to trigger default
        "",
    ]
    
    # Let's also try the original bars/events structure from your proxy
    # Based on the C++ code showing piece->tracks()->bars()->events()
    base_request = {
        'piece': {
            'tracks': [{
                'bars': [{
                    'events': [0, 1],  # Indices into events array
                    'ts_numerator': 4,
                    'ts_denominator': 4
                }],
                'instrument': 0
                # Removed track_type as we determined it shouldn't be here
            }],
            'events': [
                {'velocity': 80, 'pitch': 60, 'start': 0, 'end': 240},
                {'velocity': 80, 'pitch': 64, 'start': 480, 'end': 720}
            ],
            'resolution': 480
        },
        'status': {
            'tracks': [{
                'track_id': 0,
                'temperature': 1.0,
                'instrument': 'acoustic_grand_piano',
                'density': 10,
                'track_type': 10,
                'ignore': False,
                'selected_bars': [True],
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY',
                'autoregressive': False,
                'polyphony_hard_limit': 6,
                'bars': [{
                    'ts_numerator': 4,
                    'ts_denominator': 4
                }]
            }]
        },
        'params': {
            'tracks_per_step': 1,
            'bars_per_step': 1,
            'model_dim': 4,
            'percentage': 100,
            'batch_size': 1,
            'temperature': 1.0,
            'max_steps': 10,
            'polyphony_hard_limit': 6,
            'shuffle': True,
            'verbose': True,
            'sampling_seed': -1,
            'mask_top_k': 0
        }
    }
    
    for i, ckpt_path in enumerate(model_paths):
        print(f"\n=== Testing model path {i+1}/{len(model_paths)} ===")
        if ckpt_path is None:
            print("Using server default model path")
            request = base_request.copy()
            # Don't set ckpt parameter
        else:
            print(f"Model path: {ckpt_path}")
            request = base_request.copy()
            request['params'] = base_request['params'].copy()
            request['params']['ckpt'] = ckpt_path
            
            # Check if file exists
            if ckpt_path and os.path.exists(ckpt_path):
                print(f"✅ File exists: {ckpt_path}")
            elif ckpt_path:
                print(f"❌ File not found: {ckpt_path}")
        
        try:
            response = requests.post(
                'http://127.0.0.1:3457/generate',
                json=request,
                timeout=60
            )
            
            print(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                print("✅ SUCCESS! Model loaded and format accepted!")
                result = response.json()
                if result.get('success'):
                    print("✅ Generation successful!")
                    if 'result' in result:
                        generated = result['result']
                        print(f"Generated structure: {list(generated.keys())}")
                        if 'tracks' in generated and len(generated['tracks']) > 0:
                            track = generated['tracks'][0]
                            print(f"Generated track structure: {list(track.keys())}")
                            
                        # This tells us the EXACT format the server produces/expects!
                        print("🎉 FOUND THE WORKING FORMAT!")
                        print("Request that worked:")
                        print(json.dumps(request, indent=2))
                        return True
                else:
                    print(f"❌ Generation failed: {result.get('error')}")
            else:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', 'Unknown error')
                    print(f"❌ Error: {error_msg}")
                    
                    # Different errors tell us different things
                    if "ERROR LOADING MODEL" in error_msg:
                        print("  → Model file not found at this path")
                    elif "PROTOBUF ERROR" in error_msg:
                        print("  → Model loaded but protobuf format wrong")
                        print(f"  → Specific error: {error_msg}")
                    
                except:
                    print(f"❌ Response: {response.text[:200]}")
        
        except Exception as e:
            print(f"❌ Exception: {e}")
    
    return False

if __name__ == "__main__":
    print("🔍 Testing different model paths and the bars/events format...")
    
    success = test_model_paths()
    
    if not success:
        print("\n💡 Next steps:")
        print("1. Check if the model file exists in your filesystem")
        print("2. The bars/events structure might be correct - just need right model path")
        print("3. Consider running pythoninferencetest.py to see ExpressiveEncoder output")