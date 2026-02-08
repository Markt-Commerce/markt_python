from flask import Flask, send_from_directory
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app, supports_credentials=True, origins=['http://localhost:3000'])  # Enable CORS with credentials

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def serve_file(filename):
    return send_from_directory('.', filename)

if __name__ == '__main__':
    print("🚀 Starting Test UI Server...")
    print("📱 Open your browser and go to: http://localhost:3000")
    print("🔗 Make sure your Flask API server is running on: http://127.0.0.1:8000")
    print("⚡ Real-time websocket events will be visible in the browser console")
    print("\n" + "="*50)
    print("🎯 Test Features:")
    print("✅ Authentication (Login/Logout)")
    print("✅ Create Posts")
    print("✅ Like Posts (Real-time)")
    print("✅ Add Comments")
    print("✅ React to Comments (Real-time)")
    print("✅ Chat Messages")
    print("✅ React to Chat Messages (Real-time)")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=3000, debug=True) 