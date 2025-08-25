# rpr_midigpt_functions.py - Clean ASCII version

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

def get_midigpt_global_options():
    print("get_midigpt_global_options called")
    return MidigptGlobalOptionsObj()

def get_midigpt_track_options_by_track_idx():
    print("get_midigpt_track_options_by_track_idx called")
    return {}

def build_midigpt_generation_request(global_options, track_options, project_data):
    print("No need to build midigpt request - using proxy server")
    return None

def call_midigpt_via_proxy(nn_input, options):
    print("Calling midigpt via proxy server...")
    
    try:
        import xmlrpc.client
        
        print("Connecting to proxy server on port 3456...")
        proxy = xmlrpc.client.ServerProxy('http://127.0.0.1:3456')
        
        print("Calling proxy.call_nn_infill with positional arguments...")
        
        # Convert nn_input.S to the format expected by proxy
        import preprocessing_functions as pre
        S_dict = pre.encode_midisongbymeasure_to_save_dict(nn_input.S)
        
        # Call with positional arguments in the correct order:
        # call_nn_infill(s, S, use_sampling, min_length, enc_no_repeat_ngram_size, has_fully_masked_inst, temperature)
        result = proxy.call_nn_infill(
            nn_input.nn_input_string,     # s
            S_dict,                       # S (as dict)
            True,                         # use_sampling
            10,                           # min_length
            0,                            # enc_no_repeat_ngram_size
            nn_input.has_fully_masked_inst, # has_fully_masked_inst
            options.temperature           # temperature
        )
        
        print("Proxy server returned result (length: " + str(len(str(result))) + ")")
        return result
        
    except Exception as e:
        print("ERROR calling proxy server: " + str(e))
        import traceback
        traceback.print_exc()
        return None

def get_global_options():
    print("Compatibility get_global_options called")
    
    class CompatOptions:
        def __init__(self):
            self.temperature = 1.0
            self.display_track_to_MIDI_inst = True
            self.generated_notes_are_selected = True
            self.display_warnings = True
            self.do_rhythm_conditioning = False
            self.rhythm_conditioning_type = None
            self.do_note_range_conditioning = False
            self.note_range_conditioning_type = None
            self.enc_no_repeat_ngram_size = 3
            self.variation_alg = 0
    
    return CompatOptions()