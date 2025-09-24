# CA Output Capture Script - Run this in REAPER to see actual CA output
# Fixed for Unicode issues

import rpr_ca_functions as fn
from reaper_python import *
import sys

def patch_stdout_stderr_open():
    class ReaperConsole:
        def write(self, output):
            # Handle Unicode properly
            if isinstance(output, bytes):
                output = output.decode('utf-8', errors='replace')
            RPR_ShowConsoleMsg(str(output))
        def flush(self):
            pass
        def close(self):
            pass
    
    reaper_console = ReaperConsole()
    sys.stdout = reaper_console
    sys.stderr = reaper_console

patch_stdout_stderr_open()

def simple_ca_format_analysis():
    """Simple analysis to understand CA format without server calls"""
    
    print("=== SIMPLE CA FORMAT ANALYSIS ===")
    RPR_ClearConsole()
    
    print("Let's examine what we know about CA format from the code...")
    
    # Test instruction parsing
    print("\n1. Testing CA instruction parsing with known examples:")
    import nn_str_functions as nns
    
    # From the code comments, we know this is a valid example:
    test_example = ";<extra_id_36>;D:36;D:49;w:12;D:42;w:12;D:38;D:42"
    
    print(f"   Example from CA code: {test_example}")
    
    try:
        parsed = nns.instructions_by_extra_id(test_example)
        print(f"   Parsed result: {dict(parsed)}")
        
        for extra_id, instructions in parsed.items():
            if extra_id:
                print(f"   {extra_id}: {instructions}")
                
    except Exception as e:
        print(f"   Parsing error: {e}")
    
    # Test with note format
    print("\n2. Testing with note format:")
    note_example = ";<extra_id_100>;N:60;d:480;N:64;d:480;w:240"
    print(f"   Note example: {note_example}")
    
    try:
        parsed_notes = nns.instructions_by_extra_id(note_example)
        print(f"   Parsed notes: {dict(parsed_notes)}")
        
    except Exception as e:
        print(f"   Note parsing error: {e}")
    
    # Test different orderings
    print("\n3. Testing different instruction orders:")
    
    test_formats = [
        ";<extra_id_101>;N:60;d:480;w:240;N:64;d:480",  # Note first
        ";<extra_id_102>;d:480;N:60;w:240;d:480;N:64",  # Duration first  
        ";<extra_id_103>;w:0;d:480;N:60;w:240;d:480;N:64"  # Wait, duration, note
    ]
    
    for i, test_format in enumerate(test_formats):
        print(f"   Format {i+1}: {test_format}")
        try:
            result = nns.instructions_by_extra_id(test_format)
            for extra_id, instructions in result.items():
                if extra_id:
                    note_count = len([inst for inst in instructions if inst.startswith('N:')])
                    print(f"      {extra_id}: {note_count} notes in {instructions}")
        except Exception as e:
            print(f"      Error: {e}")
    
    print("\n4. What do we see in our current input?")
    try:
        options = fn.get_global_options()
        nn_input = fn.get_nn_input_from_project(
            mask_empty_midi_items=True, 
            mask_selected_midi_items=True,
            do_rhythmic_conditioning=options.do_rhythm_conditioning,
            rhythmic_conditioning_type=options.rhythm_conditioning_type,
            do_note_range_conditioning_by_measure=options.do_note_range_conditioning,
            note_range_conditioning_type=options.note_range_conditioning_type,
            display_track_to_MIDI_inst=options.display_track_to_MIDI_inst,
            display_warnings=options.display_warnings
        )
        
        if nn_input.continue_:
            # Clean the input string of any problematic characters
            clean_input = ''.join(char for char in nn_input.nn_input_string if ord(char) < 128)
            
            print(f"   Input length: {len(nn_input.nn_input_string)} chars")
            print(f"   Clean preview: {clean_input[:200]}...")
            
            # Find extra_id tokens in input
            import re
            extra_ids = re.findall(r'<extra_id_(\d+)>', clean_input)
            print(f"   Extra IDs in input: {extra_ids}")
            
            # Look at structure around extra_ids
            segments = clean_input.split(';')
            extra_id_segments = [seg for seg in segments if 'extra_id' in seg]
            print(f"   Extra ID segments: {extra_id_segments}")
            
        else:
            print("   No masked items found")
            
    except Exception as e:
        print(f"   Input analysis error: {e}")
    
    print("\n=== CONCLUSION ===")
    print("Based on CA code examples:")
    print("- Instructions are separated by semicolons")
    print("- Each extra_id gets a list of instructions")
    print("- Format seems to be: <extra_id_N> followed by instructions")
    print("- Need to test which instruction order works!")

if __name__ == '__main__':
    simple_ca_format_analysis()

RPR_Undo_OnStateChange('Simple_CA_Analysis')