# 🎯 Markt Test UI - Social & Chat System

A comprehensive test interface for visually testing the social media and chat features with real-time websocket functionality.

## 🚀 Quick Start

### Prerequisites
- Python 3.7+
- Flask API server running on `127.0.0.1:8000`
- WebSocket server enabled

### Setup

1. **Install dependencies:**
```bash
pip install flask flask-cors
```

2. **Start the test UI server:**
```bash
cd test_ui
python server.py
```

3. **Open your browser:**
```
http://localhost:3000
```

## 🎯 Features to Test

### ✅ Authentication
- **Login/Logout** - Test user authentication flow
- **Token Management** - Automatic token storage and usage
- **User Info Display** - Shows logged-in user details

### ✅ Posts System
- **Create Posts** - Write and publish new posts
- **View Posts** - See all posts with author and timestamp
- **Like Posts** - Click like button with real-time updates
- **Real-time Like Updates** - See likes from other users instantly

### ✅ Comments System
- **Add Comments** - Comment on any post
- **View Comments** - See all comments with author info
- **React to Comments** - Use emoji reactions (❤️, 👍, 🔥, ⭐)
- **Real-time Reaction Updates** - See reactions from other users instantly

### ✅ Chat System
- **Send Messages** - Type and send chat messages
- **View Messages** - See conversation history
- **React to Messages** - Add emoji reactions to chat messages
- **Real-time Message Reactions** - See reactions instantly
- **Bot Responses** - Simulated responses for testing

### ✅ Real-time Features
- **WebSocket Connection** - Live connection status indicator
- **Instant Updates** - All interactions update in real-time
- **Visual Feedback** - Status messages for all actions
- **Console Logging** - Detailed logs in browser console

## 🔧 Configuration

The test UI is configured to connect to:
- **API Base URL:** `http://127.0.0.1:8000/api/v1`
- **WebSocket URL:** `http://127.0.0.1:8000`

### Default Test Credentials
- **Email:** `test@example.com`
- **Password:** `password123`

## 🧪 Testing Scenarios

### 1. Basic Authentication
1. Open the test UI
2. Click "Login" with default credentials
3. Verify user info appears
4. Test logout functionality

### 2. Posts & Likes
1. Create a new post
2. Verify post appears in the list
3. Click the like button
4. Open another browser tab/window
5. Verify like count updates in real-time

### 3. Comments & Reactions
1. Click "Comment" on any post
2. Add a comment
3. Click reaction emojis (❤️, 👍, 🔥, ⭐)
4. Open another browser tab
5. Verify reactions appear in real-time

### 4. Chat System
1. Type a message in the chat
2. Press Enter or click Send
3. Wait for bot response
4. Add reactions to messages
5. Test real-time reaction updates

### 5. Multi-User Testing
1. Open multiple browser tabs/windows
2. Login with different users (if available)
3. Interact with posts/comments/chat
4. Verify real-time updates across all tabs

## 🔍 Debugging

### Browser Console
Open browser developer tools (F12) to see:
- WebSocket connection status
- Real-time event logs
- API request/response details
- Error messages

### Network Tab
Monitor:
- API requests to `/api/v1/*`
- WebSocket connections
- Real-time event emissions

### Common Issues

1. **Connection Failed**
   - Ensure Flask API server is running on port 8000
   - Check CORS settings
   - Verify WebSocket server is enabled

2. **Authentication Errors**
   - Check if auth endpoints are working
   - Verify token format
   - Test with valid credentials

3. **Real-time Not Working**
   - Check WebSocket connection status
   - Verify event handlers are registered
   - Check browser console for errors

## 📱 Mobile Testing

The UI is responsive and works on:
- **Mobile browsers** (iOS Safari, Android Chrome)
- **Tablets** (iPad, Android tablets)
- **Desktop browsers** (Chrome, Firefox, Safari, Edge)

## 🎨 UI Features

### Modern Design
- **Gradient background** with modern styling
- **Card-based layout** for easy reading
- **Responsive design** for all screen sizes
- **Smooth animations** and hover effects

### Visual Indicators
- **Real-time status** indicator (top-right)
- **Success/Error messages** with auto-dismiss
- **Loading states** for all operations
- **Connection status** for WebSocket

### Interactive Elements
- **Hover effects** on buttons and cards
- **Click animations** for reactions
- **Auto-scroll** in chat
- **Keyboard shortcuts** (Enter to send)

## 🔧 Customization

### API Endpoints
Edit the configuration in `index.html`:
```javascript
const API_BASE = 'http://127.0.0.1:8000/api/v1';
const SOCKET_URL = 'http://127.0.0.1:8000';
```

### Styling
Modify the CSS in the `<style>` section to:
- Change colors and themes
- Adjust layout and spacing
- Add custom animations
- Modify responsive breakpoints

### Test Data
Add more test scenarios by:
- Creating additional bot responses
- Adding more reaction types
- Simulating different user interactions

## 📊 Performance

The test UI is optimized for:
- **Fast loading** with CDN resources
- **Efficient rendering** with minimal DOM updates
- **Memory management** with proper cleanup
- **Network optimization** with request caching

## 🚀 Production Notes

For production deployment:
1. **Security** - Add proper authentication
2. **Error Handling** - Implement comprehensive error handling
3. **Logging** - Add server-side logging
4. **Monitoring** - Add performance monitoring
5. **Testing** - Add automated tests

## 📞 Support

If you encounter issues:
1. Check the browser console for errors
2. Verify server connectivity
3. Test with different browsers
4. Check network connectivity
5. Review server logs

---

**Happy Testing! 🎉** 