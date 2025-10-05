#!/usr/bin/env python3
"""
MidiGPT Diagnostic Wrapper
Comprehensive logging to understand REAPER→Server→MidiGPT flow
"""

import os
import sys
from xmlrpc.server import SimpleXMLRPCServer
import json
import tempfile

# Add project paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, 'src', 'Scripts', 'composers_assistant_v2'))

import preprocessing_functions as pre

DEBUG = True

def log_section(title):
    if DEBUG:
        print("\n" + "="*60)
        print(f"  {title}")
        print("="*60)

def analyze_ca_string(s):
    """Analyze the CA format string to understand the request"""
    log_section("CA STRING ANALYSIS")
    print(f"Length: {len(s)} characters")
    
    # Find all extra_id tokens
    import re
    extra_ids = re.findall(r'<extra_id_(\d+)>', s)
    print(f"Extra IDs found: {extra_ids}")
    
    # Count note events
    note_count = s.count(';N:')
    print(f"Note events: {note_count}")
    
    # Check for measure markers
    measure_count = s.count(';M:')
    print(f"Measure markers: {measure_count}")
    
    # Sample the string
    preview_len = min(200, len(s))
    print(f"\nFirst {preview_len} chars:")
    print(s[:preview_len])
    
    return {
        'extra_ids': extra_ids,
        'note_count': note_count,
        'measure_count': measure_count
    }

def analyze_S_structure(S_dict):
    """Analyze the MidiSongByMeasure structure"""
    log_section("S PARAMETER ANALYSIS")
    
    # Check if it's a dict (needs conversion)
    if isinstance(S_dict, dict):
        print("S is dict - needs conversion to MidiSongByMeasure")
        S = pre.midisongbymeasure_from_save_dict(S_dict)
    else:
        print("S is already MidiSongByMeasure object")
        S = S_dict
    
    # Analyze structure
    num_tracks = len(S.tracks)
    print(f"Number of tracks: {num_tracks}")
    
    for track_idx, track in enumerate(S.tracks):
        num_measures = len(track.tracks_by_measure)
        
        # Count notes per measure
        notes_per_measure = []
        for measure_idx, m_track in enumerate(track.tracks_by_measure):
            note_count = len(m_track.note_ons) if hasattr(m_track, 'note_ons') else 0
            notes_per_measure.append((measure_idx, note_count))
        
        # Find empty measures
        empty_measures = [m for m, n in notes_per_measure if n == 0]
        
        print(f"\nTrack {track_idx}:")
        print(f"  Measures: {num_measures}")
        print(f"  Empty measures: {empty_measures}")
        print(f"  Notes per measure: {notes_per_measure[:10]}")  # First 10
        
        if hasattr(track, 'extra_info'):
            print(f"  Extra info: {track.extra_info}")
    
    return S

def analyze_time_selection(start_measure, end_measure):
    """Analyze the time selection parameters"""
    log_section("TIME SELECTION ANALYSIS")
    
    if start_measure is None or end_measure is None:
        print("No time selection bounds provided")
        return None, None
    
    print(f"Start measure: {start_measure}")
    print(f"End measure: {end_measure}")
    print(f"Measure range: {end_measure - start_measure + 1} measures")
    
    return start_measure, end_measure

def extract_target_measures(s, S, start_measure, end_measure):
    """Determine which measures need generation"""
    log_section("TARGET MEASURE DETECTION")
    
    # Parse extra_ids from CA string
    import re
    extra_ids = re.findall(r'<extra_id_(\d+)>', s)
    
    # Find where notes exist and where extra_ids are
    ca_parts = s.split(';')
    
    measure_contexts = {}
    current_measure = None
    
    for part in ca_parts:
        if part.startswith('M:'):
            current_measure = int(part[2:])
            if current_measure not in measure_contexts:
                measure_contexts[current_measure] = {
                    'has_notes': False,
                    'has_extra_id': False,
                    'extra_id_num': None
                }
        elif part.startswith('N:') and current_measure is not None:
            measure_contexts[current_measure]['has_notes'] = True
        elif part.startswith('<extra_id_'):
            extra_id_num = part.split('_')[2].rstrip('>')
            if current_measure is not None:
                measure_contexts[current_measure]['has_extra_id'] = True
                measure_contexts[current_measure]['extra_id_num'] = extra_id_num
    
    print("Measure contexts:")
    for measure, context in sorted(measure_contexts.items()):
        status = []
        if context['has_notes']:
            status.append("HAS_NOTES")
        if context['has_extra_id']:
            status.append(f"NEEDS_FILL(extra_id_{context['extra_id_num']})")
        print(f"  Measure {measure}: {', '.join(status) if status else 'EMPTY'}")
    
    # Determine target measures for generation
    target_measures = set()
    for measure, context in measure_contexts.items():
        if context['has_extra_id']:
            if start_measure is None or (start_measure <= measure <= end_measure):
                target_measures.add(measure)
    
    print(f"\nTarget measures for generation: {sorted(target_measures)}")
    return target_measures

def call_nn_infill(s, S_dict, use_sampling=True, min_length=10, 
                   enc_no_repeat_ngram_size=0, has_fully_masked_inst=False, 
                   temperature=1.0, start_measure=None, end_measure=None):
    """
    Diagnostic wrapper for call_nn_infill
    """
    log_section("CALL_NN_INFILL INVOKED")
    print(f"Parameters:")
    print(f"  use_sampling: {use_sampling}")
    print(f"  min_length: {min_length}")
    print(f"  enc_no_repeat_ngram_size: {enc_no_repeat_ngram_size}")
    print(f"  has_fully_masked_inst: {has_fully_masked_inst}")
    print(f"  temperature: {temperature}")
    
    # Analyze inputs
    ca_analysis = analyze_ca_string(s)
    S = analyze_S_structure(S_dict)
    start_m, end_m = analyze_time_selection(start_measure, end_measure)
    target_measures = extract_target_measures(s, S, start_measure, end_measure)
    
    # Create diagnostic report
    log_section("DIAGNOSTIC SUMMARY")
    print(f"Request type: {'INFILL' if ca_analysis['extra_ids'] else 'CONTINUATION'}")
    print(f"Extra IDs to fill: {ca_analysis['extra_ids']}")
    print(f"Context notes provided: {ca_analysis['note_count']}")
    print(f"Measures to generate: {sorted(target_measures)}")
    print(f"Time selection: measures {start_m} to {end_m}" if start_m else "No time selection")
    
    # Save diagnostic data
    diagnostic_file = os.path.join(tempfile.gettempdir(), 'midigpt_diagnostic.json')
    diagnostic_data = {
        'ca_string_length': len(s),
        'ca_string_preview': s[:500],
        'extra_ids': ca_analysis['extra_ids'],
        'note_count': ca_analysis['note_count'],
        'num_tracks': len(S.tracks),
        'target_measures': sorted(target_measures),
        'start_measure': start_m,
        'end_measure': end_m,
        'temperature': temperature
    }
    
    with open(diagnostic_file, 'w') as f:
        json.dump(diagnostic_data, f, indent=2)
    print(f"\nDiagnostic data saved to: {diagnostic_file}")
    
    # Now forward to actual midigpt server
    log_section("FORWARDING TO MIDIGPT SERVER")
    
    try:
        from xmlrpc.client import ServerProxy
        proxy = ServerProxy('http://127.0.0.1:3456')
        
        # Encode S back to dict for transmission
        S_encoded = pre.encode_midisongbymeasure_to_save_dict(S)
        
        print(f"Calling actual midigpt server on port 3456...")
        result = proxy.call_nn_infill(
            s, S_encoded, use_sampling, min_length,
            enc_no_repeat_ngram_size, has_fully_masked_inst,
            temperature, start_measure, end_measure
        )
        
        log_section("RESULT FROM MIDIGPT")
        print(f"Result length: {len(result)} characters")
        print(f"Preview: {result[:200]}")
        
        return result
        
    except Exception as e:
        print(f"ERROR calling midigpt server: {e}")
        import traceback
        traceback.print_exc()
        
        # Return diagnostic fallback
        fallback = f"<extra_id_{ca_analysis['extra_ids'][0]}>;N:60;d:480;w:0;N:64;d:480;w:0;N:67;d:480;w:0"
        print(f"Returning fallback: {fallback}")
        return fallback

def start_diagnostic_server():
    """Start diagnostic XML-RPC server on port 3455"""
    server = SimpleXMLRPCServer(('127.0.0.1', 3455), logRequests=True)
    server.register_function(call_nn_infill, 'call_nn_infill')
    
    print("\n" + "="*60)
    print("  MidiGPT Diagnostic Server Started")
    print("="*60)
    print("Port: 3455 (diagnostic wrapper)")
    print("Forwards to: port 3456 (actual midigpt server)")
    print("\nTo use this diagnostic server:")
    print("1. Start the actual midigpt server on port 3456")
    print("2. Change rpr_midigpt_functions.py to use port 3455")
    print("3. Run your REAPER script")
    print("4. Check console output and /tmp/midigpt_diagnostic.json")
    print("\nPress Ctrl+C to stop")
    print("="*60 + "\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDiagnostic server stopped")

if __name__ == '__main__':
    start_diagnostic_server()