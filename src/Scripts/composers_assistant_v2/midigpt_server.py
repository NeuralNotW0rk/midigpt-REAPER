#!/usr/bin/env python3
"""
Timing-Preserving MidiGPT Server
Model-agnostic approach that preserves the relationship between input and output timing
"""

import json
import os
import sys
import tempfile
import re
from xmlrpc.server import SimpleXMLRPCServer
import traceback
from collections import defaultdict

# Add paths for dependencies
current_dir = os.path.dirname(__file__)
midigpt_path = os.path.join(current_dir, "../../../MIDI-GPT/python_lib")
if os.path.exists(midigpt_path):
    sys.path.insert(0, os.path.abspath(midigpt_path))

# Import dependencies
try:
    import mido
    print("✓ Mido library available")
    MIDO_AVAILABLE = True
except ImportError:
    print("✗ Mido library not available")
    MIDO_AVAILABLE = False
    sys.exit(1)

try:
    import preprocessing_functions as pre
    print("✓ Preprocessing functions loaded")
except ImportError as e:
    print(f"✗ Failed to load preprocessing functions: {e}")
    sys.exit(1)

try:
    import midigpt
    print("✓ MidiGPT library available")
    MIDIGPT_AVAILABLE = True
except ImportError as e:
    print(f"✗ MidiGPT library not available: {e}")
    MIDIGPT_AVAILABLE = False

# Configuration
DEBUG = True
DEFAULT_CKPT = None  # Will be found dynamically

class TimingMap:
    """Captures the timing structure and intent from the original CA format"""
    
    def __init__(self, ca_string, project_measures):
        self.project_start_measure = min(project_measures) if project_measures else 0
        self.project_end_measure = max(project_measures) if project_measures else 3
        self.project_total_measures = len(project_measures)
        self.notes_by_measure = defaultdict(list)
        self.measure_positions = {}  # Track measure timing positions
        self.extra_ids = []
        self.original_ca_string = ca_string
        
        self._parse_ca_structure(ca_string)
    
    def _parse_ca_structure(self, ca_string):
        """Parse CA format to extract timing structure and musical intent"""
        if DEBUG:
            print(f"Parsing CA structure: {len(ca_string)} characters")
        
        segments = ca_string.split(';')
        current_measure = self.project_start_measure
        current_time_in_measure = 0
        
        for segment in segments:
            if not segment:
                continue
                
            if segment.startswith('M:'):
                current_measure = int(segment[2:])
                current_time_in_measure = 0
                if current_measure not in self.measure_positions:
                    self.measure_positions[current_measure] = {
                        'start_time': current_measure * 1920,  # Standard ticks per measure
                        'notes': []
                    }
                    
            elif segment.startswith('N:'):
                parts = segment.split(':')
                pitch = int(parts[1])
                duration = int(parts[2]) if len(parts) > 2 else 480
                
                note_info = {
                    'type': 'note',
                    'pitch': pitch,
                    'duration': duration,
                    'measure': current_measure,
                    'time_in_measure': current_time_in_measure,
                    'absolute_time': current_measure * 1920 + current_time_in_measure
                }
                
                self.notes_by_measure[current_measure].append(note_info)
                self.measure_positions[current_measure]['notes'].append(note_info)
                
            elif segment.startswith('w:'):
                # Wait time - advance position in measure
                wait_time = int(segment[2:])
                current_time_in_measure += wait_time
                
            elif segment.startswith('d:'):
                # Duration - this affects the current note but not timing position
                pass
                
            elif segment.startswith('<extra_id_'):
                # Extract extra ID number
                match = re.search(r'<extra_id_(\d+)>', segment)
                if match:
                    self.extra_ids.append(int(match.group(1)))
        
        if DEBUG:
            print(f"Parsed structure: {len(self.notes_by_measure)} measures with content")
            print(f"Extra IDs found: {self.extra_ids}")
            for measure, notes in self.notes_by_measure.items():
                print(f"  Measure {measure}: {len(notes)} notes")

def generate_instructions_by_extra_id(generated_notes, requested_extra_ids):
    """Convert generated notes to extra_id instruction format that REAPER expects - CA-compatible format"""
    
    if not requested_extra_ids:
        if DEBUG:
            print("No extra_id tokens requested, using fallback format")
        return {}
    
    if DEBUG:
        print(f"Generating CA-compatible instructions for extra_ids: {requested_extra_ids}")
        print(f"Distributing {len(generated_notes)} notes among {len(requested_extra_ids)} extra_ids")
    
    instructions_by_extra_id = {}
    
    if len(generated_notes) == 0:
        # No generated notes, provide empty instructions for each extra_id
        for extra_id in requested_extra_ids:
            instructions_by_extra_id[f"<extra_id_{extra_id}>"] = []
        return instructions_by_extra_id
    
    # Distribute notes more evenly - ensure each extra_id gets substantial content
    min_notes_per_id = max(2, len(generated_notes) // len(requested_extra_ids))
    note_idx = 0
    
    for i, extra_id in enumerate(requested_extra_ids):
        instructions = []
        
        # Calculate how many notes this extra_id should get
        if i == len(requested_extra_ids) - 1:
            # Last extra_id gets all remaining notes
            notes_for_this_id = len(generated_notes) - note_idx
        else:
            # Each extra_id gets fair share
            available_notes = len(generated_notes) - note_idx
            remaining_extra_ids = len(requested_extra_ids) - i
            notes_for_this_id = max(min_notes_per_id, available_notes // remaining_extra_ids)
        
        # Generate instructions in CA-compatible format
        current_position = 0
        
        for j in range(notes_for_this_id):
            if note_idx < len(generated_notes):
                note = generated_notes[note_idx]
                
                # CA Format: Use w: (wait) to position notes, then N: and d: for the note
                if j > 0 or current_position > 0:
                    # Add wait time to position this note (CA pattern)
                    wait_time = max(120, min(480, note['duration'] // 4))  # Reasonable musical spacing
                    instructions.append(f"w:{wait_time}")
                    current_position += wait_time
                
                # Add the note in CA format: N:pitch, d:duration (NO automatic wait after)
                instructions.extend([
                    f"N:{note['pitch']}",
                    f"d:{note['duration']}"
                ])
                
                current_position += note['duration']
                note_idx += 1
        
        if DEBUG and instructions:
            note_count = len([inst for inst in instructions if inst.startswith('N:')])
            print(f"  <extra_id_{extra_id}>: {note_count} notes, {len(instructions)} instructions (CA format)")
        
        instructions_by_extra_id[f"<extra_id_{extra_id}>"] = instructions
    
    # Debug summary
    if DEBUG:
        total_notes_assigned = sum(len([inst for inst in instructions if inst.startswith('N:')]) 
                                 for instructions in instructions_by_extra_id.values())
        print(f"Total notes assigned: {total_notes_assigned} out of {len(generated_notes)} generated (CA-compatible)")
    
    return instructions_by_extra_id

def format_as_extra_id_response(instructions_by_extra_id):
    """Convert to the CA extra_id format that REAPER expects"""
    
    if not instructions_by_extra_id:
        if DEBUG:
            print("No extra_id instructions to format")
        return ""
    
    parts = []
    
    for extra_id, instructions in instructions_by_extra_id.items():
        parts.append(extra_id)  # Add the token: <extra_id_151>
        parts.extend(instructions)  # Add the instructions: N:60, d:480, w:480
    
    result = ";" + ";".join(parts) + ";"
    
    if DEBUG:
        print(f"Formatted extra_id response: {len(result)} characters")
        print(f"Preview: {result[:200]}...")
    
    return result

def create_timing_preserving_midi(timing_map):
    """Create MIDI file that preserves the original project's timing structure"""
    
    # Create MIDI with proper timing resolution
    midi_file = mido.MidiFile(ticks_per_beat=480, type=1)  # Type 1 for multiple tracks
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    
    # Add standard MIDI headers
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))  # 120 BPM
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    track.append(mido.MetaMessage('track_name', name='Generated', time=0))
    
    # Convert notes to MIDI events with preserved timing
    all_events = []
    
    for measure_num, notes in timing_map.notes_by_measure.items():
        for note in notes:
            # Calculate absolute timing in MIDI ticks
            measure_start_ticks = (measure_num - timing_map.project_start_measure) * 1920
            note_start_ticks = measure_start_ticks + note['time_in_measure']
            note_end_ticks = note_start_ticks + note['duration']
            
            # Create MIDI events
            all_events.append({
                'time': note_start_ticks,
                'type': 'note_on',
                'note': note['pitch'],
                'velocity': 80
            })
            all_events.append({
                'time': note_end_ticks,
                'type': 'note_off', 
                'note': note['pitch'],
                'velocity': 0
            })
    
    # Add generation targets (empty space for MidiGPT to fill)
    project_duration = timing_map.project_total_measures * 1920
    
    # If we have extra_ids, add placeholder notes to give MidiGPT context
    if timing_map.extra_ids:
        for i, extra_id in enumerate(timing_map.extra_ids):
            # Add very quiet placeholder notes that MidiGPT can replace
            placeholder_time = (i + 1) * (project_duration // (len(timing_map.extra_ids) + 1))
            all_events.append({
                'time': placeholder_time,
                'type': 'note_on',
                'note': 60,  # Middle C placeholder
                'velocity': 1   # Very quiet
            })
            all_events.append({
                'time': placeholder_time + 120,  # Short placeholder
                'type': 'note_off',
                'note': 60,
                'velocity': 0
            })
    
    # Sort events by time and convert to MIDI messages
    all_events.sort(key=lambda x: (x['time'], x['type'] == 'note_off'))  # note_on before note_off at same time
    
    current_time = 0
    for event in all_events:
        delta_time = event['time'] - current_time
        current_time = event['time']
        
        if event['type'] == 'note_on':
            track.append(mido.Message('note_on', channel=0, note=event['note'], 
                                    velocity=event['velocity'], time=delta_time))
            delta_time = 0  # Reset for next event at same time
        else:
            track.append(mido.Message('note_off', channel=0, note=event['note'], 
                                    velocity=event['velocity'], time=delta_time))
            delta_time = 0
    
    # End of track
    track.append(mido.MetaMessage('end_of_track', time=0))
    
    if DEBUG:
        total_ticks = sum(msg.time for msg in track)
        print(f"Created MIDI: {len(track)} messages, {total_ticks} total ticks")
    
    return midi_file

def process_with_midigpt(midi_file, timing_map, temperature=1.0):
    """Process MIDI file with MidiGPT while preserving timing relationships"""
    
    if not MIDIGPT_AVAILABLE:
        if DEBUG:
            print("MidiGPT not available, creating fallback")
        return create_fallback_midi(timing_map)
    
    try:
        # Save input MIDI temporarily
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as temp_input:
            midi_file.save(temp_input.name)
            input_path = temp_input.name
        
        if DEBUG:
            print(f"Saved input MIDI to: {input_path}")
        
        # Initialize MidiGPT (no explicit checkpoint loading needed)
        encoder = midigpt.ExpressiveEncoder()
        
        if DEBUG:
            print("✓ MidiGPT ExpressiveEncoder initialized")
        
        # Convert to MidiGPT format
        json_str = encoder.midi_to_json(input_path)
        json_data = json.loads(json_str)
        
        if DEBUG:
            print(f"✓ Converted to JSON: {len(json_str)} characters")
        
        # Create status for generation - use exact format from working examples
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
                'autoregressive': False,  # Use infill mode for timing preservation
                'polyphony_hard_limit': 9
            }]
        }
        
        # Find model checkpoint dynamically
        model_path = find_model_checkpoint()
        
        # Create minimal params using MidiGPT's default_sample_param as base
        default_params = json.loads(midigpt.default_sample_param())
        
        # Override only the essential parameters we need
        default_params.update({
            'temperature': temperature,
            'ckpt': model_path
        })
        
        # Run MidiGPT generation with minimal validated parameters
        piece_str = json.dumps(json_data)
        status_str = json.dumps(status_data)
        params_str = json.dumps(default_params)
        
        if DEBUG:
            print(f"Using parameters: {list(default_params.keys())}")
        
        callbacks = midigpt.CallbackManager()
        results = midigpt.sample_multi_step(piece_str, status_str, params_str, 3, callbacks)
        
        if not results:
            if DEBUG:
                print("No results from MidiGPT, using fallback")
            return create_fallback_midi(timing_map)
        
        if DEBUG:
            print(f"✅ MidiGPT generation successful: {len(results[0])} characters")
        
        # Convert result back to MIDI - json_to_midi expects string, not parsed JSON
        result_json_str = results[0]  # Keep as string, don't parse to JSON
        with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as temp_output:
            encoder.json_to_midi(result_json_str, temp_output.name)  # Pass string directly
            output_path = temp_output.name
        
        # Load generated MIDI
        generated_midi = mido.MidiFile(output_path)
        
        if DEBUG:
            print(f"✓ Generated MIDI: {len(generated_midi.tracks)} tracks")
        
        # Cleanup temp files
        os.unlink(input_path)
        os.unlink(output_path)
        
        return generated_midi
        
    except Exception as e:
        if DEBUG:
            print(f"MidiGPT processing failed: {e}")
            traceback.print_exc()
        return create_fallback_midi(timing_map)

def restore_original_timing_structure(generated_midi, original_timing_map):
    """Extract notes from generated MIDI and format as extra_id instructions for REAPER"""
    
    # Extract all notes from generated MIDI (across all tracks)
    generated_notes = []
    
    for track_idx, track in enumerate(generated_midi.tracks):
        current_time = 0
        active_notes = {}
        
        for msg in track:
            current_time += msg.time
            
            if msg.type == 'note_on' and msg.velocity > 0:
                active_notes[msg.note] = {
                    'start': current_time,
                    'velocity': msg.velocity,
                    'track': track_idx
                }
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active_notes:
                    note_info = active_notes.pop(msg.note)
                    duration = current_time - note_info['start']
                    
                    generated_notes.append({
                        'pitch': msg.note,
                        'start_time': note_info['start'],
                        'end_time': current_time,
                        'duration': max(240, min(1920, duration)),  # Clamp duration to reasonable range
                        'velocity': note_info['velocity'],
                        'track': note_info['track']
                    })
    
    if DEBUG:
        print(f"Extracted {len(generated_notes)} notes from generated MIDI")
    
    # Check if we need extra_id format or simple CA format
    requested_extra_ids = original_timing_map.extra_ids
    
    if requested_extra_ids:
        # REAPER sent extra_id tokens - use extra_id instruction format
        if DEBUG:
            print(f"Using extra_id format for tokens: {requested_extra_ids}")
        
        instructions_by_extra_id = generate_instructions_by_extra_id(generated_notes, requested_extra_ids)
        result_ca = format_as_extra_id_response(instructions_by_extra_id)
        
    else:
        # No extra_id tokens - use simple measure-based CA format (fallback)
        if DEBUG:
            print("No extra_id tokens found, using simple measure-based format")
        
        # Map generated notes back to original project timing structure  
        project_start = original_timing_map.project_start_measure
        project_end = original_timing_map.project_end_measure
        project_range = project_end - project_start + 1
        project_duration_ticks = project_range * 1920
        
        # Group notes by their target measure in the original project
        notes_by_project_measure = defaultdict(list)
        
        for note in generated_notes:
            # Calculate which measure this note should go to in the original project
            if project_duration_ticks > 0:
                relative_position = (note['start_time'] % project_duration_ticks) / project_duration_ticks
                target_measure = project_start + int(relative_position * project_range)
            else:
                target_measure = project_start
            
            # Ensure we stay within project bounds
            target_measure = max(project_start, min(project_end, target_measure))
            
            notes_by_project_measure[target_measure].append({
                'pitch': note['pitch'],
                'duration': note['duration'],
                'velocity': note['velocity']
            })
        
        # Convert back to CA format with original project measures
        ca_parts = []
        
        # Sort measures to ensure consistent output
        for measure in sorted(notes_by_project_measure.keys()):
            measure_notes = notes_by_project_measure[measure]
            
            for note in measure_notes:
                ca_parts.extend([
                    f"M:{measure}",
                    f"N:{note['pitch']}",
                    f"d:{note['duration']}",
                    f"w:{note['duration']}"
                ])
        
        result_ca = ";" + ";".join(ca_parts) + ";"
    
    if DEBUG:
        print(f"Generated CA result: {len(result_ca)} characters")
        if requested_extra_ids:
            print(f"Extra_ID format with {len(requested_extra_ids)} tokens")
        else:
            print(f"Measure-based format")
        print(f"CA preview: {result_ca[:200]}...")
    
    return result_ca

def create_fallback_midi(timing_map):
    """Create simple fallback MIDI when MidiGPT fails"""
    
    midi_file = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi_file.tracks.append(track)
    
    # Add headers
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    
    # Add simple fallback notes across the project range
    pitches = [60, 64, 67, 72]  # C major chord + octave
    
    for i in range(timing_map.project_total_measures):
        measure_start = i * 1920
        pitch = pitches[i % len(pitches)]
        
        track.append(mido.Message('note_on', channel=0, note=pitch, velocity=80, time=measure_start))
        track.append(mido.Message('note_off', channel=0, note=pitch, velocity=0, time=480))
    
    track.append(mido.MetaMessage('end_of_track', time=0))
    
    if DEBUG:
        print("Created fallback MIDI with simple chord progression")
    
    return midi_file

def find_model_checkpoint():
    """Find MidiGPT model checkpoint with multiple path attempts"""
    possible_paths = [
        "../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "../../../../MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt",
        "/Users/griffinpage/Documents/GitHub/midigpt-REAPER/MIDI-GPT/models/EXPRESSIVE_ENCODER_RES_1920_12_GIGAMIDI_CKPT_150K.pt"
    ]
    
    for path in possible_paths:
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path):
            return abs_path
    
    if DEBUG:
        print("Warning: No model checkpoint found")
    return None

def call_nn_infill(s, S, use_sampling=True, min_length=10, enc_no_repeat_ngram_size=0, 
                   has_fully_masked_inst=False, temperature=1.0):
    """
    Timing-preserving version that works with any AI model.
    Preserves the relationship between input and output timing.
    """
    
    if DEBUG:
        print("🎵 MidiGPT call_nn_infill called (timing-preserving version)")
        print(f"Input string length: {len(s)} characters")
        print(f"Temperature: {temperature}")
    
    try:
        # Convert S parameter if needed
        if isinstance(S, dict):
            if DEBUG:
                print("Converting S from dict to MidiSongByMeasure...")
            S = pre.midisongbymeasure_from_save_dict(S)
        
        # Extract project measure information from S parameter
        project_measures = []
        if S and S.tracks:
            num_measures = len(S.tracks[0].tracks_by_measure)
            project_measures = list(range(num_measures))
        else:
            # Fallback to reasonable default
            project_measures = [0, 1, 2, 3]
        
        if DEBUG:
            print(f"Project measures: {project_measures}")
        
        # Create timing map from input CA string
        timing_map = TimingMap(s, project_measures)
        
        # Create MIDI with preserved timing structure
        input_midi = create_timing_preserving_midi(timing_map)
        
        # Process with MidiGPT (or other AI models)
        generated_midi = process_with_midigpt(input_midi, timing_map, temperature)
        
        # Restore original timing structure and convert to CA format
        result_ca = restore_original_timing_structure(generated_midi, timing_map)
        
        if DEBUG:
            print(f"✓ Final result: {len(result_ca)} characters")
        
        return result_ca
        
    except Exception as e:
        if DEBUG:
            print(f"❌ Error in timing-preserving generation: {e}")
            traceback.print_exc()
        
        # Ultimate fallback
        return ";M:0;N:60;d:480;w:480;M:1;N:64;d:480;w:480;M:2;N:67;d:480;w:480;"

class TimingPreservingMidiGPTServer:
    """XML-RPC server for timing-preserving MidiGPT integration"""
    
    def __init__(self, port=3456):
        self.port = port
        self.server = None
    
    def start_server(self):
        """Start the XML-RPC server"""
        print(f"Starting timing-preserving MidiGPT server on port {self.port}...")
        
        self.server = SimpleXMLRPCServer(('127.0.0.1', self.port), allow_none=True)
        self.server.register_function(call_nn_infill, 'call_nn_infill')
        
        print("✓ Server registered functions:")
        print("  - call_nn_infill (timing-preserving)")
        print(f"✓ Server ready on http://127.0.0.1:{self.port}")
        print("✓ Model-agnostic timing preservation enabled")
        
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            print("\n🛑 Server stopped by user")
        except Exception as e:
            print(f"❌ Server error: {e}")
        finally:
            if self.server:
                self.server.server_close()

if __name__ == "__main__":
    # Validate dependencies
    if not MIDO_AVAILABLE:
        print("❌ Cannot start server: mido library required")
        sys.exit(1)
    
    if not MIDIGPT_AVAILABLE:
        print("⚠️  Warning: MidiGPT not available, will use fallback generation")
    
    # Start server
    server = TimingPreservingMidiGPTServer(port=3456)
    server.start_server()