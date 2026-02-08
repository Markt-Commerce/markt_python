# Postman Collection: Cart, Order & Payment Flow

This Postman collection provides comprehensive testing for the cart, checkout, order, and payment flow in the Markt API.

## 📦 Collection File

**File**: `Cart_Order_Payment_Flow.postman_collection.json`

## 🚀 Quick Start

### 1. Import Collection

1. Open Postman
2. Click **Import** button
3. Select `Cart_Order_Payment_Flow.postman_collection.json`
4. Collection will appear in your workspace

### 2. Set Up Environment Variables

Create a new Postman Environment or use an existing one with these variables:

| Variable | Initial Value | Description |
|----------|---------------|-------------|
| `base_url` | `http://localhost:8000` | API base URL |
| `auth_token` | (empty) | JWT token (auto-set after login) |
| `user_id` | (empty) | User ID (auto-set after login) |
| `product_id` | `PRD_ABC123` | Product ID to test with |
| `order_id` | (empty) | Order ID (auto-set after checkout) |
| `payment_id` | (empty) | Payment ID (auto-set after payment creation) |
| `cart_item_id` | (empty) | Cart item ID (auto-set after adding to cart) |
| `paystack_reference` | (empty) | Paystack transaction reference |
| `authorization_url` | (empty) | Paystack authorization URL |

### 3. Run Tests

The collection is organized into folders:

1. **Authentication** - Login to get auth token
2. **Cart Operations** - Add, update, remove items
3. **Checkout & Order Creation** - Create orders from cart
4. **Payment Operations** - Initialize and process payments
5. **Complete Flow Tests** - End-to-end scenarios

## 📋 Test Scenarios

### Basic Flow

1. **Login (Buyer)** - Authenticate and get token
2. **Add Item to Cart** - Add product to cart
3. **Get Cart** - Verify items in cart
4. **Checkout Cart** - Create order (status: `pending_payment`)
5. **Get Order Details** - Verify order totals (subtotal, shipping, tax, discount, total)
6. **Initialize Payment** - Create payment and get Paystack URL
7. **Verify Payment** - Check payment status

### Advanced Tests

#### Inventory Validation Test
- **Add Out of Stock Item** - Add item with quantity > available stock
- **Try Checkout** - Should fail with 422 error and clear message

#### Idempotency Test
- **Checkout with Idempotency Key (First)** - Create order with unique key
- **Checkout with Same Key (Retry)** - Should return same order, not create duplicate

## 🔑 Key Features

### Automatic Variable Management

The collection automatically saves IDs from responses:
- `auth_token` - Saved after login
- `order_id` - Saved after checkout
- `payment_id` - Saved after payment creation
- `cart_item_id` - Saved after adding to cart

### Idempotency Support

All checkout and payment requests include `idempotency_key` using `{{$randomUUID}}` or `{{$timestamp}}` to prevent duplicates on retries.

### Complete Flow Test

The "Full Flow: Cart to Payment" folder contains a complete end-to-end test that:
1. Adds items to cart
2. Gets cart summary
3. Creates order
4. Verifies order
5. Initializes payment
6. Verifies payment status

## 📝 Request Examples

### Checkout Request

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
  "notes": "Please leave at door",
  "idempotency_key": "{{$randomUUID}}"
}
```

### Payment Initialization

```json
{
  "order_id": "{{order_id}}",
  "amount": 105.37,
  "currency": "NGN",
  "method": "card",
  "idempotency_key": "{{$randomUUID}}"
}
```

## ✅ Expected Responses

### Successful Checkout

```json
{
  "order_id": "ORD_XYZ789",
  "message": "Order created successfully"
}
```

### Order Details (After Checkout)

```json
{
  "id": "ORD_XYZ789",
  "status": "pending_payment",
  "subtotal": 89.97,
  "shipping_fee": 10.00,
  "tax": 4.50,
  "discount": 0.00,
  "total": 104.47,
  ...
}
```

### Payment Initialization

```json
{
  "payment_id": "PAY_ABC456",
  "authorization_url": "https://paystack.com/pay/...",
  "reference": "T1234567890",
  "access_code": "ABC123"
}
```

## 🐛 Error Scenarios

### Insufficient Stock (422)

```json
{
  "message": "Insufficient stock for Product Name. Available: 5, Requested: 100",
  "status_code": 422
}
```

### Duplicate Order (409)

```json
{
  "message": "Order with this idempotency key already exists",
  "status_code": 409
}
```

## 🔄 Testing Workflow

1. **Start Fresh**: Clear cart if needed
2. **Add Products**: Add items to cart
3. **Verify Cart**: Check cart summary
4. **Checkout**: Create order (note the `order_id`)
5. **Verify Order**: Check order details and totals
6. **Initialize Payment**: Create payment record
7. **Process Payment**: Use Paystack test cards or bank transfer
8. **Verify Payment**: Check payment status

## 🧪 Test Cards (Paystack)

For testing card payments, use Paystack test cards:

- **Success**: `4084084084084081`
- **Decline**: `5060666666666666666`
- **Insufficient Funds**: `5060666666666666667`

## 📊 Status Codes Reference

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 409 | Conflict (duplicate) |
| 422 | Unprocessable Entity (business logic error) |
| 500 | Internal Server Error |

## 🎯 Tips

1. **Use Environment Variables**: Set `base_url` for different environments (dev, staging, prod)
2. **Save Responses**: Use Postman's "Save Response" feature to keep examples
3. **Run Collection**: Use "Run Collection" to execute all tests in sequence
4. **Check Console**: View auto-saved variables in Postman console
5. **Test Edge Cases**: Use the "Complete Flow Tests" folder for edge cases

## 📚 Related Documentation

- **API Documentation**: `docs/FRONTEND_API_CART_ORDER_PAYMENT.md`
- **Analysis Document**: `docs/CART_ORDER_PAYMENT_ANALYSIS.md`
- **Payment Structure**: `docs/PAYMENT_STRUCTURE.md`

## 🆘 Troubleshooting

### Token Expired
- Re-run the "Login (Buyer)" request to get a new token

### Variables Not Set
- Check that test scripts are enabled in Postman settings
- Manually set variables if needed

### 422 Errors
- Check product availability
- Verify cart is not empty
- Check that order totals are calculated correctly

### Payment Issues
- Verify Paystack keys are configured
- Check order status is `pending_payment`
- Ensure payment amount matches order total

---

**Happy Testing!** 🚀




