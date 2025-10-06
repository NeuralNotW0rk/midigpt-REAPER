#!/usr/bin/env python3
"""
MidiGPT Server - Fixed measure mapping and CA format generation
"""

import os
import sys
from xmlrpc.server import SimpleXMLRPCServer
import tempfile
import json
import re

midi_gpt_path = os.path.join(os.path.dirname(__file__), "../../../MIDI-GPT/python_lib")
if os.path.exists(midi_gpt_path):
    sys.path.insert(0, os.path.abspath(midi_gpt_path))

ca_path = os.path.join(os.path.dirname(__file__), "src/Scripts/composers_assistant_v2")
if os.path.exists(ca_path):
    sys.path.insert(0, os.path.abspath(ca_path))

try:
    import midigpt
    import preprocessing_functions as pre
    import mido
    MIDIGPT_AVAILABLE = True
    print("MidiGPT library loaded successfully")
except ImportError as e:
    MIDIGPT_AVAILABLE = False
    print(f"MidiGPT not available: {e}")

try:
    import rpr_midigpt_functions as midigpt_fn
    PARAM_FUNCTIONS_AVAILABLE = True
    print("Parameter reading functions loaded")
except ImportError as e:
    PARAM_FUNCTIONS_AVAILABLE = False
    print(f"Parameter functions not available: {e}")

DEBUG = True
PORT = 3456

def find_checkpoint():
    possible_paths = [
        "MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        os.path.expanduser("~/Documents/GitHub/midigpt-REAPER/MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt")
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return os.path.abspath(path)
    return possible_paths[0]

CHECKPOINT_PATH = find_checkpoint()
LAST_CALL = None
LAST_OUTPUTS = set()


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
        
        # Extract extra_id if present
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


def apply_track_options_to_status(status_json, track_options_by_idx, global_options):
    """Apply track-specific options from REAPER FX to MidiGPT status."""
    for track_idx, track_config in enumerate(status_json.get('tracks', [])):
        if track_idx in track_options_by_idx:
            options = track_options_by_idx[track_idx]
            track_config['temperature'] = options.track_temperature if options.track_temperature >= 0 else global_options.temperature
            track_config['instrument'] = options.instrument
            track_config['density'] = options.density
            track_config['track_type'] = options.track_type
            track_config['min_polyphony_q'] = options.min_polyphony_q
            track_config['max_polyphony_q'] = options.max_polyphony_q
            track_config['polyphony_hard_limit'] = options.polyphony_hard_limit if options.polyphony_hard_limit > 0 else global_options.polyphony_hard_limit
        else:
            track_config['temperature'] = global_options.temperature
            track_config['polyphony_hard_limit'] = global_options.polyphony_hard_limit


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
                    note_info = active_notes.pop(msg.note)
                    actual_start = int(note_info['start'] * timing_ratio)
                    duration = int((current_time - note_info['start']) * timing_ratio)
                    ai_measure = actual_start // measure_length
                    
                    all_notes.append({
                        'pitch': msg.note,
                        'start': actual_start,
                        'duration': duration,
                        'velocity': note_info['velocity'],
                        'ai_measure': int(ai_measure)
                    })
    
    if not all_notes:
        if DEBUG:
            print("  No notes generated")
        # Return empty section for first extra_id
        first_extra_id = min(extra_id_to_measure.keys()) if extra_id_to_measure else 0
        return f";<extra_id_{first_extra_id}>"
    
    all_notes.sort(key=lambda n: (n['ai_measure'], n['start']))
    
    if DEBUG:
        print(f"  Extracted {len(all_notes)} notes")
        ai_measures = sorted(set(n['ai_measure'] for n in all_notes))
        print(f"  AI measures with notes: {ai_measures}")
    
    # MAP AI MEASURES TO PROJECT MEASURES
    # MidiGPT returns full context, not just generated measures
    # AI measures map to project measures by POSITION, not sequentially
    # E.g., if we're generating project measure 3 in an 8-measure project:
    #   - MidiGPT gets measures 0-3 as context
    #   - Returns AI measures 0-3 (full context)
    #   - AI measure 3 contains the NEW content for project measure 3
    #   - AI measures 0-2 are unchanged context
    
    ai_measures_sorted = sorted(set(n['ai_measure'] for n in all_notes))
    
    # Map AI measures to project measures by position
    # Assume MidiGPT returns measures starting from start_measure
    # This assumes the S structure we sent had measures [start_measure..end_measure]
    measure_map = {}
    for ai_m in ai_measures_sorted:
        # AI measure N corresponds to project measure (start_measure + N)
        project_m = min(project_measures) + ai_m
        if project_m <= max(project_measures):
            measure_map[ai_m] = project_m
    
    if DEBUG:
        print(f"  Measure mapping (AI → Project by position):")
        for ai_m, proj_m in sorted(measure_map.items()):
            note_count = sum(1 for n in all_notes if n['ai_measure'] == ai_m)
            in_gen_set = proj_m in measures_to_generate
            print(f"    {ai_m} → {proj_m} ({note_count} notes) {'[GENERATE]' if in_gen_set else '[CONTEXT]'}")
    
    # Group notes by project measure
    notes_by_measure = {}
    for note in all_notes:
        ai_m = note['ai_measure']
        if ai_m in measure_map:
            project_measure = measure_map[ai_m]
            if project_measure in measures_to_generate:
                if project_measure not in notes_by_measure:
                    notes_by_measure[project_measure] = []
                notes_by_measure[project_measure].append(note)
    
    if not notes_by_measure:
        if DEBUG:
            print("  No notes in target measures")
        first_extra_id = min(extra_id_to_measure.keys()) if extra_id_to_measure else 0
        return f";<extra_id_{first_extra_id}>"
    
    # Build reverse mapping: measure -> extra_id
    measure_to_extra_id = {m: eid for eid, m in extra_id_to_measure.items()}
    
    # Build CA format with separate sections for each extra_id
    sections = []
    
    for measure in sorted(notes_by_measure.keys()):
        extra_id = measure_to_extra_id.get(measure)
        if extra_id is None:
            if DEBUG:
                print(f"  Warning: No extra_id for measure {measure}, skipping")
            continue
        
        measure_notes = sorted(notes_by_measure[measure], key=lambda n: n['start'])
        
        # Build note tokens with timing relative to measure start
        # Notes have absolute positions from AI MIDI, convert to relative within measure
        note_tokens = []
        last_position_in_measure = 0
        
        for note in measure_notes:
            # Calculate position within the measure (0-95 for 96-tick measures)
            position_in_measure = note['start'] % measure_length
            
            # Wait from last note position
            wait = position_in_measure - last_position_in_measure
            if wait > 0:
                note_tokens.append(f"w:{int(wait)}")
            
            note_tokens.append(f"N:{note['pitch']}")
            note_tokens.append(f"d:{int(note['duration'])}")
            
            # Update last position (note start, not end - multiple notes can start simultaneously)
            last_position_in_measure = position_in_measure
        
        # Assemble section
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
                   has_fully_masked_inst=False, temperature=1.0, start_measure=None, end_measure=None):
    """Main function called by REAPER via XMLRPC"""
    global LAST_CALL, LAST_OUTPUTS
    
    temperature = max(0.5, min(2.0, temperature))
    
    if DEBUG:
        print(f"\n{'='*60}")
        print('MIDIGPT CALL_NN_INFILL')
        print(f"  Input: {len(s)} chars")
        print(f"  Temperature: {temperature}")
        if start_measure is not None and end_measure is not None:
            print(f"  Selection: measures {start_measure}-{end_measure}")
    
    try:
        if not MIDIGPT_AVAILABLE:
            return ";M:0;B:5;L:96;<extra_id_0>N:60;d:240;w:240"
        
        if PARAM_FUNCTIONS_AVAILABLE:
            try:
                global_options = midigpt_fn.get_midigpt_global_options()
                track_options = midigpt_fn.get_midigpt_track_options_by_track_idx()
            except Exception as e:
                if DEBUG:
                    print(f"  Using defaults: {e}")
                global_options = create_default_options(temperature)
                track_options = {}
        else:
            global_options = create_default_options(temperature)
            track_options = {}
        
        s_normalized = re.sub(r'<extra_id_\d+>', '<extra_id_0>', s)
        if s_normalized == LAST_CALL or s_normalized in LAST_OUTPUTS:
            if DEBUG:
                print("  Using cached result")
            return ";M:0;B:5;L:96;<extra_id_0>N:60;d:240;w:240"
        
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
        
        encoder = midigpt.ExpressiveEncoder()
        piece_json_str = encoder.midi_to_json(temp_midi_path)
        piece_json = json.loads(piece_json_str)
        
        num_tracks = max(len(piece_json.get('tracks', [])), 1)
        
        status = {'tracks': []}
        for track_idx in range(num_tracks):
            track_config = {
                'track_id': track_idx,
                'temperature': global_options.temperature,
                'instrument': 'acoustic_grand_piano',
                'density': 10,
                'track_type': 'STANDARD_TRACK',
                'ignore': False,
                'selected_bars': [i in measures_to_generate for i in range(len(project_measures))],
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY',
                'autoregressive': False,
                'polyphony_hard_limit': global_options.polyphony_hard_limit
            }
            status['tracks'].append(track_config)
        
        if track_options:
            apply_track_options_to_status(status, track_options, global_options)
        
        params = {
            'tracks_per_step': global_options.tracks_per_step,
            'bars_per_step': global_options.bars_per_step,
            'model_dim': global_options.model_dim,
            'percentage': global_options.percentage,
            'batch_size': global_options.batch_size,
            'temperature': global_options.temperature,
            'max_steps': global_options.max_steps,
            'polyphony_hard_limit': global_options.polyphony_hard_limit,
            'shuffle': global_options.shuffle,
            'verbose': False,
            'ckpt': CHECKPOINT_PATH,
            'sampling_seed': global_options.sampling_seed,
            'mask_top_k': global_options.mask_top_k
        }
        
        if DEBUG:
            print(f"\n=== MIDIGPT GENERATION ===")
            print(f"  Tracks: {num_tracks}")
            print(f"  Generating measures: {sorted(measures_to_generate)}")
        
        status_str = json.dumps(status)
        params_str = json.dumps(params)
        callbacks = midigpt.CallbackManager()
        midi_results = midigpt.sample_multi_step(piece_json_str, status_str, params_str, 3, callbacks)
        
        if not midi_results:
            if DEBUG:
                print("  No results from MidiGPT")
            return f";M:0;B:5;L:96;<extra_id_{actual_extra_id}>N:60;d:240;w:240"
        
        result_json = midi_results[0]
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as tmp:
            result_midi_path = tmp.name
        encoder.json_to_midi(result_json, result_midi_path)
        
        if DEBUG:
            print(f"  Generated {len(result_json)} chars")
        
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
    print("MidiGPT Server - Fixed Mapping & CA Format")
    print("="*60)
    print(f"Port: {PORT}")
    print(f"MidiGPT: {MIDIGPT_AVAILABLE}")
    print(f"Parameters: {PARAM_FUNCTIONS_AVAILABLE}")
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
    start_server()