# Delivery QA checklist

What to run against a local stack to convince yourself the delivery path
works, and what each step is actually proving. Every result below was
observed on 2026-09-12 against a disposable local database.

## Setup

```bash
docker start markt-postgres-dev markt-redis-dev
export DB_HOST=localhost DB_PORT=5432 DB_USER=markt DB_PASSWORD=markt123 DB_NAME=markt_db
export REDIS_URL=redis://localhost:6380/0
export FLASK_APP=main.setup:create_flask_app
flask db upgrade
python scripts/seed_delivery_areas.py --activate
flask run --host 127.0.0.1 --port 8000 --no-reload
```

The seed is idempotent: run it twice and the second run reports
`0 created, 25 already present` with no new rows. It refuses any database
that is not local.

## 1. Serviceability

| Check | Expect |
|---|---|
| `GET /delivery/serviceable?latitude=7.4305&longitude=3.9047` | `serviceable: true`, Ibadan / Bodija |
| `GET /delivery/serviceable?latitude=6.6018&longitude=3.3515` (Lagos) | `serviceable: false`, null city |
| Called with no session | works — it is deliberately unauthenticated |

Someone deciding whether Markt is worth signing up for should be able to
find out if we reach them.

## 2. Quoting

`POST /delivery/quote` with a seller in Bodija and a dropoff at UI:

```json
{"fee_minor": 50000, "distance_km": 1.7676, "strategy": "zone_band",
 "strategy_version": "1.0.0", "precision": "approximate",
 "breakdown": {"total_minor": 50000, "lines": [{"label": "Base delivery fee", "amount_minor": 50000}]}}
```

- ₦500.00 is the base fee with no distance surcharge, which is right: 1.77 km
  falls in the 0–3 km band, and 500 g is under the weight threshold.
- An unserviceable dropoff returns **422** with a structured body carrying
  `reason: "dropoff_not_serviceable"` and `error_type`. The reason field is
  the thing the app branches on, so check it survives — `flask_smorest.abort`
  drops extra keys, which is why the service raises instead.

## 3. Checkout with a quote

`POST /cart/checkout` with `delivery_quote_id`:

- Response `shipping_fee` is **500.0**, matching the quote's 50000 kobo.
- `order_deliveries` has a row: `state=QUOTED`, `fee_minor=50000`,
  `solo_fee_minor=50000`, `settled_fee_minor=null`, `batch_opt_in=false`,
  plus `distance_km`, `strategy` and `strategy_version` copied from the quote.
- The quote row flips to `CONSUMED` with `order_id` set.
- Cross-check the two representations agree:

```sql
select o.shipping_fee, od.fee_minor, (o.shipping_fee*100)::int = od.fee_minor as agree
from orders o join order_deliveries od on od.order_id = o.id;
```

## 4. The refusals

Each of these must leave **no order behind**. Check `select count(*) from orders`
before and after.

| Attempt | Expect |
|---|---|
| Re-use a quote already on an order | `409` "already been used" |
| Spend another buyer's quote | `404` "not found" — *not* 403, which would confirm it exists |
| Use an expired quote | `409` "has expired" |
| Check out with no quote at all | succeeds on the flat fallback, no `order_deliveries` row |

The last one is the compatibility case: app builds in the wild do not send a
quote yet and must keep working.

## 5. Payment-first checkout

`POST /payments/checkout/initialize` takes the same `delivery_quote_id`. Its
quote validation runs *before* Paystack is called, so the three refusals above
can be checked without a working gateway key — they return 404 / 409 / 409 and
create no Payment row.

A failed Paystack call must leave reservations `RELEASED`, not `HELD`:

```sql
select status, count(*) from inventory_reservations group by status;
```

## 6. Not covered here

- **A real payment.** Needs a genuine Paystack test secret
  (`sk_test_...` from the dashboard); the placeholder key in the local env
  fails at `transaction/initialize`, so capture, webhooks and
  `complete_checkout_payment` are untested end to end.
- **Pre-authorization.** Not reachable at all: Paystack's preauthorization
  API is ZAR-only and Markt charges in NGN. See the amendment to ADR-002.
- **Batch settlement.** Not built yet.
