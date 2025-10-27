"""
MMM Server with Context Window Filtering
Critical Fix: Only send context window measures to MMM, not entire project
"""

import sys
import os
import tempfile
import re
from xmlrpc.server import SimpleXMLRPCServer

DEBUG = True
PORT = 3456

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src/Scripts/composers_assistant_v2'))
import preprocessing_functions as pre
from midisong import MidiSong, MidiSongByMeasure

MMM_AVAILABLE = False
MODEL = None
TOKENIZER = None

try:
    from mmm import Model, Tokenizer, PromptConfig, SamplingEngine, GenerationConfig, Score, generate, ModelConfig
    MMM_AVAILABLE = True
    print("MMM library loaded successfully")
    
    if DEBUG:
        try:
            from mmm import set_log_level, LogLevel
            set_log_level(LogLevel.INFO)
        except:
            pass
except ImportError as e:
    print(f"MMM library not available: {e}")


def initialize_mmm():
    global MODEL, TOKENIZER
    
    if not MMM_AVAILABLE:
        return False
    
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        tokenizer_path = os.path.join(script_dir, 'models_mmm/MMM_trained.json')
        model_path = os.path.join(script_dir, 'models_mmm/model.onnx')
        
        if DEBUG:
            print("\n=== INITIALIZING MMM ===")
            print(f"  Tokenizer: {tokenizer_path}")
            print(f"  Model: {model_path}")
        
        TOKENIZER = Tokenizer(tokenizer_path)
        model_cfg = ModelConfig(model=model_path, cached=False, vocab_size=16000)
        MODEL = Model(model_cfg)
        
        if DEBUG:
            print("  MMM initialized successfully")
        
        return True
        
    except Exception as e:
        if DEBUG:
            print(f"  MMM initialization failed: {e}")
            import traceback
            traceback.print_exc()
        return False


def filter_midisongbymeasure_to_range(S, start_measure, end_measure, debug=False):
    """
    Create a new MidiSongByMeasure containing only measures in [start_measure, end_measure].
    This ensures MMM only receives the context window, not the entire project.
    
    Strategy:
    1. Convert full MidiSongByMeasure to MidiSong (joins note_ons/note_offs)
    2. Filter notes/events by time range
    3. Convert back to MidiSongByMeasure with adjusted measure_endpoints
    
    Args:
        S: MidiSongByMeasure object
        start_measure: First measure to include (inclusive)
        end_measure: Last measure to include (inclusive)
        debug: Print debug information
    
    Returns:
        Filtered MidiSongByMeasure with only the specified measure range
    """
    if debug:
        print(f"\n=== FILTERING CONTEXT WINDOW ===")
        print(f"  Original project: {S.get_n_measures()} measures")
        print(f"  Filtering to: measures {start_measure}-{end_measure}")
    
    # Get original measure endpoints
    original_endpoints = S.get_measure_endpoints(make_copy=True)
    
    # Calculate time range for filtering
    start_tick = original_endpoints[start_measure]
    end_tick = original_endpoints[end_measure + 1]
    
    if debug:
        print(f"  Time range: ticks {start_tick}-{end_tick}")
    
    # Convert to MidiSong (this properly handles note_on/note_off pairing)
    midi_song = MidiSong.from_MidiSongByMeasure(S, consume_calling_song=False)
    
    # Filter each track to only include events in the time range
    filtered_tracks = []
    for track in midi_song.tracks:
        # Create new filtered track (is_drum is set automatically by inst property)
        from midisong import Track, Note
        filtered_track = Track(inst=track.inst, name=track.name if hasattr(track, 'name') else "")
        
        # Calculate the adjusted end boundary (last measure endpoint in filtered context)
        adjusted_end_tick = end_tick - start_tick
        
        # Filter notes to time range and adjust timing
        notes_included = 0
        notes_excluded = 0
        for note in track.notes:
            note_start = note.click
            note_end = note.end
            
            # Only include notes that START before end_tick and END after start_tick
            if note_end > start_tick and note_start < end_tick:
                # Clip note to time range boundaries
                clipped_start = max(note_start, start_tick)
                clipped_end = min(note_end, end_tick)
                
                # Adjust timing relative to start_tick
                adjusted_start = clipped_start - start_tick
                adjusted_end = clipped_end - start_tick
                
                # CRITICAL: Exclude notes that would end exactly at or beyond the last measure endpoint
                # This prevents index errors when converting back to MidiSongByMeasure
                if adjusted_end >= adjusted_end_tick:
                    notes_excluded += 1
                    continue
                
                # Also skip notes that would start at or beyond the boundary
                if adjusted_start >= adjusted_end_tick:
                    notes_excluded += 1
                    continue
                
                adjusted_note = Note(
                    pitch=note.pitch,
                    vel=note.vel,
                    click=adjusted_start,
                    end=adjusted_end
                )
                filtered_track.notes.append(adjusted_note)
                notes_included += 1
            else:
                notes_excluded += 1
        
        if debug and (notes_included > 0 or notes_excluded > 0):
            print(f"  Track {track.inst}: {notes_included} notes included, {notes_excluded} notes excluded")
        
        # Filter control changes (if any)
        if hasattr(track, 'control_changes') and track.control_changes:
            for cc in track.control_changes:
                adjusted_cc_time = cc.click - start_tick
                if 0 <= adjusted_cc_time < adjusted_end_tick:
                    from midisong import ControlChange
                    adjusted_cc = ControlChange(
                        controller=cc.controller,
                        val=cc.val,
                        click=adjusted_cc_time
                    )
                    filtered_track.control_changes.append(adjusted_cc)
        
        filtered_tracks.append(filtered_track)
    
    # Filter time signatures to only those within the time range
    filtered_time_sigs = []
    for ts in midi_song.time_signatures:
        if start_tick <= ts.click < end_tick:
            from midisong import TimeSig
            adjusted_ts = TimeSig(
                num=ts.num,
                denom=ts.denom,
                click=ts.click - start_tick
            )
            filtered_time_sigs.append(adjusted_ts)
    
    # If no time signatures in range, add a default 4/4 at the start
    if not filtered_time_sigs:
        from midisong import TimeSig
        filtered_time_sigs = [TimeSig(num=4, denom=4, click=0)]
    
    # Filter tempo changes to only those within the time range
    filtered_tempo_changes = []
    for tc in midi_song.tempo_changes:
        if start_tick <= tc.click < end_tick:
            from midisong import TempoChange
            adjusted_tc = TempoChange(
                val=tc.val,
                click=tc.click - start_tick
            )
            filtered_tempo_changes.append(adjusted_tc)
    
    # If no tempo changes in range, add a default 120 BPM at the start
    if not filtered_tempo_changes:
        from midisong import TempoChange
        filtered_tempo_changes = [TempoChange(val=120, click=0)]
    
    # Create filtered MidiSong with adjusted timing
    filtered_midi_song = MidiSong(
        tracks=filtered_tracks,
        time_signatures=filtered_time_sigs,
        markers=[],
        cpq=midi_song.cpq,
        tempo_changes=filtered_tempo_changes,
        clean_up_time_signatures=False
    )
    
    # Calculate adjusted measure_endpoints (starting from 0)
    filtered_endpoints_raw = original_endpoints[start_measure:end_measure + 2]
    offset = filtered_endpoints_raw[0]
    filtered_endpoints = [ep - offset for ep in filtered_endpoints_raw]
    
    if debug:
        print(f"  Filtered endpoints: {filtered_endpoints}")
        print(f"  Offset applied: {offset}")
        print(f"  Time signatures: {len(filtered_time_sigs)} found")
        print(f"  Tempo changes: {len(filtered_tempo_changes)} found")
    
    # Convert back to MidiSongByMeasure with the filtered measure_endpoints
    filtered_S = MidiSongByMeasure.from_MidiSong(
        filtered_midi_song,
        measure_endpoints=filtered_endpoints,
        consume_calling_song=True
    )
    
    if debug:
        print(f"  Filtered result: {filtered_S.get_n_measures()} measures")
        print(f"  Filtered tracks: {len(filtered_S.tracks)}")
    
    return filtered_S


def parse_measures_with_extra_ids(s, start_measure, end_measure, debug=False):
    """Parse CA string to find measures and tracks with extra_ids"""
    marked_measures = set()
    extra_id_to_measure = {}
    extra_id_to_track = {}
    
    measure_starts = []
    for match in re.finditer(r';M:\d+', s):
        measure_starts.append(match.start())
    
    if not measure_starts:
        return marked_measures, extra_id_to_measure, extra_id_to_track
    
    if debug:
        print(f"  Found {len(measure_starts)} measure markers in CA string")
    
    measure_sections = []
    for i in range(len(measure_starts)):
        section_start = measure_starts[i]
        section_end = measure_starts[i + 1] if i + 1 < len(measure_starts) else len(s)
        section_text = s[section_start:section_end]
        measure_sections.append(section_text)
    
    for section_idx, section_text in enumerate(measure_sections):
        project_measure = start_measure + section_idx
        
        if project_measure > end_measure:
            break
        
        extra_ids = re.findall(r'<extra_id_(\d+)>', section_text)
        if extra_ids:
            marked_measures.add(project_measure)
            for extra_id_num in extra_ids:
                extra_id_to_measure[int(extra_id_num)] = project_measure
            if debug:
                print(f"    Measure {project_measure}, Track 24: extra_id_{extra_ids[0]}")
    
    return marked_measures, extra_id_to_measure, extra_id_to_track


def detect_measures_to_generate(S, s, start_measure, end_measure, has_extra_ids, debug=False):
    """Detect which measures need generation"""
    measures_to_generate = set()
    extra_id_to_measure = {}
    extra_id_to_track = {}
    
    if has_extra_ids:
        marked_measures, extra_id_to_measure, extra_id_to_track = parse_measures_with_extra_ids(
            s, start_measure, end_measure, debug
        )
        measures_to_generate.update(marked_measures)
    
    empty_measures = set()
    for measure_idx in range(start_measure, end_measure + 1):
        is_empty = True
        for track in S.tracks:
            if measure_idx < len(track.tracks_by_measure):
                measure_track = track.tracks_by_measure[measure_idx]
                if hasattr(measure_track, 'note_ons') and measure_track.note_ons:
                    is_empty = False
                    break
        if is_empty:
            empty_measures.add(measure_idx)
    
    measures_to_generate.update(empty_measures)
    
    return measures_to_generate, extra_id_to_measure, extra_id_to_track


def call_nn_infill(s, S_encoded, use_sampling=True, min_length=10, 
                   enc_no_repeat_ngram_size=0, has_fully_masked_inst=False,
                   options_dict=None, track_options_dict=None, 
                   start_measure=None, end_measure=None):
    """
    MMM infill with context window filtering.
    Only sends relevant measures to MMM instead of entire project.
    """
    
    if options_dict is None:
        options_dict = {}
    if track_options_dict is None:
        track_options_dict = {}
    
    temperature = options_dict.get('temperature', 1.0)
    model_dim = options_dict.get('model_dim', 4)
    sampling_seed = options_dict.get('sampling_seed', -1)
    
    if temperature < 0.5:
        temperature = 0.5
    elif temperature > 2.0:
        temperature = 2.0
    
    if not MMM_AVAILABLE or MODEL is None or TOKENIZER is None:
        if DEBUG:
            print("MMM not available, returning fallback")
        return ";<extra_id_0>"
    
    try:
        S = pre.midisongbymeasure_from_save_dict(S_encoded)
        extra_ids = [int(m) for m in re.findall(r'<extra_id_(\d+)>', s)]
        actual_extra_id = extra_ids[0] if extra_ids else 0
        
        if DEBUG:
            print(f"\n=== MMM INFILL CALL ===")
            print(f"  Extra IDs: {extra_ids}")
            print(f"  Project: {S.get_n_measures()} measures, {len(S.tracks)} tracks")
            print(f"  Selection: measures {start_measure}-{end_measure}")
            print(f"  Temperature: {temperature}")
            print(f"  Track options: {len(track_options_dict)} tracks configured")
        
        measures_to_generate, extra_id_to_measure, extra_id_to_track = detect_measures_to_generate(
            S, s, start_measure, end_measure, bool(extra_ids), debug=DEBUG
        )
        
        if not measures_to_generate:
            if DEBUG:
                print("  No measures to generate")
            return f";<extra_id_{actual_extra_id}>"
        
        # CRITICAL FIX: Filter S to only the context window before creating MIDI
        filtered_S = filter_midisongbymeasure_to_range(S, start_measure, end_measure, debug=DEBUG)
        
        # Create temporary MIDI file from filtered context
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            temp_midi_path = tmp.name
        if DEBUG:
            temp_midi_path = os.path.join(os.path.dirname(__file__), 'test_in.mid')
        
        # Convert filtered MidiSongByMeasure to MidiSong and dump
        midi_song = MidiSong.from_MidiSongByMeasure(filtered_S, consume_calling_song=False)
        midi_song.dump(filename=temp_midi_path)
        
        if DEBUG:
            # Verify the MIDI file structure
            verify_midi = MidiSong.from_midi_file(temp_midi_path)
            verify_S = MidiSongByMeasure.from_MidiSong(verify_midi)
            print(f"  Dumped MIDI verification: {verify_S.get_n_measures()} measures")
            if verify_S.get_n_measures() != (end_measure - start_measure + 1):
                print(f"  WARNING: Expected {end_measure - start_measure + 1} measures but got {verify_S.get_n_measures()}")
        
        # Extract timing information
        input_ticks_per_beat = midi_song.cpq
        input_time_sig = (4, 4)
        if midi_song.time_signatures:
            input_time_sig = (midi_song.time_signatures[0].num, midi_song.time_signatures[0].denom)
        
        if DEBUG:
            print(f"  Input timing: {input_ticks_per_beat} ticks/beat, {input_time_sig[0]}/{input_time_sig[1]}")
        
        # Convert track options control strings to bar-mode format
        track_to_measures = {}
        for track_idx_str, opts in track_options_dict.items():
            track_idx = int(track_idx_str)
            controls = opts.get('controls', [])
            
            # Map measures_to_generate to bar indices in filtered context
            measure_list = sorted(list(measures_to_generate))
            track_to_measures[track_idx] = [(m - start_measure) for m in measure_list if start_measure <= m <= end_measure]
            
            if DEBUG and controls:
                print(f"  Track {track_idx}: {len(measure_list)} range(s), controls={controls}")
        
        if not track_to_measures:
            track_to_measures[0] = [(m - start_measure) for m in sorted(measures_to_generate)]
        
        # Build bar mode structure
        bar_mode = {"bars": {}}
        for track_idx, measure_indices in track_to_measures.items():
            if not measure_indices:
                continue
            
            control_strings = []
            if str(track_idx) in track_options_dict:
                control_strings = track_options_dict[str(track_idx)].get('controls', [])
            
            # Group contiguous measures into ranges
            ranges = []
            start_idx = measure_indices[0]
            for i in range(1, len(measure_indices)):
                if measure_indices[i] != measure_indices[i-1] + 1:
                    ranges.append((start_idx, measure_indices[i-1] + 1, control_strings))
                    start_idx = measure_indices[i]
            ranges.append((start_idx, measure_indices[-1] + 1, control_strings))
            
            bar_mode["bars"][track_idx] = ranges
            
            if DEBUG:
                print(f"  Track {track_idx}: {len(ranges)} range(s), controls={control_strings}")
        
        if DEBUG:
            print(f"\n=== BAR MODE STRUCTURE ===")
            for track_idx, ranges in bar_mode["bars"].items():
                print(f"  Track {track_idx}: {len(ranges)} range(s)")
                for start_bar, end_bar, controls in ranges:
                    print(f"    [{start_bar}, {end_bar}): controls={controls}")
        
        # Create prompt config
        prompt_config = PromptConfig(bar_mode, context_length=model_dim)
        
        # Create generation config
        gen_config = GenerationConfig(
            do_sample=True,
            max_new_tokens=256,
            attempts=4,
            repetition_penalty=1.0,
            temperature=temperature,
            top_k=0,
            top_p=1.0
        )
        
        # Create sampling engine
        engine = SamplingEngine(gen_config, TOKENIZER, seed=sampling_seed)
        
        if DEBUG:
            print(f"\n=== STARTING GENERATION ===")
            print(f"  Max tokens: {gen_config.max_new_tokens}")
            print(f"  Context length: {model_dim} bars")
        
        # Generate with correct positional arguments
        generated_score = generate(
            MODEL,                      # model
            TOKENIZER,                  # tokenizer
            prompt_config,              # prompt_config
            engine,                     # sampling_engine
            Score(temp_midi_path)       # score
        )
        
        # Save generated output
        output_path = temp_midi_path.replace('test_in.mid', 'test_out.mid')
        generated_score.save(output_path)
        
        if DEBUG:
            print(f"\n=== GENERATION COMPLETE ===")
            print(f"  Output saved to: {output_path}")
        
        # Convert generated MIDI back to CA format
        generated_midi_song = MidiSong.from_midi_file(output_path)
        generated_S = MidiSongByMeasure.from_MidiSong(generated_midi_song)
        
        if DEBUG:
            print(f"  Generated output: {generated_S.get_n_measures()} measures, {len(generated_S.tracks)} tracks")
        
        # Build CA format output with proper extra_id markers
        ca_parts = []
        for measure_idx in sorted(measures_to_generate):
            # Map to filtered context indices
            filtered_measure_idx = measure_idx - start_measure
            
            if filtered_measure_idx >= 0 and filtered_measure_idx < generated_S.get_n_measures():
                # Add measure header
                ca_parts.append(f";M:0;B:5;L:{input_ticks_per_beat * 4}")
                
                # Add extra_id for this measure
                extra_id_for_measure = extra_id_to_measure.get(measure_idx, actual_extra_id)
                ca_parts.append(f"<extra_id_{extra_id_for_measure}>")
                
                # Extract notes from generated measure
                for track in generated_S.tracks:
                    if filtered_measure_idx < len(track.tracks_by_measure):
                        measure_track = track.tracks_by_measure[filtered_measure_idx]
                        if hasattr(measure_track, 'note_ons') and measure_track.note_ons:
                            # Add notes with timing
                            last_time = 0
                            for note_on in sorted(measure_track.note_ons, key=lambda n: n.click):
                                wait = note_on.click - last_time
                                if wait > 0:
                                    ca_parts.append(f"w:{wait}")
                                ca_parts.append(f"N:{note_on.pitch}")
                                ca_parts.append(f"d:{note_on.duration if hasattr(note_on, 'duration') else 24}")
                                last_time = note_on.click
        
        result = ''.join(ca_parts)
        
        if DEBUG:
            print(f"  Generated CA: {len(result)} chars")
        
        return result if result else f";<extra_id_{actual_extra_id}>"
        
    except Exception as e:
        if DEBUG:
            print(f"\n=== ERROR ===")
            print(f"  {e}")
            import traceback
            traceback.print_exc()
        raise


def main():
    """Start MMM server"""
    if DEBUG:
        print(f"\n=== MMM SERVER READY ===")
        print(f"  Port: {PORT}")
        print(f"  Debug: {DEBUG}")
        print(f"  Track options support: ENABLED")
        print(f"  Control strings: ENABLED")
        print(f"  Context window filtering: ENABLED")
    
    if initialize_mmm():
        server = SimpleXMLRPCServer(("localhost", PORT), allow_none=True, logRequests=DEBUG)
        server.register_function(call_nn_infill, "call_nn_infill")
        
        print(f"\nWaiting for requests...")
        server.serve_forever()
    else:
        print("Failed to initialize MMM. Exiting.")
        sys.exit(1)


if __name__ == "__main__":
    main()