#!/usr/bin/env python3

import os
import sys
import json
import mido
import tempfile
import traceback
from xmlrpc.server import SimpleXMLRPCServer
from collections import defaultdict

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
    
    # Track all events with their absolute times, then sort and convert to deltas
    events = []  # List of (absolute_time, event_type, data)
    
    current_measure = 0
    current_duration = 480
    current_position_in_measure = 0
    notes_to_add = []
    
    ticks_per_measure = 1920
    
    for segment in segments:
        if not segment or segment.startswith('<extra_id_'):
            continue
        
        if segment.startswith('M:'):
            # Flush pending notes before changing measure
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
    
    # Flush remaining notes
    if notes_to_add:
        absolute_time = current_measure * ticks_per_measure + current_position_in_measure
        for note_pitch in notes_to_add:
            events.append((absolute_time, 'note_on', {'note': note_pitch, 'velocity': 80}))
        for note_pitch in notes_to_add:
            events.append((absolute_time + current_duration, 'note_off', {'note': note_pitch, 'velocity': 0}))
    
    # Sort events by absolute time
    events.sort(key=lambda x: (x[0], 0 if x[1] == 'note_on' else 1))
    
    # Convert to delta times and add to track
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
            'ckpt': model_path
        })
        
        if DEBUG:
            print(f"Model checkpoint: {model_path}")
        
        piece_str = json.dumps(json_data)
        status_str = json.dumps(status_data)
        params_str = json.dumps(default_params)
        
        callbacks = midigpt.CallbackManager()
        results = midigpt.sample_multi_step(piece_str, status_str, params_str, 3, callbacks)
        
        if not results or not results[0]:
            raise RuntimeError("MidiGPT returned empty results")
        
        if DEBUG:
            print(f"✅ MidiGPT generation successful: {len(results[0])} characters")
        
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
    
    # Extract all notes from generated MIDI
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
    
    # Map notes back to original project timing using modulo arithmetic
    project_start = original_timing_map.project_start_measure
    project_end = original_timing_map.project_end_measure
    project_range = project_end - project_start + 1
    ticks_per_measure = 1920
    project_duration_ticks = project_range * ticks_per_measure
    
    notes_by_project_measure = defaultdict(list)
    
    for note in generated_notes:
        # Wrap generated content into project range
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
    
    # Convert to CA format
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
    
    if s is None or not isinstance(s, str) or len(s) == 0:
        raise ValueError("Invalid input parameter 's'")
    
    if S is None:
        raise ValueError("Invalid input parameter 'S'")
    
    try:
        # Convert S parameter if needed
        if hasattr(S, 'keys'):
            if DEBUG:
                print("Converting S parameter from dictionary")
            S = pre.midisongbymeasure_from_save_dict(S)
        
        # Extract project measures
        if S and S.tracks:
            num_measures = len(S.tracks[0].tracks_by_measure)
            project_measures = list(range(num_measures))
        else:
            project_measures = [0, 1, 2, 3]
        
        # STEP 1: Create timing map (captures original REAPER context)
        timing_map = TimingMap(s, project_measures)
        
        # STEP 2: Parse REAPER content to MIDI
        input_midi = parse_ca_string_to_midi(s, timing_map)
        
        # STEP 3: Process with AI model (works in its own timing space)
        generated_midi = process_with_midigpt(input_midi, timing_map, temperature)
        
        # STEP 4: Restore original timing structure (map back to REAPER measures)
        result_ca = restore_original_timing_structure(generated_midi, timing_map)
        
        if DEBUG:
            print(f"✓ Generation complete: {len(result_ca)} chars")
            print(f"{'='*60}\n")
        
        return result_ca
        
    except Exception as e:
        if DEBUG:
            print(f"❌ Error in timing-preserving generation: {e}")
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
    """Stores timing relationships for project measures"""
    def __init__(self):
        self.project_start_measure = 0
        self.project_end_measure = 0
        self.project_total_measures = 0
        self.measure_to_tick = {}
        self.tick_to_measure = {}
        self.extra_id_positions = {}

def extract_timing_from_s_parameter(s_param):
    """Extract timing information from S parameter object"""
    timing_map = TimingMap()
    
    if not s_param:
        raise ValueError("S parameter cannot be None")
    
    try:
        # Convert dictionary to MidiSongByMeasure object if needed
        if hasattr(s_param, 'keys'):
            if DEBUG:
                print("Converting S parameter from dictionary to MidiSongByMeasure")
            s_param = pre.midisongbymeasure_from_save_dict(s_param)
        
        # Validate the converted object
        if not hasattr(s_param, 'tracks'):
            raise AttributeError(f"S parameter object missing 'tracks' attribute. Available attributes: {dir(s_param)}")
        
        if not s_param.tracks:
            raise ValueError("S parameter has no tracks")
        
        # Get measure endpoints to determine project length
        if hasattr(s_param, 'get_measure_endpoints'):
            measure_endpoints = s_param.get_measure_endpoints()
            timing_map.project_total_measures = len(measure_endpoints) - 1  # endpoints define measure boundaries
        elif hasattr(s_param, 'measure_endpoints'):
            measure_endpoints = s_param.measure_endpoints
            timing_map.project_total_measures = len(measure_endpoints) - 1
        else:
            # Fallback: get measures from first track if available
            first_track = s_param.tracks[0]
            if hasattr(first_track, 'tracks_by_measure'):
                timing_map.project_total_measures = len(first_track.tracks_by_measure)
            else:
                raise AttributeError("Cannot determine project length from S parameter structure")
        
        if timing_map.project_total_measures <= 0:
            raise ValueError(f"Invalid project length: {timing_map.project_total_measures} measures")
        
        timing_map.project_start_measure = 0
        timing_map.project_end_measure = timing_map.project_total_measures - 1
        
        if DEBUG:
            print(f"Project timing: {timing_map.project_total_measures} measures")
            print(f"S parameter type: {type(s_param)}")
            print(f"Number of tracks: {len(s_param.tracks)}")
        
        # Create measure-to-tick mapping
        ticks_per_measure = 1920  # Standard MIDI resolution
        for measure in range(timing_map.project_total_measures):
            tick = measure * ticks_per_measure
            timing_map.measure_to_tick[measure] = tick
            timing_map.tick_to_measure[tick] = measure
            
    except Exception as e:
        if DEBUG:
            print(f"Error extracting timing from S parameter: {e}")
            print(f"S parameter type: {type(s_param)}")
            if hasattr(s_param, '__dict__'):
                print(f"S parameter attributes: {list(s_param.__dict__.keys())}")
        raise ValueError(f"Failed to extract timing information from S parameter: {e}")
    
    return timing_map

def parse_ca_string_to_midi(ca_string, timing_map):
    """Parse CA format string from REAPER and convert to MIDI file"""
    
    if not ca_string:
        raise ValueError("CA string cannot be empty")
    
    if DEBUG:
        print(f"\n=== PARSING REAPER CA FORMAT ===")
        print(f"Input: {len(ca_string)} characters")
    
    # Create MIDI file
    midi_file = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    
    # Add headers
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    
    # Parse CA format
    segments = ca_string.split(';')
    
    current_measure = 0
    current_duration = 480  # Default quarter note
    current_position = 0  # Position within current measure
    notes_to_add = []  # Accumulate notes at same position
    
    measure_start_ticks = {}  # Track absolute tick position of each measure
    ticks_per_measure = 1920  # 4/4 time signature
    
    for segment in segments:
        if not segment or segment.startswith('<extra_id_'):
            continue
            
        if segment.startswith('M:'):
            # New measure - flush any pending notes
            if notes_to_add:
                for note_pitch in notes_to_add:
                    abs_time = measure_start_ticks.get(current_measure, current_measure * ticks_per_measure) + current_position
                    track.append(mido.Message('note_on', channel=0, note=note_pitch, velocity=80, 
                                            time=abs_time if len([m for m in track if m.type == 'note_on']) == 0 else 0))
                
                for note_pitch in notes_to_add:
                    track.append(mido.Message('note_off', channel=0, note=note_pitch, velocity=0, 
                                            time=current_duration if notes_to_add.index(note_pitch) == 0 else 0))
                notes_to_add = []
            
            # Update measure
            current_measure = int(segment[2:])
            measure_start_ticks[current_measure] = current_measure * ticks_per_measure
            current_position = 0
            
        elif segment.startswith('B:'):
            pass  # Beat subdivision - informational
            
        elif segment.startswith('L:'):
            pass  # Length parameter - informational
            
        elif segment.startswith('I:'):
            pass  # Instrument - informational
            
        elif segment.startswith('d:'):
            # Duration for following notes
            current_duration = int(segment[2:])
            
        elif segment.startswith('N:'):
            # Note pitch - accumulate with same duration
            pitch = int(segment[2:])
            if 0 <= pitch <= 127:
                notes_to_add.append(pitch)
            
        elif segment.startswith('w:'):
            # Wait time - advance position and flush notes
            wait_time = int(segment[2:])
            
            if notes_to_add:
                abs_time = measure_start_ticks.get(current_measure, current_measure * ticks_per_measure) + current_position
                
                # Add note ons
                for i, note_pitch in enumerate(notes_to_add):
                    track.append(mido.Message('note_on', channel=0, note=note_pitch, velocity=80, 
                                            time=abs_time if i == 0 and len([m for m in track if m.type == 'note_on']) > 0 else 0))
                
                # Add note offs after duration
                for i, note_pitch in enumerate(notes_to_add):
                    track.append(mido.Message('note_off', channel=0, note=note_pitch, velocity=0, 
                                            time=current_duration if i == 0 else 0))
                
                notes_to_add = []
            
            current_position += wait_time
    
    # Flush any remaining notes
    if notes_to_add:
        abs_time = measure_start_ticks.get(current_measure, current_measure * ticks_per_measure) + current_position
        for i, note_pitch in enumerate(notes_to_add):
            track.append(mido.Message('note_on', channel=0, note=note_pitch, velocity=80, 
                                    time=abs_time if i == 0 else 0))
        for i, note_pitch in enumerate(notes_to_add):
            track.append(mido.Message('note_off', channel=0, note=note_pitch, velocity=0, 
                                    time=current_duration if i == 0 else 0))
    
    # Add end of track
    track.append(mido.MetaMessage('end_of_track', time=0))
    
    # Validate created MIDI
    note_ons = [msg for msg in track if msg.type == 'note_on' and msg.velocity > 0]
    if not note_ons:
        raise ValueError("No notes extracted from CA string")
    
    pitches = set(msg.note for msg in note_ons)
    
    if DEBUG:
        print(f"Parsed REAPER content:")
        print(f"  MIDI messages: {len(track)}")
        print(f"  Note events: {len(note_ons)}")
        print(f"  Unique pitches: {sorted(pitches)}")
        print(f"  Measures processed: {len(measure_start_ticks)}")
        print("=== END CA PARSING ===\n")
    
    return midi_file
    """Create MIDI structure for infill generation with rich musical context"""
    
    if not input_string:
        raise ValueError("Input string cannot be empty")
    
    # Validate timing map
    if timing_map.project_total_measures <= 0:
        raise ValueError(f"Invalid project measures: {timing_map.project_total_measures}")
    
    # Create MIDI file structure
    midi_file = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    
    # Add required MIDI headers
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    
    # Extract extra_id tokens from input
    extra_id_count = input_string.count('<extra_id_')
    if extra_id_count == 0:
        raise ValueError("No <extra_id_> tokens found in input string - cannot perform infill")
    
    if DEBUG:
        print(f"Creating infill structure with {extra_id_count} extra_id tokens for {timing_map.project_total_measures} measures")
    
    # Create a richer musical context to guide MidiGPT generation
    # Use a varied seed pattern across multiple octaves and note durations
    
    # Define seed patterns - varied pitches to encourage diverse output
    seed_patterns = [
        [60, 64, 67],      # C major triad (C4, E4, G4)
        [62, 65, 69],      # D minor triad (D4, F4, A4)
        [64, 67, 71],      # E minor triad (E4, G4, B4)
        [65, 69, 72],      # F major triad (F4, A4, C5)
        [67, 71, 74],      # G major triad (G4, B4, D5)
        [69, 72, 76],      # A minor triad (A4, C5, E5)
        [71, 74, 77],      # B diminished (B4, D5, F5)
        [72, 76, 79]       # C major octave (C5, E5, G5)
    ]
    
    current_time = 0
    ticks_per_measure = 1920
    
    # For each measure, add context notes
    for measure_idx in range(timing_map.project_total_measures):
        measure_start = measure_idx * ticks_per_measure
        
        # Select pattern based on measure index (cycle through patterns)
        pattern = seed_patterns[measure_idx % len(seed_patterns)]
        
        # Add chord notes at measure start (short duration for context)
        for i, pitch in enumerate(pattern):
            note_start = measure_start if i == 0 else 0
            track.append(mido.Message('note_on', channel=0, note=pitch, velocity=60, time=note_start))
        
        # Add note offs after a short duration (quarter note = 480 ticks)
        for i, pitch in enumerate(pattern):
            time_delta = 480 if i == 0 else 0
            track.append(mido.Message('note_off', channel=0, note=pitch, velocity=0, time=time_delta))
        
        # Add some variation within the measure (8th notes)
        remaining_time = ticks_per_measure - 480
        note_duration = 240  # 8th note
        
        # Add 2-3 more notes within the measure for variety
        for i in range(3):
            # Use notes from current and next pattern for smooth transitions
            next_pattern = seed_patterns[(measure_idx + 1) % len(seed_patterns)]
            pitch = pattern[i % len(pattern)] if i < 2 else next_pattern[0]
            
            wait_time = note_duration if i > 0 else (remaining_time - note_duration * 3)
            track.append(mido.Message('note_on', channel=0, note=pitch, velocity=50, time=wait_time))
            track.append(mido.Message('note_off', channel=0, note=pitch, velocity=0, time=note_duration))
    
    # Add final end marker
    track.append(mido.MetaMessage('end_of_track', time=240))
    
    # Validate created MIDI structure
    if len(track) < 10:  # Should have many more messages now
        raise ValueError("Created MIDI structure is invalid - insufficient messages")
    
    total_time = sum(msg.time for msg in track)
    if total_time < ticks_per_measure:  # Should span at least one measure
        raise ValueError(f"Created MIDI duration too short: {total_time} ticks")
    
    if DEBUG:
        # Count note variety in created structure
        note_ons = [msg for msg in track if msg.type == 'note_on' and msg.velocity > 0]
        pitches_used = set(msg.note for msg in note_ons)
        
        print(f"Created infill MIDI structure:")
        print(f"  Messages: {len(track)}")
        print(f"  Total ticks: {total_time}")
        print(f"  Note events: {len(note_ons)}")
        print(f"  Pitch variety: {len(pitches_used)} unique pitches: {sorted(pitches_used)}")
        print(f"  Extra ID tokens: {extra_id_count}")
    
    return midi_file

def find_model_checkpoint():
    """Find MidiGPT model checkpoint - FAIL FAST VERSION"""
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
    
    # NO FALLBACK - fail immediately with clear error
    raise FileNotFoundError(
        f"MidiGPT model checkpoint not found. Searched paths:\n" + 
        "\n".join(f"  - {path}" for path in possible_paths) +
        "\n\nEnsure the model checkpoint is downloaded and unzipped."
    )

def process_with_midigpt(midi_file, timing_map, temperature=1.0):
    """Process MIDI file with MidiGPT - FAIL FAST VERSION"""
    
    # Validate inputs
    if not midi_file:
        raise ValueError("MIDI file cannot be None")
    
    if not midi_file.tracks:
        raise ValueError("MIDI file has no tracks")
    
    if timing_map.project_total_measures <= 0:
        raise ValueError(f"Invalid timing map: {timing_map.project_total_measures} measures")
    
    # Save input MIDI temporarily
    with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as temp_input:
        midi_file.save(temp_input.name)
        input_path = temp_input.name
    
    # Validate file was created
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Failed to create temporary MIDI file: {input_path}")
    
    if DEBUG:
        print(f"Saved input MIDI to: {input_path}")
    
    try:
        # Initialize MidiGPT encoder
        encoder = midigpt.ExpressiveEncoder()
        if DEBUG:
            print("✓ MidiGPT ExpressiveEncoder initialized")
        
        # Convert MIDI to MidiGPT JSON format
        json_str = encoder.midi_to_json(input_path)
        if not json_str:
            raise ValueError("MidiGPT encoder returned empty JSON string")
        
        json_data = json.loads(json_str)
        if not isinstance(json_data, dict):
            raise ValueError(f"Expected JSON dict, got {type(json_data)}")
        
        if DEBUG:
            print(f"✓ Converted to JSON: {len(json_str)} characters")
        
        # Create status configuration
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
        
        # Get model checkpoint path
        model_path = find_model_checkpoint()  # This will fail fast if not found
        
        # Get default parameters and update with our requirements
        default_params = json.loads(midigpt.default_sample_param())
        default_params.update({
            'temperature': temperature,
            'ckpt': model_path
        })
        
        if DEBUG:
            print(f"Using parameters: {list(default_params.keys())}")
            print(f"Model checkpoint: {model_path}")
        
        # Run MidiGPT generation
        piece_str = json.dumps(json_data)
        status_str = json.dumps(status_data)
        params_str = json.dumps(default_params)
        
        callbacks = midigpt.CallbackManager()
        results = midigpt.sample_multi_step(piece_str, status_str, params_str, 3, callbacks)
        
        # Validate results
        if not results:
            raise RuntimeError("MidiGPT sample_multi_step returned empty results")
        
        if not results[0]:
            raise RuntimeError("MidiGPT returned empty first result")
        
        if DEBUG:
            print(f"✅ MidiGPT generation successful: {len(results[0])} characters")
        
        # Convert result back to MIDI
        result_json_str = results[0]
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as temp_output:
            encoder.json_to_midi(result_json_str, temp_output.name)
            output_path = temp_output.name
        
        # Validate output file was created
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"MidiGPT failed to create output file: {output_path}")
        
        # Load and validate generated MIDI
        generated_midi = mido.MidiFile(output_path)
        if not generated_midi.tracks:
            raise ValueError("Generated MIDI file has no tracks")
        
        if DEBUG:
            print(f"✓ Generated MIDI: {len(generated_midi.tracks)} tracks")
            
            # DEBUG: Examine what MidiGPT actually generated
            print(f"\n=== MIDIGPT OUTPUT ANALYSIS ===")
            total_notes = 0
            all_pitches = set()
            
            for track_idx, track in enumerate(generated_midi.tracks):
                note_count = 0
                track_pitches = set()
                
                for msg in track:
                    if msg.type == 'note_on' and msg.velocity > 0:
                        note_count += 1
                        total_notes += 1
                        track_pitches.add(msg.note)
                        all_pitches.add(msg.note)
                
                if note_count > 0:
                    print(f"Track {track_idx}: {note_count} notes, pitches: {sorted(track_pitches)}")
            
            print(f"TOTAL: {total_notes} note events across all tracks")
            print(f"Pitch variety: {len(all_pitches)} unique pitches: {sorted(all_pitches)}")
            print("=== END MIDIGPT OUTPUT ===\n")
        
        # Cleanup temp files
        os.unlink(input_path)
        os.unlink(output_path)
        
        return generated_midi
        
    except Exception as e:
        # Clean up temp file on error
        if os.path.exists(input_path):
            os.unlink(input_path)
        # Re-raise the original exception with full context
        if DEBUG:
            print(f"MidiGPT processing failed: {e}")
            traceback.print_exc()
        raise e

def extract_notes_from_midi(midi_file, timing_map):
    """Extract notes from generated MIDI and map to project timing - FAIL FAST VERSION"""
    
    if not midi_file:
        raise ValueError("MIDI file cannot be None")
    
    if not midi_file.tracks:
        raise ValueError("MIDI file has no tracks to process")
    
    if DEBUG:
        print(f"\n=== DETAILED MIDI EXTRACTION DEBUG ===")
        print(f"MIDI has {len(midi_file.tracks)} tracks, {midi_file.ticks_per_beat} ticks/beat")
    
    # Extract all notes from all tracks with detailed logging
    all_notes = []
    all_pitches_seen = set()
    
    for track_idx, track in enumerate(midi_file.tracks):
        current_time = 0
        active_notes = {}
        track_notes = []
        track_pitches = set()
        
        for msg in track:
            current_time += msg.time
            
            if msg.type == 'note_on' and msg.velocity > 0:
                active_notes[msg.note] = {
                    'start': current_time,
                    'velocity': msg.velocity,
                    'track': track_idx
                }
                track_pitches.add(msg.note)
                all_pitches_seen.add(msg.note)
                
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active_notes:
                    note_info = active_notes.pop(msg.note)
                    duration = current_time - note_info['start']
                    
                    if duration > 0:  # Valid note
                        note = {
                            'pitch': msg.note,
                            'start': note_info['start'],
                            'duration': duration,
                            'velocity': note_info['velocity'],
                            'track': note_info['track']
                        }
                        track_notes.append(note)
                        all_notes.append(note)
        
        if DEBUG and track_notes:
            print(f"Track {track_idx}: {len(track_notes)} notes, pitches: {sorted(track_pitches)}, range: {min(track_pitches)}-{max(track_pitches)}")
    
    # Validate we got some notes
    if not all_notes:
        raise ValueError("No valid notes extracted from generated MIDI")
    
    if DEBUG:
        print(f"\nEXTRACTION SUMMARY:")
        print(f"Total notes: {len(all_notes)}")
        print(f"Unique pitches: {sorted(all_pitches_seen)}")
        print(f"Pitch count: {len(all_pitches_seen)}")
        
        # Show pitch distribution
        pitch_counts = {}
        for note in all_notes:
            pitch_counts[note['pitch']] = pitch_counts.get(note['pitch'], 0) + 1
        
        print(f"Pitch distribution: {dict(sorted(pitch_counts.items())[:10])}...")  # Show first 10
        most_common = max(pitch_counts, key=pitch_counts.get)
        print(f"Most common pitch: {most_common} ({pitch_counts[most_common]} times)")
        
        # Show sample notes from different tracks
        print(f"\nSample notes (first 5):")
        for i, note in enumerate(all_notes[:5]):
            print(f"  Note {i+1}: pitch={note['pitch']}, start={note['start']}, dur={note['duration']}, track={note['track']}")
        
        print("=== END EXTRACTION DEBUG ===\n")
    
    return all_notes

def convert_notes_to_ca_format(notes, timing_map):
    """Convert extracted notes to CA format - FAIL FAST VERSION"""
    
    if not notes:
        raise ValueError("No notes provided for conversion")
    
    if timing_map.project_total_measures <= 0:
        raise ValueError(f"Invalid timing map: {timing_map.project_total_measures} measures")
    
    # Group notes by project measure
    notes_by_measure = defaultdict(list)
    ticks_per_measure = 1920
    
    for note in notes:
        # Validate note structure
        required_keys = ['pitch', 'start', 'duration']
        for key in required_keys:
            if key not in note:
                raise KeyError(f"Note missing required key '{key}': {note}")
        
        # Validate note values
        if not (0 <= note['pitch'] <= 127):
            raise ValueError(f"Invalid MIDI pitch {note['pitch']}: must be 0-127")
        
        if note['duration'] <= 0:
            raise ValueError(f"Invalid note duration {note['duration']}: must be positive")
        
        # Map to project measure
        project_measure = int(note['start'] // ticks_per_measure)
        if project_measure < timing_map.project_total_measures:
            notes_by_measure[project_measure].append(note)
    
    if not notes_by_measure:
        raise ValueError("No notes mapped to valid project measures")
    
    # Build CA format string with proper REAPER structure
    ca_parts = []
    
    for measure in sorted(notes_by_measure.keys()):
        measure_notes = notes_by_measure[measure]
        
        # CRITICAL: Each measure needs complete context
        ca_parts.extend([
            f"M:{measure}",
            "B:5",   # Beat subdivision  
            "L:96",  # Length parameter
            "I:0"    # Instrument
        ])
        
        # Group notes by timing within measure
        note_groups = defaultdict(list)
        for note in measure_notes:
            position_in_measure = int(note['start'] % ticks_per_measure)
            note_groups[position_in_measure].append(note)
        
        # Process each note group at each timing position
        for position in sorted(note_groups.keys()):
            group_notes = note_groups[position]
            
            if len(group_notes) == 1:
                # Single note
                note = group_notes[0]
                duration = max(240, min(1920, int(note['duration'])))
                ca_parts.extend([
                    f"N:{note['pitch']}",
                    f"d:{duration}",
                    f"w:{duration}"
                ])
            else:
                # Multiple simultaneous notes (chord)
                duration = max(240, min(1920, int(group_notes[0]['duration'])))
                ca_parts.append(f"d:{duration}")
                
                # Add all chord notes
                for note in group_notes:
                    ca_parts.append(f"N:{note['pitch']}")
                
                # Add wait time
                ca_parts.append(f"w:{duration}")
    
    result_ca = ";" + ";".join(ca_parts) + ";"
    
    # Clean up any double delimiters
    while ";;" in result_ca:
        result_ca = result_ca.replace(";;", ";")
    
    # Validate output format
    if not result_ca.startswith(';') or not result_ca.endswith(';'):
        raise ValueError("Generated CA string has invalid format - missing delimiters")
    
    if len(result_ca) < 20:  # Minimum reasonable length for valid CA format
        raise ValueError(f"Generated CA string too short: {len(result_ca)} characters")
    
    if DEBUG:
        print(f"Generated CA result: {len(result_ca)} characters")
        print(f"Result measures: {sorted(notes_by_measure.keys())}")
        print(f"Note groups per measure: {len(notes_by_measure)}")
        print(f"CA preview: {result_ca[:200]}...")
        
        # Debug format structure
        segments = result_ca.split(';')
        measure_count = segments.count('M:0') + segments.count('M:1') + segments.count('M:2') + segments.count('M:3')
        note_count = len([s for s in segments if s.startswith('N:')])
        print(f"Format validation: {measure_count} measures, {note_count} notes")
    
    return result_ca

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0):
    """
    Main MidiGPT generation function - FAIL FAST VERSION
    No fallback behavior - all errors propagate clearly
    """
    
    if DEBUG:
        print(f"\n{'='*60}")
        print(f"🎵 MidiGPT call_nn_infill called")
        print(f"{'='*60}")
        print(f"Input 's' parameter analysis:")
        print(f"  Type: {type(s)}")
        print(f"  Length: {len(s) if s else 0} characters")
        print(f"  Full content: {s}")
        print(f"\nParsing 's' parameter:")
        
        # Parse the CA format to understand what REAPER is sending
        if s:
            segments = s.split(';')
            measures = [seg for seg in segments if seg.startswith('M:')]
            notes = [seg for seg in segments if seg.startswith('N:')]
            extra_ids = [seg for seg in segments if 'extra_id' in seg]
            durations = [seg for seg in segments if seg.startswith('d:')]
            
            print(f"  Measures found: {measures}")
            print(f"  Notes found: {len(notes)} - {notes[:5] if len(notes) > 5 else notes}")
            print(f"  Extra IDs found: {extra_ids}")
            print(f"  Durations found: {len(durations)} - {durations[:3] if len(durations) > 3 else durations}")
        
        print(f"\nInput 'S' parameter:")
        print(f"  Type: {type(S)}")
        if hasattr(S, 'keys'):
            print(f"  Keys: {list(S.keys())[:10]}")
        print(f"{'='*60}\n")
        print(f"Temperature: {temperature}")
    
    # Validate inputs immediately
    if s is None:
        raise ValueError("Input parameter 's' cannot be None")
    
    if not isinstance(s, str):
        raise TypeError(f"Input parameter 's' must be string, got {type(s)}")
    
    if len(s) == 0:
        raise ValueError("Input parameter 's' cannot be empty")
    
    if S is None:
        raise ValueError("Input parameter 'S' cannot be None")
    
    # Check if input contains actual musical content
    has_notes = 'N:' in s
    has_extra_ids = '<extra_id_' in s
    
    if DEBUG:
        print(f"Content analysis:")
        print(f"  Has notes: {has_notes}")
        print(f"  Has extra_ids: {has_extra_ids}")
        print(f"  Strategy: {'Parse actual REAPER content' if has_notes else 'Need infill structure'}\n")
    
    if not has_notes and not has_extra_ids:
        raise ValueError("Input 's' contains neither notes nor extra_id tokens - nothing to process")
    
    try:
        # Extract timing information from S parameter
        timing_map = extract_timing_from_s_parameter(S)
        
        # Parse the actual REAPER content from 's' parameter
        if has_notes:
            if DEBUG:
                print(f"✓ Using actual REAPER musical content ({s.count('N:')} notes)")
            midi_structure = parse_ca_string_to_midi(s, timing_map)
        else:
            if DEBUG:
                print(f"⚠️  No notes in input, creating minimal context")
            # Only use artificial structure if there's literally no content
            midi_structure = create_infill_midi_structure(s, timing_map)
        
        # Process with MidiGPT
        generated_midi = process_with_midigpt(midi_structure, timing_map, temperature)
        
        # Extract notes from generated MIDI
        extracted_notes = extract_notes_from_midi(generated_midi, timing_map)
        
        # Convert to CA format
        ca_result = convert_notes_to_ca_format(extracted_notes, timing_map)
        
        if DEBUG:
            print(f"✓ Final result: {len(ca_result)} chars")
        
        return ca_result
        
    except Exception as e:
        if DEBUG:
            print(f"❌ Error in call_nn_infill: {e}")
            traceback.print_exc()
        # Re-raise with full context - no fallback behavior
        raise e

def main():
    """Start XML-RPC server - FAIL FAST VERSION"""
    
    # Validate environment before starting server
    if not MIDIGPT_AVAILABLE:
        raise RuntimeError("MidiGPT not available - cannot start server")
    
    # Test model checkpoint availability
    try:
        find_model_checkpoint()
    except FileNotFoundError as e:
        raise RuntimeError(f"Cannot start server: {e}")
    
    # Create server
    with SimpleXMLRPCServer(('127.0.0.1', 3456), allow_none=True) as server:
        server.register_function(call_nn_infill, 'call_nn_infill')
        
        print("MidiGPT Server running on http://127.0.0.1:3456")
        print("✓ MidiGPT library available")
        print("✓ Model checkpoint found")
        print("✓ All dependencies validated")
        print("Ready to process REAPER requests with fail-fast debugging")
        
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nMidiGPT server stopped by user")
        except Exception as e:
            print(f"Server error: {e}")
            raise e

if __name__ == "__main__":
    main()