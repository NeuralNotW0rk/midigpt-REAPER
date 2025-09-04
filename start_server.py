#!/usr/bin/env python3
"""
Unified Server Management - Single server design
"""

import subprocess
import signal
import sys
import time
import os
import socket

server_process = None

def find_script(filename):
    """Find script in current directory or subdirectories"""
    if os.path.exists(filename):
        return filename
    
    possible_paths = [
        os.path.join('src', 'Scripts', 'composers_assistant_v2', filename),
        os.path.join('Scripts', 'composers_assistant_v2', filename),
        os.path.join('composers_assistant_v2', filename),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    return None

def get_python_executable():
    """Get the correct Python executable (3.9+)"""
    # Try .venv first (preferred)
    venv_paths = [
        os.path.join('.venv', 'bin', 'python'),      # Unix/Mac
        os.path.join('.venv', 'Scripts', 'python.exe'), # Windows
        os.path.join('.venv', 'Scripts', 'python'),     # Windows alt
    ]
    
    for venv_path in venv_paths:
        if os.path.exists(venv_path):
            abs_path = os.path.abspath(venv_path)
            print(f"Using project venv Python: {abs_path}")
            return abs_path
    
    # Fallback to system Python (should be 3.9+ since midigpt is now compatible)
    print("Using system Python (ensure it's 3.9+)")
    return sys.executable

def setup_signal_handlers():
    """Setup signal handlers for clean shutdown"""
    def signal_handler(sig, frame):
        print(f"\nReceived signal {sig}, shutting down...")
        stop_server()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def start_server():
    """Start the unified MidiGPT-REAPER server"""
    global server_process
    
    script_path = find_script('unified_midigpt_reaper_server.py')
    if not script_path:
        print("ERROR: unified_midigpt_reaper_server.py not found")
        return False
    
    python_executable = get_python_executable()
    
    try:
        print(f"Starting unified server: {script_path}")
        server_process = subprocess.Popen(
            [python_executable, script_path],
            cwd=os.path.dirname(script_path) if os.path.dirname(script_path) else '.',
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        # Monitor output for startup confirmation
        startup_timeout = 10
        start_time = time.time()
        
        while time.time() - start_time < startup_timeout:
            if server_process.poll() is not None:
                output, _ = server_process.communicate()
                print(f"Server failed to start:\n{output}")
                return False
            
            time.sleep(0.1)
            
            # Check if port is ready
            if check_port(3456):
                print("✅ Unified server started successfully")
                return True
        
        print("⚠️  Server may have started but port not ready within timeout")
        return True
        
    except Exception as e:
        print(f"ERROR starting server: {e}")
        return False

def check_port(port, service_name="server"):
    """Check if a port is accessible"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:
            print(f"{service_name}: port {port} accessible")
            return True
        else:
            print(f"{service_name}: port {port} not accessible")
            return False
    except Exception as e:
        print(f"Error checking port {port}: {e}")
        return False

def stop_server():
    """Stop the running server"""
    global server_process
    
    if server_process:
        try:
            print("Stopping unified server...")
            server_process.terminate()
            
            # Wait for graceful shutdown
            try:
                server_process.wait(timeout=5)
                print("Server stopped gracefully")
            except subprocess.TimeoutExpired:
                print("Server didn't stop gracefully, force killing...")
                server_process.kill()
                server_process.wait()
                print("Server force killed")
                
        except Exception as e:
            print(f"ERROR stopping server: {e}")
        finally:
            server_process = None

def get_server_status():
    """Get status of the server"""
    global server_process
    
    if server_process and server_process.poll() is None:
        if check_port(3456, "XML-RPC"):
            return "running"
        else:
            return "started but not responding"
    else:
        return "stopped"

def verify_environment():
    """Verify that the environment is set up correctly"""
    print("Verifying environment...")
    
    python_executable = get_python_executable()
    
    # Check Python version
    try:
        result = subprocess.run([python_executable, '--version'], 
                              capture_output=True, text=True)
        python_version = result.stdout.strip()
        print(f"Python version: {python_version}")
        
        # Check if it's 3.9+
        version_parts = python_version.split()[1].split('.')
        major, minor = int(version_parts[0]), int(version_parts[1])
        
        if major == 3 and minor >= 9:
            print("✅ Python version compatible")
        else:
            print(f"⚠️  Python version may be incompatible (need 3.9+)")
            
    except Exception as e:
        print(f"Could not verify Python version: {e}")
    
    # Check for MIDI-GPT repo
    midigpt_paths = [
        "MIDI-GPT",
        "MIDI-GPT/python_lib",
        os.path.join("MIDI-GPT", "models")
    ]
    
    midigpt_found = False
    for path in midigpt_paths:
        if os.path.exists(path):
            print(f"✅ Found MIDI-GPT component: {path}")
            midigpt_found = True
        else:
            print(f"⚠️  MIDI-GPT component not found: {path}")
    
    if not midigpt_found:
        print("⚠️  MIDI-GPT repository not found - clone it to project root")
    
    # Check for required libraries
    required_libs = ['mido', 'miditoolkit']  # One of these
    available_libs = []
    
    for lib in required_libs:
        try:
            result = subprocess.run([python_executable, '-c', f'import {lib}; print("{lib} available")'],
                                  capture_output=True, text=True)
            if result.returncode == 0:
                available_libs.append(lib)
        except:
            pass
    
    if available_libs:
        print(f"✅ MIDI libraries available: {', '.join(available_libs)}")
    else:
        print("⚠️  No MIDI libraries found - install mido or miditoolkit")
    
    # Check for midigpt (if available)
    try:
        result = subprocess.run([python_executable, '-c', 'import midigpt; print("midigpt available")'],
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ midigpt library available")
        else:
            print("⚠️  midigpt library not available (will use fallback mode)")
    except:
        print("⚠️  midigpt library not available (will use fallback mode)")
    
    return True

def tail_logs():
    """Show live logs from the server"""
    global server_process
    
    if not server_process:
        print("Server not running")
        return
    
    print("Showing server logs (Ctrl+C to stop):")
    print("-" * 50)
    
    try:
        while server_process.poll() is None:
            output = server_process.stdout.readline()
            if output:
                print(output.strip())
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped showing logs")

def main():
    if len(sys.argv) < 2:
        print("Unified MidiGPT-REAPER Server Management")
        print("\nUsage:")
        print("  python start_unified.py start     # Start server")
        print("  python start_unified.py stop      # Stop server")  
        print("  python start_unified.py status    # Check server status")
        print("  python start_unified.py verify    # Verify environment")
        print("  python start_unified.py logs      # Show live logs")
        print("  python start_unified.py restart   # Restart server")
        return
    
    command = sys.argv[1].lower()
    
    if command == "start":
        print("Starting unified MidiGPT-REAPER server...")
        
        if not verify_environment():
            return
        
        setup_signal_handlers()
        
        if not start_server():
            print("Failed to start server")
            return
        
        # Keep running and monitor
        try:
            print("\nServer running. Press Ctrl+C to stop.")
            while True:
                status = get_server_status()
                if status == "stopped":
                    print("Server stopped unexpectedly")
                    break
                time.sleep(5)
        except KeyboardInterrupt:
            print("\nShutdown requested")
        finally:
            stop_server()
    
    elif command == "stop":
        stop_server()
    
    elif command == "status":
        status = get_server_status()
        print(f"Server status: {status}")
        
        if status == "running":
            check_port(3456, "XML-RPC endpoint")
    
    elif command == "verify":
        verify_environment()
    
    elif command == "logs":
        tail_logs()
    
    elif command == "restart":
        print("Restarting server...")
        stop_server()
        time.sleep(2)
        
        if start_server():
            print("Server restarted successfully")
        else:
            print("Failed to restart server")
    
    else:
        print(f"Unknown command: {command}")

if __name__ == "__main__":
    main()