# REAPER Debug Script - Run this in REAPER to debug note display issue
# Save as: REAPER_debug_note_display.py

import rpr_ca_functions as fn
import rpr_midigpt_functions as midigpt_fn
from reaper_python import *
import sys

def patch_stdout_stderr_open():
    global open, original_open, reaper_console

    class ReaperConsole:
        def write(self, output):
            RPR_ShowConsoleMsg(output)

        def flush(self):
            pass

        def close(self):
            pass

    reaper_console = ReaperConsole()
    sys.stdout = reaper_console
    sys.stderr = reaper_console

    original_open = open
    open = lambda *args, **kwargs: reaper_console

patch_stdout_stderr_open()

def debug_note_display_issue():
    """Debug why notes aren't appearing in REAPER after MidiGPT generation"""
    
    print("=== DEBUGGING NOTE DISPLAY ISSUE ===")
    RPR_ClearConsole()
    
    # Force debug mode
    fn.DEBUG = True
    
    print("1. Testing MidiGPT options...")
    try:
        options = midigpt_fn.get_global_options()
        print(f"   Temperature: {options.temperature}")
        print(f"   Enc no repeat ngram size: {options.enc_no_repeat_ngram_size}")
        print(f"   Generated notes are selected: {options.generated_notes_are_selected}")
        print(f"   Display warnings: {options.display_warnings}")
    except Exception as e:
        print(f"   ERROR loading MidiGPT options: {e}")
        return
    
    print("\n2. Getting project input...")
    try:
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
        print(f"   Continue: {nn_input.continue_}")
        if nn_input.continue_:
            print(f"   Input string length: {len(nn_input.nn_input_string)}")
            print(f"   Input preview: {nn_input.nn_input_string[:100]}...")
            print(f"   Start measure: {nn_input.start_measure}")
            print(f"   End measure: {nn_input.end_measure}")
        else:
            print("   No continuation needed - no masked items found")
            return
            
    except Exception as e:
        print(f"   ERROR getting project input: {e}")
        return
    
    print("\n3. Testing server call...")
    try:
        use_sampling = "None" if not fn.ALWAYS_TOP_P else True
        print(f"   Calling server with sampling: {use_sampling}")
        
        nn_output = fn.call_nn_infill(
            s=nn_input.nn_input_string,
            S=nn_input.S,
            use_sampling=use_sampling,
            min_length=2,
            enc_no_repeat_ngram_size=options.enc_no_repeat_ngram_size,
            has_fully_masked_inst=nn_input.has_fully_masked_inst,
            temperature=options.temperature
        )
        
        print(f"   Server response type: {type(nn_output)}")
        print(f"   Server response length: {len(str(nn_output))}")
        print(f"   Server response preview: {str(nn_output)[:200]}...")
        
        if not nn_output or str(nn_output).strip() == "":
            print("   ERROR: Server returned empty response!")
            return
            
    except Exception as e:
        print(f"   ERROR calling server: {e}")
        return
    
    print("\n4. Testing direct note writing with simple string...")
    try:
        # Test with a very simple known-good CA string
        simple_test = ";M:0;N:60;d:1920;w:1920;M:1;N:64;d:1920;w:1920;"
        print(f"   Testing with simple string: {simple_test}")
        
        # Get current selected items count
        num_items_before = RPR_CountSelectedMediaItems(0)
        print(f"   Selected MIDI items before: {num_items_before}")
        
        fn.write_nn_output_to_project(
            nn_output=simple_test, 
            nn_input_obj=nn_input,
            notes_are_selected=True,
            use_vels_from_tr_measures=False
        )
        
        # Check if anything changed
        num_items_after = RPR_CountSelectedMediaItems(0)
        print(f"   Selected MIDI items after: {num_items_after}")
        
        print("   Simple test completed - check if notes appeared")
        
    except Exception as e:
        print(f"   ERROR in simple note writing test: {e}")
    
    print("\n5. Testing with actual server output...")
    try:
        print("   Writing server output to project...")
        
        fn.write_nn_output_to_project(
            nn_output=nn_output, 
            nn_input_obj=nn_input,
            notes_are_selected=options.generated_notes_are_selected,
            use_vels_from_tr_measures=options.do_rhythm_conditioning
        )
        
        print("   Server output writing completed - check if notes appeared")
        
    except Exception as e:
        print(f"   ERROR writing server output: {e}")
        import traceback
        print(f"   Full traceback: {traceback.format_exc()}")
    
    print("\n6. Comparing parameters with CA system...")
    try:
        # Get CA options for comparison
        ca_options = fn.get_global_options()  # This gets CA options, not MidiGPT
        print(f"   CA enc_no_repeat_ngram_size: {ca_options.enc_no_repeat_ngram_size}")
        print(f"   MidiGPT enc_no_repeat_ngram_size: {options.enc_no_repeat_ngram_size}")
        
        if ca_options.enc_no_repeat_ngram_size != options.enc_no_repeat_ngram_size:
            print("   WARNING: Different ngram size values detected!")
            
    except Exception as e:
        print(f"   ERROR comparing with CA system: {e}")
    
    print("\n=== DEBUG SESSION COMPLETE ===")
    print("Check REAPER project for any new notes that appeared during tests")

if __name__ == '__main__':
    debug_note_display_issue()

RPR_Undo_OnStateChange('Debug_Note_Display')
