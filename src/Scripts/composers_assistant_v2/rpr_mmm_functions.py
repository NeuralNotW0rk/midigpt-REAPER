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
    Returns dict with all parameters
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
    
    # Additional CA-compatible options (not used by MMM but kept for compatibility)
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
            return options
        
        # Find MMM Global Options FX
        fx_count = RPR_TrackFX_GetCount(master)
        fx_loc = -1
        
        for i in range(fx_count):
            _, _, fx_name, _ = RPR_TrackFX_GetFXName(master, i, "", 256)
            if 'mmm Global Options' in fx_name or 'midigpt Global Options' in fx_name:
                fx_loc = i
                break
        
        if fx_loc == -1:
            return options
        
        # Read parameters from FX
        loc_offset = 0
        
        # Core generation parameters (sliders 10-20)
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 10 + loc_offset, 0, 0)
        options.temperature = 0.5 + val * 1.5
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 11 + loc_offset, 0, 0)
        options.tracks_per_step = int(1 + val * 7)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 12 + loc_offset, 0, 0)
        options.bars_per_step = int(1 + val * 3)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 13 + loc_offset, 0, 0)
        options.model_dim = int(2 + val * 6)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 14 + loc_offset, 0, 0)
        options.percentage = int(10 + val * 90)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 15 + loc_offset, 0, 0)
        options.max_steps = int(50 + val * 950)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 16 + loc_offset, 0, 0)
        options.batch_size = int(1 + val * 3)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 17 + loc_offset, 0, 0)
        options.shuffle = bool(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 18 + loc_offset, 0, 0)
        options.sampling_seed = int(-1 + val * 10000)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 19 + loc_offset, 0, 0)
        options.mask_top_k = int(val * 50)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 20 + loc_offset, 0, 0)
        options.polyphony_hard_limit = int(1 + val * 15)
        
        # CA-compatible parameters (sliders 30-33)
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 30 + loc_offset, 0, 0)
        options.rhy_cond = int(val * 2)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 31 + loc_offset, 0, 0)
        options.do_note_range_cond = int(val * 2)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 32 + loc_offset, 0, 0)
        options.enc_no_repeat_ngram_size = int(val * 10)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 33 + loc_offset, 0, 0)
        options.variation_alg = int(val * 2)
        
        # UI flags (sliders 40-43)
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 40 + loc_offset, 0, 0)
        options.disp_tr_to_midi_inst = bool(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 41 + loc_offset, 0, 0)
        options.gen_notes_are_selected = bool(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 13 + loc_offset, 0, 0)
        options.display_warnings = bool(val)
        
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, 14 + loc_offset, 0, 0)
        options.verbose = bool(val)
    
    except Exception as e:
        print(f"Warning: Could not read global options: {e}")
    
    return options


def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0, start_measure=None, end_measure=None):
    """
    Call the MMM server via XML-RPC
    Includes start_measure and end_measure for proper selection bounds
    """
    from xmlrpc.client import ServerProxy
    import xmlrpc.client
    
    try:
        proxy = ServerProxy('http://127.0.0.1:3456')
        
        # Get global options and convert to dict
        options = get_global_options()
        options_dict = {
            'temperature': options.temperature,
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


def build_mmm_generation_request(global_options, track_options, project_data):
    """Not used in current unified architecture - using direct server"""
    print("No need to build MMM request - using direct server")
    return None