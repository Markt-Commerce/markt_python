# React Native Payment Flow Guide

This guide explains how to integrate the Markt payment flow with React Native mobile apps using Paystack.

## 🎯 Payment Flow Options for React Native

There are **two main approaches** for handling payments in React Native:

### Option 1: In-App Payment (Recommended) ✅
- Uses **Paystack React Native SDK**
- Payment happens **inside your app**
- Better UX (no browser redirect)
- Native feel
- **Recommended for production**

### Option 2: Web-Based Payment (Current Implementation)
- Opens **browser/webview** for payment
- Uses `authorization_url` redirect
- Works but less native feel
- Good for quick implementation

---

## 📱 Option 1: In-App Payment (Recommended)

### Setup

#### 1. Install Paystack React Native WebView Package

**Important**: Paystack's official React Native package is `react-native-paystack-webview`.

```bash
npm install react-native-paystack-webview
# or
yarn add react-native-paystack-webview
```

For iOS, also install pods:
```bash
cd ios && pod install
```

For Android, add to `android/app/build.gradle`:
```gradle
dependencies {
    implementation 'androidx.webkit:webkit:1.4.0'
}
```

#### 2. Get Your Paystack Public Key

**IMPORTANT**: Yes, you **DO need** the Paystack public key in your mobile app!

- ✅ **Public Key** (`pk_test_...` or `pk_live_...`): Safe to use in mobile apps - this is meant for client-side use
- ❌ **Secret Key** (`sk_test_...` or `sk_live_...`): NEVER use in mobile apps - backend only!

**How to get it:**
1. Ask backend team for `PAYSTACK_PUBLIC_KEY` value from settings
2. Or get it from Paystack dashboard: Settings → API Keys & Webhooks
3. Use `pk_test_...` for development/staging
4. Use `pk_live_...` for production

```javascript
// In your config file
export const PAYSTACK_PUBLIC_KEY = 'pk_test_your_public_key_here'; // Get from backend team
export const API_BASE_URL = 'https://api.yourdomain.com'; // Your API URL
```

**Why it's safe:**
- Paystack public keys are designed to be used in client-side code
- They can only initialize payments, not access sensitive data
- The secret key (backend-only) is what's actually used to process payments

### Payment Flow

**IMPORTANT**: Paystack React Native SDK works differently. You have two options:

#### Option A: Use Backend Initialization (Recommended) ✅

```javascript
import { Paystack } from 'react-native-paystack-webview';
import { API_BASE_URL } from './config';

async function initializePayment(orderId, amount, userEmail, authToken) {
  try {
    // Step 1: Initialize payment with backend to get reference
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
        method: 'card', // For card payments
        idempotency_key: `${Date.now()}-${Math.random()}`,
      }),
    });

    if (!initResponse.ok) {
      const errorText = await initResponse.text();
      let errorData;
      try {
        errorData = JSON.parse(errorText);
      } catch {
        errorData = { message: errorText };
      }
      throw new Error(errorData.message || `HTTP ${initResponse.status}: Failed to initialize payment`);
    }

    const data = await initResponse.json();
    
    // Validate response has required fields
    if (!data.payment_id || !data.reference) {
      throw new Error('Invalid response from payment initialization');
    }

    return {
      paymentId: data.payment_id,
      reference: data.reference,
      accessCode: data.access_code,
      authorizationUrl: data.authorization_url,
    };

  } catch (error) {
    console.error('Payment initialization error:', error);
    throw error;
  }
}

// In your component
import React, { useState, useEffect } from 'react';
import { View, Button, Alert, ActivityIndicator, Text } from 'react-native';
import { Paystack } from 'react-native-paystack-webview';
import { PAYSTACK_PUBLIC_KEY, API_BASE_URL } from './config';

function PaymentScreen({ route, navigation }) {
  const { orderId, amount, userEmail } = route.params;
  const [paymentData, setPaymentData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const authToken = getAuthToken(); // Get from your auth context/store

  useEffect(() => {
    // Initialize payment when screen loads
    handleInitializePayment();
  }, []);

  const handleInitializePayment = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await initializePayment(orderId, amount, userEmail, authToken);
      setPaymentData(data);
    } catch (error) {
      console.error('Initialization error:', error);
      setError(error.message);
      Alert.alert('Payment Error', error.message);
    } finally {
      setLoading(false);
    }
  };

  const handlePaymentSuccess = async (response) => {
    console.log('Payment success response:', response);
    
    try {
      // Step 3: Verify payment with backend
      const verifyResponse = await fetch(
        `${API_BASE_URL}/api/v1/payments/${paymentData.paymentId}/verify`,
        {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${authToken}`,
          },
        }
      );

      if (!verifyResponse.ok) {
        throw new Error('Failed to verify payment');
      }

      const verifyData = await verifyResponse.json();

      if (verifyData.verified) {
        navigation.navigate('PaymentSuccess', { 
          paymentId: paymentData.paymentId,
          orderId: orderId 
        });
      } else {
        navigation.navigate('PaymentFailed', { 
          paymentId: paymentData.paymentId,
          error: 'Payment verification failed'
        });
      }
    } catch (error) {
      console.error('Verification error:', error);
      // Still navigate to success, webhook will update status
      navigation.navigate('PaymentSuccess', { 
        paymentId: paymentData.paymentId,
        orderId: orderId 
      });
    }
  };

  const handlePaymentCancel = () => {
    Alert.alert(
      'Payment Cancelled',
      'You cancelled the payment process.',
      [
        {
          text: 'OK',
          onPress: () => navigation.goBack(),
        },
      ]
    );
  };

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator size="large" />
        <Text>Initializing payment...</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20 }}>
        <Text style={{ color: 'red', marginBottom: 20 }}>{error}</Text>
        <Button title="Retry" onPress={handleInitializePayment} />
        <Button title="Go Back" onPress={() => navigation.goBack()} />
      </View>
    );
  }

  if (!paymentData) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <Button title="Initialize Payment" onPress={handleInitializePayment} />
      </View>
    );
  }

  return (
    <View style={{ flex: 1 }}>
      <Paystack
        paystackKey={PAYSTACK_PUBLIC_KEY}
        amount={amount * 100} // Convert to kobo
        billingEmail={userEmail}
        activityIndicatorColor="green"
        onCancel={handlePaymentCancel}
        onSuccess={handlePaymentSuccess}
        autoStart={true}
        refNumber={paymentData.reference}
      />
    </View>
  );
}

export default PaymentScreen;
```

#### Option B: Direct SDK Charge (Alternative)

If you want to collect card details in your app and charge directly:

```javascript
// Step 1: Initialize payment (same as above)
const { payment_id, reference, access_code } = await handlePayment(orderId, amount);

// Step 2: Use Paystack Charge API via your backend
// Note: You should NOT collect card details in your app directly
// Instead, use the WebView approach above for security

// If you must use direct charge, send card details to YOUR backend endpoint
// which then calls Paystack Charge API (your backend handles security)
const chargeResponse = await fetch(
  `https://api.yourdomain.com/api/v1/payments/${payment_id}/process`,
  {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${authToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      // For saved cards only - never send raw card details
      authorization_code: savedAuthorizationCode, // From previous payment
    }),
  }
);
```

### Alternative: Using Saved Card Authorization

If user has saved cards:

```javascript
// Step 1: Initialize payment (same as above)
const { payment_id, reference } = await initializePayment(orderId, amount);

// Step 2: Process with saved authorization code
const processResponse = await fetch(
  `https://api.yourdomain.com/api/v1/payments/${payment_id}/process`,
  {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${authToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      authorization_code: savedAuthorizationCode, // From previous payment
    }),
  }
);

const payment = await processResponse.json();

if (payment.status === 'completed') {
  // Success!
} else {
  // Failed
}
```

---

## 🌐 Option 2: Web-Based Payment (Current Implementation)

### Using WebView

```javascript
import { WebView } from 'react-native-webview';

function PaymentWebView({ authorizationUrl, onPaymentComplete }) {
  const handleNavigationStateChange = (navState) => {
    const { url } = navState;
    
    // Check if payment is complete
    if (url.includes('/payment/success') || url.includes('/payment/callback')) {
      // Extract payment_id from URL
      const paymentId = extractPaymentIdFromUrl(url);
      onPaymentComplete(paymentId);
    }
  };

  return (
    <WebView
      source={{ uri: authorizationUrl }}
      onNavigationStateChange={handleNavigationStateChange}
      startInLoadingState={true}
    />
  );
}

// Usage
function CheckoutScreen() {
  const [authorizationUrl, setAuthorizationUrl] = useState(null);

  const initializePayment = async () => {
    const response = await fetch('https://api.yourdomain.com/api/v1/payments/initialize', {
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

    const { authorization_url } = await response.json();
    setAuthorizationUrl(authorization_url);
  };

  return (
    <View>
      {authorizationUrl ? (
        <PaymentWebView
          authorizationUrl={authorizationUrl}
          onPaymentComplete={(paymentId) => {
            // Navigate to success screen
            navigation.navigate('PaymentSuccess', { paymentId });
          }}
        />
      ) : (
        <Button title="Pay Now" onPress={initializePayment} />
      )}
    </View>
  );
}
```

### Using Linking (Open in Browser)

```javascript
import { Linking } from 'react-native';

async function openPaymentInBrowser(authorizationUrl) {
  const canOpen = await Linking.canOpenURL(authorizationUrl);
  
  if (canOpen) {
    await Linking.openURL(authorizationUrl);
    
    // Listen for deep link when user returns
    Linking.addEventListener('url', handlePaymentCallback);
  }
}

function handlePaymentCallback(event) {
  const { url } = event;
  
  if (url.includes('/payment/success')) {
    // Extract payment_id and navigate
    const paymentId = extractPaymentIdFromUrl(url);
    navigation.navigate('PaymentSuccess', { paymentId });
  }
}
```

---

## 🏦 Bank Transfer Payment (Nigerian Use Case)

**Yes! Our implementation supports bank transfer payments.** This is commonly used in Nigeria where users can transfer directly to Paystack's bank account (usually Titan Bank).

### How Bank Transfer Works

1. User selects "Bank Transfer" as payment method
2. Backend creates payment with `method: "bank_transfer"`
3. User gets bank account details (account number, bank name)
4. User transfers money from their bank app
5. Payment is verified via webhook when Paystack confirms the transfer

### Implementation

```javascript
// Step 1: Create payment with bank_transfer method
const createBankTransferPayment = async (orderId, amount) => {
  const response = await fetch('https://api.yourdomain.com/api/v1/payments/create', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${authToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      order_id: orderId,
      amount: amount,
      currency: 'NGN',
      method: 'bank_transfer', // Important: use bank_transfer
      idempotency_key: `${Date.now()}-${Math.random()}`,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.message || 'Failed to create payment');
  }

  return await response.json();
};

// Step 2: Process bank transfer with account details
const processBankTransfer = async (paymentId, bankDetails) => {
  const response = await fetch(
    `https://api.yourdomain.com/api/v1/payments/${paymentId}/process`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${authToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        bank: {
          code: bankDetails.bankCode, // e.g., "057" for Zenith Bank
          account_number: bankDetails.accountNumber, // User's account number
        },
      }),
    }
  );

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.message || 'Failed to process bank transfer');
  }

  return await response.json();
};

// Step 3: Show user bank account details and instructions
function BankTransferScreen({ route, navigation }) {
  const { paymentId, amount } = route.params;
  const [paymentStatus, setPaymentStatus] = useState('pending');

  useEffect(() => {
    // Poll for payment status (bank transfers are async)
    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(
          `https://api.yourdomain.com/api/v1/payments/${paymentId}`,
          {
            headers: {
              'Authorization': `Bearer ${authToken}`,
            },
          }
        );

        const payment = await response.json();

        if (payment.status === 'completed') {
          setPaymentStatus('completed');
          clearInterval(pollInterval);
          navigation.navigate('PaymentSuccess', { paymentId });
        } else if (payment.status === 'failed') {
          setPaymentStatus('failed');
          clearInterval(pollInterval);
          Alert.alert('Payment Failed', 'Bank transfer was not successful');
        }
      } catch (error) {
        console.error('Polling error:', error);
      }
    }, 5000); // Poll every 5 seconds

    return () => clearInterval(pollInterval);
  }, [paymentId]);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Transfer Payment Instructions</Text>
      
      <View style={styles.bankDetails}>
        <Text style={styles.label}>Bank Name:</Text>
        <Text style={styles.value}>Titan Trust Bank (or provided by Paystack)</Text>
        
        <Text style={styles.label}>Account Number:</Text>
        <Text style={styles.value}>[Will be provided by Paystack in response]</Text>
        
        <Text style={styles.label}>Amount:</Text>
        <Text style={styles.value}>₦{amount.toLocaleString()}</Text>
        
        <Text style={styles.label}>Reference:</Text>
        <Text style={styles.value}>[Payment reference from backend]</Text>
      </View>

      <Text style={styles.instructions}>
        Please transfer the exact amount above to the account details shown.
        Payment will be verified automatically once the transfer is confirmed.
      </Text>

      {paymentStatus === 'pending' && (
        <ActivityIndicator size="large" color="#0000ff" />
      )}

      <Button
        title="I've Made the Transfer"
        onPress={() => {
          // Optionally, user can manually verify
          verifyPayment(paymentId);
        }}
      />
    </View>
  );
}
```

### Bank Transfer Flow Summary

1. **Create Payment** → `POST /payments/create` with `method: "bank_transfer"`
2. **Process Payment** → `POST /payments/{id}/process` with bank account details
3. **Wait for Webhook** → Payment status updates via webhook (automatic)
4. **Or Poll Status** → `GET /payments/{id}` to check status manually
5. **Verify** → `GET /payments/{id}/verify` to confirm payment

### Important Notes

- Bank transfers are **asynchronous** - payment takes time to be confirmed
- Webhook (`/payments/webhook/paystack`) automatically updates payment status
- User should be shown bank account details and reference number
- Consider showing a "waiting for confirmation" screen
- Poll payment status every 5-10 seconds until confirmed

---

## 🔄 Complete React Native Flow Example

### Full Implementation

```javascript
// PaymentService.js
import Paystack from 'react-native-paystack';
import { API_BASE_URL } from './config';

class PaymentService {
  static async initializePayment(orderId, amount, currency = 'NGN') {
    const response = await fetch(`${API_BASE_URL}/api/v1/payments/initialize`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${await getAuthToken()}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        order_id: orderId,
        amount: amount,
        currency: currency,
        method: 'card',
        idempotency_key: this.generateIdempotencyKey(),
      }),
    });

    if (!response.ok) {
      throw new Error('Failed to initialize payment');
    }

    return await response.json();
  }

  static async verifyPayment(paymentId) {
    const response = await fetch(
      `${API_BASE_URL}/api/v1/payments/${paymentId}/verify`,
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${await getAuthToken()}`,
        },
      }
    );

    if (!response.ok) {
      throw new Error('Failed to verify payment');
    }

    return await response.json();
  }

  static async chargeCard(cardDetails, paymentData) {
    try {
      // Initialize payment
      const { reference, access_code } = await this.initializePayment(
        paymentData.orderId,
        paymentData.amount
      );

      // Charge card using Paystack SDK
      const chargeResponse = await Paystack.chargeCard({
        cardNumber: cardDetails.cardNumber,
        expiryMonth: cardDetails.expiryMonth,
        expiryYear: cardDetails.expiryYear,
        cvc: cardDetails.cvc,
        email: paymentData.email,
        amount: paymentData.amount * 100, // Convert to kobo
        reference: reference,
        accessCode: access_code,
      });

      return chargeResponse;
    } catch (error) {
      throw new Error(`Payment failed: ${error.message}`);
    }
  }

  static generateIdempotencyKey() {
    return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }
}

// CheckoutScreen.js
import React, { useState } from 'react';
import { View, Button, Alert } from 'react-native';
import PaymentService from './services/PaymentService';

export default function CheckoutScreen({ route, navigation }) {
  const { orderId, amount } = route.params;
  const [loading, setLoading] = useState(false);

  const handlePayment = async () => {
    setLoading(true);
    
    try {
      // Option 1: In-app payment (recommended)
      const chargeResponse = await PaymentService.chargeCard(
        {
          cardNumber: '4084084084084081', // From user input
          expiryMonth: '12',
          expiryYear: '25',
          cvc: '408',
        },
        {
          orderId: orderId,
          amount: amount,
          email: userEmail,
        }
      );

      if (chargeResponse.status === 'success') {
        // Verify payment
        const verifyResult = await PaymentService.verifyPayment(
          chargeResponse.payment_id
        );

        if (verifyResult.verified) {
          navigation.navigate('PaymentSuccess', {
            paymentId: chargeResponse.payment_id,
            orderId: orderId,
          });
        } else {
          Alert.alert('Payment Failed', 'Payment verification failed');
        }
      } else {
        Alert.alert('Payment Failed', chargeResponse.message);
      }
    } catch (error) {
      Alert.alert('Error', error.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View>
      <Button
        title={loading ? 'Processing...' : 'Pay Now'}
        onPress={handlePayment}
        disabled={loading}
      />
    </View>
  );
}
```

---

## 🔐 Security Best Practices

### 1. Never Store Card Details
- Always use Paystack SDK to handle card input
- Never send card details directly to your backend
- Use tokenization for saved cards

### 2. Use Idempotency Keys
```javascript
// Generate unique idempotency key for each payment attempt
const idempotencyKey = `${userId}-${orderId}-${Date.now()}`;

// Include in payment request
{
  order_id: orderId,
  amount: amount,
  idempotency_key: idempotencyKey,
}
```

### 3. Verify Payments Server-Side
- Always verify payment status with backend after SDK returns success
- Don't trust client-side payment status alone
- Use webhooks as primary source of truth

### 4. Handle Network Failures
```javascript
const handlePaymentWithRetry = async (orderId, amount, retries = 3) => {
  const idempotencyKey = PaymentService.generateIdempotencyKey();
  
  for (let i = 0; i < retries; i++) {
    try {
      const result = await PaymentService.initializePayment(
        orderId,
        amount,
        idempotencyKey // Reuse same key on retry
      );
      return result;
    } catch (error) {
      if (i === retries - 1) throw error;
      await new Promise(resolve => setTimeout(resolve, 1000 * (i + 1)));
    }
  }
};
```

---

## 📊 Payment Status Polling (Alternative)

If you prefer polling instead of webhooks:

```javascript
const pollPaymentStatus = async (paymentId, maxAttempts = 30) => {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const response = await PaymentService.verifyPayment(paymentId);
      
      if (response.verified) {
        return { status: 'success', data: response };
      }
      
      // Wait 2 seconds before next poll
      await new Promise(resolve => setTimeout(resolve, 2000));
    } catch (error) {
      if (i === maxAttempts - 1) {
        return { status: 'error', error: error.message };
      }
    }
  }
  
  return { status: 'timeout' };
};
```

---

## 🎨 UI/UX Recommendations

### 1. Payment Screen Flow
```
Checkout → Payment Method Selection → Card Input → Processing → Success/Failure
```

### 2. Loading States
- Show loading spinner during payment processing
- Disable buttons to prevent double submission
- Display clear error messages

### 3. Error Handling
```javascript
const handlePaymentError = (error) => {
  let message = 'Payment failed. Please try again.';
  
  if (error.code === 'insufficient_funds') {
    message = 'Insufficient funds. Please use a different card.';
  } else if (error.code === 'card_declined') {
    message = 'Card declined. Please check your card details.';
  } else if (error.code === 'network_error') {
    message = 'Network error. Please check your connection.';
  }
  
  Alert.alert('Payment Error', message);
};
```

---

## 🔗 Deep Linking Setup

For web-based payments, set up deep linking:

### iOS (Info.plist)
```xml
<key>CFBundleURLTypes</key>
<array>
  <dict>
    <key>CFBundleURLSchemes</key>
    <array>
      <string>markt</string>
    </array>
  </dict>
</array>
```

### Android (AndroidManifest.xml)
```xml
<intent-filter>
  <action android:name="android.intent.action.VIEW" />
  <category android:name="android.intent.category.DEFAULT" />
  <category android:name="android.intent.category.BROWSABLE" />
  <data android:scheme="markt" />
</intent-filter>
```

### Handle Deep Links
```javascript
import { Linking } from 'react-native';

useEffect(() => {
  const handleDeepLink = (event) => {
    const { url } = event;
    
    if (url.includes('/payment/success')) {
      const paymentId = extractPaymentId(url);
      navigation.navigate('PaymentSuccess', { paymentId });
    }
  };

  Linking.addEventListener('url', handleDeepLink);
  
  // Check if app was opened via deep link
  Linking.getInitialURL().then((url) => {
    if (url) handleDeepLink({ url });
  });

  return () => {
    Linking.removeEventListener('url', handleDeepLink);
  };
}, []);
```

---

## 📝 Summary

### Recommended Approach: **In-App Payment**
- ✅ Better UX (native feel)
- ✅ No browser redirect
- ✅ Faster payment flow
- ✅ Better error handling

### Implementation Steps:
1. Install `react-native-paystack`
2. Initialize with public key
3. Call `/payments/initialize` to get `reference` and `access_code`
4. Use Paystack SDK to charge card
5. Verify payment with `/payments/{id}/verify`
6. Navigate to success/failure screen

### API Endpoints Used:
- `POST /api/v1/payments/initialize` - Get payment reference
- `POST /api/v1/payments/{id}/process` - Process with saved card (optional)
- `GET /api/v1/payments/{id}/verify` - Verify payment status

---

## 🆘 Troubleshooting

### Issue: Payment succeeds but order not updated
**Solution**: Webhook might be delayed. Poll `/payments/{id}/verify` or check webhook logs.

### Issue: Card charge fails
**Solution**: Check card details, ensure test cards are used in test mode.

### Issue: Deep link not working
**Solution**: Verify URL scheme configuration in iOS/Android manifests.

---

## 📝 Common Error Messages & Solutions

### "Order is not in pending payment status"
**Cause**: Order status is not `pending_payment`  
**Solution**: Check order status, ensure order was created via `/cart/checkout`

### "Order not found"
**Cause**: Invalid `order_id` or order doesn't belong to user  
**Solution**: Verify order_id is correct and belongs to authenticated user

### "Failed to initialize payment"
**Cause**: Paystack API error or missing configuration  
**Solution**: Check Paystack keys are configured, verify network connectivity

### "Payment verification failed"
**Cause**: Payment not yet confirmed by Paystack  
**Solution**: Wait a few seconds and retry, or rely on webhook for status update

---

**Need Help?** Check:
- [Paystack React Native WebView Docs](https://www.npmjs.com/package/react-native-paystack-webview)
- [Frontend API Documentation](./FRONTEND_API_CART_ORDER_PAYMENT.md)
- [Payment Structure](./PAYMENT_STRUCTURE.md)
- [Paystack API Docs](https://paystack.com/docs/api/)



