# React Native Payment Integration - Quick Start

This guide addresses common issues when integrating Paystack payments in React Native.

## 🚨 Common Issues & Solutions

### Issue 1: Initialize Endpoint Error

**Problem**: `/payments/initialize` returns error or doesn't work

**Solutions**:

1. **Check Request Format**:
```javascript
const response = await fetch(`${API_BASE_URL}/api/v1/payments/initialize`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${authToken}`, // REQUIRED
    'Content-Type': 'application/json',     // REQUIRED
  },
  body: JSON.stringify({
    order_id: 'ORD_XYZ789',     // Must exist and be in pending_payment status
    amount: 105.37,              // Must match order total
    currency: 'NGN',
    method: 'card',              // For card payments
    idempotency_key: `${Date.now()}-${Math.random()}`, // Optional but recommended
  }),
});
```

2. **Error Handling**:
```javascript
if (!response.ok) {
  const errorText = await response.text();
  let error;
  try {
    error = JSON.parse(errorText);
  } catch {
    error = { message: errorText };
  }
  console.error('Error:', error);
  throw new Error(error.message || `HTTP ${response.status}`);
}

const data = await response.json();
console.log('Success:', data);
```

3. **Common Errors**:
   - `401 Unauthorized` → Check auth token
   - `404 Not Found` → Order doesn't exist
   - `422 Unprocessable Entity` → Order not in `pending_payment` status
   - `500 Internal Server Error` → Check backend logs

### Issue 2: Paystack SDK Usage (Line 77 Issue)

**Problem**: `Paystack.chargeCard` doesn't work or isn't available

**Solution**: Paystack React Native uses **WebView component**, not direct card charging.

**Correct Implementation**:

```javascript
import { Paystack } from 'react-native-paystack-webview';

// Step 1: Initialize payment (get reference)
const initResponse = await fetch(`${API_BASE_URL}/api/v1/payments/initialize`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${authToken}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    order_id: orderId,
    amount: amount,
    currency: 'NGN',
    method: 'card',
  }),
});

const { payment_id, reference, authorization_url } = await initResponse.json();

// Step 2: Use Paystack WebView component (NOT chargeCard)
<Paystack
  paystackKey="pk_test_your_public_key" // From backend config
  amount={amount * 100}                  // In kobo
  billingEmail={userEmail}
  refNumber={reference}                  // From initialize response
  onSuccess={(response) => {
    // Handle success
    verifyPayment(payment_id);
  }}
  onCancel={() => {
    // Handle cancel
  }}
  autoStart={true}
/>
```

**Key Points**:
- ✅ Use `react-native-paystack-webview` package (not `react-native-paystack`)
- ✅ Use `<Paystack>` component (not `Paystack.chargeCard()`)
- ✅ Get `reference` from `/payments/initialize` endpoint
- ✅ Pass `reference` to `refNumber` prop

### Issue 3: Bank Transfer Support

**Yes, bank transfers are supported!** Here's how to implement:

```javascript
// Step 1: Create payment with bank_transfer method
const createResponse = await fetch(`${API_BASE_URL}/api/v1/payments/create`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${authToken}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    order_id: orderId,
    amount: amount,
    currency: 'NGN',
    method: 'bank_transfer', // Important!
  }),
});

const { payment_id } = await createResponse.json();

// Step 2: Process with bank details
const processResponse = await fetch(
  `${API_BASE_URL}/api/v1/payments/${payment_id}/process`,
  {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${authToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      bank: {
        code: '057',           // Bank code (e.g., 057 for Zenith)
        account_number: '0000000000', // User's account number
      },
    }),
  }
);

// Step 3: Poll for status (bank transfers are async)
const pollPaymentStatus = async (paymentId) => {
  const checkStatus = setInterval(async () => {
    const response = await fetch(
      `${API_BASE_URL}/api/v1/payments/${paymentId}`,
      {
        headers: {
          'Authorization': `Bearer ${authToken}`,
        },
      }
    );

    const payment = await response.json();

    if (payment.status === 'completed') {
      clearInterval(checkStatus);
      // Payment successful!
    } else if (payment.status === 'failed') {
      clearInterval(checkStatus);
      // Payment failed
    }
  }, 5000); // Poll every 5 seconds

  // Clear after 5 minutes
  setTimeout(() => clearInterval(checkStatus), 300000);
};
```

## 📱 Complete Working Example

```javascript
import React, { useState } from 'react';
import { View, Button, Alert, ActivityIndicator } from 'react-native';
import { Paystack } from 'react-native-paystack-webview';

const API_BASE_URL = 'https://api.yourdomain.com';
const PAYSTACK_PUBLIC_KEY = 'pk_test_your_key'; // From backend

function PaymentScreen({ route, navigation }) {
  const { orderId, amount, userEmail } = route.params;
  const [paymentData, setPaymentData] = useState(null);
  const [loading, setLoading] = useState(false);
  const authToken = getAuthToken(); // From your auth context

  const initializePayment = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/payments/initialize`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${authToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          order_id: orderId,
          amount: amount,
          currency: 'NGN',
          method: 'card',
          idempotency_key: `${Date.now()}-${Math.random()}`,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.message || 'Failed to initialize payment');
      }

      const data = await response.json();
      setPaymentData(data);
    } catch (error) {
      Alert.alert('Error', error.message);
    } finally {
      setLoading(false);
    }
  };

  const handlePaymentSuccess = async (response) => {
    try {
      // Verify payment
      const verifyResponse = await fetch(
        `${API_BASE_URL}/api/v1/payments/${paymentData.payment_id}/verify`,
        {
          headers: {
            'Authorization': `Bearer ${authToken}`,
          },
        }
      );

      const verifyData = await verifyResponse.json();
      
      if (verifyData.verified) {
        navigation.navigate('PaymentSuccess', {
          paymentId: paymentData.payment_id,
          orderId: orderId,
        });
      }
    } catch (error) {
      // Still navigate to success, webhook will update status
      navigation.navigate('PaymentSuccess', {
        paymentId: paymentData.payment_id,
        orderId: orderId,
      });
    }
  };

  if (loading) {
    return <ActivityIndicator />;
  }

  if (!paymentData) {
    return (
      <View>
        <Button title="Pay Now" onPress={initializePayment} />
      </View>
    );
  }

  return (
    <Paystack
      paystackKey={PAYSTACK_PUBLIC_KEY}
      amount={amount * 100}
      billingEmail={userEmail}
      refNumber={paymentData.reference}
      onSuccess={handlePaymentSuccess}
      onCancel={() => navigation.goBack()}
      autoStart={true}
    />
  );
}
```

## ✅ Checklist

Before reporting issues, verify:

- [ ] `Authorization: Bearer <token>` header is included
- [ ] Order exists and status is `pending_payment`
- [ ] Amount matches order total
- [ ] `react-native-paystack-webview` is installed (not `react-native-paystack`)
- [ ] iOS: `pod install` was run
- [ ] Android: WebKit dependency is added
- [ ] Paystack public key is correct
- [ ] `refNumber` comes from `/payments/initialize` response
- [ ] Amount is in kobo (multiply by 100)

## 📚 Full Documentation

See [React Native Payment Flow Guide](./REACT_NATIVE_PAYMENT_FLOW.md) for complete documentation.

## 🆘 Still Having Issues?

1. Check backend logs for specific error messages
2. Verify Paystack keys are configured correctly
3. Test with Postman first to ensure backend works
4. Check network connectivity
5. Verify order status before initializing payment


