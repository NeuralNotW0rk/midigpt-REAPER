"""
midigpt Reaper integration functions - refactored for direct midigpt parameter usage
"""

import collections
import random
import json
from dataclasses import dataclass
from typing import Dict, Set, List, Tuple, Optional

# Import existing modules (these would remain the same)
# import midigpt_tools as mt
# import midigpt_misc_functions as mf
# import encoding_functions as enc
# import preprocessing_functions as pre
# import midisong as ms

DEBUG = False

@dataclass
class MidigptGlobalOptions:
    """Global options that map directly to midigpt parameters"""
    temperature: float = 1.0
    tracks_per_step: int = 1
    bars_per_step: int = 1
    model_dim: int = 4
    percentage: int = 100
    max_steps: int = 200
    batch_size: int = 1
    shuffle: bool = True
    sampling_seed: int = -1
    mask_top_k: int = 0
    polyphony_hard_limit: int = 6
    
    # UI/Display options
    display_track_to_MIDI_inst: bool = True
    generated_notes_are_selected: bool = True
    display_warnings: bool = True
    verbose: bool = False

@dataclass
class MidigptTrackOptions:
    """Track-specific options that map to midigpt track parameters"""
    track_id: int = 0
    temperature: float = -1  # -1 means use global
    instrument: str = 'acoustic_grand_piano'
    density: int = 10
    track_type: int = 10
    ignore: bool = False
    selected_bars: List[bool] = None
    min_polyphony_q: str = 'POLYPHONY_ANY'
    max_polyphony_q: str = 'POLYPHONY_ANY'
    autoregressive: bool = False
    polyphony_hard_limit: int = 9

def _locate_midigpt_global_options_FX_loc() -> int:
    """Find the midigpt global options JSFX. -1 means not found."""
    from reaper_python import RPR_GetMasterTrack, RPR_TrackFX_GetEnabled, RPR_TrackFX_GetParam
    tr = RPR_GetMasterTrack(-1)
    n_fx = 100  # search up to 100 FX
    for i in range(0x1000000, 0x1000000 + n_fx):
        if RPR_TrackFX_GetEnabled(tr, i):
            v = RPR_TrackFX_GetParam(tr, i, 0, 0, 0)[0]
            if mf.is_approx(v, 54964318):  # New ID for midigpt global options
                return i
    return -1

def _locate_midigpt_track_options_FX_loc(track) -> int:
    """Find the midigpt track options JSFX. -1 means not found."""
    res = -1
    from reaper_python import RPR_TrackFX_GetEnabled, RPR_TrackFX_GetParam
    for i in range(mt.get_num_FX_on_track(track)):
        if RPR_TrackFX_GetEnabled(track, i):
            val = RPR_TrackFX_GetParam(track, i, 0, 0, 0)[0]
            if mf.is_approx(val, 349583025):  # New ID for midigpt track options
                res = i
    return res

def get_midigpt_global_options() -> MidigptGlobalOptions:
    """Read global midigpt options from the Reaper JSFX"""
    from reaper_python import RPR_GetMasterTrack, RPR_TrackFX_GetParam
    res = MidigptGlobalOptions()
    
    fx_loc = _locate_midigpt_global_options_FX_loc()
    if fx_loc != -1:
        t = RPR_GetMasterTrack(-1)
        loc_offset = 1  # Skip the ID parameter

        # Core generation parameters
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 0 + loc_offset, 0, 0)
        res.temperature = val

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 1 + loc_offset, 0, 0)
        res.tracks_per_step = int(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 2 + loc_offset, 0, 0)
        res.bars_per_step = int(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 3 + loc_offset, 0, 0)
        res.model_dim = int(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 4 + loc_offset, 0, 0)
        res.percentage = int(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 5 + loc_offset, 0, 0)
        res.max_steps = int(val)

        # Sampling control parameters
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 6 + loc_offset, 0, 0)
        res.batch_size = int(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 7 + loc_offset, 0, 0)
        res.shuffle = bool(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 8 + loc_offset, 0, 0)
        res.sampling_seed = int(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 9 + loc_offset, 0, 0)
        res.mask_top_k = int(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 10 + loc_offset, 0, 0)
        res.polyphony_hard_limit = int(val)

        # UI options
        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 11 + loc_offset, 0, 0)
        res.display_track_to_MIDI_inst = bool(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 12 + loc_offset, 0, 0)
        res.generated_notes_are_selected = bool(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 13 + loc_offset, 0, 0)
        res.display_warnings = bool(val)

        val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, fx_loc, 14 + loc_offset, 0, 0)
        res.verbose = bool(val)

    return res

def get_midigpt_track_options_by_track_idx() -> Dict[int, MidigptTrackOptions]:
    """Read track-specific midigpt options from Reaper JSFX instances"""
    from reaper_python import RPR_TrackFX_GetParam
    res = {}
    loc_offset = 1

    for i, t in mt.get_tracks_by_idx().items():
        midigpt_track_fx_loc = _locate_midigpt_track_options_FX_loc(t)
        if midigpt_track_fx_loc > -1:
            track_options = MidigptTrackOptions()
            track_options.track_id = i

            # Track temperature
            val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, midigpt_track_fx_loc, 0 + loc_offset, 0, 0)
            track_options.temperature = val

            # Track density
            val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, midigpt_track_fx_loc, 1 + loc_offset, 0, 0)
            track_options.density = int(val)

            # Track type
            val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, midigpt_track_fx_loc, 2 + loc_offset, 0, 0)
            track_options.track_type = int(val)

            # Polyphony controls
            val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, midigpt_track_fx_loc, 3 + loc_offset, 0, 0)
            min_poly = int(val)
            if min_poly == 0:
                track_options.min_polyphony_q = 'POLYPHONY_ANY'
            else:
                track_options.min_polyphony_q = f'POLYPHONY_{min_poly}'

            val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, midigpt_track_fx_loc, 4 + loc_offset, 0, 0)
            max_poly = int(val)
            if max_poly == 0:
                track_options.max_polyphony_q = 'POLYPHONY_ANY'
            else:
                track_options.max_polyphony_q = f'POLYPHONY_{max_poly}'

            val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, midigpt_track_fx_loc, 5 + loc_offset, 0, 0)
            track_options.polyphony_hard_limit = int(val)

            # Generation behavior
            val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, midigpt_track_fx_loc, 6 + loc_offset, 0, 0)
            track_options.autoregressive = bool(val)

            val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, midigpt_track_fx_loc, 7 + loc_offset, 0, 0)
            track_options.ignore = bool(val)

            # Instrument
            val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, midigpt_track_fx_loc, 8 + loc_offset, 0, 0)
            instrument_id = int(val)
            
            val, _, _, _, _, _ = RPR_TrackFX_GetParam(t, midigpt_track_fx_loc, 9 + loc_offset, 0, 0)
            use_piano_default = bool(val)
            
            if use_piano_default or instrument_id == 0:
                track_options.instrument = 'acoustic_grand_piano'
            else:
                # Map MIDI instrument numbers to midigpt instrument names
                track_options.instrument = midi_instrument_to_midigpt_name(instrument_id)

            res[i] = track_options

    return res

def midi_instrument_to_midigpt_name(midi_instrument: int) -> str:
    """Convert MIDI instrument number to midigpt instrument name"""
    # This is a simplified mapping - you may need to expand this based on
    # what instruments midigpt actually supports
    instrument_mapping = {
        0: 'acoustic_grand_piano',
        1: 'bright_acoustic_piano',
        4: 'electric_piano_1',
        5: 'electric_piano_2',
        24: 'acoustic_guitar_nylon',
        25: 'acoustic_guitar_steel',
        26: 'electric_guitar_jazz',
        27: 'electric_guitar_clean',
        32: 'acoustic_bass',
        33: 'electric_bass_finger',
        40: 'violin',
        41: 'viola',
        42: 'cello',
        48: 'string_ensemble_1',
        56: 'trumpet',
        60: 'french_horn',
        64: 'soprano_sax',
        65: 'alto_sax',
        66: 'tenor_sax',
        67: 'baritone_sax',
        72: 'piccolo',
        73: 'flute',
        80: 'lead_1_square',
        # Add more mappings as needed
    }
    
    return instrument_mapping.get(midi_instrument, 'acoustic_grand_piano')

def create_midigpt_status_from_reaper_selection(S, mask_locations, track_options_by_idx, global_options):
    """Create midigpt status JSON from Reaper track selection and options"""
    
    tracks = []
    
    # Get unique tracks that have masks
    track_ids = set()
    for track_idx, measure_idx in mask_locations:
        track_ids.add(track_idx)
    
    for track_idx in sorted(track_ids):
        # Get track options, or use defaults
        track_opts = track_options_by_idx.get(track_idx, MidigptTrackOptions())
        track_opts.track_id = track_idx
        
        # Create selected_bars array based on which measures are masked for this track
        num_measures = S.get_n_measures()
        selected_bars = [False] * num_measures
        
        for t_idx, m_idx in mask_locations:
            if t_idx == track_idx:
                selected_bars[m_idx] = True
        
        # Use track temperature if specified, otherwise use global
        temperature = track_opts.temperature if track_opts.temperature >= 0 else global_options.temperature
        
        track_status = {
            'track_id': track_idx,
            'temperature': temperature,
            'instrument': track_opts.instrument,
            'density': track_opts.density,
            'track_type': track_opts.track_type,
            'ignore': track_opts.ignore,
            'selected_bars': selected_bars,
            'min_polyphony_q': track_opts.min_polyphony_q,
            'max_polyphony_q': track_opts.max_polyphony_q,
            'autoregressive': track_opts.autoregressive,
            'polyphony_hard_limit': track_opts.polyphony_hard_limit
        }
        
        tracks.append(track_status)
    
    status = {
        'tracks': tracks
    }
    
    return status

def create_midigpt_param_from_options(global_options):
    """Create midigpt param JSON from global options"""
    
    param = {
        'tracks_per_step': global_options.tracks_per_step,
        'bars_per_step': global_options.bars_per_step,
        'model_dim': global_options.model_dim,
        'percentage': global_options.percentage,
        'batch_size': global_options.batch_size,
        'temperature': global_options.temperature,
        'max_steps': global_options.max_steps,
        'polyphony_hard_limit': global_options.polyphony_hard_limit,
        'shuffle': global_options.shuffle,
        'verbose': global_options.verbose,
        'ckpt': cs.MIDIGPT_MODEL_PATH if hasattr(cs, 'MIDIGPT_MODEL_PATH') else 'path/to/model',
        'sampling_seed': global_options.sampling_seed,
        'mask_top_k': global_options.mask_top_k
    }
    
    return param

def get_nn_input_for_midigpt(S, mask_locations):
    """
    Create midigpt inputs from MidiSongByMeasure and mask locations.
    Returns (piece_json, status_json, param_json) suitable for midigpt.sample_multi_step()
    """
    
    # Get options from Reaper JSFX
    global_options = get_midigpt_global_options()
    track_options_by_idx = get_midigpt_track_options_by_track_idx()
    
    if DEBUG:
        print("Global options:", global_options)
        print("Track options:", track_options_by_idx)
        print("Mask locations:", mask_locations)
    
    # Convert MidiSongByMeasure to midigpt piece format
    piece = midisong_to_midigpt_piece(S)
    
    # Create status from track selections and options
    status = create_midigpt_status_from_reaper_selection(S, mask_locations, track_options_by_idx, global_options)
    
    # Create param from global options
    param = create_midigpt_param_from_options(global_options)
    
    # Convert to JSON strings
    piece_json = json.dumps(piece)
    status_json = json.dumps(status)
    param_json = json.dumps(param)
    
    if DEBUG:
        print("Piece JSON preview:", piece_json[:200] + "..." if len(piece_json) > 200 else piece_json)
        print("Status JSON:", status_json)
        print("Param JSON:", param_json)
    
    return piece_json, status_json, param_json

def midisong_to_midigpt_piece(S):
    """Convert MidiSongByMeasure to midigpt piece format"""
    
    piece = {
        "tracks": [],
        "time_signatures": [],
        "key_signatures": [],
        "tempos": [],
        "resolution": getattr(S, 'cpq', 480)  # Use cpq as resolution
    }
    
    # Convert tracks
    for track_idx, track in enumerate(S.tracks):
        track_data = {
            "instrument": getattr(track, 'inst', 0),
            "notes": [],
            "is_drum": getattr(track, 'is_drum', False)
        }
        
        # Collect all notes from all measures in this track
        current_time = 0
        measure_endpoints = S.get_measure_endpoints()
        
        for measure_idx, measure_track in enumerate(track.tracks_by_measure):
            measure_start_time = measure_endpoints[measure_idx] if measure_idx < len(measure_endpoints) else current_time
            
            # Process note ons and offs to create complete notes
            note_dict = {}  # noteidx -> note info
            
            for note_on in measure_track.note_ons:
                note_dict[note_on.noteidx] = {
                    "pitch": note_on.pitch,
                    "start": measure_start_time + note_on.click,
                    "velocity": note_on.vel,
                    "end": None  # Will be filled by note_off
                }
            
            for note_off in measure_track.note_offs:
                if note_off.noteidx in note_dict:
                    note_dict[note_off.noteidx]["end"] = measure_start_time + note_off.click
            
            # Add completed notes to track
            for note_info in note_dict.values():
                if note_info["end"] is not None:  # Only add notes with proper note-offs
                    duration = note_info["end"] - note_info["start"]
                    if duration > 0:  # Only add notes with positive duration
                        midigpt_note = {
                            "pitch": note_info["pitch"],
                            "start": note_info["start"],
                            "end": note_info["end"],
                            "velocity": note_info["velocity"]
                        }
                        track_data["notes"].append(midigpt_note)
        
        piece["tracks"].append(track_data)
    
    # Convert tempo changes
    for tempo_change in S.tempo_changes:
        piece["tempos"].append({
            "time": tempo_change.click,
            "tempo": tempo_change.val
        })
    
    # Add basic time signature (4/4 for now - could be enhanced)
    piece["time_signatures"].append({
        "time": 0,
        "numerator": 4,
        "denominator": 4
    })
    
    return piece

# Integration function that maintains compatibility with existing Reaper scripts
def create_and_call_midigpt_for_reaper_selection():
    """
    Main function to be called from Reaper scripts.
    Handles the full pipeline from Reaper selection to midigpt generation.
    """
    
    # This function would integrate with existing Reaper script logic
    # Similar to the original create_and_write_variation_for_time_selection but for midigpt
    
    # Get MIDI data and selection from Reaper
    # S, mask_locations = get_midi_and_selection_from_reaper()
    
    # Get midigpt inputs
    # piece_json, status_json, param_json = get_nn_input_for_midigpt(S, mask_locations)
    
    # Call midigpt (this would be done in the server)
    # result = call_midigpt_server(piece_json, status_json, param_json)
    
    # Process and write result back to Reaper
    # write_midigpt_result_to_reaper(result)
    
    pass
