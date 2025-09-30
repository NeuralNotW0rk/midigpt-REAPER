#!/usr/bin/env python3

import os
import sys
import json
import mido
import tempfile
import traceback
from xmlrpc.server import SimpleXMLRPCServer
from collections import defaultdict
import contextlib

@contextlib.contextmanager
def suppress_stdout():
    """Suppress C++ library stdout output at OS file descriptor level"""
    # Save the original file descriptors
    stdout_fd = sys.stdout.fileno()
    stderr_fd = sys.stderr.fileno()
    
    # Create copies of the original descriptors
    stdout_copy = os.dup(stdout_fd)
    stderr_copy = os.dup(stderr_fd)
    
    try:
        # Open devnull and redirect stdout/stderr to it at OS level
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, stdout_fd)
        os.dup2(devnull_fd, stderr_fd)
        os.close(devnull_fd)
        
        yield
    finally:
        # Restore the original descriptors
        os.dup2(stdout_copy, stdout_fd)
        os.dup2(stderr_copy, stderr_fd)
        os.close(stdout_copy)
        os.close(stderr_copy)

# Debug flag
DEBUG = True

# Check for MidiGPT availability
MIDIGPT_AVAILABLE = False
try:
    import midigpt
    MIDIGPT_AVAILABLE = True
    if DEBUG:
        print("✓ MidiGPT library available")
except ImportError as e:
    if DEBUG:
        print(f"✗ MidiGPT library not available: {e}")
    raise RuntimeError(f"MidiGPT library required but not available: {e}")

# Check for mido
try:
    import mido
    if DEBUG:
        print("✓ Mido library available")
except ImportError as e:
    if DEBUG:
        print(f"✗ Mido library not available: {e}")
    raise RuntimeError(f"Mido library required but not available: {e}")

# Import preprocessing functions
try:
    import preprocessing_functions as pre
    if DEBUG:
        print("✓ Preprocessing functions loaded")
except ImportError as e:
    if DEBUG:
        print(f"✗ Could not load preprocessing functions: {e}")
    raise RuntimeError(f"Preprocessing functions required but not available: {e}")

class TimingMap:
    """Captures timing structure and intent from original CA format - MODEL AGNOSTIC"""
    
    def __init__(self, ca_string, project_measures):
        self.project_start_measure = min(project_measures) if project_measures else 0
        self.project_end_measure = max(project_measures) if project_measures else 3
        self.project_total_measures = len(project_measures)
        self.notes_by_measure = defaultdict(list)
        self.measure_positions = {}
        self.extra_ids = []
        self.original_ca_string = ca_string
        
        self._parse_ca_structure(ca_string)
    
    def _parse_ca_structure(self, ca_string):
        """Parse CA format to extract timing structure"""
        if DEBUG:
            print(f"\n=== TIMING MAP CREATION ===")
            print(f"Project measures: {self.project_start_measure} to {self.project_end_measure} ({self.project_total_measures} total)")
        
        segments = ca_string.split(';')
        current_measure = self.project_start_measure
        
        for segment in segments:
            if not segment:
                continue
            
            if segment.startswith('M:'):
                current_measure = int(segment[2:])
                if current_measure not in self.measure_positions:
                    self.measure_positions[current_measure] = len(self.measure_positions)
            
            elif segment.startswith('<extra_id_'):
                self.extra_ids.append(segment)
        
        if DEBUG:
            print(f"Measures in input: {sorted(self.measure_positions.keys())}")
            print(f"Extra IDs found: {len(self.extra_ids)}")
            print("=== END TIMING MAP ===\n")

def parse_ca_string_to_midi(ca_string, timing_map):
    """Parse CA format from REAPER and convert to MIDI - preserving timing"""
    
    if not ca_string:
        raise ValueError("CA string cannot be empty")
    
    if DEBUG:
        print(f"=== PARSING REAPER CA FORMAT ===")
        print(f"Input: {len(ca_string)} characters")
    
    midi_file = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    
    segments = ca_string.split(';')
    events = []
    
    current_measure = 0
    current_duration = 480
    current_position_in_measure = 0
    notes_to_add = []
    ticks_per_measure = 1920
    
    for segment in segments:
        if not segment or segment.startswith('<extra_id_'):
            continue
        
        if segment.startswith('M:'):
            if notes_to_add:
                absolute_time = current_measure * ticks_per_measure + current_position_in_measure
                for note_pitch in notes_to_add:
                    events.append((absolute_time, 'note_on', {'note': note_pitch, 'velocity': 80}))
                for note_pitch in notes_to_add:
                    events.append((absolute_time + current_duration, 'note_off', {'note': note_pitch, 'velocity': 0}))
                notes_to_add = []
            
            current_measure = int(segment[2:])
            current_position_in_measure = 0
        
        elif segment.startswith('d:'):
            current_duration = int(segment[2:])
        
        elif segment.startswith('N:'):
            pitch = int(segment[2:])
            if 0 <= pitch <= 127:
                notes_to_add.append(pitch)
        
        elif segment.startswith('w:'):
            wait_time = int(segment[2:])
            
            if notes_to_add:
                absolute_time = current_measure * ticks_per_measure + current_position_in_measure
                for note_pitch in notes_to_add:
                    events.append((absolute_time, 'note_on', {'note': note_pitch, 'velocity': 80}))
                for note_pitch in notes_to_add:
                    events.append((absolute_time + current_duration, 'note_off', {'note': note_pitch, 'velocity': 0}))
                notes_to_add = []
            
            current_position_in_measure += wait_time
    
    if notes_to_add:
        absolute_time = current_measure * ticks_per_measure + current_position_in_measure
        for note_pitch in notes_to_add:
            events.append((absolute_time, 'note_on', {'note': note_pitch, 'velocity': 80}))
        for note_pitch in notes_to_add:
            events.append((absolute_time + current_duration, 'note_off', {'note': note_pitch, 'velocity': 0}))
    
    events.sort(key=lambda x: (x[0], 0 if x[1] == 'note_on' else 1))
    
    last_time = 0
    for absolute_time, event_type, data in events:
        delta_time = absolute_time - last_time
        if delta_time < 0:
            raise ValueError(f"Negative time delta: {delta_time} at time {absolute_time}")
        
        if event_type == 'note_on':
            track.append(mido.Message('note_on', channel=0, note=data['note'], 
                                     velocity=data['velocity'], time=delta_time))
        elif event_type == 'note_off':
            track.append(mido.Message('note_off', channel=0, note=data['note'], 
                                     velocity=data['velocity'], time=delta_time))
        
        last_time = absolute_time
    
    track.append(mido.MetaMessage('end_of_track', time=0))
    
    note_ons = [msg for msg in track if msg.type == 'note_on' and msg.velocity > 0]
    if not note_ons:
        raise ValueError("No notes extracted from CA string")
    
    pitches = set(msg.note for msg in note_ons)
    
    if DEBUG:
        print(f"Parsed REAPER content:")
        print(f"  Note events: {len(note_ons)}")
        print(f"  Unique pitches: {sorted(pitches)}")
        print("=== END CA PARSING ===\n")
    
    return midi_file

def find_model_checkpoint():
    """Find MidiGPT model checkpoint"""
    possible_paths = [
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "/Users/griffinpage/Documents/GitHub/midigpt-REAPER/MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"
    ]
    
    for path in possible_paths:
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path):
            if DEBUG:
                print(f"✓ Found model checkpoint: {abs_path}")
            return abs_path
    
    raise FileNotFoundError(
        f"MidiGPT model checkpoint not found. Searched paths:\n" + 
        "\n".join(f"  - {path}" for path in possible_paths)
    )

def process_with_midigpt(midi_file, timing_map, temperature=1.0):
    """Process MIDI with MidiGPT - MODEL AGNOSTIC PROCESSING"""
    
    if not midi_file or not midi_file.tracks:
        raise ValueError("Invalid MIDI file for processing")
    
    with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as temp_input:
        midi_file.save(temp_input.name)
        input_path = temp_input.name
    
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Failed to create temporary MIDI file: {input_path}")
    
    if DEBUG:
        print(f"Saved input MIDI to: {input_path}")
    
    try:
        encoder = midigpt.ExpressiveEncoder()
        if DEBUG:
            print("✓ MidiGPT ExpressiveEncoder initialized")
        
        json_str = encoder.midi_to_json(input_path)
        if not json_str:
            raise ValueError("MidiGPT encoder returned empty JSON")
        
        json_data = json.loads(json_str)
        
        if DEBUG:
            print(f"✓ Converted to JSON: {len(json_str)} characters")
        
        status_data = {
            'tracks': [{
                'track_id': 0,
                'temperature': temperature,
                'instrument': 'acoustic_grand_piano',
                'density': 10,
                'track_type': 10,
                'ignore': False,
                'selected_bars': [True] * timing_map.project_total_measures,
                'min_polyphony_q': 'POLYPHONY_ANY',
                'max_polyphony_q': 'POLYPHONY_ANY',
                'autoregressive': False,
                'polyphony_hard_limit': 9
            }]
        }
        
        model_path = find_model_checkpoint()
        default_params = json.loads(midigpt.default_sample_param())
        default_params.update({
            'temperature': temperature,
            'ckpt': model_path,
            'verbose': False
        })
        
        if DEBUG:
            print(f"Model checkpoint: {model_path}")
        
        piece_str = json.dumps(json_data)
        status_str = json.dumps(status_data)
        params_str = json.dumps(default_params)
        
        callbacks = midigpt.CallbackManager()
        
        if DEBUG:
            print("Generating with MidiGPT...")
        
        with suppress_stdout():
            results = midigpt.sample_multi_step(piece_str, status_str, params_str, 3, callbacks)
        
        if DEBUG:
            print(f"Generation complete: {len(results[0])} characters")
        
        if not results or not results[0]:
            raise RuntimeError("MidiGPT returned empty results")
        
        if DEBUG:
            print(f"✓ MidiGPT generation successful: {len(results[0])} characters")
        
        result_json_str = results[0]
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as temp_output:
            encoder.json_to_midi(result_json_str, temp_output.name)
            output_path = temp_output.name
        
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"MidiGPT failed to create output: {output_path}")
        
        generated_midi = mido.MidiFile(output_path)
        if not generated_midi.tracks:
            raise ValueError("Generated MIDI has no tracks")
        
        if DEBUG:
            print(f"✓ Generated MIDI: {len(generated_midi.tracks)} tracks")
        
        os.unlink(input_path)
        os.unlink(output_path)
        
        return generated_midi
        
    except Exception as e:
        if os.path.exists(input_path):
            os.unlink(input_path)
        if DEBUG:
            print(f"MidiGPT processing failed: {e}")
            traceback.print_exc()
        raise e

def restore_original_timing_structure(generated_midi, original_timing_map):
    """
    TIMING PRESERVATION LAYER - MODEL AGNOSTIC
    Maps AI-generated content back to original REAPER project timing
    """
    
    if DEBUG:
        print(f"\n=== TIMING RESTORATION ===")
        print(f"Target: measures {original_timing_map.project_start_measure}-{original_timing_map.project_end_measure}")
    
    generated_notes = []
    
    for track_idx, track in enumerate(generated_midi.tracks):
        current_time = 0
        active_notes = {}
        
        for msg in track:
            current_time += msg.time
            
            if msg.type == 'note_on' and msg.velocity > 0:
                active_notes[msg.note] = {
                    'start': current_time,
                    'velocity': msg.velocity
                }
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active_notes:
                    note_info = active_notes.pop(msg.note)
                    duration = current_time - note_info['start']
                    
                    if duration > 0:
                        generated_notes.append({
                            'pitch': msg.note,
                            'start_time': note_info['start'],
                            'duration': duration,
                            'velocity': note_info['velocity']
                        })
    
    if not generated_notes:
        raise ValueError("No notes extracted from generated MIDI")
    
    project_start = original_timing_map.project_start_measure
    project_end = original_timing_map.project_end_measure
    project_range = project_end - project_start + 1
    ticks_per_measure = 1920
    project_duration_ticks = project_range * ticks_per_measure
    
    notes_by_project_measure = defaultdict(list)
    
    for note in generated_notes:
        if project_duration_ticks > 0:
            relative_position = (note['start_time'] % project_duration_ticks) / project_duration_ticks
            target_measure = project_start + int(relative_position * project_range)
        else:
            target_measure = project_start
        
        target_measure = max(project_start, min(project_end, target_measure))
        
        notes_by_project_measure[target_measure].append({
            'pitch': note['pitch'],
            'duration': max(240, min(1920, int(note['duration']))),
            'velocity': note['velocity']
        })
    
    ca_parts = []
    
    for measure in sorted(notes_by_project_measure.keys()):
        measure_notes = notes_by_project_measure[measure]
        
        ca_parts.extend([
            f"M:{measure}",
            "B:5",
            "L:96",
            "I:0"
        ])
        
        for i, note in enumerate(measure_notes):
            if i > 0:
                ca_parts.append(f"w:{note['duration']}")
            ca_parts.extend([
                f"N:{note['pitch']}",
                f"d:{note['duration']}"
            ])
    
    result_ca = ";" + ";".join(ca_parts) + ";"
    
    while ";;" in result_ca:
        result_ca = result_ca.replace(";;", ";")
    
    if not result_ca.startswith(';') or not result_ca.endswith(';'):
        raise ValueError("Invalid CA format structure")
    
    if DEBUG:
        print(f"Mapped {len(generated_notes)} notes to measures: {sorted(notes_by_project_measure.keys())}")
        print(f"Final CA result: {len(result_ca)} characters")
        print(f"Preview: {result_ca[:200]}...")
        print("=== END TIMING RESTORATION ===\n")
    
    return result_ca

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0):
    """
    TIMING-PRESERVING MODEL-AGNOSTIC GENERATION
    Preserves timing relationships between REAPER and AI coordinate systems
    """
    
    if DEBUG:
        print(f"\n{'='*60}")
        print(f"TIMING-PRESERVING MIDIGPT GENERATION")
        print(f"{'='*60}")
        print(f"\nRAW INPUT 's' STRING:")
        print(f"{s}")
        print(f"\nPARSING 's' STRING:")
        segments = s.split(';')
        measures_found = [seg for seg in segments if seg.startswith('M:')]
        notes_found = [seg for seg in segments if seg.startswith('N:')]
        extra_ids_found = [seg for seg in segments if 'extra_id' in seg]
        print(f"  Measures with M: tags: {measures_found}")
        print(f"  Total notes: {len(notes_found)}")
        print(f"  Extra IDs: {extra_ids_found}")
        print()
    
    if s is None or not isinstance(s, str) or len(s) == 0:
        raise ValueError("Invalid input parameter 's'")
    
    if S is None:
        raise ValueError("Invalid input parameter 'S'")
    
    try:
        # Convert S parameter if it's a dictionary
        s_was_dict = hasattr(S, 'keys')
        if s_was_dict:
            if DEBUG:
                print("Converting S parameter from dictionary")
            S = pre.midisongbymeasure_from_save_dict(S)
        
        if DEBUG:
            print(f"\n=== S PARAMETER ANALYSIS ===")
            print(f"S type: {type(S)}")
            print(f"S was dictionary: {s_was_dict}")
            
            if hasattr(S, '__dict__'):
                print(f"S attributes: {list(S.__dict__.keys())[:20]}")
            
            if hasattr(S, 'tracks'):
                print(f"Number of tracks: {len(S.tracks)}")
                if S.tracks:
                    track = S.tracks[0]
                    print(f"Track type: {type(track)}")
                    track_attrs = [a for a in dir(track) if not a.startswith('_')]
                    print(f"Track attributes: {track_attrs[:20]}")
                    
                    if hasattr(track, 'tracks_by_measure'):
                        tbm = track.tracks_by_measure
                        print(f"tracks_by_measure type: {type(tbm)}")
                        
                        if isinstance(tbm, dict):
                            print(f"Total measures in track: {len(tbm)}")
                            measure_keys = list(tbm.keys())
                            print(f"Measure indices: {measure_keys[:15]}")
                            if measure_keys:
                                print(f"First measure: {min(measure_keys)}")
                                print(f"Last measure: {max(measure_keys)}")
                        elif isinstance(tbm, list):
                            print(f"Total measures in track (list): {len(tbm)}")
                            print(f"Measure range: 0 to {len(tbm)-1}")
                        else:
                            print(f"tracks_by_measure is neither dict nor list: {type(tbm)}")
            else:
                print(f"S has no 'tracks' attribute")
                print(f"S dir: {[a for a in dir(S) if not a.startswith('_')][:20]}")
            
            print(f"=== END S PARAMETER ===\n")
        
        # QUICK FIX: Extract actual selection range from measures in s string
        measure_numbers = []
        for segment in s.split(';'):
            if segment.startswith('M:'):
                try:
                    measure_numbers.append(int(segment[2:]))
                except ValueError:
                    pass
        
        unique_measures = sorted(set(measure_numbers))
        
        if unique_measures:
            selection_start = min(unique_measures)
            selection_end = max(unique_measures)
            # Create contiguous range from min to max
            project_measures = list(range(selection_start, selection_end + 1))
            
            if DEBUG:
                print(f"=== SELECTION RANGE EXTRACTION ===")
                print(f"Measures found in s string: {unique_measures}")
                print(f"Inferred selection: {selection_start} to {selection_end}")
                print(f"Using measure range: {project_measures}")
                print(f"=== END SELECTION RANGE ===\n")
        else:
            # Fallback to S parameter if no measures in s string
            if S and hasattr(S, 'tracks') and S.tracks:
                track = S.tracks[0]
                if hasattr(track, 'tracks_by_measure'):
                    tbm = track.tracks_by_measure
                    if isinstance(tbm, dict):
                        num_measures = len(tbm)
                    elif isinstance(tbm, list):
                        num_measures = len(tbm)
                    else:
                        num_measures = 4
                else:
                    num_measures = 4
                project_measures = list(range(num_measures))
            else:
                project_measures = [0, 1, 2, 3]
            
            if DEBUG:
                print(f"No measures found in s string, using S parameter: {project_measures}")
        
        timing_map = TimingMap(s, project_measures)
        input_midi = parse_ca_string_to_midi(s, timing_map)
        generated_midi = process_with_midigpt(input_midi, timing_map, temperature)
        result_ca = restore_original_timing_structure(generated_midi, timing_map)
        
        if DEBUG:
            print(f"✓ Generation complete: {len(result_ca)} chars")
            print(f"{'='*60}\n")
        
        return result_ca
        
    except Exception as e:
        if DEBUG:
            print(f"Error in timing-preserving generation: {e}")
            traceback.print_exc()
        raise e

def main():
    """Start timing-preserving MidiGPT server"""
    
    if not MIDIGPT_AVAILABLE:
        raise RuntimeError("MidiGPT not available")
    
    try:
        find_model_checkpoint()
    except FileNotFoundError as e:
        raise RuntimeError(f"Cannot start server: {e}")
    
    with SimpleXMLRPCServer(('127.0.0.1', 3456), allow_none=True) as server:
        server.register_function(call_nn_infill, 'call_nn_infill')
        
        print("Timing-Preserving MidiGPT Server running on http://127.0.0.1:3456")
        print("✓ Model-agnostic timing preservation enabled")
        print("✓ REAPER measure ↔ AI time coordinate mapping active")
        print("Ready to process requests")
        
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped")
        except Exception as e:
            print(f"Server error: {e}")
            raise e

if __name__ == "__main__":
    main()