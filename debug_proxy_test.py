#!/usr/bin/env python3
"""
Debug script to test NN proxy server directly
"""

import sys
import os

# Add the path to make sure we can import
sys.path.insert(0, 'src/Scripts/composers_assistant_v2')

# Change to the correct directory
os.chdir('src/Scripts/composers_assistant_v2')

print("Testing NN proxy server...")
print(f"Current directory: {os.getcwd()}")
print(f"Python path: {sys.path}")

try:
    # Import and run the proxy server with debug enabled
    import proxy_nn_server
    
    # Enable debug mode
    proxy_nn_server.DEBUG = True
    
    print("Starting server with debug enabled...")
    proxy_nn_server.start_xmlrpc_server()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()