# Logistics API contract

**Audience:** the affiliated logistics partner's engineering team.

**Status: proposed, and implemented on our side.** Markt speaks this today
behind an adapter interface (`app/delivery_pricing/logistics.py`); the
inbound half (§2) is live and tested, and the outbound half (§1) runs against
a stub until you confirm the shapes below. Anything still open is listed in
§5 rather than left for you to discover.

---

## What Markt does and does not do

Markt prices the delivery, takes the money, and tells you there is a parcel to
move. Markt does **not** route, dispatch, or decide which rider takes what —
that is yours.

Markt also runs its own rider fleet in some cities. Both models work at once:
an order goes to one provider or the other by configuration
(`LOGISTICS_ADAPTER`), and nothing downstream knows which. You will never
receive a job that our own fleet is also working.

---

## 1. Markt → you: create a job

```
POST {your_base_url}/jobs
Authorization: Bearer {token you issue to Markt}
Idempotency-Key: {order_id}
```

```json
{
  "order_id": "ORD_8KD2M1XQ",
  "pickup":  { "lat": 7.4188, "lng": 3.9060, "contact": "Amaka Fabrics" },
  "dropoff": { "lat": 7.4441, "lng": 3.8964, "contact": "Amaka Obi",
               "phone": "+2348087654321" },
  "items":   { "count": 3, "total_weight_grams": 2400 },
  "fee_minor": 70000,
  "notes": "Gate 2, ask for Amaka"
}
```

These fields are exactly the `JobRequest` dataclass, so the wire shape and the
code cannot drift apart. Notes on it, and why:

- **`fee_minor` is an integer number of kobo.** ₦700.00 is `70000`. No decimals
  anywhere in this contract, in either direction. Money that can carry a
  fraction of a kobo cannot be reconciled. Currency is NGN throughout and is
  not a field; when that stops being true it becomes one, deliberately.
- **`Idempotency-Key` is the order id and is stable across retries.** If we
  retry a job you already accepted, return the *same* job reference with `200`
  or `201` — do not create a second job. We will retry: networks fail after
  your side has already committed.
- **`pickup` has a contact name but no phone; `dropoff` has both.** That is
  what the dataclass carries. If your riders need to call the seller, say so
  and we will add it — we did not want to ship a field nobody had asked for.
- **No buyer identity beyond a name and phone.** A courier needs to find a door
  and announce themselves. Who shops on Markt is not part of that.
- **`notes` is free text from the buyer** and may be absent, empty, or
  unhelpful. Treat it as a hint for the rider, never as routing input.

**Expected response — `201`:**

```json
{ "job_id": "your-reference", "estimated_pickup_at": "2026-09-12T14:20:00Z" }
```

We store `job_id` opaquely and echo it back; it can be any string you like.
`estimated_pickup_at` is optional and ISO-8601 UTC.

**On a non-2xx** the order stays in `awaiting_dispatch` on our side, which
raises an operational alert. The buyer has already paid, so we do not retry
indefinitely and silently — we escalate to a human.

---

## 2. You → Markt: status updates

> **Live.** Implemented, signed, and exercised end to end against a local
> stack: synonyms map, duplicates and out-of-order updates are accepted and
> ignored, and an unsigned request is refused.

```
POST https://{markt_base_url}/api/v1/delivery/jobs/{job_id}/status
X-Markt-Signature: {see §3}
```

```json
{
  "status": "picked_up",
  "occurred_at": "2026-09-12T14:31:07Z",
  "reason": null
}
```

**Statuses we understand.** Send the one that matches. Both columns are
accepted — we map synonyms on our side so you never have to change your
vocabulary to suit ours:

| You send | | Means |
|---|---|---|
| `assigned` | `accepted` | a rider has the job |
| `picked_up` | `collected` | parcel is in the rider's hands |
| `in_transit` | `en_route` | on the way to the buyer |
| `delivered` | `completed` | handed over |
| `failed` | | could not be delivered — **send `reason`** |
| `cancelled` | | job will not happen |

Matching is case-insensitive and trims whitespace. Anything else is logged and
ignored rather than rejected.

**Three things we do deliberately, so you can retry freely:**

1. **Duplicates are a no-op.** Re-sending `picked_up` when we already have it
   returns `200` and changes nothing. Retry as much as you like.
2. **Out-of-order updates never rewind a parcel.** A late `assigned` arriving
   after `picked_up` is ignored, not applied. Webhooks arrive out of order and
   we would rather be right than obedient.
3. **We never return 5xx for a status we cannot use.** An unknown word gets
   `200` and a log line. A 500 only makes you retry harder at something that
   will never work.

`occurred_at` is when it happened on your side, not when you sent it. We use it
for ordering and for what the buyer sees; do not omit it.

`reason` is required on `failed` and shown to the buyer, so write it for them —
"nobody at the address" rather than an internal code.

---

## 3. Signing

Both directions sign the **raw request body** with HMAC-SHA512, hex-encoded,
in the header named above. We verify before parsing, using a constant-time
comparison.

SHA-512 rather than the more usual SHA-256 for one boring reason: it is what
our existing webhook verifier already does (`_verify_webhook_signature`, used
for Paystack), so the partner path is the same code rather than a second
implementation of the same idea. If SHA-512 is awkward for you, say so — this
is a preference, not a requirement.

Secrets are per-environment and issued by us. Rotation is a coordinated swap
with both keys accepted for 24 hours.

---

## 4. What we need from you

1. Base URL and auth scheme for job creation (we have assumed bearer above).
2. Confirmation of the status vocabulary. If yours differs, send us your list —
   we will map it on our side rather than ask you to change.
3. Whether you can honour `Idempotency-Key`. If not, tell us plainly and we
   will add a reconciliation step rather than risk duplicate jobs.
4. Your retry policy and timeout on status delivery.
5. Whether you can accept a **cancellation** before pickup, and what happens if
   one arrives after. We have not designed the call (`DELETE /jobs/{job_id}` is
   a guess) because the answer determines its shape. On our side cancellation
   is legal up to `assigned` and refused once the parcel is picked up.
6. Whether pickup needs a phone number (see §1).

---

## 5. Open on our side

- **Proof of delivery.** We have a QR-based flow for our own riders. Whether
  yours uses it, sends a photo, or neither, is undecided and blocks nothing
  above.
- **Multi-pickup jobs.** A Markt basket can span two sellers, and we price that
  as two deliveries. Whether it reaches you as two jobs or one multi-stop job
  is worth revisiting once volume justifies it; for now, two jobs.
- **Batch delivery.** We are building an option where several buyers in one
  area share a run and split the fee. It changes what we charge, not what we
  send you — a batched run is still one job per pickup-dropoff pair. If that
  assumption is wrong for your routing, tell us early.
