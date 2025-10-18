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
        tokenizer_path = os.path.join(script_dir, '../../../MMM/configs/MMM.json')
        model_path = os.path.join(script_dir, '../../../models/model.onnx')
        
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
    marked_measures = set()
    extra_id_to_measure = {}
    
    measure_starts = []
    for match in re.finditer(r';M:\d+', s):
        measure_starts.append(match.start())
    
    if not measure_starts:
        if debug:
            print("  No measure markers found in CA string")
        return marked_measures, extra_id_to_measure
    
    if debug:
        print(f"  Found {len(measure_starts)} measure markers in CA string")
    
    measure_sections = []
    for i in range(len(measure_starts)):
        section_start = measure_starts[i]
        section_end = measure_starts[i + 1] if i + 1 < len(measure_starts) else len(s)
        section_text = s[section_start:section_end]
        has_extra_id = '<extra_id_' in section_text
        
        if has_extra_id:
            extra_id_match = re.search(r'<extra_id_(\d+)>', section_text)
            if extra_id_match:
                extra_id = int(extra_id_match.group(1))
                measure_sections.append({
                    'section_idx': i,
                    'extra_id': extra_id,
                    'has_extra_id': True
                })
    
    for section in measure_sections:
        project_measure = start_measure + section['section_idx']
        
        if project_measure > end_measure:
            break
            
        marked_measures.add(project_measure)
        extra_id_to_measure[section['extra_id']] = project_measure
        
        if debug:
            print(f"    Measure {project_measure}: extra_id_{section['extra_id']}")
    
    return marked_measures, extra_id_to_measure


def detect_measures_to_generate(S, s, start_measure, end_measure, has_extra_ids, debug=False):
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


def convert_midi_to_ca_format_with_timing(midi_path, project_measures, measures_to_generate, 
                                          extra_id_to_measure, input_ticks_per_beat=None, 
                                          input_time_signature=None):
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
    
    # No adjustment needed - MIDI contains full project at original indices
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
    global LAST_CALL, LAST_OUTPUTS
    
    if options_dict is None:
        options_dict = {}
    
    temperature = options_dict.get('temperature', 1.0)
    model_dim = options_dict.get('model_dim', 4)
    max_steps = options_dict.get('max_steps', 200)
    shuffle = options_dict.get('shuffle', True)
    sampling_seed = options_dict.get('sampling_seed', -1)
    mask_top_k = options_dict.get('mask_top_k', 0)
    
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
        
        # Dump full S to MIDI (don't trim - preserves note on/off pairs)
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            temp_midi_path = tmp.name
        S.dump(filename=temp_midi_path)
        
        if DEBUG:
            print(f"  Created full project MIDI with {S.get_n_measures()} measures")
        
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
        
        if DEBUG:
            print(f"\n=== BUILDING PROMPT CONFIG ===")
            print(f"  REAPER selection: measures {start_measure}-{end_measure}")
            print(f"  Total measures in score: {len(project_measures)}")
            print(f"  Context length: {context_length} bars (on each side of target)")
            print(f"  Measures to infill: {sorted(measures_to_generate)}")
        
        bar_mode = {"bars": {}}
        
        # Use project measure indices directly (no adjustment needed)
        sorted_measures = sorted(measures_to_generate)
        
        if not sorted_measures:
            if DEBUG:
                print("  No measures to generate, using empty config")
            prompt_cfg = PromptConfig({}, context_length=context_length)
        else:
            ranges = []
            range_start = sorted_measures[0]
            range_end = sorted_measures[0]
            
            for measure in sorted_measures:
                if measure == range_end:
                    range_end = measure + 1
                else:
                    ranges.append((range_start, range_end, []))
                    range_start = measure
                    range_end = measure + 1
            
            ranges.append((range_start, range_end, []))
            
            bar_mode["bars"][0] = ranges
            
            if DEBUG:
                print(f"  Total tracks in score: {len(S.tracks)}")
                print(f"  Configuring infill for track 0 only")
                print(f"  Bar ranges to infill: {ranges}")
            
            prompt_cfg = PromptConfig(bar_mode, context_length=context_length)
        
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
            print(f"\n=== MMM GENERATION ===")
            print(f"  Tracks: {len(S.tracks)}")
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
                import traceback
                traceback.print_exc()
            raise
        
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            result_midi_path = tmp.name
        
        try:
            generated_score.save(result_midi_path)
        except Exception as save_error:
            if DEBUG:
                print(f"  Error saving score: {save_error}")
            raise
        
        if not os.path.exists(result_midi_path):
            if DEBUG:
                print(f"  ERROR: Generated MIDI file does not exist")
            raise FileNotFoundError("Generated MIDI file not created")
        
        file_size = os.path.getsize(result_midi_path)
        if file_size == 0:
            if DEBUG:
                print(f"  ERROR: Generated MIDI file is empty")
            raise ValueError("Generated MIDI file is empty")
        
        if DEBUG:
            print(f"  Generation complete, saved to {result_midi_path}")
            print(f"  File size: {file_size} bytes")
        
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