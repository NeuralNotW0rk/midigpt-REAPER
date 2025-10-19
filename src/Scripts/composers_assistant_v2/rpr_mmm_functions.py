"""
REAPER Functions for MMM Integration
Handles parameter reading and server communication
"""

import sys
import os

script_path = os.path.dirname(os.path.realpath(__file__))
ca_path = os.path.join(script_path, 'src', 'Scripts', 'composers_assistant_v2')
if os.path.exists(ca_path):
    sys.path.insert(0, os.path.abspath(ca_path))

try:
    from reaper_python import *
    import preprocessing_functions as pre
except ImportError as e:
    print(f"Warning: Could not import REAPER modules: {e}")


def get_global_options():
    """
    Read global MMM options from master track FX
    Returns object with all parameters matching MMM server expectations
    """
    class GlobalOptions:
        pass
    
    options = GlobalOptions()
    
    # Default values matching MMM server expectations
    options.temperature = 1.0
    options.tracks_per_step = 1
    options.bars_per_step = 1
    options.model_dim = 4
    options.percentage = 100
    options.max_steps = 200
    options.batch_size = 1
    options.shuffle = True
    options.sampling_seed = -1
    options.mask_top_k = 0
    options.polyphony_hard_limit = 6
    
    # CA-compatible options (used by REAPER scripts but not by MMM)
    options.rhy_cond = 0
    options.do_note_range_cond = 0
    options.enc_no_repeat_ngram_size = 0
    options.variation_alg = 0
    options.disp_tr_to_midi_inst = True
    options.gen_notes_are_selected = True
    options.display_warnings = True
    options.verbose = False
    
    try:
        master = RPR_GetMasterTrack(0)
        if master is None:
            print("Warning: Could not get master track")
            return options
        
        # Search Monitor FX chain (like CA does)
        # Monitor FX uses special index: 0x1000000 + fx_index
        fx_loc = -1
        n_fx = 100  # search up to 100 FX
        
        print(f"Searching for MMM Global Options in Monitor FX chain")
        for i in range(0x1000000, 0x1000000 + n_fx):
            if RPR_TrackFX_GetEnabled(master, i):
                # Check if this is our FX by reading the jsfx_id parameter
                val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, i, 0, 0, 0)
                print(f"  Monitor FX {i - 0x1000000}: jsfx_id={val}")
                # MMM/MidiGPT Global Options has jsfx_id = 54964318
                if abs(val - 54964318) < 0.5:
                    fx_loc = i
                    print(f"  --> Found MMM Global Options at monitor FX index {i - 0x1000000}")
                    break
        
        if fx_loc == -1:
            print("Warning: MMM Global Options FX not found in Monitor FX, using defaults")
            return options
        
        # REAPER uses sequential parameter indices, not JSFX slider numbers
        # Parameter 0 = slider1 (jsfx_id), so use loc_offset=1 to skip it
        loc_offset = 1
        
        print(f"Reading parameters from FX at index {fx_loc} with loc_offset={loc_offset}")
        
        # Core generation parameters - REAPER returns actual slider values, no scaling needed!
        # slider10-20 map to parameters 1-11
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 0 + loc_offset, 0, 0)
        options.temperature = val
        print(f"  Temperature: {options.temperature:.3f}")
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 1 + loc_offset, 0, 0)
        options.tracks_per_step = int(val)
        print(f"  Tracks per step: {options.tracks_per_step}")
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 2 + loc_offset, 0, 0)
        options.bars_per_step = int(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 3 + loc_offset, 0, 0)
        options.model_dim = int(val)
        print(f"  Model dim: {options.model_dim}")
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 4 + loc_offset, 0, 0)
        options.percentage = int(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 5 + loc_offset, 0, 0)
        options.max_steps = int(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 6 + loc_offset, 0, 0)
        options.batch_size = int(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 7 + loc_offset, 0, 0)
        options.shuffle = bool(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 8 + loc_offset, 0, 0)
        options.sampling_seed = int(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 9 + loc_offset, 0, 0)
        options.mask_top_k = int(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 10 + loc_offset, 0, 0)
        options.polyphony_hard_limit = int(val)
        
        # CA-compatible parameters
        # slider30-33 map to parameters 12-15
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 11 + loc_offset, 0, 0)
        options.rhy_cond = int(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 12 + loc_offset, 0, 0)
        options.do_note_range_cond = int(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 13 + loc_offset, 0, 0)
        options.enc_no_repeat_ngram_size = int(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 14 + loc_offset, 0, 0)
        options.variation_alg = int(val)
        
        # UI flags
        # slider40-43 map to parameters 16-19
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 15 + loc_offset, 0, 0)
        options.disp_tr_to_midi_inst = bool(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 16 + loc_offset, 0, 0)
        options.gen_notes_are_selected = bool(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 17 + loc_offset, 0, 0)
        options.display_warnings = bool(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 18 + loc_offset, 0, 0)
        options.verbose = bool(val)
    
    except Exception as e:
        print(f"Warning: Could not read global options: {e}")
    
    return options


def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0, start_measure=None, end_measure=None):
    """
    Call the MMM server via XML-RPC
    Uses parameters passed to function, supplementing with global options for MMM-specific params
    """
    from xmlrpc.client import ServerProxy
    import xmlrpc.client
    
    print(f"\ncall_nn_infill called with temperature={temperature}")
    
    try:
        proxy = ServerProxy('http://127.0.0.1:3456')
        
        # Read global options for MMM-specific parameters not in CA signature
        options = get_global_options()
        
        # Build options dict using passed parameters where available
        options_dict = {
            'temperature': temperature,  # Use passed parameter, not options.temperature
            'tracks_per_step': options.tracks_per_step,
            'bars_per_step': options.bars_per_step,
            'model_dim': options.model_dim,
            'percentage': options.percentage,
            'max_steps': options.max_steps,
            'batch_size': options.batch_size,
            'shuffle': options.shuffle,
            'sampling_seed': options.sampling_seed,
            'mask_top_k': options.mask_top_k,
            'polyphony_hard_limit': options.polyphony_hard_limit
        }
        
        print(f"Sending to server: temperature={options_dict['temperature']}, model_dim={options_dict['model_dim']}")
        
        res = proxy.call_nn_infill(
            s, 
            pre.encode_midisongbymeasure_to_save_dict(S), 
            use_sampling, 
            min_length, 
            enc_no_repeat_ngram_size, 
            has_fully_masked_inst, 
            options_dict,
            start_measure, 
            end_measure
        )
        return res
    except xmlrpc.client.Fault as e:
        print('Exception raised by MMM server:')
        print(str(e))
        raise
    except Exception as e:
        print('MMM server connection failed. Make sure mmm_nn_server.py is running on port 3456.')
        print(f'Error: {e}')
        raise