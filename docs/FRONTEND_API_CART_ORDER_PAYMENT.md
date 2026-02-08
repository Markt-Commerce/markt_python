# Frontend API Documentation: Cart, Order, Checkout & Payment Flow

This document provides complete API contracts for the frontend team to implement the cart, checkout, order, and payment flow.

**Base URL**: `/api/v1`

**Authentication**: All endpoints require authentication via `Authorization: Bearer <token>` header.

**Platform Support**: This API is platform-agnostic and works with:
- ✅ **Web** (React, Vue, Angular, etc.)
- ✅ **Mobile** (React Native, Flutter, Native iOS/Android)
- ✅ **Desktop** (Electron, etc.)

All examples use standard HTTP/REST, making them compatible with any HTTP client library.

**📱 React Native Users**: See [React Native Payment Flow Guide](./REACT_NATIVE_PAYMENT_FLOW.md) for mobile-specific implementation details, including in-app payment setup with Paystack SDK.

---

## Table of Contents

1. [Cart APIs](#cart-apis)
2. [Order APIs](#order-apis)
3. [Payment APIs](#payment-apis)
4. [Complete Flow Examples](#complete-flow-examples)
5. [Error Handling](#error-handling)
6. [WebSocket Events](#websocket-events)

---

## Cart APIs

### 1. Get Cart

**Endpoint**: `GET /cart`

**Description**: Retrieve the current user's active cart with all items.

**Response**:
```json
{
  "id": 123,
  "buyer_id": 456,
  "expires_at": "2024-02-15T10:30:00Z",
  "coupon_code": null,
  "items": [
    {
      "id": 789,
      "product_id": "PRD_ABC123",
      "variant_id": 1,
      "quantity": 2,
      "product_price": 29.99,
      "product": {
        "id": "PRD_ABC123",
        "name": "Product Name",
        "price": 29.99,
        "images": [...]
      }
    }
  ],
  "total_items": 2,
  "subtotal": 59.98
}
```

**Status Codes**:
- `200 OK`: Cart retrieved successfully
- `401 Unauthorized`: Not authenticated
- `403 Forbidden`: User is not a buyer

---

### 2. Add Item to Cart

**Endpoint**: `POST /cart/add`

**Description**: Add a product to the cart or update quantity if item already exists.

**Request Body**:
```json
{
  "product_id": "PRD_ABC123",
  "quantity": 2,
  "variant_id": 1  // Optional, omit for products without variants
}
```

**Response**:
```json
{
  "id": 789,
  "cart_id": 123,
  "product_id": "PRD_ABC123",
  "variant_id": 1,
  "quantity": 2,
  "product_price": 29.99,
  "product": {
    "id": "PRD_ABC123",
    "name": "Product Name",
    "price": 29.99
  }
}
```

**Status Codes**:
- `201 Created`: Item added successfully
- `400 Bad Request`: Invalid product_id, variant_id, or quantity
- `404 Not Found`: Product not found
- `403 Forbidden`: User is not a buyer

**Notes**:
- If item already exists in cart, quantity is incremented
- `product_price` is a snapshot of price at time of addition
- For products without variants, omit `variant_id` or send `null`

---

### 3. Update Cart Item Quantity

**Endpoint**: `PUT /cart/items/<item_id>`

**Description**: Update the quantity of a cart item. Set quantity to 0 to remove.

**Request Body**:
```json
{
  "quantity": 3
}
```

**Response**:
```json
{
  "id": 789,
  "cart_id": 123,
  "product_id": "PRD_ABC123",
  "variant_id": 1,
  "quantity": 3,
  "product_price": 29.99
}
```

**Status Codes**:
- `200 OK`: Item updated successfully
- `204 No Content`: Item removed (when quantity = 0)
- `404 Not Found`: Cart item not found

---

### 4. Remove Item from Cart

**Endpoint**: `DELETE /cart/items/<item_id>`

**Description**: Remove an item from the cart.

**Response**: `204 No Content`

**Status Codes**:
- `204 No Content`: Item removed successfully
- `404 Not Found`: Cart item not found

---

### 5. Clear Cart

**Endpoint**: `DELETE /cart`

**Description**: Remove all items from the cart.

**Response**: `204 No Content`

---

### 6. Get Cart Summary

**Endpoint**: `GET /cart/summary`

**Description**: Get a lightweight summary of the cart (for header/mini-cart display).

**Response**:
```json
{
  "item_count": 3,
  "subtotal": 89.97,
  "total": 89.97,  // TODO: Will include tax, shipping, discount
  "discount": 0
}
```

---

### 7. Apply Coupon

**Endpoint**: `POST /cart/coupon`

**Description**: Apply a coupon code to the cart.

**Request Body**:
```json
{
  "coupon_code": "SAVE10"  // TODO: Currently not implemented in request body
}
```

**Response**:
```json
{
  "success": true,
  "message": "Coupon applied successfully",
  "discount": 0  // TODO: Calculate actual discount
}
```

**Status Codes**:
- `200 OK`: Coupon applied (or invalid coupon)
- `400 Bad Request`: Invalid coupon code

**Note**: Currently coupon code is hardcoded. Frontend should send in request body when backend is updated.

---

### 8. Checkout Cart

**Endpoint**: `POST /cart/checkout`

**Description**: Convert cart to order. This creates an order with status `pending_payment` and clears the cart. **All order totals are calculated** (subtotal, shipping, tax, discount, total).

**Request Body**:
```json
{
  "shipping_address": {
    "street": "123 Main St",
    "city": "Lagos",
    "state": "Lagos",
    "country": "Nigeria",
    "postal_code": "100001",
    "phone": "+2348012345678"
  },
  "billing_address": {
    "street": "123 Main St",
    "city": "Lagos",
    "state": "Lagos",
    "country": "Nigeria",
    "postal_code": "100001"
  },
  "notes": "Please leave at door",  // Optional
  "idempotency_key": "unique-key-123"  // Optional: Prevents duplicate orders on retries
}
```

**Response**:
```json
{
  "order_id": "ORD_XYZ789",
  "message": "Order created successfully"
}
```

**Status Codes**:
- `201 Created`: Order created successfully
- `400 Bad Request`: Cart is empty or validation failed
- `422 Unprocessable Entity`: Product unavailable, price changed, or insufficient stock
- `409 Conflict`: Duplicate order (if idempotency_key matches existing order)

**Important Notes**:
- Cart is cleared after order creation
- Order status is `pending_payment` (waiting for payment)
- Order prices are snapshots (immutable)
- **All totals are calculated**: `subtotal`, `shipping_fee`, `tax`, `discount`, `total`
- **Inventory is validated** before order creation (prevents orders for out-of-stock items)
- **Inventory is NOT deducted yet** (only after payment succeeds)
- **Idempotency**: If `idempotency_key` is provided and matches an existing order, returns that order instead of creating a duplicate

---

## Order APIs

### 1. List User Orders

**Endpoint**: `GET /orders`

**Description**: Get all orders for the current buyer.

**Response**:
```json
[
  {
    "id": "ORD_XYZ789",
    "order_number": "ORD-20240215-789",
    "status": "pending_payment",
    "subtotal": 89.97,
    "shipping_fee": 10.00,
    "tax": 4.50,
    "discount": 0.00,
    "total": 104.47,
    "created_at": "2024-02-15T10:30:00Z",
    "items": [
      {
        "product_id": "PRD_ABC123",
        "variant_id": 1,
        "quantity": 2,
        "price": 29.99,
        "status": "pending",
        "product": {
          "id": "PRD_ABC123",
          "name": "Product Name"
        }
      }
    ]
  }
]
```

**Status Codes**:
- `200 OK`: Orders retrieved successfully
- `401 Unauthorized`: Not authenticated

---

### 2. Get Order Details

**Endpoint**: `GET /orders/<order_id>`

**Description**: Get detailed information about a specific order, including payment status.

**Response**:
```json
{
  "id": "ORD_XYZ789",
  "order_number": "ORD-20240215-789",
  "buyer_id": 456,
  "status": "processing",
  "subtotal": 89.97,
  "shipping_fee": 10.00,
  "tax": 5.40,
  "discount": 0,
  "total": 105.37,
  "shipping_address": {...},
  "billing_address": {...},
  "customer_note": "Please leave at door",
  "created_at": "2024-02-15T10:30:00Z",
  "items": [...],
  "payments": [
    {
      "id": "PAY_ABC456",
      "amount": 105.37,
      "status": "completed",
      "method": "card",
      "paid_at": "2024-02-15T10:35:00Z"
    }
  ]
}
```

**Status Codes**:
- `200 OK`: Order retrieved successfully
- `404 Not Found`: Order not found
- `403 Forbidden`: Order does not belong to user

---

### 3. Create Order (Alternative Endpoint)

**Endpoint**: `POST /orders`

**Description**: Alternative way to create order from cart. **Note**: Prefer using `/cart/checkout` instead.

**Request Body**:
```json
{
  "cart_id": 123,
  "shipping_address": {...},
  "payment_method": "card"
}
```

**Response**: Same as order details response

**Status Codes**:
- `201 Created`: Order created successfully
- `400 Bad Request`: Invalid cart or cart is empty

---

## Payment APIs

### 1. Create Payment

**Endpoint**: `POST /payments/create`

**Description**: Create a payment record for an order. This initializes the payment process.

**Request Body**:
```json
{
  "order_id": "ORD_XYZ789",
  "amount": 105.37,
  "currency": "NGN",
  "method": "card",  // "card" | "bank_transfer" | "mobile_money" | "wallet"
  "metadata": {},  // Optional, for additional payment data
  "idempotency_key": "unique-payment-key-123"  // Optional: Prevents duplicate payments on retries
}
```

**Response**:
```json
{
  "id": "PAY_ABC456",
  "order_id": "ORD_XYZ789",
  "amount": 105.37,
  "currency": "NGN",
  "method": "card",
  "status": "pending",
  "transaction_id": "T1234567890",
  "gateway_response": {
    "data": {
      "authorization_url": "https://paystack.com/pay/...",
      "reference": "T1234567890",
      "access_code": "ABC123"
    }
  },
  "created_at": "2024-02-15T10:35:00Z"
}
```

**Status Codes**:
- `201 Created`: Payment created successfully
- `400 Bad Request`: Invalid order or order not in pending_payment status
- `404 Not Found`: Order not found
- `409 Conflict`: Duplicate payment (if idempotency_key matches existing payment)

**Important**:
- For card payments, `gateway_response.data.authorization_url` contains the Paystack payment URL
- Frontend should redirect user to this URL or embed Paystack inline widget

---

### 2. Initialize Payment (Paystack)

**Endpoint**: `POST /payments/initialize`

**Description**: Initialize Paystack payment and get authorization URL. This is a convenience endpoint that creates payment and returns Paystack data.

**Request Body**: Same as `/payments/create`

**Response**:
```json
{
  "payment_id": "PAY_ABC456",
  "authorization_url": "https://paystack.com/pay/...",
  "reference": "T1234567890",
  "access_code": "ABC123"
}
```

**Status Codes**:
- `200 OK`: Payment initialized successfully
- `500 Internal Server Error`: Failed to initialize payment

**Usage**:
```javascript
// Frontend flow
const response = await fetch('/api/v1/payments/initialize', {
  method: 'POST',
  body: JSON.stringify({
    order_id: 'ORD_XYZ789',
    amount: 105.37,
    currency: 'NGN',
    method: 'card'
  })
});

const { authorization_url } = await response.json();
// Redirect to authorization_url or open Paystack widget
window.location.href = authorization_url;
```

---

### 3. Process Payment

**Endpoint**: `POST /payments/<payment_id>/process`

**Description**: Process a payment with payment details (for saved cards or bank transfers).

**Request Body** (Card Payment):
```json
{
  "authorization_code": "AUTH_xyz123",  // Saved card authorization code
  "metadata": {}
}
```

**Request Body** (Bank Transfer):
```json
{
  "bank": {
    "code": "057",  // Bank code
    "account_number": "0000000000"
  },
  "metadata": {}
}
```

**Response**: Payment object with updated status

**Status Codes**:
- `200 OK`: Payment processed
- `400 Bad Request`: Invalid payment data
- `404 Not Found`: Payment not found

---

### 4. Verify Payment

**Endpoint**: `GET /payments/<payment_id>/verify`

**Description**: Verify payment status with Paystack. Use this for polling after redirect.

**Response**:
```json
{
  "verified": true,
  "amount": 105.37,
  "gateway_response": {
    "status": true,
    "data": {
      "status": "success",
      "reference": "T1234567890"
    }
  }
}
```

**Status Codes**:
- `200 OK`: Verification completed
- `404 Not Found`: Payment not found

**Frontend Usage**:
```javascript
// Poll payment status after redirect
const checkPayment = async (paymentId) => {
  const response = await fetch(`/api/v1/payments/${paymentId}/verify`);
  const data = await response.json();
  
  if (data.verified) {
    // Payment successful, redirect to success page
    window.location.href = '/orders/success';
  } else {
    // Payment failed or still pending
    setTimeout(() => checkPayment(paymentId), 2000);
  }
};
```

---

### 5. Get Payment Details

**Endpoint**: `GET /payments/<payment_id>`

**Description**: Get payment information.

**Response**: Full payment object (same structure as create payment response)

---

### 6. List User Payments

**Endpoint**: `GET /payments?page=1&per_page=20`

**Description**: Get paginated list of user's payments.

**Query Parameters**:
- `page` (optional): Page number, default 1
- `per_page` (optional): Items per page, default 20

**Response**:
```json
{
  "payments": [...],
  "total": 50,
  "page": 1,
  "per_page": 20,
  "pages": 3
}
```

---

### 7. Payment Callback

**Endpoint**: `GET /payments/callback/<payment_id>?reference=T1234567890`

**Description**: Handle Paystack redirect callback. Frontend should call this after Paystack redirects back.

**Query Parameters**:
- `reference`: Paystack transaction reference

**Response**:
```json
{
  "status": "success",
  "message": "Payment verified successfully",
  "payment_id": "PAY_ABC456"
}
```

**Status Codes**:
- `200 OK`: Payment verified
- `400 Bad Request`: Missing reference or verification failed

---

## Complete Flow Examples

### Flow 1: Standard Checkout with Card Payment

```javascript
// Step 1: Get cart
const cart = await fetch('/api/v1/cart').then(r => r.json());

// Step 2: Checkout cart (create order)
// Generate idempotency key for retry safety
const idempotencyKey = crypto.randomUUID(); // or use a library like uuid

const order = await fetch('/api/v1/cart/checkout', {
  method: 'POST',
  body: JSON.stringify({
    shipping_address: {...},
    billing_address: {...},
    notes: "Optional note",
    idempotency_key: idempotencyKey  // Prevents duplicate orders on retries
  })
}).then(r => r.json());

// Step 3: Initialize payment
const paymentIdempotencyKey = crypto.randomUUID();

const payment = await fetch('/api/v1/payments/initialize', {
  method: 'POST',
  body: JSON.stringify({
    order_id: order.order_id,
    amount: 105.37,
    currency: 'NGN',
    method: 'card',
    idempotency_key: paymentIdempotencyKey  // Prevents duplicate payments on retries
  })
}).then(r => r.json());

// Step 4: Redirect to Paystack
window.location.href = payment.authorization_url;

// Step 5: After redirect, verify payment
const verifyResult = await fetch(
  `/api/v1/payments/${payment.payment_id}/verify`
).then(r => r.json());

if (verifyResult.verified) {
  // Success! Redirect to order confirmation
  window.location.href = `/orders/${order.order_id}`;
}
```

### Flow 2: Bank Transfer Payment

```javascript
// Steps 1-2: Same as above (get cart, checkout)

// Step 3: Create payment
const payment = await fetch('/api/v1/payments/create', {
  method: 'POST',
  body: JSON.stringify({
    order_id: order.order_id,
    amount: 105.37,
    currency: 'NGN',
    method: 'bank_transfer'
  })
}).then(r => r.json());

// Step 4: Process bank transfer
const processResult = await fetch(
  `/api/v1/payments/${payment.id}/process`,
  {
    method: 'POST',
    body: JSON.stringify({
      bank: {
        code: '057',
        account_number: '0000000000'
      }
    })
  }
).then(r => r.json());

// Step 5: Poll for payment status (bank transfers are async)
const checkStatus = setInterval(async () => {
  const status = await fetch(`/api/v1/payments/${payment.id}`)
    .then(r => r.json());
  
  if (status.status === 'completed') {
    clearInterval(checkStatus);
    // Payment successful
  } else if (status.status === 'failed') {
    clearInterval(checkStatus);
    // Payment failed
  }
}, 3000);
```

---

## Error Handling

### Error Response Format

All errors follow this structure:

```json
{
  "message": "Error description",
  "status_code": 400,
  "errors": {
    "field_name": ["Error message"]
  }
}
```

### Common Error Codes

- `400 Bad Request`: Invalid input, validation failed
- `401 Unauthorized`: Missing or invalid authentication token
- `403 Forbidden`: User doesn't have required role (buyer/seller)
- `404 Not Found`: Resource not found
- `409 Conflict`: Duplicate resource (e.g., duplicate order)
- `422 Unprocessable Entity`: Business logic error (e.g., insufficient stock, price changed)
- `500 Internal Server Error`: Server error

### Error Handling Example

```javascript
try {
  const response = await fetch('/api/v1/cart/checkout', {
    method: 'POST',
    body: JSON.stringify(checkoutData)
  });
  
  if (!response.ok) {
    const error = await response.json();
    
    if (response.status === 422) {
      // Business logic error (e.g., product unavailable)
      showError(error.message);
      // Optionally refresh cart to show updated availability
      refreshCart();
    } else if (response.status === 400) {
      // Validation error
      showValidationErrors(error.errors);
    } else {
      // Other errors
      showError(error.message);
    }
    return;
  }
  
  const order = await response.json();
  // Proceed with payment
} catch (error) {
  // Network error
  showError('Network error. Please try again.');
}
```

---

## WebSocket Events

The backend emits real-time events for order and payment status changes.

### Connection

```javascript
import io from 'socket.io-client';

const socket = io('http://api.markt.com', {
  path: '/socket.io',
  auth: {
    token: 'your-auth-token'
  }
});

// Join order room
socket.emit('join_order', { order_id: 'ORD_XYZ789' });
```

### Events

#### `order_status_changed`

Emitted when order status changes.

```javascript
socket.on('order_status_changed', (data) => {
  console.log(data);
  // {
  //   order_id: "ORD_XYZ789",
  //   user_id: "USR_123",
  //   status: "processing",
  //   old_status: "pending",
  //   metadata: {
  //     order_number: "ORD-20240215-789",
  //     total: 105.37
  //   }
  // }
});
```

#### `payment_confirmed`

Emitted when payment is confirmed.

```javascript
socket.on('payment_confirmed', (data) => {
  console.log(data);
  // {
  //   payment_id: "PAY_ABC456",
  //   order_id: "ORD_XYZ789",
  //   user_id: "USR_123",
  //   amount: 105.37,
  //   status: "completed",
  //   transaction_id: "T1234567890",
  //   metadata: {
  //     method: "card",
  //     order_number: "ORD-20240215-789"
  //   }
  // }
});
```

#### `payment_update`

Emitted when payment status changes.

```javascript
socket.on('payment_update', (data) => {
  console.log(data);
  // {
  //   payment_id: "PAY_ABC456",
  //   status: "failed",
  //   amount: 105.37,
  //   updated_at: "2024-02-15T10:40:00Z"
  // }
});
```

---

## Status Enums Reference

### Order Status
- `pending_payment`: Order created, waiting for payment (new orders use this)
- `pending`: Deprecated, use `pending_payment` instead (backward compatibility)
- `processing`: Payment confirmed, order being processed
- `shipped`: Order shipped
- `delivered`: Order delivered
- `cancelled`: Order cancelled
- `returned`: Order returned
- `failed`: Payment failed or order failed

### Payment Status
- `pending`: Payment initiated, waiting for completion
- `completed`: Payment successful
- `failed`: Payment failed
- `refunded`: Payment refunded
- `partially_refunded`: Partial refund

### Payment Method
- `card`: Credit/debit card
- `bank_transfer`: Bank transfer
- `mobile_money`: Mobile money
- `wallet`: Digital wallet

---

## Best Practices for Frontend

1. **Always validate cart before checkout**: Check that cart is not empty and items are still available
2. **Handle payment redirects gracefully**: Store order_id and payment_id in localStorage before redirect
3. **Poll payment status**: After redirect, poll `/payments/<id>/verify` every 2-3 seconds
4. **Use WebSocket events**: Subscribe to order/payment events for real-time updates
5. **Show clear error messages**: Display user-friendly messages for business logic errors (e.g., "Product is out of stock")
6. **Refresh cart after errors**: If checkout fails due to availability, refresh cart to show updated quantities
7. **Idempotency**: Use `idempotency_key` in checkout and payment requests to prevent duplicates on retries. Generate a unique key (e.g., UUID) and reuse it if the request fails and needs to be retried.

---

## Testing Checklist

- [ ] Add item to cart
- [ ] Update cart item quantity
- [ ] Remove item from cart
- [ ] Clear cart
- [ ] Checkout with valid cart
- [ ] Checkout with empty cart (should fail)
- [ ] Checkout with unavailable product (should fail)
- [ ] Create payment for order
- [ ] Initialize Paystack payment
- [ ] Verify payment after redirect
- [ ] Handle payment failure
- [ ] List user orders
- [ ] Get order details
- [ ] WebSocket events for order status changes
- [ ] WebSocket events for payment updates

---

## Support & Questions

For questions or issues with these APIs, contact the backend team or refer to:
- Analysis document: `docs/CART_ORDER_PAYMENT_ANALYSIS.md`
- Payment structure: `docs/PAYMENT_STRUCTURE.md`

