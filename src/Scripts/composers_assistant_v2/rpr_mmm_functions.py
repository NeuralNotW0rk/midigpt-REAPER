"""
Functions for reading MMM Track Options from REAPER and converting to control strings.
"""

DEBUG = False


def _locate_mmm_global_options_FX_loc() -> int:
    """-1 means not found or not enabled. Look on monitor FX."""
    try:
        from reaper_python import RPR_GetMasterTrack, RPR_TrackFX_GetEnabled, RPR_TrackFX_GetParam
        tr = RPR_GetMasterTrack(-1)
        n_fx = 100
        for i in range(0x1000000, 0x1000000 + n_fx):
            if RPR_TrackFX_GetEnabled(tr, i):
                v = RPR_TrackFX_GetParam(tr, i, 0, 0, 0)[0]
                if abs(v - 54964318) < 0.1:
                    return i
        return -1
    except:
        return -1


def _locate_mmm_track_options_FX_loc(track) -> int:
    """-1 means not found or not enabled. Get the last enabled instance."""
    try:
        from reaper_python import RPR_TrackFX_GetEnabled, RPR_TrackFX_GetParam
        res = -1
        for i in range(100):
            if RPR_TrackFX_GetEnabled(track, i):
                val = RPR_TrackFX_GetParam(track, i, 0, 0, 0)[0]
                if abs(val - 349583025) < 0.1:
                    res = i
        return res
    except:
        return -1


class MMMGlobalOptionsObj:
    temperature = 1.0
    tracks_per_step = 1
    bars_per_step = 1
    model_dim = 4
    percentage = 100
    max_steps = 200
    batch_size = 1
    shuffle = True
    sampling_seed = -1
    mask_top_k = 0
    polyphony_hard_limit = 6


def get_mmm_global_options() -> MMMGlobalOptionsObj:
    """Read MMM Global Options from master track FX."""
    res = MMMGlobalOptionsObj()
    
    try:
        from reaper_python import RPR_GetMasterTrack, RPR_TrackFX_GetParam
        
        fx_loc = _locate_mmm_global_options_FX_loc()
        if fx_loc == -1:
            if DEBUG:
                print("MMM Global Options FX not found")
            return res
        
        t = RPR_GetMasterTrack(-1)
        loc_offset = 1
        
        res.temperature = RPR_TrackFX_GetParam(t, fx_loc, 0 + loc_offset, 0, 0)[0]
        res.tracks_per_step = int(RPR_TrackFX_GetParam(t, fx_loc, 1 + loc_offset, 0, 0)[0])
        res.bars_per_step = int(RPR_TrackFX_GetParam(t, fx_loc, 2 + loc_offset, 0, 0)[0])
        res.model_dim = int(RPR_TrackFX_GetParam(t, fx_loc, 3 + loc_offset, 0, 0)[0])
        res.percentage = int(RPR_TrackFX_GetParam(t, fx_loc, 4 + loc_offset, 0, 0)[0])
        res.max_steps = int(RPR_TrackFX_GetParam(t, fx_loc, 5 + loc_offset, 0, 0)[0])
        res.batch_size = int(RPR_TrackFX_GetParam(t, fx_loc, 6 + loc_offset, 0, 0)[0])
        res.shuffle = bool(RPR_TrackFX_GetParam(t, fx_loc, 7 + loc_offset, 0, 0)[0])
        res.sampling_seed = int(RPR_TrackFX_GetParam(t, fx_loc, 8 + loc_offset, 0, 0)[0])
        res.mask_top_k = int(RPR_TrackFX_GetParam(t, fx_loc, 9 + loc_offset, 0, 0)[0])
        res.polyphony_hard_limit = int(RPR_TrackFX_GetParam(t, fx_loc, 10 + loc_offset, 0, 0)[0])
        
        if DEBUG:
            print(f"MMM Global Options: temp={res.temperature}, model_dim={res.model_dim}")
        
    except Exception as e:
        if DEBUG:
            print(f"Error reading MMM Global Options: {e}")
    
    return res


class MMMTrackOptionsObj:
    track_temperature = -1.0
    vert_density = -1
    n_pitch_classes = -1
    horiz_density = 4
    rhy_ins = 3
    step_bin = 4
    leap_bin = 3
    low_note_strict = -1
    high_note_strict = -1
    low_note_loose = -1
    high_note_loose = -1


def get_mmm_track_options_by_track_idx() -> dict:
    """Read MMM Track Options from all tracks, return dict keyed by track index."""
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
                
                opts.track_temperature = RPR_TrackFX_GetParam(t, fx_loc, 0 + loc_offset, 0, 0)[0]
                
                val = RPR_TrackFX_GetParam(t, fx_loc, 2 + loc_offset, 0, 0)[0]
                opts.vert_density = int(val) - 1
                
                val = RPR_TrackFX_GetParam(t, fx_loc, 3 + loc_offset, 0, 0)[0]
                opts.n_pitch_classes = int(val) - 1
                
                val = RPR_TrackFX_GetParam(t, fx_loc, 4 + loc_offset, 0, 0)[0]
                opts.horiz_density = int(val) - 1
                
                val = RPR_TrackFX_GetParam(t, fx_loc, 5 + loc_offset, 0, 0)[0]
                opts.rhy_ins = int(val) - 1
                
                val = RPR_TrackFX_GetParam(t, fx_loc, 6 + loc_offset, 0, 0)[0]
                opts.step_bin = int(val) - 1
                
                val = RPR_TrackFX_GetParam(t, fx_loc, 7 + loc_offset, 0, 0)[0]
                opts.leap_bin = int(val) - 1
                
                opts.low_note_strict = int(RPR_TrackFX_GetParam(t, fx_loc, 8 + loc_offset, 0, 0)[0])
                opts.high_note_strict = int(RPR_TrackFX_GetParam(t, fx_loc, 9 + loc_offset, 0, 0)[0])
                opts.low_note_loose = int(RPR_TrackFX_GetParam(t, fx_loc, 10 + loc_offset, 0, 0)[0])
                opts.high_note_loose = int(RPR_TrackFX_GetParam(t, fx_loc, 11 + loc_offset, 0, 0)[0])
                
                res[i] = opts
                
                if DEBUG:
                    print(f"Track {i} options: vert={opts.vert_density}, horiz={opts.horiz_density}")
        
    except Exception as e:
        if DEBUG:
            print(f"Error reading MMM Track Options: {e}")
    
    return res


def convert_track_options_to_control_strings(opts: MMMTrackOptionsObj) -> list:
    """Convert track options to MMM attribute control strings."""
    controls = []
    
    if opts.vert_density >= 0:
        controls.append(f"VERT_{opts.vert_density}")
    
    if opts.n_pitch_classes >= 0:
        controls.append(f"PITCH_CLASS_{opts.n_pitch_classes}")
    
    if opts.horiz_density >= 0:
        controls.append(f"HORIZ_{opts.horiz_density}")
    
    if opts.rhy_ins >= 0:
        controls.append(f"RHYTHM_{opts.rhy_ins}")
    
    if opts.step_bin >= 0:
        controls.append(f"STEP_{opts.step_bin}")
    
    if opts.leap_bin >= 0:
        controls.append(f"LEAP_{opts.leap_bin}")
    
    if opts.low_note_strict > -1:
        controls.append(f"LOW_NOTE_STRICT_{opts.low_note_strict}")
    
    if opts.high_note_strict > -1:
        controls.append(f"HIGH_NOTE_STRICT_{opts.high_note_strict}")
    
    if opts.low_note_loose > -1:
        controls.append(f"LOW_NOTE_LOOSE_{opts.low_note_loose}")
    
    if opts.high_note_loose > -1:
        controls.append(f"HIGH_NOTE_LOOSE_{opts.high_note_loose}")
    
    return controls