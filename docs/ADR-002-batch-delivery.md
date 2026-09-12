# ADR 002 — Batch delivery: the payment-timing model

**Status:** proposed, awaiting sign-off
**Depends on:** ADR 001 (quote object), and a decision on Paystack preauth

---

## Context

Batch delivery is mostly built. `DeliveryRun` has the anchor (market→area), the
window (`cutoff_at`, 2h cadence), capacity (30 packages / 50kg), a nine-state
machine with enforced transitions, surge, a thin-volume prompt, and a per-order
split (`price_per_order`). `app/deliveries/runs.py` runs attach/cutoff/close.

What it does not have is **the money**. Both files say so:

- `CartService._calculate_shipping_fee`: *"this checkout-time captured
  `shipping_fee` and the real cost … are two unconnected numbers today —
  nothing reconciles a difference."*
- `runs.py`: *"the single-drop upcharge is a real payment-flow gap, not built
  here … rather than silently pretending it was charged."*

So the buyer is charged a flat estimate at checkout, the run computes a true
per-order price hours later at cutoff, and nothing ever settles the difference.
The product promise — *share a run, split the fee* — is currently computed and
discarded.

**This ADR is about that, and only that.** Do not rebuild the run machinery.

## The core problem

The batch fee is unknowable at pay time. It depends on how many other buyers
join before cutoff, which is up to two hours away. So either:

- we charge late (and risk a failed charge after goods are committed), or
- we charge the maximum early and give back the difference, or
- we hold the maximum early and capture only what is owed.

## Decision: hold-max-capture-actual, with a charge-max-refund fallback

### Primary — preauth (card payments, if enabled)

1. At checkout, quote the **solo** fee (ADR 001). This is the ceiling: a batch
   can only ever make it cheaper, never dearer.
2. **Authorize** `items + solo_fee`. Funds held, not taken.
3. Buyer joins a run. Cutoff passes. `price_per_order` is known.
4. **Capture** `items + actual_fee`. Paystack releases the difference
   automatically; no refund, no fee on the refund, no reconciliation.
5. Run never fills → capture at the solo fee. The buyer pays exactly what they
   were quoted, which is what they agreed to.

The window matters: Paystack holds are valid **5–10 days** depending on the
issuer. The 2h cadence sits well inside that, with room for a failed run and one
reassignment. If a run cannot complete inside the hold window, capture at solo
and treat the shortfall as a business cost — never let a hold lapse silently.

### Fallback — charge-max-then-refund (bank transfer, USSD, non-preauth cards)

Same ceiling, different mechanics: charge `items + solo_fee` up front, then
refund `solo_fee − actual_fee` after cutoff.

Worse in three specific ways, which is why it is the fallback: the buyer's money
genuinely leaves and comes back (days, visibly), Paystack refund fees apply to
us, and a failed refund needs a retry queue with alerting rather than being
Paystack's problem.

**A third option — charge solo, credit the saving to the wallet — is rejected.**
The wallet exists, so it is tempting. But "you saved ₦200, here is store credit"
is not a discount, it is a lock-in, and selling it as a saving is dishonest. If
we ever offer it, it must be an opt-in choice with the cash refund as default.

### Selection

`PaymentCapability.supports_preauth(payment_method)` decides, per payment, at
checkout. The buyer is told which applies in plain terms *before* paying —
"you'll be charged ₦500; if the batch fills you'll be charged less" versus
"you'll be charged ₦500 and refunded the difference within N days". Never
discover it afterwards.

## Fee split

At cutoff, over the surviving orders in the run:

```
run_cost_minor = base_lane_fee + distance_component + (surge × base)   # ADR 001 engine
share_minor    = run_cost_minor ÷ n_surviving
capped_share   = min(share_minor, order.solo_quote_fee_minor)
```

**The cap is not optional.** A buyer must never pay more for sharing than they
were quoted alone — that is the promise. If the arithmetic ever exceeds the solo
fee (a tiny run with high surge), Markt absorbs the difference.

Deliberately **equal split, not detour-weighted**, for launch. Detour weighting
needs real routing data we do not have, and an unexplainable fee is worse than a
slightly unfair one. Revisit when routing data exists; the shape allows it.

**Rounding:** integer kobo division, remainder distributed one kobo at a time to
the **earliest joiners** by `created_at`. Deterministic, favours the people who
committed first, and never leaves the run under-collected. Recorded in the run's
breakdown so support can explain any individual number.

## Join / leave / concurrency

- **Joining** is attaching to an `OPEN` run — already implemented
  (`attach_eligible_orders`).
- **Leaving** (cancellation before cutoff) recomputes remaining shares. Safe,
  because nothing is captured until cutoff and every share is capped at its own
  solo quote — a departure can raise others' shares but never above what each
  already agreed to. **No one is ever surprised.**
- **Leaving after cutoff** does not recompute. Prices are final at cutoff;
  a late cancellation refunds that buyer and the run's cost stays split as
  closed. Markt absorbs it.
- **Concurrency.** `close_runs_past_cutoff` must take `SELECT … FOR UPDATE` on
  the run before reading its roster, and joining must take the same lock. The
  repo already uses `with_for_update()` in inventory reservation and has a
  concurrency test for it (`tests/test_inventory_concurrency.py`) — same pattern,
  and batch needs its own equivalent test with two real threads.
- **Capacity** is already enforced (`RUN_MAX_PACKAGES` / `RUN_MAX_WEIGHT_GRAMS`)
  with overflow to a second run.

## Transactional boundary

The dangerous edge is *paid, but no delivery*. Explicitly:

1. Order + quote snapshot + authorization → **one transaction**. Failure here
   leaves no order.
2. Run attachment → **separate**, retryable, and *not* required for the order to
   be valid. An order that never attaches is a solo delivery at the solo fee.
3. Capture → separate, idempotent on `(order_id, capture_attempt)`.
4. Rider/job dispatch → separate. Failure here **must not** strand a captured
   order: it raises an ops alert and the order sits in `awaiting_dispatch`, it
   does not silently succeed.

Every step idempotent, because network retries will happen.

## Feature flag

Everything above sits behind `DELIVERY_BATCH_ENABLED` (default **off**). With
it off: solo quote, charge at solo, no run attachment, no capture step. The solo
flow must be shippable and correct with batch entirely dark.

## Scenarios

| Scenario | Behaviour |
|---|---|
| Batch never fills | Capture at solo fee. Buyer pays the quoted number. |
| Buyer joins then leaves pre-cutoff | Others recomputed, each capped at their own solo quote |
| Batch closes mid-join | Row lock; the late joiner goes to the next open run |
| Method can't preauth | Charge-max-refund, disclosed before paying |
| Preauth expires before cutoff | Capture at solo; never let a hold lapse |
| Capture fails after cutoff | Retry queue + alert; order flagged, not silently completed |
| Run cancelled after capture | Full refund of the delivery line only; items unaffected |

## Blockers

1. **Is preauth enabled on the Paystack account?** Not inferable from code —
   it is per-merchant. If no, the fallback becomes primary and the buyer
   experience is materially worse; worth pursuing with Paystack first.
2. **Window (2h) and thin-volume threshold (3)** — currently judgment calls in
   `runs.py`, explicitly flagged there as not spec-given. Need real numbers.
3. **Who absorbs the capped-share shortfall** and post-cutoff cancellations —
   assumed Markt above; confirm.
4. **Radius vs. area membership.** The brief says radius-from-pickup; the code
   uses market→area membership. Membership is more honest with the data we have.
   Confirm we keep it.
