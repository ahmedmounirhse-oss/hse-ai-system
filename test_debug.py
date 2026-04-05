#!/usr/bin/env python
"""Test script to debug the /leaderboard endpoint"""
import sys
import time
import requests
import subprocess
import threading

def run_server():
    """Run the Flask server"""
    import os
    os.chdir(r'd:\master\master project\HSE_AI_Platform')
    import app
    # Run with some event capture
    app.app.run(debug=False, use_reloader=False, port=5001)

# Start server in thread
server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

# Wait for server to start
time.sleep(3)

# Test the endpoint
print("Testing /leaderboard endpoint...")
try:
    response = requests.get('http://127.0.0.1:5001/leaderboard', timeout=5)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:1000]}")
except Exception as e:
    print(f"Error: {e}")

# Test a working endpoint for comparison
print("\nTesting /reports endpoint...")
try:
    response = requests.get('http://127.0.0.1:5001/reports', timeout=5)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
