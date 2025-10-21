"""
MMM server with integrated track-level control support.
Key changes:
1. Import rpr_mmm_functions for reading track options
2. Convert track options to MMM control strings
3. Pass controls to PromptConfig bars configuration
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

# Import MMM track options functions
try:
    import rpr_mmm_functions as mmm_fn
    MMM_FN_AVAILABLE = True
    if DEBUG:
        print("rpr_mmm_functions loaded successfully")
except ImportError as e:
    MMM_FN_AVAILABLE = False
    if DEBUG:
        print(f"rpr_mmm_functions not available: {e}")

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
    if debug:
        print('  CA string preview:', s[:200] if len(s) > 200 else s)
    
    marked_measures = set()
    extra_id_to_measure = {}
    extra_id_to_track = {}
    
    measure_starts = []
    for match in re.finditer(r';M:\d+', s):
        measure_starts.append(match.start())
    
    if not measure_starts:
        if debug:
            print("  No measure markers found")
        return marked_measures, extra_id_to_measure, extra_id_to_track
    
    if debug:
        print(f"  Found {len(measure_starts)} measure markers")
    
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
    
    return marked_measures, extra_id_to_measure, extra_id_to_track


def build_bars_with_controls(S, measures_to_generate, extra_id_to_track, track_options_by_idx, debug=False):
    """
    Build bars configuration with track-specific control strings.
    
    Returns:
        bars: dict {track_idx: [(start_bar, end_bar, [controls])]}
    """
    bars = {}
    
    # Group measures by track
    track_measures = {}
    for measure_idx in measures_to_generate:
        # Find track for this measure from extra_id mapping
        track_idx = None
        for extra_id, m_idx in extra_id_to_track.items():
            if m_idx == measure_idx:
                track_idx = extra_id_to_track[extra_id]
                break
        
        if track_idx is None:
            track_idx = 0
        
        if track_idx not in track_measures:
            track_measures[track_idx] = []
        track_measures[track_idx].append(measure_idx)
    
    # Build bars configuration with controls
    for track_idx, measures in track_measures.items():
        if not measures:
            continue
        
        measures_sorted = sorted(measures)
        
        # Get controls for this track
        controls = []
        if MMM_FN_AVAILABLE and track_idx in track_options_by_idx:
            opts = track_options_by_idx[track_idx]
            controls = mmm_fn.convert_track_options_to_control_strings(opts)
            if debug:
                print(f"  Track {track_idx} controls: {controls}")
        
        # Group consecutive measures
        ranges = []
        start = measures_sorted[0]
        end = start
        
        for m in measures_sorted[1:]:
            if m == end + 1:
                end = m
            else:
                ranges.append((start, end + 1, controls))
                start = m
                end = m
        ranges.append((start, end + 1, controls))
        
        bars[track_idx] = ranges
    
    return bars


def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, options_dict=None, start_measure=None, end_measure=None):
    
    if options_dict is None:
        options_dict = {}
    
    temperature = options_dict.get('temperature', 1.0)
    model_dim = options_dict.get('model_dim', 4)
    max_steps = options_dict.get('max_steps', 200)
    
    if temperature < 0.5:
        temperature = 0.5
    elif temperature > 2.0:
        temperature = 2.0
    
    if DEBUG:
        print(f"\n{'='*60}")
        print('MMM CALL_NN_INFILL')
        print(f"  Temperature: {temperature}")
        print(f"  Model dim: {model_dim}")
    
    try:
        if not MMM_AVAILABLE or MODEL is None or TOKENIZER is None:
            if DEBUG:
                print("  MMM not available")
            return ";M:0;B:5;L:96;<extra_id_0>N:60;d:240;w:240"
        
        if isinstance(S, dict):
            S = pre.midisongbymeasure_from_save_dict(S)
        
        # Parse measures with extra_ids
        has_extra_ids = '<extra_id_' in s
        measures_to_generate = set()
        extra_id_to_track = {}
        
        if has_extra_ids:
            marked_measures, extra_id_to_measure, extra_id_to_track = parse_measures_with_extra_ids(
                s, start_measure, end_measure, DEBUG
            )
            measures_to_generate = marked_measures
        
        if not measures_to_generate:
            if DEBUG:
                print("  No measures to generate")
            return s
        
        # Read track options from REAPER
        track_options_by_idx = {}
        if MMM_FN_AVAILABLE:
            try:
                track_options_by_idx = mmm_fn.get_mmm_track_options_by_track_idx()
                if DEBUG:
                    print(f"  Loaded track options for {len(track_options_by_idx)} tracks")
            except Exception as e:
                if DEBUG:
                    print(f"  Could not read track options: {e}")
        
        # Create MIDI file from S
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as temp_file:
            temp_path = temp_file.name
        
        S.dump(filename=temp_path)
        
        if DEBUG:
            print(f"  Created MIDI: {temp_path}")
        
        # Load as MMM Score
        score = Score(temp_path)
        
        # Build bars configuration with controls
        bars = build_bars_with_controls(
            S, measures_to_generate, extra_id_to_track, track_options_by_idx, DEBUG
        )
        
        if DEBUG:
            print(f"  Bars configuration:")
            for track_idx, ranges in bars.items():
                for start, end, controls in ranges:
                    print(f"    Track {track_idx}: bars {start}-{end-1}, controls: {controls}")
        
        # Create PromptConfig with controls
        prompt_cfg = PromptConfig({"bars": bars}, context_length=model_dim)
        
        # Create generation config
        gen_cfg = GenerationConfig(
            do_sample=use_sampling,
            max_new_tokens=max_steps,
            temperature=temperature
        )
        
        # Create sampling engine
        engine = SamplingEngine(gen_cfg, TOKENIZER, seed=-1)
        
        # Generate
        if DEBUG:
            print("  Running generation...")
        
        generated_score = generate(MODEL, TOKENIZER, prompt_cfg, engine, score, verbose=DEBUG)
        
        # Save result
        result_path = temp_path.replace('.mid', '_result.mid')
        generated_score.save(result_path)
        
        if DEBUG:
            print(f"  Generated: {result_path}")
        
        # Convert back to CA format
        result_s = convert_midi_to_ca_format(result_path, measures_to_generate, extra_id_to_measure)
        
        # Cleanup
        try:
            os.unlink(temp_path)
            os.unlink(result_path)
        except:
            pass
        
        if DEBUG:
            print(f"  Result: {len(result_s)} chars")
        
        return result_s
        
    except Exception as e:
        if DEBUG:
            print(f"  Generation failed: {e}")
            import traceback
            traceback.print_exc()
        return s


def convert_midi_to_ca_format(midi_path, measures_to_generate, extra_id_to_measure):
    """Convert MIDI file back to CA format string."""
    import mido
    
    try:
        mid = mido.MidiFile(midi_path)
        
        # Simple conversion - extract notes
        notes_by_measure = {}
        current_time = 0
        
        for track in mid.tracks:
            for msg in track:
                current_time += msg.time
                if msg.type == 'note_on' and msg.velocity > 0:
                    measure = int(current_time / (mid.ticks_per_beat * 4))
                    if measure in measures_to_generate:
                        if measure not in notes_by_measure:
                            notes_by_measure[measure] = []
                        notes_by_measure[measure].append({
                            'pitch': msg.note,
                            'velocity': msg.velocity,
                            'time': current_time
                        })
        
        # Build CA string
        sections = []
        for measure_idx in sorted(measures_to_generate):
            extra_id = None
            for eid, m_idx in extra_id_to_measure.items():
                if m_idx == measure_idx:
                    extra_id = eid
                    break
            
            if extra_id is None:
                continue
            
            notes = notes_by_measure.get(measure_idx, [])
            note_strs = [f"N:{n['pitch']};d:240;w:240" for n in notes]
            
            section = f"<extra_id_{extra_id}>;" + ';'.join(note_strs)
            sections.append(section)
        
        return ';'.join(sections)
        
    except Exception as e:
        if DEBUG:
            print(f"  Conversion error: {e}")
        return ""


def start_server():
    """Start the XML-RPC server."""
    if not initialize_mmm():
        print("Warning: MMM initialization failed, server will return fallback responses")
    
    server = SimpleXMLRPCServer(('127.0.0.1', PORT), allow_none=True)
    server.register_function(call_nn_infill, 'call_nn_infill')
    
    print(f"\nMMM Server ready on port {PORT}")
    if MMM_FN_AVAILABLE:
        print("Track options support: ENABLED")
    else:
        print("Track options support: DISABLED (using defaults)")
    
    print("\nWaiting for requests...")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")


if __name__ == '__main__':
    start_server()