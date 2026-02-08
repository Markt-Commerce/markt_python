## Payment & Checkout Structure (Markt Python Backend)

This document explains how the payment system is wired end‑to‑end so you
can reason about the flow, debug issues, and safely extend it.

### 1. Core domain models

- **Order (`app/orders/models.py`)**
  - Represents what the buyer is paying for.
  - Has many `OrderItem` rows (each tied to a `Product` and `Seller`).
  - Key fields that matter for payments:
    - `id` / `order_number`
    - `buyer_id`
    - `status` (e.g. `PENDING`, `PROCESSING`, ...)

- **Payment (`app/payments/models.py`)**
  - One payment record per attempted charge for an order.
  - Key fields:
    - `order_id`: FK to `Order`
    - `amount`, `currency`
    - `method`: `PaymentMethod` enum (`CARD`, `BANK_TRANSFER`, ...)
    - `status`: `PaymentStatus` enum (`PENDING`, `COMPLETED`, `FAILED`)
    - `transaction_id`: gateway reference (Paystack `reference`/`id`)
    - `gateway_response`: raw JSON blob returned by Paystack
    - `paid_at`, `created_at`, `updated_at`

- **Transaction (`app/payments/models.py`)**
  - Ledger‑style record created when a payment succeeds.
  - Captures who paid whom, how much, and links back to the payment:
    - `user_id` (buyer), `seller_id`
    - `amount`, `reference`, `status`
    - `payment_metadata` (mirrors the gateway response snapshot)

### 2. High‑level payment flow

1. **Checkout creates an `Order`**
   - Cart → `Order` + `OrderItem`s.
   - `Order.status` starts as `PENDING`.

2. **Frontend calls `/api/v1/payments/create` or `/api/v1/payments/initialize`**
   - Both use `PaymentService.create_payment` under the hood.
   - A new `Payment` row is created with:
     - `status = PENDING`
     - `method` set from the request (`card` or `bank_transfer`).
   - For **card payments** (`CARD`):
     - `_initialize_paystack_transaction` calls Paystack
       `/transaction/initialize` and stores:
       - `payment.transaction_id` = Paystack `reference`
       - `payment.gateway_response` = full JSON response
     - `/payments/initialize` returns `authorization_url`, `reference`,
       `access_code` to the frontend.

3. **User completes payment on Paystack (inline widget / redirect)**
   - Paystack redirects/calls back with a `reference`.
   - Two verification paths exist:
     - **Synchronous**: `/api/v1/payments/<payment_id>/verify`
       calls `PaymentService.verify_payment` (GET
       `/transaction/verify/{reference}`).
     - **Asynchronous**: Paystack hits the webhook
       `/api/v1/payments/webhook/paystack` with events such as
       `charge.success` or `charge.failed`.

4. **On successful charge (`charge.success` webhook or direct processing)**
   - `Payment.status` becomes `COMPLETED`.
   - `Payment.paid_at` is set.
   - `Order.status` is moved from `PENDING` → `PROCESSING`.
   - Inventory is reduced via
     `ProductService.reduce_inventory_for_order(order.items)`.
   - A `Transaction` row is created to record the money movement.
   - Notifications are emitted to:
     - Buyer (`NotificationType.PAYMENT_SUCCESS`)
     - Seller(s) (`NotificationType.PAYMENT_SUCCESS`)
   - Real‑time events are published via `EventManager.emit_to_order(...)`
     so live dashboards can update.

5. **On failed charge (`charge.failed` webhook or exception)**
   - `Payment.status` becomes `FAILED`.
   - `gateway_response` contains failure detail.
   - Buyer receives a `PAYMENT_FAILED` notification.
   - Real‑time `payment_update` events are emitted.

### 3. Card payments (`PaymentMethod.CARD`)

- **Creation**
  - `POST /api/v1/payments/create`
  - Body: `PaymentCreateSchema` (order_id, amount, optional currency,
    method `card`, metadata).
  - `PaymentService.create_payment`:
    - Validates the order and status.
    - Ensures `method` resolves to `PaymentMethod.CARD`.
    - Calls `_initialize_paystack_transaction`:
      - `POST /transaction/initialize`
      - Sets `transaction_id` and `gateway_response`.

- **Charge existing authorization**
  - `POST /api/v1/payments/<payment_id>/process`
  - Body: `PaymentProcessSchema` with `authorization_code` or
    `card_token`.
  - `PaymentService.process_payment` routes to
    `_process_paystack_payment`:
    - `POST /transaction/charge_authorization`
    - On success:
      - Returns `status = PaymentStatus.COMPLETED`,
        `transaction_id`, and `gateway_response`.
    - On failure:
      - Returns `status = PaymentStatus.FAILED` with the raw response.

### 4. Bank transfer via Paystack Charge API (`PaymentMethod.BANK_TRANSFER`)

This is the dedicated flow for paying **from a bank account** using
Paystack's Charge API.

#### 4.1. Creating a bank‑transfer payment

- Frontend sends:

```json
POST /api/v1/payments/create
{
  "order_id": "ORD_...",
  "amount": 5000,
  "currency": "NGN",
  "method": "bank_transfer",
  "metadata": {
    "...": "..."
  }
}
```

- `PaymentService.create_payment`:
  - Creates the `Payment` row with `method = BANK_TRANSFER` and
    `status = PENDING`.
  - **Does not** immediately talk to Paystack; that happens when we
    "process" the payment.

#### 4.2. Processing the bank‑transfer charge

- Frontend then calls:

```http
POST /api/v1/payments/{payment_id}/process
Content-Type: application/json
```

Body (simplified example, see Paystack docs for full structure):

```json
{
  "bank": {
    "code": "057",
    "account_number": "0000000000"
  }
}
```

- `PaymentProcessSchema` accepts a `bank` object and passes it to
  `PaymentService.process_payment`.
- Inside `PaymentService.process_payment`:
  - Because `payment.method == PaymentMethod.BANK_TRANSFER`, it calls
    `_process_bank_transfer(payment, payment_data)`.

- `_process_bank_transfer`:
  - Validates that `bank` details are present and that the order/buyer
    are attached.
  - Builds a payload:
    - `amount` in kobo
    - `email` from the buyer
    - `currency`
    - `bank` (as provided from the frontend)
    - `metadata` containing `payment_id`, `order_id`, `buyer_id` and
      `method = "bank_transfer"`
    - `reference` reusing `PAY_{payment.id}` style references
  - Calls:

```text
POST {PAYSTACK_BASE_URL}/charge
Authorization: Bearer {PAYSTACK_SECRET_KEY}
```

  - On a successful API response:
    - Returns `status = PaymentStatus.PENDING`
    - Sets `transaction_id` based on the Paystack `reference`/`id`
    - Attaches the full `gateway_response` payload
  - If Paystack responds with an error or a non‑200 status:
    - Raises `APIError("Bank transfer processing failed", 500)`
    - `PaymentService.process_payment` marks the payment as `FAILED` and
      triggers failure notifications.

> **Why PENDING, not COMPLETED?**
> For bank transfers, Paystack usually needs an extra confirmation
> (customer action / OTP / settlement). The reliable signal of success
> is the asynchronous `charge.success` webhook, which reuses the same
> `reference` and updates the payment and order just like a normal
> card‑based charge.

#### 4.3. Webhook handling for bank transfers

- Webhook endpoint:
  - `POST /api/v1/payments/webhook/paystack`
  - `PaymentService.handle_webhook(payload, signature)`:
    - Verifies HMAC signature.
    - Routes events:
      - `charge.success` → `_handle_successful_charge`
      - `charge.failed` → `_handle_failed_charge`
      - `transfer.success` → `_handle_successful_transfer` (payouts).

- `_handle_successful_charge`:
  - Looks up the `Payment` by `transaction_id = reference`.
  - Sets:
    - `status = PaymentStatus.COMPLETED`
    - `paid_at = now`
    - `gateway_response = data`
  - Updates the `Order` to `PROCESSING`, reduces inventory, creates a
    `Transaction`, sends notifications and emits real‑time events.

### 5. How everything ties together in checkout

- **Buyer perspective**
  - Adds items to cart → places order.
  - Chooses payment method:
    - Card:
      - Initialise + redirect/inline Paystack.
      - Optionally re‑use saved `authorization_code` via `/process`.
    - Bank transfer:
      - Create payment with `method = bank_transfer`.
      - Call `/process` with `bank` details to start the charge flow.
  - Waits for success/failure UI updates driven by:
    - Polling `/payments/{id}` or `/payments/{id}/verify`.
    - Listening to real‑time events / webhook‑driven state on the
      frontend.

- **Seller perspective**
  - Receives `PAYMENT_SUCCESS` notifications and real‑time updates.
  - Sees order move into a "processing/fulfilment" state.
  - Inventory is already reduced by the time they act.

### 6. Extending the payment system safely

When adding new payment methods or changing flows:

1. **Respect the `Payment` lifecycle**
   - Always create a `Payment` in `PENDING`.
   - Move to `COMPLETED` only when the gateway confirms success (ideally
     via webhook).
   - Use `FAILED` for any hard failure and emit clear notifications.

2. **Keep the `transaction_id` and `reference` consistent**
   - They are the glue between:
     - our DB
     - Paystack's API
     - webhooks and callbacks

3. **Always update `Order` and inventory from a single, central path**
   - This is currently `_handle_successful_charge` and the
     `PaymentStatus.COMPLETED` branch in `process_payment`.
   - Avoid duplicating that business logic elsewhere.

4. **Prefer metadata over schema changes for one‑off gateway details**
   - If you need to track extra gateway data, add it under
     `gateway_response` or `metadata` instead of exploding the `Payment`
     table with many columns.
