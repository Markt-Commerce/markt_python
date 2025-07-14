# Markt API - Postman Collection Guide

## 🚀 **Quick Start**

### **Base URL**
```
Development: http://localhost:8000/api/v1
Production: https://your-domain.com/api/v1
```

### **Authentication**
All authenticated endpoints require a Bearer token in the Authorization header:
```
Authorization: Bearer <your_jwt_token>
```

---

## 📋 **Authentication Endpoints**

### **1. User Registration**
```http
POST /auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword123",
  "username": "testuser",
  "first_name": "John",
  "last_name": "Doe",
  "phone": "+2348012345678",
  "role": "buyer" // or "seller"
}
```

### **2. User Login**
```http
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

### **3. Refresh Token**
```http
POST /auth/refresh
Authorization: Bearer <refresh_token>
```

---

## 🛍️ **Product Endpoints**

### **1. Search Products (with caching)**
```http
GET /products/search?search=laptop&min_price=100&max_price=1000&category_id=1&page=1&per_page=20&sort_by=price&sort_order=asc
```

### **2. Get Product Details**
```http
GET /products/PROD_12345678
```

### **3. Create Product (Seller only)**
```http
POST /products/
Authorization: Bearer <seller_token>
Content-Type: application/json

{
  "name": "MacBook Pro 2024",
  "description": "Latest MacBook Pro with M3 chip",
  "price": 1299.99,
  "category_id": 1,
  "variants": [
    {
      "name": "16GB RAM, 512GB SSD",
      "price": 1499.99,
      "sku": "MBP-16-512",
      "inventory": 10
    }
  ],
  "metadata": {
    "brand": "Apple",
    "warranty": "1 year"
  }
}
```

### **4. Update Product**
```http
PUT /products/PROD_12345678
Authorization: Bearer <seller_token>
Content-Type: application/json

{
  "name": "MacBook Pro 2024 (Updated)",
  "price": 1199.99,
  "status": "active"
}
```

---

## 🛒 **Cart Endpoints**

### **1. Add to Cart**
```http
POST /cart/add
Authorization: Bearer <buyer_token>
Content-Type: application/json

{
  "product_id": "PROD_12345678",
  "quantity": 2,
  "variant_id": 1
}
```

### **2. Get Cart**
```http
GET /cart/
Authorization: Bearer <buyer_token>
```

### **3. Update Cart Item**
```http
PUT /cart/items/1
Authorization: Bearer <buyer_token>
Content-Type: application/json

{
  "quantity": 3
}
```

### **4. Remove from Cart**
```http
DELETE /cart/items/1
Authorization: Bearer <buyer_token>
```

### **5. Clear Cart**
```http
DELETE /cart/clear
Authorization: Bearer <buyer_token>
```

---

## 💳 **Payment Endpoints**

### **1. Initialize Payment (Paystack)**
```http
POST /payments/initialize
Authorization: Bearer <buyer_token>
Content-Type: application/json

{
  "order_id": "ORD_12345678",
  "amount": 2599.98,
  "currency": "NGN",
  "method": "card",
  "metadata": {
    "customer_note": "Please deliver before 5pm"
  }
}
```

### **2. Process Payment**
```http
POST /payments/PAY_12345678/process
Authorization: Bearer <buyer_token>
Content-Type: application/json

{
  "authorization_code": "AUTH_1234567890",
  "card_token": "CARD_TOKEN_123"
}
```

### **3. Verify Payment**
```http
GET /payments/PAY_12345678/verify
Authorization: Bearer <buyer_token>
```

### **4. Get Payment Details**
```http
GET /payments/PAY_12345678
Authorization: Bearer <buyer_token>
```

### **5. List User Payments**
```http
GET /payments/?page=1&per_page=20
Authorization: Bearer <buyer_token>
```

---

## 📦 **Order Endpoints**

### **1. Create Order from Cart**
```http
POST /orders/
Authorization: Bearer <buyer_token>
Content-Type: application/json

{
  "cart_id": 1,
  "shipping_address": {
    "street": "123 Main St",
    "city": "Lagos",
    "state": "Lagos",
    "postal_code": "100001",
    "country": "Nigeria"
  },
  "payment_method": "card"
}
```

### **2. Get Order Details**
```http
GET /orders/ORD_12345678
Authorization: Bearer <buyer_token>
```

### **3. List User Orders**
```http
GET /orders/
Authorization: Bearer <buyer_token>
```

### **4. Seller Order Management**
```http
GET /orders/seller?status=pending&page=1&per_page=20
Authorization: Bearer <seller_token>
```

### **5. Update Order Item Status**
```http
PATCH /orders/seller/items/1
Authorization: Bearer <seller_token>
Content-Type: application/json

{
  "status": "shipped"
}
```

---

## 🔍 **Buyer Request Endpoints**

### **1. Create Buyer Request**
```http
POST /requests/
Authorization: Bearer <buyer_token>
Content-Type: application/json

{
  "title": "Looking for iPhone 15 Pro",
  "description": "Need iPhone 15 Pro 256GB in good condition",
  "category_id": 2,
  "budget": 800000,
  "expires_at": "2024-02-15T00:00:00Z",
  "images": [
    {
      "url": "https://example.com/image1.jpg",
      "is_primary": true
    }
  ],
  "metadata": {
    "condition": "new",
    "color": "natural_titanium"
  }
}
```

### **2. Search Requests**
```http
GET /requests/search?search=iPhone&category_id=2&min_budget=500000&max_budget=1000000&page=1&per_page=20
```

### **3. Get Request Details**
```http
GET /requests/REQ_12345678
Authorization: Bearer <buyer_token>
```

### **4. Create Offer (Seller)**
```http
POST /requests/REQ_12345678/offers
Authorization: Bearer <seller_token>
Content-Type: application/json

{
  "price": 750000,
  "description": "Brand new iPhone 15 Pro 256GB Natural Titanium",
  "delivery_time": "2-3 days",
  "warranty": "1 year Apple warranty",
  "images": [
    {
      "url": "https://example.com/offer-image.jpg"
    }
  ]
}
```

### **5. Accept Offer**
```http
POST /requests/offers/1/accept
Authorization: Bearer <buyer_token>
```

---

## 🏘️ **Niche/Community Endpoints**

### **1. Create Niche**
```http
POST /socials/niches/
Authorization: Bearer <seller_token>
Content-Type: application/json

{
  "name": "Tech Enthusiasts Nigeria",
  "description": "Community for tech lovers in Nigeria",
  "slug": "tech-enthusiasts-ng",
  "visibility": "public",
  "allow_buyer_posts": true,
  "allow_seller_posts": true,
  "require_approval": true,
  "max_members": 1000,
  "category_id": 1,
  "tags": ["technology", "nigeria", "community"],
  "rules": [
    "No spam",
    "Be respectful",
    "No self-promotion without approval"
  ]
}
```

### **2. Join Niche**
```http
POST /socials/niches/NICHE_12345678/join
Authorization: Bearer <buyer_token>
```

### **3. Get Niche Posts**
```http
GET /socials/niches/NICHE_12345678/posts?page=1&per_page=20
Authorization: Bearer <buyer_token>
```

### **4. Create Post in Niche**
```http
POST /socials/niches/NICHE_12345678/posts
Authorization: Bearer <buyer_token>
Content-Type: application/json

{
  "caption": "Just got the new iPhone 15 Pro! Amazing camera quality!",
  "products": ["PROD_12345678"],
  "media": [
    {
      "url": "https://example.com/post-image.jpg",
      "type": "image"
    }
  ]
}
```

---

## 🔔 **Notification Endpoints**

### **1. Get Notifications**
```http
GET /notifications/?page=1&per_page=20&unread_only=true
Authorization: Bearer <buyer_token>
```

### **2. Mark as Read**
```http
POST /notifications/mark-read
Authorization: Bearer <buyer_token>
Content-Type: application/json

{
  "notification_ids": [1, 2, 3]
}
```

### **3. Get Unread Count**
```http
GET /notifications/unread-count
Authorization: Bearer <buyer_token>
```

---

## 🏥 **Health Check Endpoints**

### **1. Basic Health Check**
```http
GET /health/
```

### **2. Detailed Health Check**
```http
GET /health/detailed
```

### **3. Readiness Check**
```http
GET /health/ready
```

### **4. Liveness Check**
```http
GET /health/live
```

### **5. Metrics Endpoint**
```http
GET /health/metrics
```

### **6. Status Endpoint**
```http
GET /health/status
```

---

## 🔧 **Testing Flows**

### **Flow 1: Complete Purchase Flow**
1. **Register Buyer Account**
2. **Login Buyer**
3. **Search Products**
4. **Add to Cart**
5. **Create Order**
6. **Initialize Payment**
7. **Process Payment**
8. **Verify Payment**

### **Flow 2: Seller Product Management**
1. **Register Seller Account**
2. **Login Seller**
3. **Create Product**
4. **Update Product**
5. **View Orders**
6. **Update Order Status**

### **Flow 3: Buyer Request Flow**
1. **Login Buyer**
2. **Create Request**
3. **Login Seller**
4. **Search Requests**
5. **Create Offer**
6. **Login Buyer**
7. **Accept Offer**

### **Flow 4: Community Engagement**
1. **Login User**
2. **Create Niche**
3. **Join Niche**
4. **Create Post**
5. **Like/Comment on Post**

---

## 📊 **Rate Limiting**

### **Default Limits**
- **Buyer endpoints**: 60 requests/minute
- **Seller endpoints**: 30 requests/minute
- **Admin endpoints**: 10 requests/minute
- **Public endpoints**: 100 requests/minute

### **Rate Limit Headers**
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1640995200
```

---

## 🛡️ **Security Headers**

### **Required Headers**
```
Authorization: Bearer <token>
Content-Type: application/json
User-Agent: PostmanRuntime/7.29.0
```

### **Optional Headers**
```
X-Request-ID: <unique_request_id>
X-Client-Version: 1.0.0
```

---

## 📝 **Error Responses**

### **400 Bad Request**
```json
{
  "error": "Validation failed",
  "message": "Invalid input data",
  "details": {
    "field": "email",
    "error": "Invalid email format"
  }
}
```

### **401 Unauthorized**
```json
{
  "error": "Authentication required",
  "message": "Valid token required"
}
```

### **403 Forbidden**
```json
{
  "error": "Access denied",
  "message": "Insufficient permissions"
}
```

### **429 Too Many Requests**
```json
{
  "error": "Rate limit exceeded",
  "message": "Maximum 60 requests per minute"
}
```

### **500 Internal Server Error**
```json
{
  "error": "Internal server error",
  "message": "Something went wrong"
}
```

---

## 🎯 **Postman Environment Variables**

### **Development Environment**
```
base_url: http://localhost:8000/api/v1
auth_token: <your_jwt_token>
refresh_token: <your_refresh_token>
user_id: <current_user_id>
seller_id: <seller_account_id>
buyer_id: <buyer_account_id>
```

### **Production Environment**
```
base_url: https://your-domain.com/api/v1
auth_token: <your_jwt_token>
refresh_token: <your_refresh_token>
user_id: <current_user_id>
seller_id: <seller_account_id>
buyer_id: <buyer_account_id>
```

---

## 🔄 **WebSocket Events**

### **Connection**
```javascript
// Connect to Socket.IO
const socket = io('http://localhost:8000', {
  auth: {
    token: 'your_jwt_token'
  }
});

// Join namespaces
socket.emit('join', { namespace: '/notifications' });
socket.emit('join', { namespace: '/orders' });
socket.emit('join', { namespace: '/social' });
```

### **Listen for Events**
```javascript
// Notifications
socket.on('notification', (data) => {
  console.log('New notification:', data);
});

// Order updates
socket.on('order_status', (data) => {
  console.log('Order status update:', data);
});

// Payment updates
socket.on('payment_update', (data) => {
  console.log('Payment update:', data);
});

// Social interactions
socket.on('post_like', (data) => {
  console.log('Post liked:', data);
});
```

---

## 📈 **Performance Testing**

### **Load Testing with Artillery**
```yaml
# artillery-config.yml
config:
  target: 'http://localhost:8000'
  phases:
    - duration: 60
      arrivalRate: 10
  defaults:
    headers:
      Authorization: 'Bearer {{ $randomString() }}'

scenarios:
  - name: "Product Search"
    flow:
      - get:
          url: "/api/v1/products/search?search=laptop&page=1"
```

### **Stress Testing**
```bash
# Using Apache Bench
ab -n 1000 -c 10 http://localhost:8000/api/v1/health/

# Using wrk
wrk -t12 -c400 -d30s http://localhost:8000/api/v1/health/
```

---

## 🎉 **Success!**

You now have a comprehensive Postman collection for testing all Markt API endpoints. The collection includes:

✅ **Authentication flows**  
✅ **Product management**  
✅ **Cart and checkout**  
✅ **Payment processing**  
✅ **Order management**  
✅ **Buyer requests**  
✅ **Community features**  
✅ **Real-time notifications**  
✅ **Health monitoring**  
✅ **Rate limiting**  
✅ **Error handling**  

Happy testing! 🚀 