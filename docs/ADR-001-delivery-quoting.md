# ADR 001 — Delivery serviceability, quoting & fee engine

**Status:** proposed, awaiting sign-off
**Supersedes:** the inline `CartService._calculate_shipping_fee` stub

---

## Context

Delivery has a price today: a flat `DEFAULT_BASE_PRICE` multiplied by the number
of distinct markets a cart spans. It is computed twice (cart checkout and
payment initialisation), locked to nothing, expires never, and is not an
estimate of distance, zone, or anything else.

Launch is city-by-city with landmark-based estimates, and the data for that does
not exist yet. So the job now is the **seams**, not the numbers.

## Decision

Three separate things, deliberately not one:

### 1. Serviceability is a data-driven registry

Add `ServiceArea` above the existing Market/Area pair. Markets and Areas stay
exactly as they are — named, explicitly assigned, never geofenced.

```
ServiceCity      id, name, slug, is_active, launched_at
ServiceZone      id, city_id, name, slug, is_active,
                 centroid_lat, centroid_lng, radius_km    -- coarse, replaceable
DeliveryLane     id, from_zone_id, to_zone_id, is_active   -- what we actually serve
```

A lane, not a pair of points, is the unit of serviceability. "We deliver from
Bodija to UI campus" is a business fact someone decides; it is not derivable
from coordinates, and pretending otherwise is how you end up quoting a fee for
a route no rider will take.

`radius_km` on a zone is explicitly a placeholder shape for coarse containment
until landmark data exists. It is not the fee input.

**Checkout gates on the lane, both ends:**
- seller's `shop_latitude/longitude` → zone → is it active?
- buyer's pin → zone → is it active?
- is there an active `DeliveryLane` between them?

Any of those failing blocks checkout with a typed reason, never a silent pass.

### 2. A quote is an explicit, expiring object

```
DeliveryQuote
  id, buyer_id, created_at, expires_at
  pickup_zone_id, dropoff_zone_id, distance_km
  strategy, strategy_version
  fee_minor              -- kobo, integer
  breakdown_json         -- ordered, human-readable lines
  status                 -- active | consumed | expired
  idempotency_key
```

- **Minor units only.** `fee_minor` is an integer of kobo. Floats do not appear
  in this object. (The repo has a `MONEY` type and `to_money`; quotes use the
  integer form and convert at the boundary.)
- **Short TTL** — proposed **15 minutes**. Long enough to finish a checkout,
  short enough that a fee cannot be held while rates change.
- **Snapshotted onto the order at payment**, not re-read. The order stores the
  whole quote, including `strategy_version`, so a fee is always explainable
  after the fact even once the engine changes.
- **Re-quote on expiry** is a first-class flow, not an error: the client asks
  again, shows the new number, and requires an explicit re-confirm if it moved.

### 3. The fee engine is a strategy interface

```python
class FeeStrategy(Protocol):
    version: str
    def quote(self, ctx: QuoteContext) -> FeeBreakdown: ...
```

`QuoteContext` carries pickup, dropoff, resolved zones, distance, item count,
total weight, and cart value. `FeeBreakdown` is an ordered list of named
components plus a total in kobo.

Ship one implementation: **`ZoneBandStrategy`** — `base fee for the lane` +
`distance band surcharge`, both read from config, not code:

```
DELIVERY_FEE_CONFIG = {
  "lane_base_minor":   {"default": 50000},          # ₦500
  "distance_bands":    [[0, 3, 0], [3, 7, 20000], [7, 15, 50000]],
  "weight_surcharge":  {"threshold_grams": 10000, "per_kg_minor": 5000},
}
```

Distance comes from **`app/libs/geo.py:haversine_km`** — and as part of this,
`app/deliveries/services.py:haversine_distance` is deleted and its callers
repointed. Two implementations with different radii and units is the parallel
service the brief warned about, and it already exists.

When landmark/routing data arrives, it is a new strategy behind the same
interface and a config switch. No caller changes.

## Why not the alternatives

- **Keep computing inline.** Rejected: nothing to snapshot, nothing to expire,
  and the fee shown at cart can differ from the one charged with no record of
  either.
- **Geofence serviceability from coordinates.** Rejected: the Market/Area design
  already deliberately rejected this ("geographic coordinates are never the
  membership mechanism"), and coarse Nigerian address data would make it worse,
  not better.
- **Quote as a signed token instead of a row.** Rejected: we need to query
  quotes for reconciliation and support, and a row we can join to an order is
  worth more than a stateless token.

## Scenarios this must survive

| Scenario | Behaviour |
|---|---|
| Dropoff outside every served city | `NOT_SERVICEABLE_DROPOFF` + "not available here yet" + notify-me capture |
| Pickup not serviceable | `NOT_SERVICEABLE_PICKUP` — names the shop, not the buyer |
| Both serviceable, no lane | `NO_LANE` — "we don't deliver between these two yet" |
| Quote expired before pay | 409 `QUOTE_EXPIRED`, client re-quotes, re-confirms if the number moved |
| Landmark-only address | Quote returns `precision: "approximate"`; client requires pin confirmation before pay |
| Multi-seller cart | One quote **per pickup**, summed, each line shown separately (extends today's `delivery_count`) |
| Fee refunded independently | `fee_minor` is its own order line, refundable without touching item lines |

## Consequences

- One more round trip at checkout (quote before pay). Mitigated by quoting on
  address selection, not on the pay tap, and skeleton-loading the line.
- Quote rows accumulate; they expire and are prunable.
- `_calculate_shipping_fee` is deleted. Both current callers move to the quote.

## Open (blocking) questions

- Served cities and lanes for launch — which, exactly?
- Fee numbers for `ZoneBandStrategy` config. Stubs are non-fabricated
  placeholders (₦500 base, bands at 3/7/15km) and must not ship as real.
- Is the delivery fee refundable in full before pickup?
