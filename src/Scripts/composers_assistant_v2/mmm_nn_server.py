"""
MMM Server with Track Options Control String Integration
Merges working conversion logic with control string support
"""

import sys
import os
import tempfile
import re
import json
from xmlrpc.server import SimpleXMLRPCServer
import mido

DEBUG = True
PORT = 3456

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src/Scripts/composers_assistant_v2'))
import preprocessing_functions as pre

MMM_AVAILABLE = False
MODEL = None
TOKENIZER = None
LAST_CALL = None
LAST_OUTPUTS = set()

try:
    from mmm import Model, Tokenizer, PromptConfig, SamplingEngine, GenerationConfig, Score, generate, ModelConfig
    MMM_AVAILABLE = True
    print("MMM library loaded successfully")
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
    
    for i in range(len(measure_starts)):
        section_start = measure_starts[i]
        section_end = measure_starts[i + 1] if i + 1 < len(measure_starts) else len(s)
        section_text = s[section_start:section_end]
        
        extra_id_match = re.search(r'<extra_id_(\d+)>', section_text)
        if not extra_id_match:
            continue
        
        extra_id = int(extra_id_match.group(1))
        track_match = re.search(r';I:(\d+)', section_text)
        track_idx = int(track_match.group(1)) if track_match else 0
        
        project_measure = start_measure + i
        
        if project_measure > end_measure:
            break
        
        marked_measures.add(project_measure)
        extra_id_to_measure[extra_id] = project_measure
        extra_id_to_track[extra_id] = track_idx
        
        if debug:
            print(f"    Measure {project_measure}, Track {track_idx}: extra_id_{extra_id}")
    
    return marked_measures, extra_id_to_measure, extra_id_to_track


def detect_measures_to_generate(S, s, start_measure, end_measure, has_extra_ids, debug=False):
    """Detect which measures need generation"""
    measures_to_generate = set()
    extra_id_to_measure = {}
    extra_id_to_track = {}
    
    if start_measure is None or end_measure is None:
        return measures_to_generate, extra_id_to_measure, extra_id_to_track
    
    if has_extra_ids:
        marked_measures, extra_id_to_measure, extra_id_to_track = parse_measures_with_extra_ids(
            s, start_measure, end_measure, debug
        )
        measures_to_generate = marked_measures
    
    return measures_to_generate, extra_id_to_measure, extra_id_to_track


def build_track_specific_bar_mode_with_controls(S, measures_to_generate, extra_id_to_measure, 
                                                  extra_id_to_track, track_options, debug=False):
    """Build bar_mode with track-specific infill ranges AND control strings"""
    bar_mode = {"bars": {}}
    
    if not measures_to_generate:
        return bar_mode
    
    measure_to_extra_id = {v: k for k, v in extra_id_to_measure.items()}
    track_to_measures = {}
    
    for track_idx, track in enumerate(S.tracks):
        track_measures = []
        for measure_idx in measures_to_generate:
            has_extra_id_for_this_track = (
                measure_idx in measure_to_extra_id and
                extra_id_to_track.get(measure_to_extra_id[measure_idx]) == track_idx
            )
            
            is_empty = False
            if measure_idx >= len(track.tracks_by_measure):
                is_empty = True
            else:
                measure_track = track.tracks_by_measure[measure_idx]
                if not (hasattr(measure_track, 'note_ons') and measure_track.note_ons):
                    is_empty = True
            
            if is_empty or has_extra_id_for_this_track:
                track_measures.append(measure_idx)
                if debug and has_extra_id_for_this_track and not is_empty:
                    print(f"    Track {track_idx}, Measure {measure_idx}: regenerating existing content")
        
        if track_measures:
            track_to_measures[track_idx] = track_measures
    
    if debug:
        print(f"  Track-to-measures mapping:")
        for track_idx, measures in sorted(track_to_measures.items()):
            print(f"    Track {track_idx}: {sorted(measures)}")
    
    for track_idx, track_measures in track_to_measures.items():
        if not track_measures:
            continue
        
        sorted_measures = sorted(track_measures)
        
        # Get control strings for this track
        controls = []
        track_key = str(track_idx)
        if track_key in track_options:
            controls = track_options[track_key].get('controls', [])
        elif track_idx in track_options:
            controls = track_options[track_idx].get('controls', [])
        
        # Group into contiguous ranges
        ranges = []
        range_start = sorted_measures[0]
        range_end = sorted_measures[0]
        
        for measure in sorted_measures[1:]:
            if measure == range_end + 1:
                range_end = measure
            else:
                ranges.append((range_start, range_end + 1, controls))
                range_start = measure
                range_end = measure
        
        ranges.append((range_start, range_end + 1, controls))
        bar_mode["bars"][track_idx] = ranges
        
        if debug:
            print(f"  Track {track_idx}: {len(ranges)} range(s), controls={controls}")
    
    return bar_mode


def convert_midi_to_ca_format_with_timing(midi_path, project_measures, measures_to_generate, 
                                          extra_id_to_measure, input_ticks_per_beat=None, 
                                          input_time_signature=None):
    """Convert generated MIDI back to CA format with proper timing"""
    if DEBUG:
        print(f"\n=== CA FORMAT CONVERSION ===")
        print(f"  MIDI: {midi_path}")
        print(f"  Measures to generate: {sorted(measures_to_generate)}")
    
    midi_file = mido.MidiFile(midi_path)
    output_ticks_per_beat = midi_file.ticks_per_beat
    
    output_time_sig_num = 4
    output_time_sig_denom = 4
    for track in midi_file.tracks:
        for msg in track:
            if msg.type == 'time_signature':
                output_time_sig_num = msg.numerator
                output_time_sig_denom = msg.denominator
                break
        if output_time_sig_num != 4:
            break
    
    if input_ticks_per_beat and input_time_signature:
        ticks_per_beat = input_ticks_per_beat
        time_sig_num, time_sig_denom = input_time_signature
    else:
        ticks_per_beat = output_ticks_per_beat
        time_sig_num = output_time_sig_num
        time_sig_denom = output_time_sig_denom
    
    timing_ratio = 1.0
    if input_ticks_per_beat and output_ticks_per_beat != input_ticks_per_beat:
        timing_ratio = input_ticks_per_beat / output_ticks_per_beat
        if DEBUG:
            print(f"  Timing conversion: {output_ticks_per_beat} → {input_ticks_per_beat} (ratio {timing_ratio})")
    
    beats_per_measure = time_sig_num * (4.0 / time_sig_denom)
    measure_length = int(ticks_per_beat * beats_per_measure)
    
    all_notes = []
    for track_idx, track in enumerate(midi_file.tracks):
        current_time = 0
        active_notes = {}
        
        for msg in track:
            current_time += msg.time
            
            if msg.type == 'note_on' and msg.velocity > 0:
                active_notes[msg.note] = {'start': current_time, 'velocity': msg.velocity}
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active_notes:
                    note_start = active_notes[msg.note]['start']
                    note_duration = current_time - note_start
                    
                    converted_start = int(note_start * timing_ratio)
                    converted_duration = int(note_duration * timing_ratio)
                    
                    all_notes.append({
                        'pitch': msg.note,
                        'start': converted_start,
                        'duration': converted_duration,
                        'velocity': active_notes[msg.note]['velocity']
                    })
                    del active_notes[msg.note]
    
    if DEBUG:
        print(f"  Extracted {len(all_notes)} notes from MIDI")
    
    notes_by_measure = {m: [] for m in measures_to_generate}
    
    for note in all_notes:
        measure_idx = note['start'] // measure_length
        if measure_idx in measures_to_generate:
            position_in_measure = note['start'] - (measure_idx * measure_length)
            notes_by_measure[measure_idx].append({
                'pitch': note['pitch'],
                'position': position_in_measure,
                'duration': note['duration'],
                'velocity': note['velocity']
            })
    
    measure_to_extra_id = {m: eid for eid, m in extra_id_to_measure.items()}
    sections = []
    
    for measure in sorted(measures_to_generate):
        notes = notes_by_measure[measure]
        
        if measure not in measure_to_extra_id:
            if DEBUG:
                print(f"  Warning: measure {measure} has no extra_id mapping")
            continue
        
        extra_id = measure_to_extra_id[measure]
        notes.sort(key=lambda n: (n['position'], n['pitch']))
        
        note_tokens = []
        last_position_in_measure = 0
        
        for note in notes:
            position_in_measure = note['position']
            wait = position_in_measure - last_position_in_measure
            if wait > 0:
                note_tokens.append(f"w:{int(wait)}")
            
            note_tokens.append(f"N:{note['pitch']}")
            note_tokens.append(f"d:{int(note['duration'])}")
            last_position_in_measure = position_in_measure
        
        section = f"<extra_id_{extra_id}>;" + ';'.join(note_tokens)
        sections.append(section)
    
    result = ';' + ';'.join(sections)
    
    if DEBUG:
        print(f"  Generated CA format: {len(result)} chars")
        print(f"  Sections: {len(sections)}")
    
    return result


def call_nn_infill(s, S_encoded, use_sampling, min_length, enc_no_repeat_ngram_size,
                   has_fully_masked_inst, options_dict, track_options_dict, 
                   start_measure, end_measure):
    """MMM infill with track options control strings"""
    global LAST_CALL, LAST_OUTPUTS
    
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
            for track_idx_str, opts in track_options_dict.items():
                controls = opts.get('controls', [])
                if controls:
                    print(f"    Track {track_idx_str}: {controls}")
        
        measures_to_generate, extra_id_to_measure, extra_id_to_track = detect_measures_to_generate(
            S, s, start_measure, end_measure, bool(extra_ids), debug=DEBUG
        )
        
        if not measures_to_generate:
            if DEBUG:
                print("  No measures to generate")
            return f";<extra_id_{actual_extra_id}>"
        
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            temp_midi_path = tmp.name
        S.dump(filename=temp_midi_path)
        
        input_midi = mido.MidiFile(temp_midi_path)
        input_ticks_per_beat = input_midi.ticks_per_beat
        input_time_sig = (4, 4)
        for track in input_midi.tracks:
            for msg in track:
                if msg.type == 'time_signature':
                    input_time_sig = (msg.numerator, msg.denominator)
                    break
        
        score_obj = Score(temp_midi_path)
        context_length = model_dim
        
        bar_mode = build_track_specific_bar_mode_with_controls(
            S, measures_to_generate, extra_id_to_measure, extra_id_to_track,
            track_options_dict, debug=DEBUG
        )
        
        if not bar_mode["bars"]:
            if DEBUG:
                print("  No tracks configured for infilling")
            prompt_cfg = PromptConfig({}, context_length=context_length)
        else:
            if DEBUG:
                print(f"\n=== BAR MODE STRUCTURE ===")
                for track_idx, ranges in bar_mode["bars"].items():
                    print(f"  Track {track_idx}: {len(ranges)} range(s)")
                    for start, end, controls in ranges:
                        print(f"    [{start}, {end}): controls={controls}")
            
            prompt_cfg = PromptConfig(bar_mode, context_length=context_length)
        
        for track_idx_str, opts in track_options_dict.items():
            track_temp = opts.get('temperature', -1.0)
            if track_temp > 0:
                temperature = track_temp
                if DEBUG:
                    print(f"  Using track {track_idx_str} temperature: {temperature}")
                break
        
        gen_cfg = GenerationConfig(
            do_sample=use_sampling,
            max_new_tokens=256,
            attempts=4,
            pad_token_id=0,
            repetition_penalty=1.0,
            temperature=temperature,
            top_k=50,
            top_p=1.0,
        )
        
        engine = SamplingEngine(gen_cfg, TOKENIZER, seed=sampling_seed, verbose=DEBUG)
        
        if DEBUG:
            print(f"\n=== STARTING GENERATION ===")
            print(f"  Max tokens: {gen_cfg.max_new_tokens}")
            print(f"  Context length: {prompt_cfg.context_length} bars")
        
        generated_score = generate(
            model=MODEL,
            tokenizer=TOKENIZER,
            prompt_config=prompt_cfg,
            sampling_engine=engine,
            score=score_obj,
            verbose=bool(DEBUG)
        )
        
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            result_midi_path = tmp.name
        generated_score.save(result_midi_path)
        
        if not os.path.exists(result_midi_path):
            if DEBUG:
                print("ERROR: Generated MIDI file does not exist")
            raise FileNotFoundError("Generated MIDI file not created")
        
        file_size = os.path.getsize(result_midi_path)
        if file_size == 0:
            if DEBUG:
                print("ERROR: Generated MIDI file is empty")
            raise ValueError("Generated MIDI file is empty")
        
        if DEBUG:
            print(f"  File size: {file_size} bytes")
        
        project_measures = list(range(S.get_n_measures()))
        ca_result = convert_midi_to_ca_format_with_timing(
            result_midi_path,
            project_measures,
            measures_to_generate,
            extra_id_to_measure,
            input_ticks_per_beat=input_ticks_per_beat,
            input_time_signature=input_time_sig
        )
        
        try:
            os.unlink(temp_midi_path)
            os.unlink(result_midi_path)
        except:
            pass
        
        LAST_CALL = s
        LAST_OUTPUTS.add(ca_result)
        
        if DEBUG:
            print(f"\n=== GENERATION COMPLETE ===")
            print(f"  Output length: {len(ca_result)} chars")
            print(f"  Preview: {ca_result[:200]}")
        
        return ca_result
        
    except Exception as e:
        if DEBUG:
            print(f"\n=== ERROR ===")
            print(f"  {e}")
            import traceback
            traceback.print_exc()
        
        fallback_extra_id = actual_extra_id if 'actual_extra_id' in locals() else 0
        return f";<extra_id_{fallback_extra_id}>"


def main():
    if not initialize_mmm():
        print("Failed to initialize MMM - server will not function")
        return
    
    print(f"\n=== MMM SERVER READY ===")
    print(f"  Port: {PORT}")
    print(f"  Debug: {DEBUG}")
    print(f"  Track options support: ENABLED")
    print(f"  Control strings: ENABLED")
    print("\nWaiting for requests...")
    
    server = SimpleXMLRPCServer(('127.0.0.1', PORT), allow_none=True, logRequests=False)
    server.register_function(call_nn_infill, 'call_nn_infill')
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server")


if __name__ == "__main__":
    main()