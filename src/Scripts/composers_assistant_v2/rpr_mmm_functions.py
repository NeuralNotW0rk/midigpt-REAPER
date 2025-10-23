"""
REAPER Functions for MMM Integration
Handles parameter reading, control string conversion, and server communication
"""

import sys
import os

import mytrackviewstuff as mt
import mymidistuff as mm
import myfunctions as mf
import midisong as ms
import nn_str_functions as nns
import constants as cs
import encoding_functions as enc
import tokenizer_functions as tok
import preprocessing_functions as pre
import midi_inst_to_name

GLOBAL_FX_ID = 54964318
TRACK_FX_ID = 349583025
DEBUG = True

script_path = os.path.dirname(os.path.realpath(__file__))
ca_path = os.path.join(script_path, 'src', 'Scripts', 'composers_assistant_v2')
if os.path.exists(ca_path):
    sys.path.insert(0, os.path.abspath(ca_path))

try:
    from reaper_python import *
    import preprocessing_functions as pre
except ImportError as e:
    print(f"Warning: Could not import REAPER modules: {e}")

# Polyphony quantile mapping
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

# GM MIDI Instrument mapping
INSTRUMENT_MAP = {
    0: 'acoustic_grand_piano', 1: 'bright_acoustic_piano', 2: 'electric_grand_piano',
    3: 'honky_tonk_piano', 4: 'electric_piano_1', 5: 'electric_piano_2',
    6: 'harpsichord', 7: 'clavinet', 8: 'celesta', 9: 'glockenspiel',
    10: 'music_box', 11: 'vibraphone', 12: 'marimba', 13: 'xylophone',
    14: 'tubular_bells', 15: 'dulcimer', 16: 'drawbar_organ', 17: 'percussive_organ',
    18: 'rock_organ', 19: 'church_organ', 20: 'reed_organ', 21: 'accordion',
    22: 'harmonica', 23: 'tango_accordion', 24: 'acoustic_guitar_nylon', 
    25: 'acoustic_guitar_steel', 26: 'electric_guitar_jazz', 27: 'electric_guitar_clean',
    28: 'electric_guitar_muted', 29: 'overdriven_guitar', 30: 'distortion_guitar',
    31: 'guitar_harmonics', 32: 'acoustic_bass', 33: 'electric_bass_finger',
    34: 'electric_bass_pick', 35: 'fretless_bass', 36: 'slap_bass_1',
    37: 'slap_bass_2', 38: 'synth_bass_1', 39: 'synth_bass_2',
    40: 'violin', 41: 'viola', 42: 'cello', 43: 'contrabass',
    44: 'tremolo_strings', 45: 'pizzicato_strings', 46: 'orchestral_harp',
    47: 'timpani', 48: 'string_ensemble_1', 49: 'string_ensemble_2',
    50: 'synth_strings_1', 51: 'synth_strings_2', 52: 'choir_aahs',
    53: 'voice_oohs', 54: 'synth_choir', 55: 'orchestra_hit',
    56: 'trumpet', 57: 'trombone', 58: 'tuba', 59: 'muted_trumpet',
    60: 'french_horn', 61: 'brass_section', 62: 'synth_brass_1',
    63: 'synth_brass_2', 64: 'soprano_sax', 65: 'alto_sax',
    66: 'tenor_sax', 67: 'baritone_sax', 68: 'oboe', 69: 'english_horn',
    70: 'bassoon', 71: 'clarinet', 72: 'piccolo', 73: 'flute',
    74: 'recorder', 75: 'pan_flute', 76: 'blown_bottle', 77: 'shakuhachi',
    78: 'whistle', 79: 'ocarina', 80: 'lead_1_square', 81: 'lead_2_sawtooth',
    82: 'lead_3_calliope', 83: 'lead_4_chiff', 84: 'lead_5_charang',
    85: 'lead_6_voice', 86: 'lead_7_fifths', 87: 'lead_8_bass_lead',
    88: 'pad_1_new_age', 89: 'pad_2_warm', 90: 'pad_3_polysynth',
    91: 'pad_4_choir', 92: 'pad_5_bowed', 93: 'pad_6_metallic',
    94: 'pad_7_halo', 95: 'pad_8_sweep', 96: 'fx_1_rain',
    97: 'fx_2_soundtrack', 98: 'fx_3_crystal', 99: 'fx_4_atmosphere',
    100: 'fx_5_brightness', 101: 'fx_6_goblins', 102: 'fx_7_echoes',
    103: 'fx_8_sci_fi', 104: 'sitar', 105: 'banjo', 106: 'shamisen',
    107: 'koto', 108: 'kalimba', 109: 'bagpipe', 110: 'fiddle',
    111: 'shanai', 112: 'tinkle_bell', 113: 'agogo', 114: 'steel_drums',
    115: 'woodblock', 116: 'taiko_drum', 117: 'melodic_tom', 118: 'synth_drum',
    119: 'reverse_cymbal', 120: 'guitar_fret_noise', 121: 'breath_noise',
    122: 'seashore', 123: 'bird_tweet', 124: 'telephone_ring', 125: 'helicopter',
    126: 'applause', 127: 'gunshot', 128: 'drums'
}

# Track type mapping
TRACK_TYPE_MAP = {
    8: 'AUX_DRUM_TRACK',
    9: 'AUX_INST_TRACK',
    10: 'STANDARD_TRACK',
    11: 'STANDARD_DRUM_TRACK',
    12: 'STANDARD_BOTH'
}

def _locate_infiller_global_options_FX_loc() -> int:
    from reaper_python import RPR_GetMasterTrack, RPR_TrackFX_GetEnabled, RPR_TrackFX_GetParam
    tr = RPR_GetMasterTrack(-1)
    n_fx = 100
    for i in range(0x1000000, 0x1000000 + n_fx):
        if RPR_TrackFX_GetEnabled(tr, i):
            v = RPR_TrackFX_GetParam(tr, i, 0, 0, 0)[0]
            if mf.is_approx(v, GLOBAL_FX_ID):
                return i
    return -1


def _locate_mmm_track_options_FX_loc(track) -> int:
    res = -1
    from reaper_python import RPR_TrackFX_GetEnabled, RPR_TrackFX_GetParam
    for i in range(mt.get_num_FX_on_track(track)):
        if RPR_TrackFX_GetEnabled(track, i):
            val = RPR_TrackFX_GetParam(track, i, 0, 0, 0)[0]
            if mf.is_approx(val, TRACK_FX_ID) or mf.is_approx(val, 349583024):
                res = i
    return res


def get_global_options():
    """Read global MMM options from master track FX"""
    class GlobalOptions:
        pass
    
    options = GlobalOptions()
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
        
        fx_loc = _locate_infiller_global_options_FX_loc()
        loc_offset = 1
        
        # Read parameters (same as before)
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.temperature = val
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.tracks_per_step = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.bars_per_step = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.model_dim = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.percentage = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.max_steps = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.batch_size = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.shuffle = bool(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.sampling_seed = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.mask_top_k = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.polyphony_hard_limit = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.rhy_cond = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.do_note_range_cond = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.enc_no_repeat_ngram_size = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.variation_alg = int(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.disp_tr_to_midi_inst = bool(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.gen_notes_are_selected = bool(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.display_warnings = bool(val)
        loc_offset += 1
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(master, fx_loc, loc_offset, 0, 0)
        options.verbose = bool(val)
    
    except Exception as e:
        if DEBUG:
            print(f"Warning: Could not read global options: {e}")
    
    return options


class MMMTrackOptionsObj:
    """Track options object with streamlined parameters"""
    def __init__(self):
        self.track_temperature = -1.0
        self.instrument = -1
        self.density = 10
        self.track_type = 10
        self.min_polyphony_q = 0
        self.max_polyphony_q = 0
        self.polyphony_hard_limit = -1


def get_mmm_track_options_by_track_idx() -> dict:
    """Read MMM Track Options from all tracks"""
    res = {}
    
    try:
        from reaper_python import RPR_TrackFX_GetParam, RPR_CountTracks, RPR_GetTrack
        
        num_tracks = RPR_CountTracks(0)
        
        for i in range(num_tracks):
            t = RPR_GetTrack(0, i)
            fx_loc = _locate_mmm_track_options_FX_loc(t)
            
            if fx_loc > -1:
                opts = MMMTrackOptionsObj()
                loc_offset = 1
                
                # opts.track_temperature = RPR_TrackFX_GetParam(t, fx_loc, 0 + loc_offset, 0, 0)[0]
                opts.instrument = int(RPR_TrackFX_GetParam(t, fx_loc, loc_offset, 0, 0)[0]) - 1
                loc_offset += 1
                opts.min_polyphony = int(RPR_TrackFX_GetParam(t, fx_loc, loc_offset, 0, 0)[0])
                loc_offset += 1
                opts.max_polyphony = int(RPR_TrackFX_GetParam(t, fx_loc, loc_offset, 0, 0)[0])
                loc_offset += 1
                opts.density = int(RPR_TrackFX_GetParam(t, fx_loc, loc_offset, 0, 0)[0])
                loc_offset += 1
                opts.note_dur_whole = int(RPR_TrackFX_GetParam(t, fx_loc, loc_offset, 0, 0)[0])
                loc_offset += 1
                opts.note_dur_half = int(RPR_TrackFX_GetParam(t, fx_loc, loc_offset, 0, 0)[0])
                loc_offset += 1
                opts.note_dur_quarter = int(RPR_TrackFX_GetParam(t, fx_loc, loc_offset, 0, 0)[0])
                loc_offset += 1
                opts.note_dur_eight = int(RPR_TrackFX_GetParam(t, fx_loc, loc_offset, 0, 0)[0])
                loc_offset += 1
                opts.note_dur_sixteenth = int(RPR_TrackFX_GetParam(t, fx_loc, loc_offset, 0, 0)[0])
                loc_offset += 1
                opts.note_dur_thirtysecond = int(RPR_TrackFX_GetParam(t, fx_loc, loc_offset, 0, 0)[0])
                
                res[i] = opts
        
    except Exception as e:
        if DEBUG:
            print(f"Error reading MMM Track Options: {e}")
    
    return res


def convert_track_options_to_control_strings(opts: MMMTrackOptionsObj) -> list:
    """
    Convert track options to MMM attribute control strings.
    """
    controls = []
    
    # Instrument control
    if opts.instrument >= 0:
        controls.append(f"Program_{opts.instrument}")

    # Polyphony controls
    if opts.min_polyphony > 0:
        controls.append(f"ACBarOnsetPolyphonyMin_{opts.min_polyphony}")
    if opts.max_polyphony > 0:
        controls.append(f"ACBarOnsetPolyphonyMax_{opts.max_polyphony}")
    
    # Density control - map to horizontal density bins
    if opts.density == 18:
        controls.append(f"ACBarNoteDensity_18+")
    elif opts.density >= 0:
        controls.append(f"ACBarNoteDensity_{opts.density}")
    
    # Note duration
    if opts.note_dur_whole >= 0:
        controls.append(f"ACBarNoteDurationWhole_{opts.note_dur_whole}")
    if opts.note_dur_half >= 0:
        controls.append(f"ACBarNoteDurationHalf_{opts.note_dur_half}")
    if opts.note_dur_quarter >= 0:
        controls.append(f"ACBarNoteDurationQuarter_{opts.note_dur_quarter}")
    if opts.note_dur_eight >= 0:
        controls.append(f"ACBarNoteDurationEight_{opts.note_dur_eight}")
    if opts.note_dur_sixteenth >= 0:
        controls.append(f"ACBarNoteDurationSixteenth_{opts.note_dur_sixteenth}")
    if opts.note_dur_thirtysecond >= 0:
        controls.append(f"ACBarNoteDurationThirtySecond_{opts.note_dur_thirtysecond}")
    
    if DEBUG and controls:
        print(f"  Generated controls: {controls}")
    
    return controls


def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0, start_measure=None, end_measure=None):
    """Call the MMM server via XML-RPC with track options"""
    from xmlrpc.client import ServerProxy
    
    if DEBUG:
        print(f"MMM call_nn_infill: temp={temperature}, measures={start_measure}-{end_measure}")
    
    try:
        proxy = ServerProxy('http://127.0.0.1:3456')
        
        options = get_global_options()
        track_options = get_mmm_track_options_by_track_idx()
        
        options_dict = {
            'temperature': temperature,
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
        
        # Encode S parameter
        if isinstance(S, ms.MidiSongByMeasure):
            S_encoded = pre.encode_midisongbymeasure_to_save_dict(S)
        else:
            S_encoded = S
        
        # Convert track options to serializable format with control strings
        # XML-RPC requires string keys
        track_options_dict = {}
        for idx, opts in track_options.items():
            track_options_dict[str(idx)] = {
                'controls': convert_track_options_to_control_strings(opts)
            }
        
        result = proxy.call_nn_infill(
            s, 
            S_encoded,
            use_sampling,
            min_length,
            enc_no_repeat_ngram_size,
            has_fully_masked_inst,
            options_dict,
            track_options_dict,
            start_measure,
            end_measure
        )
        
        if DEBUG:
            print(f"MMM server returned: {len(result)} chars")
        
        return result
        
    except Exception as e:
        print(f"Error calling MMM server: {e}")
        return f";<extra_id_0>"