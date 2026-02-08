# 🧪 Chat Discount System Testing Guide

## 🚀 Quick Start Testing

### **Option 1: Test Mode (Recommended for Development)**

1. **Enable Test Mode** - Temporarily replace the chat namespace import:
   ```bash
   # In main/sockets.py, change:
   from app.chats.sockets import ChatNamespace
   # To:
   from app.chats.test_sockets import TestChatNamespace
   
   # And update the namespace registration:
   socketio.on_namespace(TestChatNamespace("/chat"))
   ```

2. **Start the Server**:
   ```bash
   python3 -m main.run
   ```

3. **Open Test Client**:
   ```bash
   # Open test_chat_client.html in your browser
   open test_chat_client.html
   ```

4. **Test the Flow**:
   - Connect as Seller with any ID (e.g., "test_seller")
   - Connect as Buyer with any ID (e.g., "test_buyer") 
   - Use Room ID: 1
   - Create discount offers and test responses

### **Option 2: Full Authentication (Production-like)**

1. **Create Test Data**:
   ```bash
   python3 test_auth_setup.py
   ```

2. **Use the provided IDs** in your test client

3. **Test with real authentication** (requires proper login setup)

## 🎯 Testing Scenarios

### **Scenario 1: Basic Discount Flow**
1. **Seller** creates a 15% discount offer
2. **Buyer** receives real-time notification
3. **Buyer** accepts the offer
4. **Seller** sees acceptance notification

### **Scenario 2: Discount Application**
1. Create an accepted discount
2. Test applying it to different order amounts
3. Verify discount calculations
4. Test with minimum order requirements

### **Scenario 3: Edge Cases**
1. **Expired Discounts** - Test with past expiry dates
2. **Usage Limits** - Test multiple applications
3. **Invalid Amounts** - Test with invalid discount values
4. **Real-time Events** - Verify all websocket events fire

## 🔧 Test Client Features

### **Seller Panel**
- ✅ Create discount offers (percentage/fixed amount)
- ✅ Set minimum order amounts
- ✅ Set maximum discount caps
- ✅ Custom discount messages
- ✅ Expiry date configuration

### **Buyer Panel**
- ✅ Accept/reject discount offers
- ✅ Test discount application
- ✅ Real-time notifications
- ✅ Order amount testing

### **Real-time Features**
- ✅ Instant discount notifications
- ✅ Live chat messages
- ✅ Connection status monitoring
- ✅ Event logging

## 🐛 Troubleshooting

### **Common Issues**

1. **"Access denied to this room"**
   - **Solution**: Use Test Mode or create proper test data

2. **"Unauthorized" errors**
   - **Solution**: Enable Test Mode or set up authentication

3. **WebSocket connection fails**
   - **Check**: Server is running on correct port
   - **Check**: Socket.IO namespace is correct (`/chat`)

4. **Migration errors**
   - **Solution**: Run `flask db upgrade` to apply migrations

### **Debug Mode**

Enable detailed logging in your Flask app:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 📊 Expected Behavior

### **Discount Creation**
- Seller creates discount → Real-time notification to buyer
- Discount appears in chat with accept/reject buttons
- All validation rules apply (min/max amounts, expiry)

### **Discount Response**
- Buyer accepts/rejects → Real-time notification to seller
- Status updates immediately
- Chat message shows response

### **Discount Application**
- Calculate correct discount amounts
- Respect minimum order requirements
- Handle usage limits properly
- Real-time notifications for usage

## 🎉 Success Criteria

✅ **All discount types work** (percentage, fixed amount)  
✅ **Real-time notifications** fire correctly  
✅ **Validation** prevents invalid discounts  
✅ **Status tracking** works throughout lifecycle  
✅ **WebSocket events** are reliable  
✅ **API endpoints** return correct data  
✅ **Database persistence** maintains state  

## 🔄 Production Deployment

When ready for production:

1. **Revert Test Mode**:
   ```bash
   # Change back to:
   from app.chats.sockets import ChatNamespace
   ```

2. **Set up proper authentication** for real users

3. **Configure production database** and Redis

4. **Test with real user accounts** and actual products

---

**Happy Testing! 🚀**


