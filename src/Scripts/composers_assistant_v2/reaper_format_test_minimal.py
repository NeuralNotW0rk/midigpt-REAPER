# Minimal REAPER CA Format Test
# Save as: REAPER_test_simple.py in Scripts/composers_assistant_v2/

import rpr_ca_functions as fn
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

def test():
    RPR_ClearConsole()
    print("=== TESTING CA FORMAT ===")
    
    # Get project state
    nn_input = fn.get_nn_input_from_project(
        mask_empty_midi_items=True, 
        mask_selected_midi_items=True,
        do_rhythmic_conditioning=False,
        rhythmic_conditioning_type=None,
        do_note_range_conditioning_by_measure=False,
        note_range_conditioning_type=None,
        display_track_to_MIDI_inst=False,
        display_warnings=True
    )
    
    if not nn_input.continue_:
        print("ERROR: No MIDI items selected")
        return
    
    print(f"Project context: measures {nn_input.start_measure}-{nn_input.end_measure}")
    
    # Test 1: Absolute simplest format
    test1 = ";M:0;N:60;d:1920;w:1920;"
    print(f"\nTest 1 - Simple: {test1}")
    
    try:
        fn.write_nn_output_to_project(
            nn_output=test1,
            nn_input_obj=nn_input,
            notes_are_selected=True,
            use_vels_from_tr_measures=False
        )
        print("Test 1: SUCCESS - Check REAPER for C4 (pitch 60)")
    except Exception as e:
        print(f"Test 1: FAILED - {e}")
    
    # Test 2: Your server's exact format
    test2 = ";M:0;B:5;L:96;I:0;N:43;d:1920;w:1920;M:1;B:5;L:96;I:0;N:45;d:1920;w:1920;N:48;d:1920;w:1920;"
    print(f"\nTest 2 - Server format: {test2}")
    
    try:
        fn.write_nn_output_to_project(
            nn_output=test2,
            nn_input_obj=nn_input,
            notes_are_selected=True,
            use_vels_from_tr_measures=False
        )
        print("Test 2: SUCCESS - Check REAPER for notes in measures 0-1")
    except Exception as e:
        print(f"Test 2: FAILED - {e}")
    
    print("\n=== TEST COMPLETE ===")
    print("If no notes appeared, the issue is in write_nn_output_to_project")

if __name__ == '__main__':
    test()

RPR_Undo_OnStateChange('CA_Format_Test')
