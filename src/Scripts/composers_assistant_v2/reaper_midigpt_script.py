# REAPER_midigpt_replace_selected_midi_items.py
# Streamlined midigpt integration for Reaper - replaces selected MIDI items with AI-generated content

import midigpt_rpr_functions as midigpt_fn
from reaper_python import *
import sys
import xmlrpc.client

def patch_stdout_stderr_open():
    """Redirect Python output to Reaper console"""
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

def call_midigpt_server_direct(piece_json, status_json, param_json):
    """
    Call the midigpt server directly using the new JSON-based interface.
    Returns the result JSON from midigpt.
    """
    try:
        # Connect to midigpt server
        server = xmlrpc.client.ServerProxy('http://127.0.0.1:3456')
        
        print("🎛️ Calling midigpt server with native JSON interface...")
        
        # Call the new direct interface (not legacy compatibility)
        result = server.call_nn_infill_direct(piece_json, status_json, param_json)
        
        print("✅ midigpt server responded successfully")
        return result
        
    except Exception as e:
        print(f"❌ Error calling midigpt server: {e}")
        print("💡 Make sure midigpt_nn_server.py is running on port 3456")
        return None

def get_selected_midi_items_and_time_selection():
    """
    Get the current time selection and selected MIDI items from Reaper.
    Returns (start_time, end_time, selected_items, track_info)
    """
    # Get time selection
    start_time, end_time = RPR_GetSet_LoopTimeRange2(0, False, False, 0, 0, False)
    
    if start_time == end_time:
        print("❌ No time selection found. Please select a time range in Reaper.")
        return None, None, None, None
    
    # Get selected items
    selected_items = []
    num_selected = RPR_CountSelectedMediaItems(0)
    
    if num_selected == 0:
        print("❌ No MIDI items selected. Please select MIDI items in your time selection.")
        return None, None, None, None
    
    for i in range(num_selected):
        item = RPR_GetSelectedMediaItem(0, i)
        take = RPR_GetActiveTake(item)
        if take and RPR_TakeIsMIDI(take):
            track = RPR_GetMediaItem_Track(item)
            selected_items.append((item, take, track))
    
    if not selected_items:
        print("❌ No MIDI takes found in selected items.")
        return None, None, None, None
    
    print(f"✅ Found {len(selected_items)} MIDI items in time selection {start_time:.2f}-{end_time:.2f}s")
    
    return start_time, end_time, selected_items, None

def process_selected_items_with_midigpt():
    """
    Main processing function: get selection, call midigpt, write results back to Reaper.
    """
    try:
        # Step 1: Read midigpt parameters from JSFX
        print("📖 Reading midigpt parameters from JSFX...")
        global_options = midigpt_fn.get_midigpt_global_options()
        track_options = midigpt_fn.get_midigpt_track_options_by_track_idx()
        
        if midigpt_fn.DEBUG or global_options.display_track_to_MIDI_inst:
            print(f"Global options: temperature={global_options.temperature}, bars_per_step={global_options.bars_per_step}")
        
        # Step 2: Get current Reaper selection
        print("🎯 Analyzing Reaper selection...")
        start_time, end_time, selected_items, _ = get_selected_midi_items_and_time_selection()
        
        if not selected_items:
            return
        
        # Step 3: Convert Reaper data to midigpt format
        print("🔄 Converting Reaper data to midigpt format...")
        
        # This is where we'd normally call existing functions to get S (MidiSongByMeasure)
        # and mask_locations from the Reaper selection
        
        # For now, using the existing legacy input processing but converting to new format:
        import rpr_ca_functions as legacy_fn
        
        # Get input using existing function (this gives us S and masks)
        nn_input = legacy_fn.get_nn_input_from_project(
            mask_empty_midi_items=True,
            mask_selected_midi_items=True,
            do_rhythmic_conditioning=False,  # midigpt handles this differently
            rhythmic_conditioning_type="none",
            do_note_range_conditioning_by_measure=False,
            note_range_conditioning_type="none",
            display_track_to_MIDI_inst=global_options.display_track_to_MIDI_inst,
            display_warnings=global_options.display_warnings
        )
        
        if not nn_input.continue_:
            print("❌ No valid input for midigpt generation")
            return
        
        # Convert to midigpt format
        print("🎼 Converting to native midigpt JSON format...")
        piece_json, status_json, param_json = midigpt_fn.get_nn_input_for_midigpt(
            S=nn_input.S,
            mask_locations=nn_input.mask_locations
        )
        
        # Step 4: Call midigpt server
        print("🤖 Generating music with midigpt...")
        result_json = call_midigpt_server_direct(piece_json, status_json, param_json)
        
        if not result_json:
            return
        
        # Step 5: Process midigpt result and write to Reaper
        print("📝 Writing generated music back to Reaper...")
        
        # Convert midigpt JSON result back to the format the write functions expect
        # This uses the existing write infrastructure but with midigpt-generated content
        
        # For now, we'll need to convert the midigpt result to the legacy format
        # that the existing write_nn_output_to_project function expects
        legacy_format_result = midigpt_fn.convert_midigpt_result_to_legacy_format(
            midigpt_result=result_json,
            mask_locations=nn_input.mask_locations
        )
        
        # Use existing write function with new result
        legacy_fn.write_nn_output_to_project(
            nn_output=legacy_format_result,
            nn_input_obj=nn_input,
            notes_are_selected=global_options.generated_notes_are_selected,
            use_vels_from_tr_measures=False  # midigpt handles velocity
        )
        
        print("✅ midigpt generation completed successfully!")
        print(f"🎵 Generated content written to {len(selected_items)} tracks")
        
    except Exception as e:
        print(f"❌ Error in midigpt processing: {e}")
        if midigpt_fn.DEBUG:
            import traceback
            traceback.print_exc()

def check_midigpt_setup():
    """
    Check if midigpt system is properly configured.
    """
    print("🔍 Checking midigpt setup...")
    
    # Check for global options JSFX
    global_fx_loc = midigpt_fn._locate_midigpt_global_options_FX_loc()
    if global_fx_loc == -1:
        print("⚠️  Warning: midigpt_global_options.jsfx not found on master track")
        print("💡 Add midigpt_global_options.jsfx to your master track for full control")
        return False
    else:
        print("✅ midigpt global options JSFX found on master track")
    
    # Check for track options JSFX
    track_count = 0
    for i, track in midigpt_fn.mt.get_tracks_by_idx().items():
        if midigpt_fn._locate_midigpt_track_options_FX_loc(track) != -1:
            track_count += 1
    
    if track_count > 0:
        print(f"✅ midigpt track options found on {track_count} tracks")
    else:
        print("⚠️  Warning: No midigpt_track_options.jsfx found on any tracks")
        print("💡 Add midigpt_track_options.jsfx to tracks for per-track control")
    
    # Test server connection
    try:
        server = xmlrpc.client.ServerProxy('http://127.0.0.1:3456')
        # Try a simple call to test connectivity
        result = server.system.listMethods()
        print("✅ midigpt server connection successful")
        return True
    except Exception as e:
        print(f"❌ Cannot connect to midigpt server: {e}")
        print("💡 Make sure midigpt_nn_server.py is running")
        return False

def main():
    """Main entry point for the midigpt Reaper script."""
    
    # Clear console for fresh output
    RPR_ClearConsole()
    
    print("🎛️ midigpt Music Generation for Reaper")
    print("=" * 50)
    
    # Check setup
    if not check_midigpt_setup():
        print("\n❌ midigpt setup incomplete. Please fix the issues above and try again.")
        return
    
    print("\n🚀 Starting midigpt generation process...")
    
    # Process the selection
    process_selected_items_with_midigpt()

if __name__ == '__main__':
    main()

# Create undo point
RPR_Undo_OnStateChange('midigpt Generation')