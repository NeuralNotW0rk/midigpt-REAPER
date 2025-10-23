"""
MMM Server with Track Options Control String Integration
Applies per-track control strings to bar infill ranges
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
    """
    Build bar_mode dictionary with track-specific infill ranges AND control strings.
    Integrates per-track attribute controls from REAPER Track Options FX.
    
    Returns:
        {
            "bars": {
                track_idx: [
                    (start_bar, end_bar, ["INST_0", "DENS_10", "HORIZ_3", ...])
                ]
            }
        }
    """
    bar_mode = {"bars": {}}
    
    if not measures_to_generate:
        return bar_mode
    
    # Group measures by track
    track_to_measures = {}
    for measure in measures_to_generate:
        for extra_id, extra_measure in extra_id_to_measure.items():
            if extra_measure == measure:
                track_idx = extra_id_to_track.get(extra_id, 0)
                if track_idx not in track_to_measures:
                    track_to_measures[track_idx] = []
                track_to_measures[track_idx].append(measure)
                break
    
    # Build contiguous ranges with controls for each track
    for track_idx, measures in track_to_measures.items():
        sorted_measures = sorted(set(measures))
        ranges = []
        
        current_start = sorted_measures[0]
        current_end = sorted_measures[0] + 1
        
        for measure in sorted_measures[1:]:
            if measure == current_end:
                current_end = measure + 1
            else:
                # Get control strings for this track if available
                # Track options dict has string keys from XML-RPC
                controls = []
                track_key = str(track_idx)
                if track_key in track_options:
                    controls = track_options[track_key].get('controls', [])
                elif track_idx in track_options:  # Fallback for integer keys
                    controls = track_options[track_idx].get('controls', [])
                
                ranges.append((current_start, current_end, controls))
                current_start = measure
                current_end = measure + 1
        
        # Add final range
        controls = []
        track_key = str(track_idx)
        if track_key in track_options:
            controls = track_options[track_key].get('controls', [])
        elif track_idx in track_options:  # Fallback for integer keys
            controls = track_options[track_idx].get('controls', [])
        
        ranges.append((current_start, current_end, controls))
        
        bar_mode["bars"][track_idx] = ranges
        
        if debug:
            print(f"  Track {track_idx}: {len(ranges)} range(s), controls={controls}")
    
    return bar_mode


def call_nn_infill(s, S_encoded, use_sampling, min_length, enc_no_repeat_ngram_size,
                   has_fully_masked_inst, options_dict, track_options_dict, 
                   start_measure, end_measure):
    """
    MMM infill with track options control strings.
    
    Args:
        s: CA format string with extra_id tokens
        S_encoded: Encoded MidiSongByMeasure
        options_dict: Global options
        track_options_dict: Per-track options with control strings
        start_measure, end_measure: Selection range
    """
    
    if not MMM_AVAILABLE or MODEL is None or TOKENIZER is None:
        return ";<extra_id_0>"
    
    try:
        S = pre.midisongbymeasure_from_save_dict(S_encoded)
        
        extra_ids = [int(m) for m in re.findall(r'<extra_id_(\d+)>', s)]
        
        if DEBUG:
            print(f"\n=== MMM INFILL CALL ===")
            print(f"  Extra IDs: {extra_ids}")
            print(f"  Project: {S.get_n_measures()} measures, {len(S.tracks)} tracks")
            print(f"  Selection: measures {start_measure}-{end_measure}")
            print(f"  Temperature: {options_dict.get('temperature', 1.0)}")
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
            return f";<extra_id_{extra_ids[0] if extra_ids else 0}>"
        
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            temp_midi_path = tmp.name
        S.dump(filename=temp_midi_path)
        
        score_obj = Score(temp_midi_path)
        
        model_dim = options_dict.get('model_dim', 4)
        context_length = model_dim
        
        # Build bar mode WITH control strings
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
        
        # Apply per-track temperature if specified
        temperature = options_dict.get('temperature', 1.0)
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
        
        sampling_seed = options_dict.get('sampling_seed', -1)
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
        
        # Convert back to CA format
        result_midi = mido.MidiFile(result_midi_path)
        result_song = pre.import_midi_file_to_midisongbymeasure(result_midi_path)
        
        # Build CA string with proper extra_id placement
        ca_output = pre.midisongbymeasure_to_ca_string(
            result_song, 
            extra_id_to_measure,
            extra_id_to_track
        )
        
        if DEBUG:
            print(f"\n=== GENERATION COMPLETE ===")
            print(f"  Output length: {len(ca_output)} chars")
            print(f"  Preview: {ca_output[:200]}")
        
        return ca_output
        
    except Exception as e:
        if DEBUG:
            print(f"\n=== ERROR ===")
            print(f"  {e}")
            import traceback
            traceback.print_exc()
        return f";<extra_id_0>"


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