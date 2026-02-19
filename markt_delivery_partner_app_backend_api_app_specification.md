# Markt Delivery System – Separated Specifications

This rewrite separates **responsibilities and documentation** clearly:

- **Document A:** Backend Engineer Specification
- **Document B:** Delivery Partner App (Rider App) Specification

This separation is intentional so work can be delegated independently without ambiguity.

---

# DOCUMENT A: BACKEND ENGINEER SPECIFICATION

## 1. Scope & Assumptions

### In Scope
- Delivery partner authentication via **sessions**
- Proximity-based order discovery
- Atomic order assignment
- Real-time location broadcasting via **WebSockets**
- Delivery lifecycle management
- QR-based proof of delivery

### Explicitly Out of Scope (MVP)
- Chat
- Escrow logic beyond QR confirmation
- Dispute resolution
- Earnings payout logic

---

## 2. Authentication & Sessions

### Model
- Delivery partners authenticate via session-based auth (cookie or session token)
- Separate auth namespace from buyers/sellers

### Endpoints

#### POST `/auth/delivery/login`
Initiates login (OTP or credential-based).

**Request**
```json
{
  "phone": "+234xxxxxxxxx",
  "otp": "123456"
}
```

**Response**
```json
{
  "partner": {
    "id": "dp_123",
    "name": "John",
    "status": "ACTIVE"
  }
}
```

Session is established server-side.

---

## 3. Delivery Partner State

### PATCH `/delivery-partners/me/status`

```json
{
  "status": "ONLINE" | "OFFLINE"
}
```

### GET `/delivery-partners/me`

```json
{
  "id": "dp_123",
  "name": "John",
  "vehicleType": "BIKE",
  "rating": 4.7,
  "status": "ONLINE"
}
```

---

## 4. Location Ingestion

### POST `/delivery-partners/me/location`

```json
{
  "lat": 53.3498,
  "lng": -6.2603,
  "accuracy": 8,
  "heading": 120,
  "speed": 4.5
}
```

### Backend Responsibilities
- Store last known location
- Throttle updates
- Reject stale or invalid coordinates

---

## 5. Order Discovery (Proximity Logic)

### GET `/delivery/orders/available`

**Response**
```json
{
  "rangeMeters": 3000,
  "orders": [
    {
      "orderId": "ord_789",
      "pickup": {
        "lat": 53.348,
        "lng": -6.261
      },
      "dropoff": {
        "lat": 53.351,
        "lng": -6.258
      },
      "distanceMeters": 1200,
      "estimatedEarnings": 6.5
    }
  ]
}
```

### Rules
- Order status = `READY_FOR_DELIVERY`
- Not assigned
- Within backend-defined radius

---

## 6. Atomic Order Assignment

### POST `/delivery/orders/{orderId}/accept`

Success:
```json
{
  "assignmentId": "as_456",
  "status": "ASSIGNED"
}
```

Failure:
```json
{
  "error": "ORDER_ALREADY_ASSIGNED"
}
```

Must be transactional.

---

## 7. Delivery Lifecycle

### GET `/delivery/assignments/active`

```json
{
  "assignmentId": "as_456",
  "orderId": "ord_789",
  "pickup": { "lat": 53.348, "lng": -6.261 },
  "dropoff": { "lat": 53.351, "lng": -6.258 },
  "status": "EN_ROUTE_TO_PICKUP"
}
```

### PATCH `/delivery/assignments/{id}/status`

```json
{
  "status": "ARRIVED_PICKUP" | "PICKED_UP" | "EN_ROUTE_TO_DROPOFF" | "DELIVERED_PENDING_QR"
}
```

---

## 8. Proof of Delivery (QR-Based)

### Flow
1. Backend generates QR token bound to `orderId`
2. Buyer (logged in) scans QR
3. Backend validates token + buyer identity
4. Order marked `DELIVERED`

### POST `/delivery/orders/{orderId}/qr`
Returns QR payload.

### POST `/delivery/orders/{orderId}/qr/confirm`
Called by buyer app.

---

## 9. Real-Time Updates (WebSockets)

### Channels
- `delivery.partner.{partnerId}`
- `delivery.order.{orderId}`

### Events
```json
{
  "type": "DELIVERY_LOCATION_UPDATE",
  "lat": 53.349,
  "lng": -6.259
}
```

```json
{
  "type": "DELIVERY_STATUS_UPDATE",
  "status": "PICKED_UP"
}
```

---

---

# DOCUMENT B: DELIVERY PARTNER APP SPECIFICATION

## 1. Tech Constraints (Non-Negotiable)

- Expo (managed)
- NativeWind
- lucide-react-native
- React Context (no Redux, no TanStack)
- WebSockets for realtime

---

## 2. App Responsibilities

The app is **operational only**. No business logic.

### Core Responsibilities
- Authenticate and maintain session
- Report location
- Show nearby orders
- Accept one order at a time
- Update delivery status
- Display QR for buyer scan

---

## 3. Screens

1. Login (OTP)
2. Availability Toggle
3. Nearby Orders List
4. Order Preview
5. Active Delivery Map
6. Delivery Status Controls
7. QR Code Screen (Delivery Completion)

---

## 4. Global State (Context)

- Auth/session state
- Partner profile
- Availability status
- Active assignment
- WebSocket connection state
- Location tracking state

---

## 5. Location Tracking

### Rules
- Only active when ONLINE or on delivery
- Background updates allowed
- Respect OS battery limits

---

## 6. WebSocket Usage

### Subscriptions
- Partner channel
- Active order channel

### Handles
- Order taken elsewhere
- Status sync
- Location echo

---

## 7. Error Handling

- GPS denied
- Session expired
- Order already assigned
- Network loss
- App killed → restore state

---

## 8. Explicit Non-Goals (MVP)

- Chat
- Earnings dashboard
- History beyond last delivery
- Multi-order batching

---

## 9. Developer Success Criteria

The app is complete when:
- A partner can go online
- See nearby orders
- Accept exactly one
- Complete delivery via QR scan
- Recover state after app restart

Anything beyond this is feature creep.

