#!/usr/bin/env python3
"""
Simple HTTP server to serve the test client HTML file locally.
This fixes CORS issues when loading HTML files directly.
"""

from flask import Flask, send_from_directory
import os

app = Flask(__name__)

@app.route('/')
def serve_test_client():
    """Serve the authenticated test client HTML file"""
    return send_file_from_current_dir('authenticated_test_client.html')

def send_file_from_current_dir(filename):
    """Helper to send file from current directory"""
    try:
        return send_from_directory('.', filename)
    except Exception as e:
        print(f"Error serving file {filename}: {e}")
        return """
        <!DOCTYPE html>
        <html>
        <head><title>Test Client Server</title></head>
        <body>
            <h1>Test Client Server</h1>
            <p>Could not serve file: """ + filename + """</p>
            <p>Make sure the file exists in the current directory.</p>
            <p>Error: """ + str(e) + """</p>
        </body>
        </html>""", 500

if __name__ == '__main__':
    print("🚀 Starting test client server...")
    print("📁 Serving files from:", os.getcwd())
    print("🌐 Open: http://localhost:3000")
    print("⚠️  Authenticated test client connects to: https://test.api.marktcommerce.com")
    app.run(host='127.0.0.1', port=3000, debug=True)
