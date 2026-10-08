# Delivery architecture

How a parcel gets priced, paid for, and carried. Written as-built.

## The shape

```
        buyer picks an address
                 │
       GET /delivery/serviceable ──── do we reach this point at all?
                 │
       POST /delivery/quote ───────── a price, held for 15 minutes
                 │
            checkout ──────────────── the quote is consumed and snapshotted
                 │                    onto the order, in one transaction
             payment
                 │
            mark_paid ─────────────── QUOTED → PAID, inside the payment's
                 │                    own transaction
             dispatch ────────────── PAID → JOB_CREATED, after it commits
                 │
     POST /delivery/jobs/<id>/status  the courier reports back
                 │
             DELIVERED
```

## The five pieces

| Module | Holds |
|---|---|
| `delivery_pricing/models.py` | `ServiceCity`, `ServiceZone`, `DeliveryLane`, `DeliveryQuote` |
| `delivery_pricing/fees.py` | the pluggable `FeeStrategy`, and `ZoneBandStrategy` |
| `delivery_pricing/services.py` | serviceability, quote creation and consumption |
| `delivery_pricing/order_delivery.py` | `OrderDelivery` and its state machine |
| `delivery_pricing/dispatch.py` | `mark_paid`, `dispatch`, `cancel_for_order` |
| `delivery_pricing/logistics.py` | the adapter boundary and inbound status mapping |

## Decisions worth knowing

**Money is integer kobo everywhere in delivery.** Orders store naira in
`NUMERIC(12,2)`; `from_subunit` / `to_subunit` in `app/libs/money.py` are the
only crossings. A delivery fee gets divided across several buyers when a run
is shared, and a fee that can carry a fraction of a kobo cannot be reconciled.

**A quote is consumed, once, inside the order's transaction.** Not read and
then written: two checkout submissions milliseconds apart would both see an
active quote and both attach it, and the second order would ride on a fee it
never reserved. `consume()` takes a row lock and re-checks expiry inside it.

**The quote is snapshotted onto the order, field for field.** The quote row
records what we quoted; `OrderDelivery` records what this order was sold. They
stop being the same thing the moment a fee strategy is retuned or a zone
redrawn, and a six-month-old order still has to be able to explain its own fee.

**An expired quote is still honoured once the money is taken.** Expiry exists
to stop a stale price *starting* a purchase, not to void one that completed —
a slow gateway can outlast fifteen minutes on its own. Taking someone's money
and then refusing to record what they bought is not a way to enforce a TTL.

**Paying and dispatching are separate, on purpose.** `mark_paid` runs inside
the payment's transaction, because a delivery that thinks it is unpaid for an
order that is paid is a lie. `dispatch` runs after it commits, because it
calls another company over the network: it must never roll back a payment that
succeeded, nor leave a real courier job against an order that did not commit.

**Nothing about delivery may fail a paid order.** A provider that refuses the
job parks the delivery at `AWAITING_DISPATCH` where an operator can see it. A
delivery that cannot be attached at all is logged and left. The money has
moved; the order must exist.

**Cancellation is legal up to `ASSIGNED` and refused after pickup.** Past that
a rider is holding the parcel, and cancelling becomes a return — a different
process with a real cost. The check runs before the order is mutated, so a
refusal leaves it untouched.

**Serviceability is a circle per zone, and that is temporary.** `ServiceZone`
is a centroid and a radius; `zone_for_point` answers with the nearest centroid
whose radius contains the point, which is deterministic and explainable rather
than correct. Real boundary polygons replace it without touching anything
above.

## Fee strategies

`ZoneBandStrategy` (`zone_band`, v1.0.0) is a base fee, a distance band, and a
weight surcharge over a threshold. It is registered by name, and every quote
records `strategy` and `strategy_version`, so an old fee can be explained by
the rules that actually produced it. `get_strategy()` falls back rather than
raising on an unknown name, because a quote written by a strategy that has
since been removed still has to be readable.

## What is not built

- **Batch delivery settlement.** Designed in ADR-002; the money model is not
  implemented. Note the amendment there: Paystack's preauthorization is
  ZAR-only, so the hold-and-capture mechanism that ADR chose is unavailable
  for NGN, and the fallback is materially worse for the buyer.
- **Multi-market baskets.** A basket spanning two markets is two deliveries.
  Checkout refuses a single quote for one rather than undercharging.
- **Proof of delivery from a partner.** Our own riders have a QR flow; what a
  partner sends is undecided.
- **Real payment verification end to end.** Needs a genuine Paystack test
  secret; capture and webhooks are untested against the live gateway.

## Where to look first

- Something is priced wrong → `fees.py`, then the quote's own `breakdown`.
- A delivery is stuck → its `state`, then `dispatch.py`.
- A courier's updates are not landing → `logistics.py`'s `PROVIDER_STATUS_MAP`
  and the signature check in `routes.py`.
- A fee disagrees with the order total → `from_subunit`, the one crossing.
