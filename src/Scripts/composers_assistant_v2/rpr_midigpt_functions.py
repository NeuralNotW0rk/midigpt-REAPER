# rpr_midigpt_functions.py - Fixed version with missing get_global_options

def test_function():
    return "midigpt functions loaded"

class MidigptGlobalOptionsObj:
    def __init__(self):
        self.temperature = 1.0
        self.tracks_per_step = 1
        self.bars_per_step = 1
        self.model_dim = 4
        self.percentage = 100
        self.max_steps = 200
        self.batch_size = 1
        self.shuffle = True
        self.sampling_seed = -1
        self.mask_top_k = 0
        self.polyphony_hard_limit = 6
        self.display_track_to_MIDI_inst = True
        self.generated_notes_are_selected = True
        self.display_warnings = True
        self.verbose = False
        
        # Add CA-compatible options that the REAPER script expects
        self.do_rhythm_conditioning = False
        self.rhythm_conditioning_type = 'none'
        self.do_note_range_conditioning = False
        self.note_range_conditioning_type = 'none'
        self.enc_no_repeat_ngram_size = 0

def get_midigpt_global_options():
    print("get_midigpt_global_options called")
    return MidigptGlobalOptionsObj()

def get_global_options():
    """CA-compatible function name that REAPER script expects"""
    print("get_global_options called (midigpt version)")
    return get_midigpt_global_options()

def get_midigpt_track_options_by_track_idx():
    print("get_midigpt_track_options_by_track_idx called")
    return {}

def build_midigpt_generation_request(global_options, track_options, project_data):
    print("No need to build midigpt request - using direct server")
    return None

def call_midigpt_via_proxy(nn_input, options):
    """Legacy proxy method - not used in current unified architecture"""
    print("call_midigpt_via_proxy called but not implemented")
    print("Using direct call_nn_infill instead")
    
    # This should not be called in the unified architecture
    # The REAPER script should use rpr_ca_functions.call_nn_infill directly
    return "<extra_id_0>N:60;d:240;w:240;N:64;d:240;w:240"

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, has_fully_masked_inst=False,
                   temperature=1.0, start_measure=None, end_measure=None):
    """
    Call the MidiGPT server via XML-RPC
    Includes start_measure and end_measure for proper selection bounds
    """
    from xmlrpc.client import ServerProxy
    import xmlrpc.client
    import preprocessing_functions as pre
    import message_tools as mt
    
    try:
        proxy = ServerProxy('http://127.0.0.1:3456')
        # Pass all parameters including the new selection bounds
        res = proxy.call_nn_infill(s, pre.encode_midisongbymeasure_to_save_dict(S), use_sampling, min_length, 
                                   enc_no_repeat_ngram_size, has_fully_masked_inst, temperature,
                                   start_measure, end_measure)
    except Exception as exception:
        if type(exception) == xmlrpc.client.Fault:
            print('Exception raised by NN:')
        else:
            errormsg = 'NN server not found. '
            errormsg += 'Make sure you have started the MidiGPT server manually.'
            mt.messagebox(msg=errormsg,
                          title='REAPER: MidiGPT server error',
                          int_type=0)
        raise exception

    return res