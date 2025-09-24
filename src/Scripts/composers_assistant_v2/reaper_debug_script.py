#!/usr/bin/env python3
"""
REAPER Note Writing Debug Script v2.0
Focus: Diagnose why generated notes aren't appearing in REAPER
Architecture: Test CA format parsing and note insertion mechanisms
"""

import sys
import os

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    import reapy as rpr
    from rpr_midigpt_functions import get_global_options
    import preprocessing_functions as pre
except ImportError as e:
    print(f"Import error: {e}")
    print("Ensure all required modules are available")
    sys.exit(1)

def debug_ca_format_parsing():
    """Test CA format parsing with actual server output"""
    print("1. CA Format Parsing Test")
    
    # Test simple format
    simple_ca = ";M:0;N:60;d:1920;w:1920;M:1;N:64;d:1920;w:1920;"
    print(f"   Simple CA: {simple_ca}")
    
    # Test complex format (actual server output)
    complex_ca = ";M:0;N:60;d:1920;w:1920;M:1;N:64;d:1920;w:1920;M:3;N:67;d:1920;w:1920;M:9;N:64;d:1920;w:1920;M:10;N:62;d:1920;w:1920;"
    print(f"   Complex CA: {complex_ca[:80]}...")
    
    return complex_ca

def debug_reaper_state():
    """Check REAPER project state and selected items"""
    print("2. REAPER State Analysis")
    
    try:
        project = rpr.Project()
        print(f"   Project length: {project.length:.2f} seconds")
        print(f"   Time signature: {project.time_signature}")
        
        # Check selected items
        selected_items = [item for item in project.items if item.is_selected]
        print(f"   Selected items: {len(selected_items)}")
        
        if selected_items:
            item = selected_items[0]
            print(f"   First item: {item.name or 'unnamed'}")
            print(f"   Item length: {item.length:.2f} seconds")
            
            # Check takes
            takes = list(item.takes)
            print(f"   Takes: {len(takes)}")
            
            if takes:
                take = takes[0]
                print(f"   Active take: {take.name or 'unnamed'}")
                return take
        else:
            print("   WARNING: No selected items found")
            
    except Exception as e:
        print(f"   REAPER state error: {e}")
    
    return None

def test_direct_note_insertion(take, ca_string):
    """Test direct note insertion using REAPER API"""
    print("3. Direct Note Insertion Test")
    
    if not take:
        print("   ERROR: No take available for testing")
        return
        
    try:
        # Get initial note count
        initial_notes = len(list(take.midi.notes))
        print(f"   Initial notes: {initial_notes}")
        
        # Parse CA string manually
        notes_to_add = parse_ca_string(ca_string)
        print(f"   Parsed notes: {len(notes_to_add)}")
        
        # Add notes directly via REAPER API
        for note_data in notes_to_add[:3]:  # Test first 3 notes only
            try:
                start_ppq = note_data['start_ppq']
                end_ppq = start_ppq + note_data['duration_ppq']
                pitch = note_data['pitch']
                velocity = note_data.get('velocity', 96)
                
                # Create note using reapy
                take.midi.notes.create(
                    start=start_ppq,
                    end=end_ppq, 
                    pitch=pitch,
                    velocity=velocity
                )
                print(f"   Added note: pitch={pitch}, start={start_ppq}")
                
            except Exception as e:
                print(f"   Note creation error: {e}")
        
        # Check final note count
        final_notes = len(list(take.midi.notes))
        print(f"   Final notes: {final_notes}")
        print(f"   Net change: +{final_notes - initial_notes}")
        
    except Exception as e:
        print(f"   Direct insertion error: {e}")

def parse_ca_string(ca_string):
    """Parse CA format string into note data"""
    notes = []
    segments = ca_string.split(';')
    
    current_measure = 0
    current_pitch = None
    current_duration = None
    
    for segment in segments:
        if not segment:
            continue
            
        if segment.startswith('M:'):
            current_measure = int(segment[2:])
        elif segment.startswith('N:'):
            current_pitch = int(segment[2:])
        elif segment.startswith('d:'):
            current_duration = int(segment[2:])
        elif segment.startswith('w:') and current_pitch and current_duration:
            # Calculate PPQ timing (assuming 480 PPQ per quarter note)
            start_ppq = current_measure * 1920  # 4 quarter notes per measure
            
            note = {
                'measure': current_measure,
                'pitch': current_pitch,
                'start_ppq': start_ppq,
                'duration_ppq': current_duration,
                'velocity': 96
            }
            notes.append(note)
            
            # Reset for next note
            current_pitch = None
            current_duration = None
    
    return notes

def test_write_function_integration():
    """Test integration with write_nn_output_to_project if available"""
    print("4. Write Function Integration Test")
    
    try:
        # Check if write function exists
        if hasattr(pre, 'write_nn_output_to_project'):
            print("   write_nn_output_to_project found")
            # Test with simple CA string
            test_ca = ";M:0;N:72;d:960;w:960;"
            result = pre.write_nn_output_to_project(test_ca)
            print(f"   Function result: {result}")
        else:
            print("   write_nn_output_to_project not found in preprocessing_functions")
            
        # Check available functions
        pre_functions = [f for f in dir(pre) if not f.startswith('_')]
        print(f"   Available functions: {', '.join(pre_functions[:5])}...")
        
    except Exception as e:
        print(f"   Write function test error: {e}")

def compare_with_working_system():
    """Compare with Composer's Assistant approach"""
    print("5. CA System Comparison")
    
    try:
        # Test global options
        midigpt_options = get_global_options()
        print(f"   MidiGPT temperature: {midigpt_options.temperature}")
        print(f"   MidiGPT ngram size: {midigpt_options.enc_no_repeat_ngram_size}")
        print("   Options loaded successfully")
        
    except Exception as e:
        print(f"   Options comparison error: {e}")

def main():
    print("=== REAPER Note Writing Debug v2.0 ===")
    print("Focus: Diagnose note appearance issues")
    print()
    
    # Test CA format parsing
    ca_string = debug_ca_format_parsing()
    print()
    
    # Analyze REAPER state
    take = debug_reaper_state()
    print()
    
    # Test direct note insertion
    test_direct_note_insertion(take, ca_string)
    print()
    
    # Test write function integration
    test_write_function_integration()
    print()
    
    # Compare with working system
    compare_with_working_system()
    print()
    
    print("=== DEBUG COMPLETE ===")
    print("Next steps:")
    print("1. Check if direct API insertion worked")
    print("2. Compare CA format variations")
    print("3. Investigate write_nn_output_to_project implementation")

if __name__ == "__main__":
    main()