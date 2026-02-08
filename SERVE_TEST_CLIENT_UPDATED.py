#!/usr/bin/env python3
"""
Updated test client server that properly handles SocketIO connections
"""
from flask import Flask, send_from_directory
import os

app = Flask(__name__)

# Serve the test client HTML
@app.route('/')
def serve_test_client():
    return send_from_directory('.', 'test_chat_client.html')

# Add CORS headers for SocketIO
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

if __name__ == '__main__':
    print("🌐 Test Client Server starting...")
    print("📱 Access at: http://localhost:3000")
    print("🔌 SocketIO will connect to: http://localhost:5000/chat")
    print("⚠️  Make sure your Flask-SocketIO server is running on port 5000!")
    
    app.run(host='0.0.0.0', port=3000, debug=True)

