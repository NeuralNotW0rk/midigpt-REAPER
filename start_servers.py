#!/usr/bin/env python3
"""
Lean Server Management Script
Simplified version for dual server architecture
"""

import os
import sys
import subprocess
import time
import signal
import platform

# Simple configuration - using absolute paths
MIDIGPT_VENV = "midigpt_workspace/venv"
NN_VENV = ".venv"
MIDIGPT_SCRIPT = "midigpt_server.py"
NN_SCRIPT = "src/Scripts/composers_assistant_v2/proxy_nn_server.py"

# Global server processes
servers = {}

def get_python_exe(venv_path):
    """Get Python executable from venv with absolute path resolution"""
    # Convert to absolute path to avoid issues when changing working directories
    abs_venv_path = os.path.abspath(venv_path)
    
    if not os.path.exists(abs_venv_path):
        print(f"ERROR: Virtual environment not found: {abs_venv_path}")
        return None
    
    if platform.system() == "Windows":
        python_exe = os.path.join(abs_venv_path, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(abs_venv_path, "bin", "python")
    
    if os.path.exists(python_exe):
        try:
            result = subprocess.run([python_exe, "--version"], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return python_exe
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    
    print(f"ERROR: Python executable not found at: {python_exe}")
    return None

def start_midigpt():
    """Start midigpt server (Python 3.8)"""
    print("Starting midigpt server...")
    
    python_exe = get_python_exe(MIDIGPT_VENV)
    if not python_exe:
        print("ERROR: midigpt venv not found")
        return False
    
    if not os.path.exists(MIDIGPT_SCRIPT):
        print(f"ERROR: midigpt script not found: {MIDIGPT_SCRIPT}")
        return False
    
    try:
        # Set PYTHONPATH to include midigpt workspace
        env = os.environ.copy()
        midigpt_path = os.path.abspath(os.path.join("midigpt_workspace", "MIDI-GPT", "python_lib"))
        if os.path.exists(midigpt_path):
            current_pythonpath = env.get('PYTHONPATH', '')
            env['PYTHONPATH'] = f"{midigpt_path}:{current_pythonpath}" if current_pythonpath else midigpt_path
        
        process = subprocess.Popen([python_exe, MIDIGPT_SCRIPT], env=env)
        servers['midigpt'] = process
        print(f"midigpt server started (PID: {process.pid})")
        return True
    except Exception as e:
        print(f"ERROR: Failed to start midigpt: {e}")
        return False

def start_nn():
    """Start NN proxy server (Python 3.9)"""
    print("Starting NN proxy server...")
    
    python_exe = get_python_exe(NN_VENV)
    if not python_exe:
        print("ERROR: NN venv not found")
        return False
    
    if not os.path.exists(NN_SCRIPT):
        print(f"ERROR: NN script not found: {NN_SCRIPT}")
        return False
    
    try:
        # Run from the script's directory
        script_dir = os.path.dirname(NN_SCRIPT)
        script_name = os.path.basename(NN_SCRIPT)
        
        # Use absolute path for python_exe so it works when cwd changes
        process = subprocess.Popen([python_exe, script_name], cwd=script_dir)
        servers['nn'] = process
        print(f"NN proxy server started (PID: {process.pid})")
        return True
    except Exception as e:
        print(f"ERROR: Failed to start NN proxy: {e}")
        return False

def stop_servers():
    """Stop all servers"""
    print("Stopping servers...")
    
    for name, process in servers.items():
        try:
            process.terminate()
            process.wait(timeout=5)
            print(f"Stopped {name} server")
        except subprocess.TimeoutExpired:
            process.kill()
            print(f"Force killed {name} server")
        except Exception as e:
            print(f"ERROR: Error stopping {name}: {e}")
    
    servers.clear()

def check_health(verbose=False):
    """Quick health check with better error reporting"""
    print("Checking server health...")
    
    # Check midigpt
    try:
        import requests
        response = requests.get('http://127.0.0.1:3457/health', timeout=2)
        if response.status_code == 200:
            print("midigpt server: healthy")
        else:
            print(f"midigpt server: status {response.status_code}")
            if verbose:
                print(f"  Response: {response.text[:200]}")
    except requests.exceptions.ConnectionError as e:
        print("midigpt server: connection refused")
        if verbose:
            print(f"  Details: {e}")
    except requests.exceptions.Timeout as e:
        print("midigpt server: timeout")
        if verbose:
            print(f"  Details: {e}")
    except Exception as e:
        print(f"midigpt server: error - {type(e).__name__}: {e}")
    
    # Check NN proxy
    try:
        import xmlrpc.client
        proxy = xmlrpc.client.ServerProxy('http://127.0.0.1:3456')
        # Test with both required arguments - s (string input) and S (song dict)
        result = proxy.call_nn_infill('<extra_id_0>N:60;d:240', {})
        if result and '<extra_id_0>' in result:
            print("NN proxy server: healthy")
            if verbose:
                print(f"  Sample response: {result[:50]}...")
        else:
            print("NN proxy server: unexpected response")
            if verbose:
                print(f"  Response: {result}")
    except xmlrpc.client.ProtocolError as e:
        print(f"NN proxy server: protocol error - {e.errcode}: {e.errmsg}")
        if verbose:
            print(f"  URL: {e.url}")
            print(f"  Headers: {e.headers}")
    except xmlrpc.client.Fault as e:
        print(f"NN proxy server: RPC fault - {e.faultCode}: {e.faultString}")
        if verbose:
            print(f"  This usually means the server is running but there's an issue with the function call")
    except ConnectionRefusedError as e:
        print("NN proxy server: connection refused")
        if verbose:
            print(f"  Details: {e}")
    except Exception as e:
        print(f"NN proxy server: error - {type(e).__name__}: {e}")
        if verbose:
            import traceback
            print(f"  Full traceback:")
            traceback.print_exc()

def main():
    """Main function with verbose option"""
    if len(sys.argv) < 2:
        print("Lean Server Management")
        print("\nUsage:")
        print("  python start_servers.py start [--verbose]    # Start both servers")
        print("  python start_servers.py stop                 # Stop servers")
        print("  python start_servers.py status [--verbose]   # Check health")
        return
    
    command = sys.argv[1].lower()
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    
    if command == "start":
        print("Starting midigpt system...")
        setup_signal_handlers()
        
        # Start midigpt first
        if not start_midigpt():
            print("ERROR: Failed to start midigpt server")
            return
        
        # Wait for startup
        time.sleep(2)
        
        # Start NN proxy
        if not start_nn():
            print("ERROR: Failed to start NN proxy")
            stop_servers()
            return
        
        # Wait for startup
        time.sleep(2)
        
        print("System ready!")
        check_health(verbose=verbose)
        
        # Keep running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_servers()
    
    elif command == "stop":
        stop_servers()
    
    elif command == "status":
        check_health(verbose=verbose)
    
    else:
        print(f"ERROR: Unknown command: {command}")


def setup_signal_handlers():
    """Setup graceful shutdown"""
    def signal_handler(sig, frame):
        print("\nReceived shutdown signal...")
        stop_servers()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Lean Server Management")
        print("\nUsage:")
        print("  python start_servers.py start    # Start both servers")
        print("  python start_servers.py stop     # Stop servers")
        print("  python start_servers.py status   # Check health")
        return
    
    command = sys.argv[1].lower()
    
    if command == "start":
        print("Starting midigpt system...")
        setup_signal_handlers()
        
        # Start midigpt first
        if not start_midigpt():
            print("ERROR: Failed to start midigpt server")
            return
        
        # Wait for startup
        time.sleep(2)
        
        # Start NN proxy
        if not start_nn():
            print("ERROR: Failed to start NN proxy")
            stop_servers()
            return
        
        # Wait for startup
        time.sleep(2)
        
        print("System ready!")
        check_health()
        
        # Keep running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_servers()
    
    elif command == "stop":
        stop_servers()
    
    elif command == "status":
        check_health()
    
    else:
        print(f"ERROR: Unknown command: {command}")

if __name__ == "__main__":
    main()