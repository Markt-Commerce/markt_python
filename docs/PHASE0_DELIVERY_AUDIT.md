# Phase 0 — Delivery audit

**Status:** for sign-off. No feature code written.
**Scope:** what exists in `markt_python` and `markt_mobile` today for delivery in
the checkout → payment → order flow, and what is genuinely missing.

---

## Headline: three of the brief's premises do not match the repo

The brief was written from an understanding I could not confirm in the code.
Three corrections, because each changes what the work actually is.

### 1. Batch delivery is largely built already

`DeliveryRun` (`app/deliveries/models.py`) **is** batch delivery. It has a
market→area anchor, a cutoff window, capacity limits, a nine-state machine with
enforced transitions, a fee split (`price_per_order`), surge multipliers, and a
thin-volume prompt for the batch-does-not-fill case (`DeliveryRunWaitChoice`).
`app/deliveries/runs.py` implements attach/cutoff/close with worker tasks.

Workstream C as written ("batch entity + membership + anchor + radius + window
+ status + capacity + split") would rebuild what is there. The real batch work
is narrower and harder: **the money**.

### 2. There is no external logistics app in the code — riders are ours

`DeliveryUser` is a first-class authenticated user with vehicle type, live
location (`DeliveryLastLocation`), run assignment, QR proof-of-delivery, and
failure/recovery handling. There is no adapter, no outbound job creation, no
inbound status webhook, nothing addressed to a third party.

So "hand a job to an external logistics app" is not an integration we are
missing — it is a **different operating model** from the one built. This needs
a decision before any of Workstream B's logistics section makes sense.

### 3. The mobile client is not empty

`app/checkout/confirm.tsx` already renders an itemised breakdown including
`shipping_fee`, a `delivery_count`, and a multi-market warning.
`hooks/useShippingAddress.ts` already resolves an address from saved /
geolocation / manual sources. What is missing is narrower: serviceability
gating, a quote with a TTL, batch opt-in, and delivery tracking states.

---

## What exists

| Capability | Where | State |
|---|---|---|
| Markets & Areas (named, explicitly assigned, `is_active`, lat/lng) | `app/markets/models.py` | Works. This is the serviceability primitive. |
| Buyer address → Area resolution | `MarketService.resolve_area_for_coordinates` | Works, best-effort, returns `None` rather than raising |
| Seller shop coordinates | `Seller.shop_latitude/longitude` | Works (settable since the onboarding work) |
| Haversine distance | `app/libs/geo.py` **and** `app/deliveries/services.py` | **Duplicated** — see findings |
| Order money lines (`subtotal`, `shipping_fee`, `tax`, `discount`, `service_fee`, `total`) | `app/orders/models.py` | Columns exist; `shipping_fee` is a stub value |
| Shipping fee calculation | `CartService._calculate_shipping_fee` | Flat `DEFAULT_BASE_PRICE` × distinct markets |
| Order state machine | `OrderItem` / `Order` status enums with `transition_to` | Works |
| Batch runs | `app/deliveries/runs.py`, `DeliveryRun*` models | Substantially built |
| Rider execution layer | `DeliveryUser`, assignments, stops, QR POD, failures | Built |
| Paystack charge + webhook + signature verification | `app/payments/services.py` | Works |
| Refunds (partial, per-item, within-captured assertion) | `app/orders/services.py` | Works |
| Checkout fee breakdown UI | `app/checkout/confirm.tsx` | Works |

## What is missing

| Gap | Consequence |
|---|---|
| **No quote object** | The fee is computed inline at checkout and again at order creation. Nothing is versioned, nothing expires, nothing is locked. |
| **No serviceability gate** | An unresolved Area makes the order *ineligible for a run* — silently. Checkout is never blocked. A buyer outside every served area can pay and then have no delivery path. |
| **No fee engine seam** | `_calculate_shipping_fee` is a static method reaching into `app.deliveries.runs.DEFAULT_BASE_PRICE`. No interface to swap. |
| **No preauth** | Paystack is charge-only here. No authorization hold, no capture, no partial capture. |
| **Captured fee ≠ actual fee** | See below — the single most important finding. |
| **No idempotency on payment init** | `Order.idempotency_key` exists; payment initialisation has none. |
| **No delivery state on the order** | Delivery status lives on `DeliveryRun`/assignments, not reflected as an order-level delivery state the client can render. |
| **Client: no serviceability / quote / batch / tracking UI** | Buyer cannot see whether delivery is possible before paying. |

---

## The finding that matters most

`CartService._calculate_shipping_fee` documents its own gap, verbatim:

> **FLAGGED, NOT SOLVED**: this checkout-time captured `shipping_fee` and the
> real cost `DeliveryRunService.close_runs_past_cutoff` computes later
> (`run.price_per_order`, once the run's actual roster is known) are two
> unconnected numbers today — nothing reconciles a difference between what was
> captured here and what delivery actually costs once batched.

And `runs.py` on the same seam:

> the single-drop upcharge is a real payment-flow gap, not built here … rather
> than silently pretending it was charged.

So today: the buyer is charged a flat estimate at checkout; the batch computes a
real per-order price at cutoff; **the two never meet**. Batch delivery's promise
— "share a run, split the fee" — is computed and never collected or refunded.

This is the whole of ADR 2. Everything else in batch is built.

---

## Other findings worth fixing while here

1. **Two Haversine implementations.** `app/libs/geo.py:haversine_km` (km,
   radius 6371.0088) and `app/deliveries/services.py:haversine_distance`
   (metres, radius 6371000). Different units, different radii, same job. The
   brief asked me not to add a parallel one; there is already a parallel one.
2. **`shipping_fee` is per-market, not per-distance.** A buyer 200m from the
   market and one 8km away pay the same. Defensible as a placeholder, but it
   means the fee is not yet an estimate of anything.
3. **Area resolution is optional and silent.** An address that resolves to no
   Area produces a normal, payable order that can never join a run.
4. **No `city` concept.** Launch is city-by-city, but the hierarchy is
   Market → Area with no city above it. Serviceability has nowhere to hang.

---

## Blockers — I need decisions on these

1. **PSP preauth.** Paystack is confirmed as the gateway
   (`PAYMENT_GATEWAY=paystack`, `PAYSTACK_BASE_URL` in
   `app/payments/services.py`). **Preauth is not implemented anywhere.** I
   cannot confirm from the code whether it is *enabled on your account* —
   Paystack gates pre-authorization per-merchant. Please confirm with Paystack
   support. ADR 2 is written to work either way, but which branch is primary
   depends on this.
2. **Logistics: internal or external?** The code has an internal rider fleet.
   The brief describes an external partner. These are different products.
   Which is it at launch — and if external, does the internal rider layer stay,
   get retired, or run alongside for some cities?
3. **Multi-seller carts at launch.** Allowed today, and priced as one fee per
   distinct market. Keep, split into per-seller orders, or block?
4. **Business numbers:** batch window length (currently 2h), radius/anchor
   (currently market→area membership, not a radius), thin-volume threshold
   (currently 3 orders), and who absorbs kobo rounding on a split.
5. **Cancellation/refund policy** for the delivery fee specifically — is it
   refundable before pickup, and in full?
6. **(Later) data:** served cities, landmark/zone table, distance→fee bands.

---

## Recommended sequencing, given what exists

Not the brief's A→B→C. The dependency order the code implies:

1. **Serviceability + quote + fee engine** (Workstream A) — genuinely new, and
   everything else locks onto the quote.
2. **Order/payment wiring of the quote** (Workstream B, minus logistics) —
   snapshot the quote, idempotent payment, delivery state on the order.
3. **Logistics boundary** — blocked on decision 2 above.
4. **Batch money model** (the real Workstream C) — reconcile captured vs actual
   against the existing `DeliveryRun`. Behind a flag.
5. **Mobile wiring** (Workstream D) — after the quote endpoint exists.
