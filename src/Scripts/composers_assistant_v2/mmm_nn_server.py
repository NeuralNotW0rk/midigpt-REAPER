#!/usr/bin/env python3
"""
MMM Server - Refactored for new MMM implementation
Fixed measure mapping and CA format generation
"""

import os
import sys
from xmlrpc.server import SimpleXMLRPCServer
import tempfile
import json
import re

ca_path = os.path.join(os.path.dirname(__file__), "src/Scripts/composers_assistant_v2")
if os.path.exists(ca_path):
    sys.path.insert(0, os.path.abspath(ca_path))

try:
    from mmm import Model, Tokenizer, Score, GenerationConfig, SamplingEngine, PromptConfig, ModelConfig, generate
    import preprocessing_functions as pre
    import mido
    MMM_AVAILABLE = True
    print("MMM library loaded successfully")
except ImportError as e:
    MMM_AVAILABLE = False
    print(f"MMM not available: {e}")

DEBUG = True
PORT = 3456

# Global MMM resources - initialized once at startup
MODEL = None
TOKENIZER = None
VOCAB_SIZE = 663  # Changed from 16000 - must match tokenizer actual vocab size

LAST_CALL = None
LAST_OUTPUTS = set()


def initialize_mmm():
    """Initialize MMM model and tokenizer once at startup"""
    global MODEL, TOKENIZER, VOCAB_SIZE
    
    if not MMM_AVAILABLE:
        print("MMM not available, skipping initialization")
        return False
    
    try:
        # Find tokenizer and model paths
        base_path = os.path.dirname(os.path.abspath(__file__))
        tokenizer_path = os.path.join(base_path, "../../../MMM/configs/MMM.json")
        model_path = os.path.join(base_path, "../../../models/model.onnx")
        
        # Fallback paths - update these to your actual paths
        if not os.path.exists(tokenizer_path):
            tokenizer_path = "/path/to/your/tokenizer.json"
        if not os.path.exists(model_path):
            model_path = "/path/to/your/model.onnx"
        
        if not os.path.exists(tokenizer_path):
            print(f"Warning: Tokenizer not found at {tokenizer_path}")
            print("MMM will not be available for generation")
            return False
        
        if not os.path.exists(model_path):
            print(f"Warning: Model not found at {model_path}")
            print("MMM will not be available for generation")
            return False
        
        if DEBUG:
            print(f"\n=== INITIALIZING MMM ===")
            print(f"  Tokenizer: {tokenizer_path}")
            print(f"  Model: {model_path}")
            print(f"  Vocab size: {VOCAB_SIZE}")
        
        # Load tokenizer
        TOKENIZER = Tokenizer(tokenizer_path)
        
        # Load model with configuration
        model_cfg = ModelConfig(
            model=model_path,  # Changed from 'path' to 'model'
            vocab_size=VOCAB_SIZE
        )
        MODEL = Model(model_cfg)
        
        if DEBUG:
            print(f"  MMM initialized successfully")
        
        return True
        
    except Exception as e:
        print(f"Error initializing MMM: {e}")
        import traceback
        traceback.print_exc()
        return False


def parse_measures_with_extra_ids(s, start_measure, end_measure, debug=False):
    """
    Parse CA string to find measures with extra_id tokens.
    Returns both the set of marked measures AND the extra_id -> measure mapping.
    """
    marked_measures = set()
    extra_id_to_measure = {}
    
    measure_starts = []
    for match in re.finditer(r';M:\d+', s):
        measure_starts.append(match.start())
    
    if not measure_starts:
        if debug:
            print("  No measure markers in CA string")
        return marked_measures, extra_id_to_measure
    
    if debug:
        print(f"  Found {len(measure_starts)} measure markers in CA string")
    
    measure_sections = []
    for i in range(len(measure_starts)):
        section_start = measure_starts[i]
        section_end = measure_starts[i + 1] if i + 1 < len(measure_starts) else len(s)
        section_text = s[section_start:section_end]
        
        extra_id_match = re.search(r'<extra_id_(\d+)>', section_text)
        extra_id = int(extra_id_match.group(1)) if extra_id_match else None
        
        measure_sections.append({
            'start': section_start,
            'end': section_end,
            'text': section_text,
            'extra_id': extra_id
        })
    
    for section_idx, section in enumerate(measure_sections):
        project_measure = start_measure + section_idx
        
        if project_measure > end_measure:
            break
            
        if section['extra_id'] is not None:
            marked_measures.add(project_measure)
            extra_id_to_measure[section['extra_id']] = project_measure
            if debug:
                print(f"    Measure {project_measure}: extra_id_{section['extra_id']}")
    
    return marked_measures, extra_id_to_measure


def detect_measures_to_generate(S, s, start_measure, end_measure, has_extra_ids, debug=False):
    """
    Detect which measures need generation.
    Returns the set of measures AND the extra_id -> measure mapping.
    """
    measures_to_generate = set()
    extra_id_to_measure = {}
    
    if start_measure is None or end_measure is None:
        if debug:
            print("  No selection bounds")
        return measures_to_generate, extra_id_to_measure
    
    if debug:
        print(f"\n=== MEASURE DETECTION ===")
        print(f"  Selection: measures {start_measure}-{end_measure}")
        print(f"  Has extra_ids: {has_extra_ids}")
    
    if has_extra_ids:
        marked_measures, extra_id_to_measure = parse_measures_with_extra_ids(s, start_measure, end_measure, debug)
        measures_to_generate = marked_measures
        if debug:
            print(f"  Marked measures: {sorted(marked_measures)}")
            print(f"  Extra_id mapping: {extra_id_to_measure}")
    else:
        if debug:
            print("  No extra_ids, nothing to generate")
    
    if debug:
        print(f"  Will generate: {sorted(measures_to_generate)}")
    
    return measures_to_generate, extra_id_to_measure


def get_loudness_level(avg_velocity):
    """Convert velocity to loudness level (0-7)."""
    DYNAMICS_SLICER = [64.4, 76.67, 81.9, 89.37, 95.9, 100.5, 109.9]
    if avg_velocity is None or avg_velocity < DYNAMICS_SLICER[0]:
        return 0
    for i, threshold in enumerate(DYNAMICS_SLICER):
        if avg_velocity < threshold:
            return i
    return 7


def convert_midi_to_ca_format_with_timing(midi_path, project_measures, measures_to_generate, 
                                          extra_id_to_measure, input_ticks_per_beat=None, 
                                          input_time_signature=None):
    """
    Convert MIDI to CA format with separate sections for each extra_id.
    extra_id_to_measure: dict mapping extra_id -> measure_number
    Returns format: ;<extra_id_X>;notes_for_X;<extra_id_Y>;notes_for_Y;...
    """
    if DEBUG:
        print(f"\n=== CA FORMAT CONVERSION ===")
        print(f"  MIDI: {midi_path}")
        print(f"  Project measures: {project_measures}")
        print(f"  Measures to generate: {sorted(measures_to_generate)}")
        print(f"  Extra_id mapping: {extra_id_to_measure}")
    
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
    
    if DEBUG:
        print(f"  Timing: {ticks_per_beat} ticks/beat, {time_sig_num}/{time_sig_denom}")
        print(f"  Measure length: {measure_length} ticks")
    
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
                print(f"  Warning: measure {measure} has no extra_id mapping, skipping")
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
        print(f"  Sections: {len(sections)} (one per measure)")
        note_count = sum(len(notes) for notes in notes_by_measure.values())
        print(f"  Total notes: {note_count}")
    
    return result


def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, options_dict=None, start_measure=None, end_measure=None):
    """
    Main function called by REAPER via XMLRPC
    Now receives full options_dict with all global parameters
    """
    global LAST_CALL, LAST_OUTPUTS
    
    if options_dict is None:
        options_dict = {}
    
    temperature = options_dict.get('temperature', 1.0)
    tracks_per_step = options_dict.get('tracks_per_step', 1)
    bars_per_step = options_dict.get('bars_per_step', 1)
    model_dim = options_dict.get('model_dim', 4)
    percentage = options_dict.get('percentage', 100)
    max_steps = options_dict.get('max_steps', 200)
    batch_size = options_dict.get('batch_size', 1)
    shuffle = options_dict.get('shuffle', True)
    sampling_seed = options_dict.get('sampling_seed', -1)
    mask_top_k = options_dict.get('mask_top_k', 0)
    polyphony_hard_limit = options_dict.get('polyphony_hard_limit', 6)
    
    if temperature < 0.5:
        temperature = 0.5
    elif temperature > 2.0:
        temperature = 2.0
    
    if DEBUG:
        print(f"\n{'='*60}")
        print('MMM CALL_NN_INFILL')
        print(f"  Temperature: {temperature}")
        print(f"  Model dim: {model_dim}")
        print(f"  Max steps: {max_steps}")
        print(f"  Shuffle: {shuffle}")
    
    try:
        if not MMM_AVAILABLE or MODEL is None or TOKENIZER is None:
            if DEBUG:
                print("  MMM not available, returning fallback")
            return ";M:0;B:5;L:96;<extra_id_0>N:60;d:240;w:240"
        
        s_normalized = re.sub(r'<extra_id_\d+>', '<extra_id_0>', s)
        
        extra_ids = [int(m) for m in re.findall(r'<extra_id_(\d+)>', s)]
        actual_extra_id = extra_ids[0] if extra_ids else 0
        
        if isinstance(S, dict):
            S = pre.midisongbymeasure_from_save_dict(S)
        
        project_measures = list(range(S.get_n_measures()))
        
        if DEBUG:
            print(f"  Extra IDs: {extra_ids}")
            print(f"  Project: {len(project_measures)} measures, {len(S.tracks)} tracks")
        
        measures_to_generate, extra_id_to_measure = detect_measures_to_generate(
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
        
        # Load input MIDI as Score
        score_obj = Score(temp_midi_path)
        
        # context_length is a hyperparameter: number of bars on EACH SIDE of the target
        # e.g., context_length=4 means 4 bars before + target + 4 bars after = 9 total
        # This is independent of the actual score length
        # Use model_dim from REAPER settings, which defaults to 4
        context_length = model_dim
        
        if DEBUG:
            print(f"\n=== BUILDING PROMPT CONFIG ===")
            print(f"  REAPER selection: measures {start_measure}-{end_measure}")
            print(f"  Total measures in score: {len(project_measures)}")
            print(f"  Context length: {context_length} bars (on each side of target)")
            print(f"  Measures to infill: {sorted(measures_to_generate)}")
            print(f"  Expected total bars: {2*context_length + 1} (approx)")
        
        # Build prompt configuration for bar infilling
        # Format: {"bars": {track_idx: [(start_bar, end_bar, [controls])], ...}}
        bar_mode = {"bars": {}}
        
        # Group consecutive measures into ranges for each track
        sorted_measures = sorted(measures_to_generate)
        
        if not sorted_measures:
            if DEBUG:
                print("  No measures to generate, using empty config")
            prompt_cfg = PromptConfig({}, context_length=context_length)
        else:
            # Build ranges from consecutive measures
            ranges = []
            range_start = sorted_measures[0]
            range_end = sorted_measures[0]
            
            for measure in sorted_measures:
                if measure == range_end:
                    range_end = measure + 1
                else:
                    # Gap found, save current range and start new one
                    ranges.append((range_start, range_end, []))
                    range_start = measure
                    range_end = measure + 1
            
            # Add final range
            ranges.append((range_start, range_end, []))
            
            # Validate ranges are within score bounds
            total_bars = len(project_measures)
            for start, end, _ in ranges:
                if start < 0 or end > total_bars:
                    if DEBUG:
                        print(f"  WARNING: Range ({start}, {end}) extends beyond score bounds (0, {total_bars})")
                    # Clamp to valid range
                    start = max(0, start)
                    end = min(total_bars, end)
            
            # Only configure track 0 for infilling
            # In REAPER, the <extra_id> markers typically apply to a single track context
            # If we need multi-track infilling, we'd need to parse which tracks from the CA string
            num_tracks = len(S.tracks)
            bar_mode["bars"][0] = ranges
            
            if DEBUG:
                print(f"  Total tracks in score: {num_tracks}")
                print(f"  Configuring infill for track 0 only")
                print(f"  Bar ranges to infill: {ranges}")
            
            prompt_cfg = PromptConfig(bar_mode, context_length=context_length)
        
        # Build generation configuration
        gen_cfg = GenerationConfig(
            do_sample=use_sampling,
            max_new_tokens=min(max_steps * 10, 1000),  # More reasonable limit
            temperature=temperature,
            top_p=0.95,
            top_k=mask_top_k if mask_top_k > 0 else 0,
            repetition_penalty=1.0,
            attempts=3
        )
        
        # Create sampling engine
        engine = SamplingEngine(gen_cfg, TOKENIZER, seed=sampling_seed, verbose=DEBUG)
        
        if DEBUG:
            print(f"\n=== MMM GENERATION ===")
            print(f"  Tracks: {num_tracks}")
            print(f"  Generating measures: {sorted(measures_to_generate)}")
            print(f"  Context length: {prompt_cfg.context_length} bars")
            print(f"  Temperature: {temperature}")
            print(f"  Max tokens: {gen_cfg.max_new_tokens}")
            print(f"  PromptConfig:")
            print(f"    Mode: {'BarInfilling' if prompt_cfg.bar_infilling() else 'Other'}")
            print(f"    Empty: {prompt_cfg.empty()}")
            if prompt_cfg.bar_infilling() and not prompt_cfg.empty():
                bars_dict = prompt_cfg.bars()
                print(f"    Tracks configured: {len(bars_dict)}")
                for track_idx, ranges in bars_dict.items():
                    print(f"      Track {track_idx}: {ranges}")
        
        # Generate (verbose as boolean)
        try:
            generated_score = generate(
                model=MODEL,
                tokenizer=TOKENIZER,
                prompt_config=prompt_cfg,
                sampling_engine=engine,
                score=score_obj,
                verbose=bool(DEBUG)
            )
        except Exception as gen_error:
            if DEBUG:
                print(f"\n=== GENERATION ERROR ===")
                print(f"  Error: {gen_error}")
                print(f"  Error type: {type(gen_error).__name__}")
                print(f"  Score had {len(project_measures)} measures")
                print(f"  Tried to infill: {sorted(measures_to_generate)}")
                print(f"  PromptConfig context_length: {prompt_cfg.context_length}")
            raise
        
        # Save generated score to temporary MIDI file
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            result_midi_path = tmp.name
        generated_score.save(result_midi_path)
        
        if DEBUG:
            print(f"  Generation complete, saved to {result_midi_path}")
        
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
        
        LAST_CALL = s_normalized
        LAST_OUTPUTS.add(ca_result)
        
        if DEBUG:
            print(f"\n=== RESULT ===")
            print(f"  CA format: {len(ca_result)} chars")
            print(f"  Preview: {ca_result[:200]}...")
        
        return ca_result
        
    except Exception as e:
        if DEBUG:
            print(f'\nError: {e}')
            import traceback
            traceback.print_exc()
        
        fallback_extra_id = actual_extra_id if 'actual_extra_id' in locals() else 0
        return f";M:0;B:5;L:96;<extra_id_{fallback_extra_id}>N:60;d:240;w:240"


def create_default_options(temp):
    """Create default global options object"""
    class DefaultOptions:
        pass
    opts = DefaultOptions()
    opts.temperature = temp
    opts.tracks_per_step = 1
    opts.bars_per_step = 1
    opts.model_dim = 4
    opts.percentage = 100
    opts.max_steps = 200
    opts.batch_size = 1
    opts.shuffle = True
    opts.sampling_seed = -1
    opts.mask_top_k = 0
    opts.polyphony_hard_limit = 6
    return opts


def start_server():
    print("="*60)
    print("MMM Server")
    print("="*60)
    print(f"Port: {PORT}")
    print(f"MMM: {MMM_AVAILABLE}")
    print("="*60)
    
    server = SimpleXMLRPCServer(('127.0.0.1', PORT), logRequests=DEBUG, allow_none=True)
    server.register_function(call_nn_infill, 'call_nn_infill')
    
    print(f"\nServer ready on port {PORT}")
    print("Detection: marked + empty measures")
    print("Mapping: 1:1 AI→project (truncate extras)")
    print("Format: continuous CA string with proper headers")
    print("\nPress Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")


if __name__ == "__main__":
    if MMM_AVAILABLE:
        success = initialize_mmm()
        if not success:
            print("Warning: MMM initialization failed, server will use fallback responses")
    
    start_server()