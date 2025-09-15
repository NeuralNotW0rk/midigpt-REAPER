#!/usr/bin/env python3
"""
Server Management Script - Handles all environment setup and server launching
All venv integration and environment logic happens here
"""

import subprocess
import signal
import sys
import time
import os
import socket
import platform
from pathlib import Path

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
    """Get the correct Python executable from venv - all venv logic here"""
    current_dir = Path.cwd()
    
    print(f"Looking for venv in: {current_dir}")
    
    # Priority order: venv, .venv (legacy), system
    if platform.system() == "Windows":
        venv_paths = [
            current_dir / "venv" / "Scripts" / "python.exe",      # New standard
            current_dir / "venv" / "Scripts" / "python",
            current_dir / ".venv" / "Scripts" / "python.exe",    # Legacy
            current_dir / ".venv" / "Scripts" / "python",
        ]
    else:
        venv_paths = [
            current_dir / "venv" / "bin" / "python",             # New standard
            current_dir / ".venv" / "bin" / "python",            # Legacy
        ]
    
    # Debug: show what we're checking
    for venv_path in venv_paths:
        exists = venv_path.exists()
        print(f"Checking {venv_path}: {'EXISTS' if exists else 'NOT FOUND'}")
        if exists:
            # CRITICAL: Return the actual venv path, not the resolved system path
            abs_path = str(venv_path.absolute())  # Use .absolute() not .resolve()
            
            # Double check this is actually in our venv directory
            if str(current_dir) in abs_path and ("venv" in abs_path or ".venv" in abs_path):
                print(f"Using project venv Python: {abs_path}")
                return abs_path
            else:
                print(f"Warning: {venv_path} does not appear to be in project venv")
    
    # Check if venv directories exist but python is missing
    for venv_name in ["venv", ".venv"]:
        venv_dir = current_dir / venv_name
        if venv_dir.exists():
            print(f"Found {venv_name} directory but no proper python executable inside")
            if platform.system() == "Windows":
                print(f"  Expected: {venv_dir}/Scripts/python.exe")
            else:
                print(f"  Expected: {venv_dir}/bin/python")
    
    # Fallback to system Python
    print("No virtual environment found - using system Python")
    print("Run 'python complete_setup.py' to create the virtual environment")
    return sys.executable

def setup_python_environment():
    """Setup Python environment with all necessary paths"""
    python_executable = get_python_executable()
    
    # Setup environment variables for the subprocess
    env = os.environ.copy()
    
    # Add MIDI-GPT paths if they exist - all path logic here
    possible_midigpt_paths = [
        "MIDI-GPT/python_lib",
        "midigpt_workspace/MIDI-GPT/python_lib",
        "../MIDI-GPT/python_lib",
        "../../MIDI-GPT/python_lib",
    ]
    
    python_paths = []
    for path in possible_midigpt_paths:
        if os.path.exists(path):
            abs_path = os.path.abspath(path)
            python_paths.append(abs_path)
    
    if python_paths:
        existing_path = env.get('PYTHONPATH', '')
        if existing_path:
            python_paths.append(existing_path)
        env['PYTHONPATH'] = os.pathsep.join(python_paths)
        print(f"Set PYTHONPATH to include: {python_paths[0]}")
    
    return python_executable, env

def get_server_script():
    """Find the correct server script"""
    possible_scripts = [
        'midigpt_server.py',                  # Primary midigpt server
        'composers_assistant_nn_server.py'    # Fallback to CA server
    ]
    
    for script in possible_scripts:
        script_path = find_script(script)
        if script_path:
            print(f"Found server script: {script_path}")
            return script_path
    
    return None

def setup_signal_handlers():
    """Setup signal handlers for clean shutdown"""
    def signal_handler(sig, frame):
        print(f"\nReceived signal {sig}, shutting down...")
        stop_server()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def start_server():
    """Start the server with proper environment setup"""
    global server_process
    
    script_path = get_server_script()
    if not script_path:
        print("ERROR: No server script found")
        print("Looking for: midigpt_server.py or composers_assistant_nn_server.py")
        return False
    
    # Setup environment - all venv logic happens here
    python_executable, env = setup_python_environment()
    
    # Fix path doubling issue - use absolute path for script
    script_abs_path = os.path.abspath(script_path)
    script_dir = os.path.dirname(script_abs_path)
    
    try:
        print(f"Starting server: {script_path}")
        print(f"Absolute path: {script_abs_path}")
        print(f"Working directory: {script_dir}")
        print(f"Command: {python_executable} {os.path.basename(script_abs_path)}")
        
        server_process = subprocess.Popen(
            [python_executable, os.path.basename(script_abs_path)],
            cwd=script_dir,  # Run from script directory to avoid path issues
            env=env,  # Pass environment with PYTHONPATH set
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Give server time to start and capture initial output
        time.sleep(3)
        
        # Check if process is still running and get any output
        if server_process.poll() is None:
            print("Server started successfully")
            return True
        else:
            print("Server failed to start")
            # Get any error output
            try:
                output, _ = server_process.communicate(timeout=1)
                if output:
                    print("Server output:")
                    print(output)
            except subprocess.TimeoutExpired:
                pass
            return False
            
    except Exception as e:
        print(f"Failed to start server: {e}")
        return False

def stop_server():
    """Stop the server gracefully"""
    global server_process
    
    if server_process is None:
        print("Server not running")
        return True
    
    if server_process.poll() is not None:
        print("Server already stopped")
        server_process = None
        return True
    
    print("Stopping server...")
    try:
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
            print("Server stopped gracefully")
        except subprocess.TimeoutExpired:
            print("Server didn't stop gracefully, forcing...")
            server_process.kill()
            server_process.wait()
            print("Server force stopped")
    except Exception as e:
        print(f"Error stopping server: {e}")
        return False
    
    server_process = None
    return True

def check_port(port):
    """Check if a port is in use"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        result = sock.connect_ex(('localhost', port))
        return result == 0

def get_server_status():
    """Get the current server status"""
    global server_process
    
    if server_process is None:
        return "stopped"
    
    if server_process.poll() is None:
        return "running"
    else:
        return "crashed"

def verify_environment():
    """Verify environment setup - all verification logic here"""
    print("Verifying environment...")
    
    python_executable, env = setup_python_environment()
    
    # Check Python version
    try:
        result = subprocess.run([python_executable, '--version'], 
                              capture_output=True, text=True, env=env)
        print(f"Python version: {result.stdout.strip()}")
        
        # Parse version to ensure it's 3.9+
        version_str = result.stdout.strip().split()[-1]
        major, minor = map(int, version_str.split('.')[:2])
        if major == 3 and minor >= 9:
            print("✅ Python version compatible")
        else:
            print("⚠️ Python version may be incompatible (need 3.9+)")
    except Exception as e:
        print(f"⚠️ Could not verify Python version: {e}")
    
    # Check for MIDI-GPT components
    midigpt_dirs = ['MIDI-GPT', 'MIDI-GPT/python_lib', 'MIDI-GPT/models']
    for dir_name in midigpt_dirs:
        if os.path.exists(dir_name):
            print(f"✅ Found MIDI-GPT component: {dir_name}")
        else:
            print(f"⚠️ Missing MIDI-GPT component: {dir_name}")
    
    # Check for MIDI libraries
    available_libs = []
    for lib in ['mido', 'miditoolkit']:
        try:
            result = subprocess.run([python_executable, '-c', f'import {lib}'],
                                  capture_output=True, text=True, env=env)
            if result.returncode == 0:
                available_libs.append(lib)
        except:
            pass
    
    if available_libs:
        print(f"✅ MIDI libraries available: {', '.join(available_libs)}")
    else:
        print("⚠️  No MIDI libraries found - install mido or miditoolkit")
    
    # Check for midigpt - test both direct and path-based import
    try:
        # Try direct import first (--install flag)
        result = subprocess.run([python_executable, '-c', 'import midigpt; print("midigpt available")'],
                              capture_output=True, text=True, env=env)
        if result.returncode == 0:
            print("✅ midigpt library available")
        else:
            # Try path-based import
            test_cmd = 'import sys; sys.path.append("MIDI-GPT/python_lib"); import midigpt; print("midigpt available")'
            result = subprocess.run([python_executable, '-c', test_cmd],
                                  capture_output=True, text=True, env=env)
            if result.returncode == 0:
                print("✅ midigpt library available (path-based)")
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
        print("MidiGPT-REAPER Server Management")
        print("\nUsage:")
        print("  python start_server.py start     # Start server")
        print("  python start_server.py stop      # Stop server")  
        print("  python start_server.py status    # Check server status")
        print("  python start_server.py verify    # Verify environment")
        print("  python start_server.py logs      # Show live logs")
        print("  python start_server.py restart   # Restart server")
        return
    
    command = sys.argv[1].lower()
    
    if command == "start":
        print("Starting MidiGPT-REAPER server...")
        
        if not verify_environment():
            return
        
        setup_signal_handlers()
        
        if not start_server():
            print("Failed to start server")
            return
        
        # Keep running and monitor
        try:
            print("\nServer running. Press Ctrl+C to stop.")
            while server_process and server_process.poll() is None:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            stop_server()
    
    elif command == "stop":
        stop_server()
    
    elif command == "status":
        status = get_server_status()
        port_status = "in use" if check_port(3456) else "free"
        print(f"Server status: {status}")
        print(f"Port 3456: {port_status}")
    
    elif command == "verify":
        verify_environment()
    
    elif command == "logs":
        tail_logs()
    
    elif command == "restart":
        print("Restarting server...")
        stop_server()
        time.sleep(1)
        if start_server():
            try:
                print("\nServer restarted. Press Ctrl+C to stop.")
                while server_process and server_process.poll() is None:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nShutting down...")
            finally:
                stop_server()
    
    else:
        print(f"Unknown command: {command}")

if __name__ == "__main__":
    main()