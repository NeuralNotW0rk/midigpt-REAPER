# rpr_midigpt_functions.py - Complete with parameter reading AND call_nn_infill
import preprocessing_functions as pre


def test_function():
    return "midigpt functions loaded"


# Mapping from slider values to MidiGPT polyphony enum strings
POLYPHONY_MAP = {
    0: 'POLYPHONY_ANY',
    1: 'POLYPHONY_0_1',
    2: 'POLYPHONY_1_2',
    3: 'POLYPHONY_2_3',
    4: 'POLYPHONY_3_4',
    5: 'POLYPHONY_4_5',
    6: 'POLYPHONY_5_6',
    7: 'POLYPHONY_6_7',
    8: 'POLYPHONY_7_8',
    9: 'POLYPHONY_8_PLUS'
}

# Mapping from slider values to instrument enum strings (GM MIDI names)
INSTRUMENT_MAP = {
    0: 'acoustic_grand_piano',
    1: 'bright_acoustic_piano',
    2: 'electric_grand_piano',
    3: 'honky_tonk_piano',
    4: 'electric_piano_1',
    5: 'electric_piano_2',
    6: 'harpsichord',
    7: 'clavi',
    8: 'celesta',
    9: 'glockenspiel',
    10: 'music_box',
    11: 'vibraphone',
    12: 'marimba',
    13: 'xylophone',
    14: 'tubular_bells',
    15: 'dulcimer',
    16: 'drawbar_organ',
    17: 'percussive_organ',
    18: 'rock_organ',
    19: 'church_organ',
    20: 'reed_organ',
    21: 'accordion',
    22: 'harmonica',
    23: 'tango_accordion',
    24: 'acoustic_guitar_nylon',
    25: 'acoustic_guitar_steel',
    26: 'electric_guitar_jazz',
    27: 'electric_guitar_clean',
    28: 'electric_guitar_muted',
    29: 'overdriven_guitar',
    30: 'distortion_guitar',
    31: 'guitar_harmonics',
    32: 'acoustic_bass',
    33: 'electric_bass_finger',
    34: 'electric_bass_pick',
    35: 'fretless_bass',
    36: 'slap_bass_1',
    37: 'slap_bass_2',
    38: 'synth_bass_1',
    39: 'synth_bass_2',
    40: 'violin',
    41: 'viola',
    42: 'cello',
    43: 'contrabass',
    44: 'tremolo_strings',
    45: 'pizzicato_strings',
    46: 'orchestral_harp',
    47: 'timpani',
    48: 'string_ensemble_1',
    49: 'string_ensemble_2',
    50: 'synth_strings_1',
    51: 'synth_strings_2',
    52: 'choir_aahs',
    53: 'voice_oohs',
    54: 'synth_voice',
    55: 'orchestra_hit',
    56: 'trumpet',
    57: 'trombone',
    58: 'tuba',
    59: 'muted_trumpet',
    60: 'french_horn',
    61: 'brass_section',
    62: 'synth_brass_1',
    63: 'synth_brass_2',
    64: 'soprano_sax',
    65: 'alto_sax',
    66: 'tenor_sax',
    67: 'baritone_sax',
    68: 'oboe',
    69: 'english_horn',
    70: 'bassoon',
    71: 'clarinet',
    72: 'piccolo',
    73: 'flute',
    74: 'recorder',
    75: 'pan_flute',
    76: 'blown_bottle',
    77: 'shakuhachi',
    78: 'whistle',
    79: 'ocarina',
    80: 'lead_1_square',
    81: 'lead_2_sawtooth',
    82: 'lead_3_calliope',
    83: 'lead_4_chiff',
    84: 'lead_5_charang',
    85: 'lead_6_voice',
    86: 'lead_7_fifths',
    87: 'lead_8_bass__lead',
    88: 'pad_1_new_age',
    89: 'pad_2_warm',
    90: 'pad_3_polysynth',
    91: 'pad_4_choir',
    92: 'pad_5_bowed',
    93: 'pad_6_metallic',
    94: 'pad_7_halo',
    95: 'pad_8_sweep',
    96: 'fx_1_rain',
    97: 'fx_2_soundtrack',
    98: 'fx_3_crystal',
    99: 'fx_4_atmosphere',
    100: 'fx_5_brightness',
    101: 'fx_6_goblins',
    102: 'fx_7_echoes',
    103: 'fx_8_sci_fi',
    104: 'sitar',
    105: 'banjo',
    106: 'shamisen',
    107: 'koto',
    108: 'kalimba',
    109: 'bag_pipe',
    110: 'fiddle',
    111: 'shanai',
    112: 'tinkle_bell',
    113: 'agogo',
    114: 'steel_drums',
    115: 'woodblock',
    116: 'taiko_drum',
    117: 'melodic_tom',
    118: 'synth_drum',
    119: 'reverse_cymbal',
    120: 'guitar_fret_noise',
    121: 'breath_noise',
    122: 'seashore',
    123: 'bird_tweet',
    124: 'telephone_ring',
    125: 'helicopter',
    126: 'applause',
    127: 'gunshot',
    128: 'drums'
}

# Track type mapping
TRACK_TYPE_MAP = {
    8: 'AUX_DRUM_TRACK',
    9: 'AUX_INST_TRACK',
    10: 'STANDARD_TRACK',
    11: 'STANDARD_DRUM_TRACK',
    12: 'STANDARD_BOTH'
}


def is_approx(a, b, tolerance=0.001):
    """Built-in approximation function - no external dependencies"""
    return abs(a - b) < tolerance


class MidigptGlobalOptionsObj:
    def __init__(self):
        # Core generation parameters
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
        
        # UI flags
        self.display_track_to_MIDI_inst = True
        self.generated_notes_are_selected = True
        self.display_warnings = True
        self.verbose = False
        
        # CA-compatible options (kept for script compatibility)
        self.do_rhythm_conditioning = False
        self.rhythm_conditioning_type = 'none'
        self.do_note_range_conditioning = False
        self.note_range_conditioning_type = 'none'
        self.enc_no_repeat_ngram_size = 0


class MidigptTrackOptionsObj:
    def __init__(self):
        # Temperature override
        self.track_temperature = -1
        
        # Instrument and track settings
        self.instrument = 'acoustic_grand_piano'
        self.density = 10
        self.track_type = 'STANDARD_TRACK'
        
        # Polyphony constraints
        self.min_polyphony_q = 'POLYPHONY_ANY'
        self.max_polyphony_q = 'POLYPHONY_ANY'
        self.polyphony_hard_limit = -1


def get_midigpt_global_options():
    """Read global options from REAPER FX"""
    from reaper_python import RPR_GetMasterTrack, RPR_TrackFX_GetParam
    
    print("get_midigpt_global_options called")
    
    options = MidigptGlobalOptionsObj()
    
    # Find the MidiGPT Global Options FX on master track
    tr = RPR_GetMasterTrack(-1)
    n_fx = 100
    fx_idx = -1
    
    for i in range(0x1000000, 0x1000000 + n_fx):
        v = RPR_TrackFX_GetParam(tr, i, 0, 0, 0)[0]
        if is_approx(v, 54964318):
            fx_idx = i
            break
    
    if fx_idx == -1:
        print("MidiGPT Global Options FX not found, using defaults")
        return options
    
    # Read parameters
    options.temperature = RPR_TrackFX_GetParam(tr, fx_idx, 10, 0, 0)[0]
    options.tracks_per_step = int(RPR_TrackFX_GetParam(tr, fx_idx, 11, 0, 0)[0])
    options.bars_per_step = int(RPR_TrackFX_GetParam(tr, fx_idx, 12, 0, 0)[0])
    options.model_dim = int(RPR_TrackFX_GetParam(tr, fx_idx, 13, 0, 0)[0])
    options.percentage = int(RPR_TrackFX_GetParam(tr, fx_idx, 14, 0, 0)[0])
    options.max_steps = int(RPR_TrackFX_GetParam(tr, fx_idx, 15, 0, 0)[0])
    options.batch_size = int(RPR_TrackFX_GetParam(tr, fx_idx, 16, 0, 0)[0])
    options.shuffle = bool(RPR_TrackFX_GetParam(tr, fx_idx, 17, 0, 0)[0])
    options.sampling_seed = int(RPR_TrackFX_GetParam(tr, fx_idx, 18, 0, 0)[0])
    options.mask_top_k = int(RPR_TrackFX_GetParam(tr, fx_idx, 19, 0, 0)[0])
    options.polyphony_hard_limit = int(RPR_TrackFX_GetParam(tr, fx_idx, 20, 0, 0)[0])
    
    # CA-compatible options
    rhy_cond_val = int(RPR_TrackFX_GetParam(tr, fx_idx, 30, 0, 0)[0])
    options.do_rhythm_conditioning = rhy_cond_val > 0
    options.rhythm_conditioning_type = ['none', 'rhythm', 'rhythm_pitch'][rhy_cond_val]
    
    note_range_val = int(RPR_TrackFX_GetParam(tr, fx_idx, 31, 0, 0)[0])
    options.do_note_range_conditioning = note_range_val > 0
    options.note_range_conditioning_type = ['none', 'loose', 'strict'][note_range_val]
    
    options.enc_no_repeat_ngram_size = int(RPR_TrackFX_GetParam(tr, fx_idx, 32, 0, 0)[0])
    
    # UI flags
    options.display_track_to_MIDI_inst = bool(RPR_TrackFX_GetParam(tr, fx_idx, 40, 0, 0)[0])
    options.generated_notes_are_selected = bool(RPR_TrackFX_GetParam(tr, fx_idx, 41, 0, 0)[0])
    options.display_warnings = bool(RPR_TrackFX_GetParam(tr, fx_idx, 42, 0, 0)[0])
    options.verbose = bool(RPR_TrackFX_GetParam(tr, fx_idx, 43, 0, 0)[0])
    
    return options


def get_global_options():
    """CA-compatible function name that REAPER script expects"""
    print("get_global_options called (midigpt version)")
    return get_midigpt_global_options()


def get_midigpt_track_options_by_track_idx():
    """Read track-specific options from REAPER FX"""
    from reaper_python import RPR_GetTrack, RPR_CountTracks, RPR_TrackFX_GetParam
    
    print("get_midigpt_track_options_by_track_idx called")
    
    track_options = {}
    num_tracks = RPR_CountTracks(0)
    
    for track_idx in range(num_tracks):
        track = RPR_GetTrack(0, track_idx)
        
        # Find MidiGPT Track Options FX on this track
        fx_idx = -1
        for i in range(100):
            v = RPR_TrackFX_GetParam(track, i, 0, 0, 0)[0]
            if is_approx(v, 349583025):
                fx_idx = i
                break
        
        if fx_idx == -1:
            continue
        
        options = MidigptTrackOptionsObj()
        
        # Read parameters
        options.track_temperature = RPR_TrackFX_GetParam(track, fx_idx, 10, 0, 0)[0]
        
        instrument_idx = int(RPR_TrackFX_GetParam(track, fx_idx, 20, 0, 0)[0])
        options.instrument = INSTRUMENT_MAP.get(instrument_idx, 'acoustic_grand_piano')
        
        options.density = int(RPR_TrackFX_GetParam(track, fx_idx, 30, 0, 0)[0])
        
        track_type_idx = int(RPR_TrackFX_GetParam(track, fx_idx, 40, 0, 0)[0])
        options.track_type = TRACK_TYPE_MAP.get(track_type_idx, 'STANDARD_TRACK')
        
        min_poly_idx = int(RPR_TrackFX_GetParam(track, fx_idx, 50, 0, 0)[0])
        options.min_polyphony_q = POLYPHONY_MAP.get(min_poly_idx, 'POLYPHONY_ANY')
        
        max_poly_idx = int(RPR_TrackFX_GetParam(track, fx_idx, 51, 0, 0)[0])
        options.max_polyphony_q = POLYPHONY_MAP.get(max_poly_idx, 'POLYPHONY_ANY')
        
        options.polyphony_hard_limit = int(RPR_TrackFX_GetParam(track, fx_idx, 52, 0, 0)[0])
        
        track_options[track_idx] = options
    
    return track_options


def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0, start_measure=None, end_measure=None):
    """
    Call the MidiGPT server via XML-RPC
    Includes start_measure and end_measure for proper selection bounds
    """
    from xmlrpc.client import ServerProxy
    import xmlrpc.client
    
    try:
        proxy = ServerProxy('http://127.0.0.1:3456')
        res = proxy.call_nn_infill(s, pre.encode_midisongbymeasure_to_save_dict(S), use_sampling, min_length, 
                                   enc_no_repeat_ngram_size, has_fully_masked_inst, temperature,
                                   start_measure, end_measure)
        return res
    except xmlrpc.client.Fault as e:
        print('Exception raised by MidiGPT server:')
        print(str(e))
        raise
    except Exception as e:
        print('MidiGPT server connection failed. Make sure midigpt_server.py is running on port 3456.')
        print(f'Error: {e}')
        raise


def build_midigpt_generation_request(global_options, track_options, project_data):
    """Not used in current unified architecture - using direct server"""
    print("No need to build midigpt request - using direct server")
    return None


def call_midigpt_via_proxy(nn_input, options):
    """Legacy proxy method - not used in current unified architecture"""
    print("call_midigpt_via_proxy called but not implemented")
    print("Using direct call_nn_infill instead")
    return "<extra_id_0>N:60;d:240;w:240;N:64;d:240;w:240;"