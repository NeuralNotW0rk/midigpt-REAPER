#!/usr/bin/env python3
"""
Simple Server Management with correct virtual environment targeting
"""

import subprocess
import signal
import sys
import time
import os
import socket

servers = []

def find_script(filename):
    """Find script in current directory or subdirectories"""
    # Check current directory first
    if os.path.exists(filename):
        return filename
    
    # Check common subdirectory patterns
    possible_paths = [
        os.path.join('src', 'Scripts', 'composers_assistant_v2', filename),
        os.path.join('Scripts', 'composers_assistant_v2', filename),
        os.path.join('composers_assistant_v2', filename),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    return None

def get_python_executable(server_name):
    """Get the correct Python executable for each server"""
    if 'midigpt' in server_name.lower():
        # Use midigpt workspace virtual environment (Python 3.8)
        venv_paths = [
            os.path.join('midigpt_workspace', 'venv', 'bin', 'python'),  # Unix/Mac
            os.path.join('midigpt_workspace', 'venv', 'Scripts', 'python.exe'),  # Windows
            os.path.join('midigpt_workspace', 'venv', 'Scripts', 'python'),  # Windows alt
        ]
        
        for venv_path in venv_paths:
            if os.path.exists(venv_path):
                abs_path = os.path.abspath(venv_path)
                print(f"Using midigpt venv Python: {abs_path}")
                return abs_path
        
        print("WARNING: midigpt venv not found, using system Python")
        print("Expected paths:")
        for path in venv_paths:
            print(f"  - {os.path.abspath(path)}")
        return sys.executable
    
    else:
        # Use project root .venv for proxy server (Python 3.9+)
        proxy_venv_paths = [
            os.path.join('.venv', 'bin', 'python'),  # Unix/Mac
            os.path.join('.venv', 'Scripts', 'python.exe'),  # Windows
            os.path.join('.venv', 'Scripts', 'python'),  # Windows alt
        ]
        
        for venv_path in proxy_venv_paths:
            if os.path.exists(venv_path):
                abs_path = os.path.abspath(venv_path)
                print(f"Using proxy venv Python: {abs_path}")
                return abs_path
        
        print("WARNING: .venv not found for proxy server, using system Python")
        print("Expected paths:")
        for path in proxy_venv_paths:
            print(f"  - {os.path.abspath(path)}")
        return sys.executable

def setup_signal_handlers():
    """Setup signal handlers for clean shutdown"""
    def signal_handler(sig, frame):
        print("\nShutting down servers...")
        stop_servers()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def start_server(script_name, server_name):
    """Start a server with the given script using correct Python executable"""
    script_path = find_script(script_name)
    
    if not script_path:
        print(f"ERROR: {script_name} not found!")
        print(f"Current directory: {os.getcwd()}")
        print("Please run this from the directory containing the server scripts.")
        return False
    
    # Get the correct Python executable for this server
    python_executable = get_python_executable(server_name)
    
    print(f"Starting {server_name}...")
    print(f"Using script: {script_path}")
    print(f"Using Python: {python_executable}")
    
    try:
        process = subprocess.Popen([
            python_executable, script_path
        ])
        
        servers.append((server_name, process))
        print(f"{server_name} started (PID: {process.pid})")
        
        # Give it a moment to start
        time.sleep(1)
        
        # Check if it crashed immediately
        if process.poll() is not None:
            print(f"ERROR: {server_name} crashed immediately (exit code: {process.returncode})")
            return False
        
        return True
        
    except Exception as e:
        print(f"ERROR: Failed to start {server_name}: {e}")
        return False

def check_port(port, service_name):
    """Check if a port is accessible"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    
    if result == 0:
        print(f"{service_name}: healthy")
        return True
    else:
        print(f"{service_name}: port not accessible")
        return False

def stop_servers():
    """Stop all running servers"""
    for name, process in servers:
        try:
            print(f"Stopping {name}...")
            process.terminate()
            process.wait(timeout=5)
            print(f"Stopped {name}")
        except subprocess.TimeoutExpired:
            process.kill()
            print(f"Force killed {name}")
        except Exception as e:
            print(f"ERROR stopping {name}: {e}")
    
    servers.clear()

def verify_environments():
    """Verify that both environments are set up correctly"""
    print("Verifying environments...")
    
    # Check midigpt venv
    midigpt_python = get_python_executable("midigpt server")
    if 'midigpt_workspace' in midigpt_python:
        print(f"✅ midigpt venv found: {midigpt_python}")
    else:
        print("⚠️  WARNING: midigpt venv not found, using system Python")
    
    # Check proxy venv
    proxy_python = get_python_executable("proxy server")
    if '.venv' in proxy_python:
        print(f"✅ Proxy venv found: {proxy_python}")
    else:
        print("⚠️  WARNING: .venv not found for proxy server, using system Python")
    
    return True

def main():
    if len(sys.argv) < 2:
        print("Server Management")
        print("\nUsage:")
        print("  python start_servers.py start    # Start both servers")
        print("  python start_servers.py stop     # Stop servers")
        print("  python start_servers.py status   # Check server status")
        print("  python start_servers.py verify   # Verify environments")
        return
    
    command = sys.argv[1].lower()
    
    if command == "start":
        print("Starting midigpt system...")
        
        # Verify environments first
        if not verify_environments():
            return
        
        setup_signal_handlers()
        
        # Start midigpt server (will use venv)
        if not start_server('midigpt_server.py', 'midigpt server'):
            print("Failed to start midigpt server")
            return
        
        time.sleep(2)
        
        # Start NN proxy server (will use current Python)
        if not start_server('proxy_nn_server.py', 'NN proxy server'):
            print("Failed to start NN proxy server")
            stop_servers()
            return
        
        time.sleep(2)
        
        print("System ready!")
        
        # Check health
        print("Checking server health...")
        check_port(3457, "midigpt server")
        check_port(3456, "NN proxy server")
        
        # Keep running
        try:
            print("\nServers running. Press Ctrl+C to stop.")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_servers()
    
    elif command == "stop":
        stop_servers()
    
    elif command == "status":
        print("Checking server health...")
        check_port(3457, "midigpt server")
        check_port(3456, "NN proxy server")
    
    elif command == "verify":
        verify_environments()
    
    else:
        print(f"Unknown command: {command}")

if __name__ == "__main__":
    main()