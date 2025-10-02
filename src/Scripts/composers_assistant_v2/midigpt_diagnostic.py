#!/usr/bin/env python3
"""
MidiGPT Refactor Diagnostic Script
Test the python-3-9-refactor branch behavior vs original
"""

import sys
import os
import json
import tempfile
from pathlib import Path

# Add MidiGPT path
current_dir = Path(__file__).parent.absolute()
midigpt_paths = [
    str(current_dir / "../../../MIDI-GPT/python_lib"),
    str(current_dir / "../../MIDI-GPT/python_lib"),
    str(current_dir / "../../../../MIDI-GPT/python_lib")
]

for path in midigpt_paths:
    if os.path.exists(path):
        sys.path.insert(0, path)
        print(f"Using MidiGPT path: {path}")
        break

try:
    import midigpt
    import mido
    print(f"MidiGPT version: {getattr(midigpt, 'version', 'Unknown')()}")
    print("Successfully imported midigpt")
except ImportError as e:
    print(f"CRITICAL: Cannot import midigpt: {e}")
    sys.exit(1)

def test_basic_encoder():
    """Test if ExpressiveEncoder works correctly"""
    print("\n=== Testing ExpressiveEncoder ===")
    
    try:
        encoder = midigpt.ExpressiveEncoder()
        print("✓ ExpressiveEncoder created successfully")
        
        # Check available methods
        methods = [method for method in dir(encoder) if not method.startswith('_')]
        print(f"Available methods: {methods}")
        
        return encoder
    except Exception as e:
        print(f"✗ ExpressiveEncoder failed: {e}")
        return None

def test_midi_to_json_conversion(encoder):
    """Test MIDI to JSON conversion with a simple file"""
    print("\n=== Testing MIDI → JSON Conversion ===")
    
    try:
        # Create a simple test MIDI file
        with tempfile.TemporaryDirectory() as temp_dir:
            test_midi = os.path.join(temp_dir, "test.mid")
            
            # Create simple MIDI: C major chord
            mid = mido.MidiFile(ticks_per_beat=96)
            track = mido.MidiTrack()
            mid.tracks.append(track)
            
            # Meta messages
            track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
            track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
            
            # C major chord: C-E-G
            for pitch in [60, 64, 67]:
                track.append(mido.Message('note_on', channel=0, note=pitch, velocity=80, time=0))
            
            track.append(mido.Message('note_off', channel=0, note=60, velocity=0, time=96))
            track.append(mido.Message('note_off', channel=0, note=64, velocity=0, time=0))
            track.append(mido.Message('note_off', channel=0, note=67, velocity=0, time=0))
            track.append(mido.MetaMessage('end_of_track', time=0))
            
            mid.save(test_midi)
            print(f"✓ Created test MIDI: {test_midi}")
            
            # Convert to JSON
            json_str = encoder.midi_to_json(test_midi)
            json_data = json.loads(json_str)
            
            print(f"✓ MIDI → JSON conversion successful")
            print(f"  JSON length: {len(json_str)} chars")
            print(f"  JSON keys: {list(json_data.keys())}")
            
            if 'tracks' in json_data:
                print(f"  Tracks: {len(json_data['tracks'])}")
                if json_data['tracks']:
                    track = json_data['tracks'][0]
                    print(f"  First track keys: {list(track.keys())}")
            
            return json_str
            
    except Exception as e:
        print(f"✗ MIDI → JSON conversion failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_json_to_midi_conversion(encoder, json_str):
    """Test JSON to MIDI conversion"""
    print("\n=== Testing JSON → MIDI Conversion ===")
    
    if not json_str:
        print("✗ No JSON to test with")
        return None
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_midi = os.path.join(temp_dir, "output.mid")
            
            # Convert JSON back to MIDI
            encoder.json_to_midi(json_str, output_midi)
            print(f"✓ JSON → MIDI conversion successful: {output_midi}")
            
            # Analyze the result
            if os.path.exists(output_midi):
                mid = mido.MidiFile(output_midi)
                print(f"  Output tracks: {len(mid.tracks)}")
                print(f"  Ticks per beat: {mid.ticks_per_beat}")
                
                for i, track in enumerate(mid.tracks):
                    note_count = sum(1 for msg in track if msg.type in ['note_on', 'note_off'])
                    print(f"  Track {i}: {len(track)} messages, {note_count} note events")
                
                return output_midi
            else:
                print("✗ Output MIDI file not created")
                return None
                
    except Exception as e:
        print(f"✗ JSON → MIDI conversion failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_sample_generation():
    """Test the actual sampling pipeline that your server uses"""
    print("\n=== Testing Sample Generation Pipeline ===")
    
    try:
        # Create the exact same setup as your server
        encoder = midigpt.ExpressiveEncoder()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create seed MIDI like your server
            seed_midi = os.path.join(temp_dir, "seed.mid")
            
            mid = mido.MidiFile(ticks_per_beat=96)
            track = mido.MidiTrack()
            mid.tracks.append(track)
            
            track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
            track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
            
            # Add seed content
            for i in range(2):  # 2 bars with content
                pitches = [60, 64, 67] if i == 0 else [62, 65, 69]
                for j, pitch in enumerate(pitches):
                    track.append(mido.Message('note_on', channel=0, note=pitch, velocity=80, time=0))
                    track.append(mido.Message('note_off', channel=0, note=pitch, velocity=0, time=48))
                # Rest of bar
                if i < 1:
                    track.append(mido.Message('note_on', channel=0, note=60, velocity=0, time=192))
            
            track.append(mido.MetaMessage('end_of_track', time=0))
            mid.save(seed_midi)
            
            # Convert to JSON
            midi_json_str = encoder.midi_to_json(seed_midi)
            midi_json_data = json.loads(midi_json_str)
            
            print(f"✓ Seed MIDI → JSON: {len(midi_json_str)} chars")
            
            # Create status exactly like your server
            status_data = {
                'tracks': [{
                    'track_id': 0,
                    'temperature': 1.0,
                    'instrument': 'acoustic_grand_piano', 
                    'density': 10, 
                    'track_type': 10, 
                    'ignore': False, 
                    'selected_bars': [False, False, True, True],
                    'min_polyphony_q': 'POLYPHONY_ANY',
                    'max_polyphony_q': 'POLYPHONY_ANY', 
                    'autoregressive': False,
                    'polyphony_hard_limit': 9 
                }]
            }
            
            # Find model
            model_paths = [
                "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
                "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"
            ]
            
            model_path = None
            for path in model_paths:
                if os.path.exists(path):
                    model_path = os.path.abspath(path)
                    break
            
            if not model_path:
                print("✗ Model checkpoint not found")
                return
            
            params = {
                'tracks_per_step': 1, 
                'bars_per_step': 1, 
                'model_dim': 4, 
                'percentage': 100, 
                'batch_size': 1, 
                'temperature': 1.0, 
                'max_steps': 10,  # Reduced for testing
                'polyphony_hard_limit': 6, 
                'shuffle': True, 
                'verbose': True,  # Enable verbose
                'ckpt': model_path,
                'sampling_seed': -1,
                'mask_top_k': 0
            }
            
            # Convert to JSON strings
            piece = json.dumps(midi_json_data)
            status = json.dumps(status_data)
            param = json.dumps(params)
            
            print(f"✓ Prepared sampling input:")
            print(f"  Piece: {len(piece)} chars")
            print(f"  Status: {len(status)} chars") 
            print(f"  Params: {len(param)} chars")
            
            # Create callback manager and sample
            callbacks = midigpt.CallbackManager()
            
            print("🚀 Running sample_multi_step...")
            results = midigpt.sample_multi_step(piece, status, param, 1, callbacks)
            
            if results and len(results) > 0:
                result_str = results[0]
                print(f"✓ Generation successful: {len(result_str)} chars")
                
                # Parse and analyze result
                result_json = json.loads(result_str)
                print(f"✓ Result JSON parsed")
                print(f"  Result keys: {list(result_json.keys())}")
                
                if 'tracks' in result_json:
                    tracks = result_json['tracks']
                    print(f"  Generated tracks: {len(tracks)}")
                    
                    for i, track in enumerate(tracks):
                        print(f"  Track {i} keys: {list(track.keys())}")
                        
                        # Look for notes or events
                        if 'notes' in track:
                            notes = track['notes']
                            print(f"    Direct notes: {len(notes)}")
                        
                        if 'bars' in track:
                            bars = track['bars']
                            print(f"    Bars: {len(bars)}")
                            for j, bar in enumerate(bars):
                                if 'events' in bar:
                                    print(f"      Bar {j} events: {len(bar['events'])}")
                
                # Test conversion back to MIDI
                output_midi = os.path.join(temp_dir, "generated.mid")
                encoder.json_to_midi(result_str, output_midi)
                
                if os.path.exists(output_midi):
                    # Analyze generated MIDI
                    gen_mid = mido.MidiFile(output_midi)
                    print(f"✓ Generated MIDI: {len(gen_mid.tracks)} tracks, {gen_mid.ticks_per_beat} tpb")
                    
                    total_notes = 0
                    for i, track in enumerate(gen_mid.tracks):
                        note_ons = [msg for msg in track if msg.type == 'note_on' and msg.velocity > 0]
                        total_notes += len(note_ons)
                        print(f"    Track {i}: {len(note_ons)} notes")
                        
                        # Show first few notes
                        for j, msg in enumerate(note_ons[:3]):
                            print(f"      Note {j+1}: pitch={msg.note}, vel={msg.velocity}")
                    
                    print(f"📊 TOTAL GENERATED NOTES: {total_notes}")
                    
                    if total_notes == 0:
                        print("🚨 PROBLEM IDENTIFIED: Generated MIDI has no notes!")
                        print("   This confirms the issue is in the generation pipeline")
                    
                    return True
                else:
                    print("✗ Generated MIDI file not created")
                    return False
            else:
                print("✗ No results from sample_multi_step")
                return False
                
    except Exception as e:
        print(f"✗ Sample generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("MidiGPT Refactor Diagnostic")
    print("=" * 50)
    
    # Test basic functionality
    encoder = test_basic_encoder()
    if not encoder:
        return
    
    # Test conversions
    json_str = test_midi_to_json_conversion(encoder)
    if json_str:
        test_json_to_midi_conversion(encoder, json_str)
    
    # Test the full generation pipeline
    test_sample_generation()
    
    print("\n" + "=" * 50)
    print("Diagnostic complete")

if __name__ == "__main__":
    main()