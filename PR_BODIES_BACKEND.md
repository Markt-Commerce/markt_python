# PR bodies — markt_python

**Ten PRs**, all branched from `develop`. Mutually independent except where a
merge-order note says otherwise.

## Suggested merge order

1. `chore/toolchain-gevent` — one-line dependency pin, unblocks fresh setups
2. `refactor/money-numeric` — **before** `feature/wallet-audit`; they conflict
   in `app/wallet/services.py` and `tests/test_wallet.py` (see PR 5)
3. `feature/wallet-audit`
4. `feature/account-deletion`
5. Everything else, any order: `fix/post-detail-liked-by-me`,
   `feat/content-reporting`, `feat/saved-items`, `feat/public-profile`,
   `feat/product-share`, `perf/feed-hydration-n1`

Three mobile PRs depend on a backend PR being **deployed** first — noted in each.

### After merging the schema branches, run `flask db merge heads`

`refactor/money-numeric`, `feature/account-deletion`, `feat/content-reporting`
and `feat/saved-items` each add a migration branching from `72bf175405d5`. Once
all four are on `develop`, alembic sees **four heads** and `flask db upgrade`
fails with *"Multiple head revisions are present"*. One command fixes it:

```
flask db merge heads -m "merge schema branches"
```

That generates an empty merge revision joining them. Verified on a branch with
everything merged: all 23 migrations then apply cleanly from an empty database,
single head, and `flask db check` reports no drift.

### One test fixture needs a one-line fix after merging

`tests/test_wallet.py::test_balance_mutations_lock_the_wallet_row` passes on
`feature/wallet-audit` and on `refactor/money-numeric` **individually**, and
fails once both are merged: the fixture sets `available_balance=1000.0` (a float)
which now meets a `Decimal` amount. Change it to `to_money("1000.00")`. Neither
branch is wrong alone, so this can only be fixed post-merge.

## Ship-blockers for App Store review

`feature/account-deletion` (guideline 5.1.1(v)) and `feat/content-reporting`
(guideline 1.2) are both hard review gates for an app with user-generated
content. Both now have their mobile UI too.

## Previously flagged, now closed

All nine items flagged for a decision have been implemented:

| # | Item | Where |
|---|---|---|
| 1 | `db.Float` → `NUMERIC(12,2)` | PR 5 |
| 2 | gevent won't build on 3.12 / needs `setuptools<81` | PR 4 |
| 3 | `/products/<id>/share` stub that 500s | PR 9 |
| 4 | Save / wishlist / report don't exist | PRs 6 and 7 |
| 5 | No public profile for the feed author to link to | PR 8 |
| 6 | Withdrawals take a hand-typed bank code | PR 1 |
| 7 | `settle_eligible_order_items` nested `session_scope` | PR 1 |
| 8 | Feed vs detail field-name mismatch | PR 3 |
| 9 | Deletion 409 dropped the blockers array | PR 2 |

Plus one found while auditing for N+1: **PR 10**, a per-item query storm in feed
hydration.

## Still open — needs your decision

- **`UserSettings.privacy_public_profile`** exists, defaults to `False`, and is
  read by nothing. Gating the public profile on it as written would hide every
  profile including sellers'. Left alone rather than given invented semantics
  (PR 8).
- **Share tracking** — the share endpoint returns links but records nothing. No
  consumer exists for the metric yet (PR 9).
- **The feed is `@login_required`.** A new user sees nothing until they sign up,
  which is directly at odds with "let people feel the value before demanding a
  signup". Opening it to anonymous callers is a product and scraping-exposure
  call, not a code cleanup — but it is the single biggest lever on that
  principle. The hydration path already handles `user_id=None`.

---
---

# PR 1 — `feature/wallet-audit` → `develop`

**Title:** `fix(wallet): correct concurrency, idempotency and Paystack verification in the wallet`

## Description

Audit of the wallet/Paystack integration against Paystack's current published
docs, plus fixes for what it turned up.

**Verified already correct** (no change needed): webhook signature verification
(HMAC-SHA512 over the raw body, `hmac.compare_digest`, `X-Paystack-Signature`),
env-based secret key handling with no client exposure, `complete_payment`'s
existing row lock and status-transition graph, and the deterministic ledger
idempotency keys.

**Fixed:**

1. **`credit()`/`debit()` had no row lock.** Unlocked read-modify-write on
   `available_balance`. Paystack retries a webhook every 3 minutes ×4 then hourly
   for up to 72 hours, so concurrent deliveries of the same event are routine —
   two interleaved credits each read the same starting balance and one write is
   lost. On the debit side, two concurrent withdrawals could both pass the
   balance check and together overdraw the wallet. Both now take
   `SELECT … FOR UPDATE` before anything else; taking it *before* the idempotency
   lookup also makes that check-then-insert atomic per wallet.
2. **Top-ups were credited without checking what Paystack reported.**
   `complete_topup` never inspected `data.status`, `data.amount` or
   `data.currency`, so a validly-signed event carrying a different amount still
   moved whatever the local top-up row claimed.
3. **The top-up callback URL pointed at a route that was never registered.**
   Users landed on a 404 and the app was never deep-linked back. Added, plus
   `GET /wallet/topup/<id>/verify` for the client.
4. **Kobo conversion truncated instead of rounding** on all four Paystack amount
   fields — ₦1234.56 became 123455, a kobo short.
5. **`transfer.reversed` was silently dropped**, leaving the user debited for a
   payout that bounced back.
6. **A failed debit orphaned the withdrawal request** as permanently PENDING.
7. **`POST /wallet/withdraw` returned `"WithdrawalStatus.PENDING"`** instead of
   `"pending"`, disagreeing with the list endpoint.
8. **Settlement committed the batch piecemeal.** The task held one
   `session_scope` open across the whole eligible set and called `WalletService`
   inside it; since `session_scope` hands out the same scoped session, the
   credit's commit also committed every `settled_at` written so far. Now one
   short transaction to select ids, then read → credit → mark per item.

**Also adds:** bank list and account-name resolution (`GET /wallet/banks`,
`GET /wallet/banks/resolve`) so the withdrawal form can be a picker with name
confirmation instead of a hand-typed code; and a local smoke harness
(`tests/smoke/`) that drives real HTTP against a disposable database.

## Tickets / Related Issue

Ticket ID [link] · Fixes #[Issue number]

## Type of Change
- [x] Bug fix
- [x] New feature <!-- callback, verify and bank endpoints -->
- [ ] Breaking change
- [ ] Documentation update

## How Has This Been Tested?

**Unit suite:** `525 passed, 2 skipped`. 7 tests added — 4 on the top-up payload
checks, 1 asserting the wallet row lock is taken, 2 on settlement.

**Coverage — `app/wallet` + `app/payments`, unit suite only: 57%**
(`app/wallet/services.py` 41%, `app/payments/services.py` 51%, models and schemas
100%). That number reads low because the unit suite mocks the session, so route
and service-integration lines look uncovered even though the smoke suite
exercises them — and the smoke run drives a separate server process, so its
coverage doesn't merge into this report.

**Smoke suite (real HTTP, real Postgres, Paystack TEST keys): 60/60 passing** —
the top-up initialize → callback → webhook path, a tampered signature rejected, a
valid signed webhook moving the balance by exactly the reported amount, 5× replay
not moving it again with exactly one ledger row, and signed webhooks with wrong
amount/currency/status refusing to credit.

**Concurrency suite: 14/14 passing**, and validated against the pre-fix code to
prove it detects what it targets:

| Scenario | Pre-fix | With fix |
|---|---|---|
| 12 concurrent distinct credits | **8 of 12 lost** (+₦400 not +₦1200) | all 12 land |
| 12 concurrent replays, one idempotency key | **`UniqueViolation`** raised | exactly one credit |
| 38 withdrawals vs. a balance funding 26 | **37 granted** (overdrawn) | exactly 26 |
| Ledger `balance_after` vs. running total | **inconsistent** | consistent |

Bank endpoints verified against the Paystack **test** API: 281 active NGN banks
sorted by name; a bogus account number resolves to a 422 carrying Paystack's own
message.

**CI gates run locally as `.github/workflows/ci.yml` runs them:** `black --check`
(22.12.0) clean on all 11 changed Python files; `flake8` clean across every
tracked file.

## Tested & Approved by? — [QA Engineer]

## Checklist
- [x] Style guidelines · [x] Self-review · [x] Commented · [ ] Docs · [x] No new warnings · [x] Tests added · [x] Existing tests pass

## Additional Notes

- **Deploy before** mobile `feature/wallet-mobile-wiring`, which calls
  `GET /wallet/topup/<id>/verify`.
- **`tests/smoke/` is not wired into CI** and shouldn't be. Every entry point
  hard-refuses unless the database name ends in `_smoke`, the host is local, and
  the Paystack key starts with `sk_test_`.
- `smoke_concurrency.py` deliberately imports the app factory rather than
  `main.run`: `main.run` calls gevent's `patch_all()`, which turns threads into
  greenlets, and since psycopg2 blocks in C every "concurrent" call would
  serialise and the test would pass without proving anything.
- Includes a `chore(pre-commit)` commit excluding `tests/smoke/` from the
  `remove-print-statements` hook, which would otherwise strip all 20 `print()`
  calls and leave three scripts that pass silently.
- The mobile withdrawal form is still free-text; turning it into a picker is the
  follow-up in `feature/wallet-mobile-wiring`.

---
---

# PR 2 — `feature/account-deletion` → `develop`

**Title:** `feat(users): in-app account deletion (Apple App Store 5.1.1(v))`

## Description

Adds `DELETE /users/account` and `GET /users/account/deletion-check`. Nothing
existed — no endpoint, no column, no UI hook. Required by guideline 5.1.1(v): an
account created in the app has to be deletable from inside the app, and
deactivation explicitly does not satisfy it.

Two constraints pull against each other: everything personal has to go, but
deleting the `User` row outright would orphan or cascade away records belonging
to other people. So the row survives as a tombstone with every personal field
overwritten, and authorship reads as a deleted user.

| Destroyed | Retained (anonymized) |
|---|---|
| Email, username, phone, avatar, password hash · postal address · push tokens and notifications · follow graph · cart · **seller Paystack subaccount and payout bank details** | Posts, comments, reviews · chat messages · orders and order items · payments and transactions · wallet ledger entries |

Products are ARCHIVED rather than DELETED, so nothing from a deleted seller stays
buyable while existing order items still resolve what was bought.

**The subtle part:** bearer tokens are a signed user id with a 30-day life and no
server-side session store, so keeping the row means it is still loadable. Both
Flask-Login loaders now return `None` when `deleted_at` is set, and `login_user`
rejects deleted accounts with the same "Invalid credentials" as a non-existent
one rather than confirming an account once existed there.

Deletion is refused while the user holds money or open obligations — a funded
wallet, an order in flight on either side, or a payment still confirming — and
`deletion-check` reports those up front. Requires the account password and a
typed `DELETE` confirmation.

## Tickets / Related Issue

Ticket ID [link] · Fixes #[Issue number]

## Type of Change
- [ ] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Documentation update

## How Has This Been Tested?

**Unit suite:** `523 passed, 2 skipped`. 6 tests added covering blockers, wrong
password, field-level anonymization, seller payout scrubbing, repeat deletion,
and the null-hash login path.

**Coverage — `app/users`, unit suite only: 42%** (`services.py` 21% of an
826-statement module of which this PR touches one service class; `schemas.py`
83%, `models.py` 69%). The deletion paths themselves are covered by the 6 new
tests plus the smoke checks below.

**Smoke suite: 11/11 deletion checks passing** — clean account reports
`can_delete: true`; wrong password 401; bad confirmation 422; deletion 200; **the
pre-deletion bearer token stops authenticating**; the account can't log in again;
a funded account reports `wallet_balance` and is refused with 409; an account
with a real checked-out order reports `open_orders_buying` and is refused; a
refused deletion leaves the account fully usable.

**Anonymization verified directly in the database** after a real deletion: email
`deleted-…@deleted.markt.invalid`, username `deleted_user_…`, phone null, avatar
reset, `email_verified` false, `is_active` false, password hash null,
`deleted_at` set, and `user_addresses`/`push_tokens`/`notifications`/`follows` all
at 0 rows.

**CI gates:** `black --check` clean on 7 changed files; `flake8` clean. Migration
`e143139d1aef` on head `72bf175405d5`, index created, no drift.

## Tested & Approved by? — [QA Engineer]

## Checklist
- [x] Style guidelines · [x] Self-review · [x] Commented · [ ] Docs · [x] No new warnings · [x] Tests added · [x] Existing tests pass

## Additional Notes

- **Deploy before** mobile `feature/account-deletion`.
- **The three retention rules were product decisions, confirmed before
  building:** block on a funded wallet, block on open orders,
  anonymize-and-keep content. Worth a second look before merge if any have moved.
- One commit fixes a bug in this branch's own first commit: the migration's
  revision id was hand-written as `a1b2c3d4e5f6`, which is **already taken** by a
  mid-chain revision. That split the graph and only surfaced when migrations were
  run from zero. Re-issued as a generated, verified-unique id. **Reviewers:
  please don't hand-write revision ids.**

---
---

# PR 3 — `fix/post-detail-liked-by-me` → `develop`

**Title:** `fix(socials): return liked_by_me from the post detail endpoint`

## Description

The feed sends `liked_by_me` on every post and the mobile detail screen reads it
(`setLikedByMe(res.liked_by_me ?? false)`), but `GET /socials/posts/<id>` never
sent the field. Opening a post you had already liked showed an empty heart, and
the next tap unliked it.

Adds `PostService.is_liked_by` for the single-post answer; the feed keeps
computing this in batch. The route stays public, so anonymous callers get
`False`.

Also emits `likes_count`/`comments_count` alongside the existing
`like_count`/`comment_count`. The two endpoints disagreed on names for identical
data, which is exactly how the missing `liked_by_me` stayed hidden — reading the
wrong name returns `None` rather than failing. Both spellings ship rather than a
rename, which would break every existing consumer for no functional gain.

## Tickets / Related Issue

Ticket ID [link] · Fixes #[Issue number]

## Type of Change
- [x] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## How Has This Been Tested?

**Unit suite:** `517 passed, 2 skipped` (this branch is off `develop`, so it
doesn't include the other branches' added tests).

**Coverage — `app/socials`, unit suite only: 32%** (`schemas.py` 95%,
`models.py` 92%, `routes.py` 55%, `services.py` 13% of a 1688-statement module).

**Verified over real HTTP:** like a post via the feed, then
`GET /socials/posts/<id>` returns `liked_by_me: true` and `like_count: 1`.

**CI gates:** `black --check` clean on 3 changed files; `flake8` clean.

## Tested & Approved by? — [QA Engineer]

## Checklist
- [x] Style guidelines · [x] Self-review · [x] Commented · [ ] Docs · [x] No new warnings · [ ] Tests added · [x] Existing tests pass

## Additional Notes

- No unit test added: the existing socials tests mock the session, so a test here
  would assert against the mock. Covered by the HTTP verification instead.
- Only found by driving the two endpoints back to back against a real server.

---
---

# PR 4 — `chore/toolchain-gevent` → `develop`

**Title:** `chore(deps): bump gevent to 24.11.1 for a modern toolchain`

## Description

`gevent==22.10.2` no longer installs or imports cleanly:

- On **Python 3.12** it fails to build outright — Cython errors compiling
  `src/gevent/libev/corecext.pyx`.
- On **3.11** it installs but won't import unless setuptools is pinned below 81,
  because `gevent/events.py` does `from pkg_resources import iter_entry_points`
  and newer setuptools dropped `pkg_resources`.

Neither shows up in CI today — it's pinned to 3.11, and neither the lint nor the
test job imports `main.run` — but it breaks anyone setting up a fresh
environment, which is exactly how I hit it.

## Tickets / Related Issue

Ticket ID [link] · Fixes #[Issue number]

## Type of Change
- [x] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## How Has This Been Tested?

Old pin vs. new, both interpreters: 22.10.2 fails to build on 3.12; 24.11.1
installs and imports on 3.11 **and** 3.12 against setuptools 84 with no
`pkg_resources`. `gevent-websocket` 0.10.1 still imports and `monkey.patch_all()`
is unaffected. App boots, 18 migrations apply, endpoints serve, **517 passed / 2
skipped**.

No Python files changed, so `black --check` has nothing to check; `flake8` clean.

## Tested & Approved by? — [QA Engineer]

## Checklist
- [x] Style guidelines · [x] Self-review · [x] Commented · [ ] Docs · [x] No new warnings · [ ] Tests added · [x] Existing tests pass

## Additional Notes

- Single-line change to `requirements/requirements.txt`; merge whenever.
- No test added: this is a dependency pin, and the meaningful verification is
  "does a fresh venv work", which the suite can't express.

---
---

# PR 5 — `refactor/money-numeric` → `develop`

**Title:** `refactor(money): store money as NUMERIC(12,2), not Float`

## Description

Binary floating point cannot represent most naira-and-kobo values exactly, and
the error compounds across a ledger read, modified and written back on every
credit, debit, settlement and refund. **25 money columns** move to
`NUMERIC(12,2)` and every money value becomes a `Decimal` end to end.

Doing this **pre-v1 is the whole point**: with no production data it's a plain
`ALTER COLUMN` — nothing to reconcile, no rollback plan. Post-launch it becomes a
careful scheduled operation over live balances.

Converted across wallet, payments, products, orders, cart, requests, chats,
deliveries. **Deliberately not converted:** latitude/longitude, gamification and
reliability scores, ratings, product weight, media processing time, delivery
surge multiplier — genuine floats where `NUMERIC` would be wrong.

`app/libs/money.py` adds `MONEY`, `to_money()` and `to_subunit()`. `to_money`
routes floats through `str()` so `Decimal(str(0.1))` is exactly `0.1` rather than
capturing the binary error, and quantizes `ROUND_HALF_UP` because Python's
default `ROUND_HALF_EVEN` rounds 0.005 *down*.

Decimal refuses to mix with float, **which is the feature**: it turns silent
precision loss into a `TypeError` at the exact line a float snuck in. That caught
a real bug immediately — checkout 500'd on `subtotal * tax_rate` in
`CartService._calculate_tax`. Rates in `orders/fees.py` are Decimal constants
now, and `credit()`/`debit()` coerce at the ledger boundary so callers can still
pass ints, floats or Decimals.

Also fixes the kobo truncation independently: `int(Decimal('1234.56') * 100)` is
exactly `123456`, where the float version gave `123455`.

## Tickets / Related Issue

Ticket ID [link] · Fixes #[Issue number]

## Type of Change
- [x] Bug fix
- [ ] New feature
- [x] Breaking change *(column types; no API shape change — marshmallow still serializes these as JSON numbers)*
- [ ] Documentation update

## How Has This Been Tested?

**517 passed / 2 skipped.** `black --check` clean on all 15 changed files;
`flake8` clean.

Migration `64666e7872bc`: 25 columns, 50 ops (upgrade + downgrade), autogenerate
diff is **money-only with no unrelated drift**, applies cleanly from an empty
database, `flask db check` reports no drift after.

Verified against a real database, which is where this actually matters — the unit
suite mocks the session so it never sees a `Decimal`: checkout creates an order,
wallet credit moves the balance, and the ledger sums exactly to the reported
balance.

## Tested & Approved by? — [QA Engineer]

## Checklist
- [x] Style guidelines · [x] Self-review · [x] Commented · [ ] Docs · [x] No new warnings · [x] Tests updated · [x] Existing tests pass

## Additional Notes

- **Merge-order note:** conflicts with `feature/wallet-audit` in
  `app/wallet/services.py` and `tests/test_wallet.py`. Merge this one **second**
  and take the Decimal version — `to_subunit` from `app/libs/money` supersedes the
  local copy the wallet PR adds to `payments/services.py`. See the post-merge
  fixture note at the top of this file.
- The unit suite passing here proves very little on its own; the real evidence is
  the live-database run above.

---
---

# PR 6 — `feat/content-reporting` → `develop`

**Title:** `feat(moderation): add content reporting and user blocking`

## Description

**App Store Review Guideline 1.2** requires apps carrying user-generated content
to ship a way to report objectionable content and a way to block abusive users.
Markt has UGC in three places — posts, product listings and chat — and had
neither. **Same class of submission blocker as the account-deletion work.**

New `app/moderation` module rather than bolting onto socials: reporting spans
socials, products and chats, and moderation state shouldn't be owned by any one
of the things it moderates.

Reporting is polymorphic over `(content_type, content_id)` and idempotent per
`(reporter, content)` behind a unique constraint — a second tap returns the
original report instead of creating a duplicate, so one user can't inflate the
queue on their own. Reports against non-existent content are rejected so the
queue stays actionable.

Blocking is **one-way on purpose**: it's about what *you* want to stop seeing,
and making it mutual would let anyone remove themselves from someone else's feed
by blocking them first. Blocking also severs any follow in either direction.

Blocks **actually filter the feed**, applied at hydration rather than in the
query because the ranked feed is served from cache — so a block takes effect on
the very next request instead of whenever the cache regenerates. The filter fails
open: if the block lookup errors the user gets an unfiltered feed, not an empty
one.

## Tickets / Related Issue

Ticket ID [link] · Fixes #[Issue number]

## Type of Change
- [ ] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Documentation update

## How Has This Been Tested?

**529 passed / 2 skipped** (12 added). `black --check` clean on all 10 changed
files; `flake8` clean. Migration `60c8535881c4` creates two tables, no drift.

Verified over HTTP: report returns 201; a repeat returns the same `report_id`
with `already_reported: true`; blocking a seller drops the feed from **7 items to
4**; unblocking restores it to 7.

**Query cost measured:** `blocked_user_ids` and `list_blocked` are 1 query each,
and the feed filter adds exactly one lookup per request — not per item.

## Tested & Approved by? — [QA Engineer]

## Checklist
- [x] Style guidelines · [x] Self-review · [x] Commented · [ ] Docs · [x] No new warnings · [x] Tests added · [x] Existing tests pass

## Additional Notes

- **Deploy before** mobile `feature/moderation-and-saved-ui`, where the report
  and block UI lives. Both are needed before this counts as shipped for review.
- Guideline 1.2 also wants **content filtering** and **published contact
  details**. Blocking covers part of the first; the rest is a product/ops task
  outside this PR.
- `resolve_report` is admin-gated and there's no moderation dashboard — reports
  are actionable via the API/DB only for now.

---
---

# PR 7 — `feat/saved-items` → `develop`

**Title:** `feat(socials): add saved posts and wishlisted products`

## Description

"Save" on a post and "wishlist" on a product didn't exist anywhere — no model, no
endpoints, no UI — despite both being standard on a commerce feed.

One `saved_items` table polymorphic over `(content_type, content_id)` rather than
separate tables: the home feed mixes posts and products, so the client wants one
saved list back, and two tables would mean two queries and a client-side merge.

Saving twice reports success rather than 409 — same intent as saving once. The
list returns enough of each item (title, image, price) to render a row without a
second round trip per entry, and skips content deleted since it was saved rather
than returning half-empty rows. `saved_ids()` answers "which of these are saved"
in one query so a feed can render filled vs empty icons without one query per row.

## Tickets / Related Issue

Ticket ID [link] · Fixes #[Issue number]

## Type of Change
- [ ] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Documentation update

## How Has This Been Tested?

**524 passed / 2 skipped** (7 added). `black --check` clean on 5 changed files;
`flake8` clean. Migration `4875f47262d6` creates one table plus an index, no
drift.

Verified over HTTP: save returns 201, the list renders the product with name and
price, unsave returns the list to empty.

**Query count is flat**, measured with a SQLAlchemy statement listener:
`list_saved` issues **4 queries at 2 items and 4 at 7 items** — no N+1.

## Tested & Approved by? — [QA Engineer]

## Checklist
- [x] Style guidelines · [x] Self-review · [x] Commented · [ ] Docs · [x] No new warnings · [x] Tests added · [x] Existing tests pass

## Additional Notes

- **Deploy before** mobile `feature/moderation-and-saved-ui`.
- The feed payload doesn't yet include `saved_by_me`; `saved_ids()` exists for it
  but wiring it into feed hydration is a separate change so this PR doesn't touch
  the feed's hot path.

---
---

# PR 8 — `feat/public-profile` → `develop`

**Title:** `feat(users): implement the public profile endpoint`

## Description

`GET /users/<id>/public` was a stub — three TODOs, no return statement, and
`PublicProfileSchema` was literally `pass` — so it **500'd for anyone who called
it**. Nothing did, which is why the feed's post-author header still linked
nowhere: there was no destination.

Returns username, avatar, join date, follower/following/post counts, and the shop
(name, description, active product count, rating) when the user sells.
Viewer-relative `is_followed` and `is_self` so a profile screen renders Follow vs
Following without a second call.

Kept as its own service rather than a branch inside
`UserService.get_user_profile`, which returns the **owner's** view including
email, phone and address. Two audiences want two shapes, and the thing that leaks
PII is one schema quietly serving both.

Open to anonymous callers on purpose — a shared product link should render its
seller — which is exactly why the schema is narrow. Deleted and deactivated
accounts 404.

## Tickets / Related Issue

Ticket ID [link] · Fixes #[Issue number]

## Type of Change
- [x] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Documentation update

## How Has This Been Tested?

**517 passed / 2 skipped.** `black --check` clean on 3 changed files; `flake8`
clean. No migration needed.

Verified over HTTP: anonymous fetch returns the seller with shop and counts;
`is_followed` flips to true after following; `is_self` is true for your own id;
an unknown id 404s. **6 queries anonymous, 7 signed-in — flat, no N+1.**

## Tested & Approved by? — [QA Engineer]

## Checklist
- [x] Style guidelines · [x] Self-review · [x] Commented · [ ] Docs · [x] No new warnings · [ ] Tests added · [x] Existing tests pass

## Additional Notes

- **Deploy before** mobile `feature/feed-optimization-and-wiring`, which links
  the post-author header to `/profile/[id]` and calls this.
- No unit test added: the existing users tests mock the session, so a test here
  would assert against the mock. Covered by the HTTP verification.
- **`UserSettings.privacy_public_profile` needs a product decision** — see "Still
  open" at the top.

---
---

# PR 9 — `feat/product-share` → `develop`

**Title:** `feat(products): make the share endpoint return real links`

## Description

`/products/<id>/share` was three TODO comments and no return statement, so
flask-smorest tried to serialize `None` against `ShareSchema` and the endpoint
**500'd**. Nothing called it — both share buttons in the app build their own URL
locally — which is why it went unnoticed.

Returns a deep link **and** a web URL: a share sheet has no idea whether the
recipient has the app. Also returns the product name so the sharer doesn't fetch
the product separately just to write the message.

Changed `POST` to `GET` — it creates nothing, and a share sheet may ask for the
same link twice. 404s for deleted and draft products.

## Tickets / Related Issue

Ticket ID [link] · Fixes #[Issue number]

## Type of Change
- [x] Bug fix
- [ ] New feature
- [x] Breaking change *(POST → GET on a route nothing calls)*
- [ ] Documentation update

## How Has This Been Tested?

**517 passed / 2 skipped.** `black --check` clean on 3 changed files; `flake8`
clean. Verified over HTTP: 200 with `deep_link`, `web_url`, `product_name` and a
ready-to-use `message`.

## Tested & Approved by? — [QA Engineer]

## Checklist
- [x] Style guidelines · [x] Self-review · [x] Commented · [ ] Docs · [x] No new warnings · [ ] Tests added · [x] Existing tests pass

## Additional Notes

- **Deliberately no share-tracking table.** Nothing reads that metric today and a
  table with no consumer is speculative schema.
- No unit test: the endpoint is a pure URL builder over settings, and the
  meaningful check (does it 500?) is the HTTP verification.

---
---

# PR 10 — `perf/feed-hydration-n1` → `develop`

**Title:** `perf(feed): stop the feed hydration issuing one query per item`

## Description

Every feed request — **including cache hits** — was issuing 12 per-product and 6
per-post single-row `SELECT`s on top of its correct batched `IN (...)` queries.
18 of 27 queries on a 7-item feed were pure waste, and it scales with feed size
on the hottest path in the app.

**Cause:** the batch loads run inside `session_scope`, which commits on exit, and
SQLAlchemy expires every instance in the identity map on commit. The dict
comprehension immediately after the block touches `product.id` on each expired
instance, and each touch re-`SELECT`s that single row. No amount of `joinedload`
helps, because the eager-loaded state is discarded along with everything else.

Adds `read_scope`: the same session with `expire_on_commit` suppressed, and
neither commit nor rollback on the happy path — **both** expire the identity map,
which is precisely what this needs to avoid. Read paths only; anything that
writes keeps using `session_scope`. All four converted blocks in the hydration
were verified query-only.

## Tickets / Related Issue

Ticket ID [link] · Fixes #[Issue number]

## Type of Change
- [x] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## How Has This Been Tested?

Measured on a 7-item feed against a real database, counting statements with a
SQLAlchemy `before_cursor_execute` listener:

| Path | Before | After |
|---|---|---|
| Warm (cache hit) | 27 queries | **9** |
| Cold (generates feed) | 41 queries | **23** |
| Per-item lookups | 18 | **0** |

**517 passed / 2 skipped**, `black --check` and `flake8` clean, and the 60-check
HTTP smoke suite is green on a branch with everything merged — so feed contents
are unchanged, only the query count.

## Tested & Approved by? — [QA Engineer]

## Checklist
- [x] Style guidelines · [x] Self-review · [x] Commented · [ ] Docs · [x] No new warnings · [ ] Tests added · [x] Existing tests pass

## Additional Notes

- **`read_scope` is a shared primitive** — the one thing worth a careful look. It
  is opt-in and only used in feed hydration today. Using it anywhere that writes
  would silently drop the write, which is why the docstring says read paths only.
- The same expire-on-commit pattern almost certainly costs queries elsewhere (any
  code that loads inside a scope and reads attributes outside it). I only changed
  the feed, which is the hot path. Worth a sweep later.
- No unit test: the suite mocks the session, so it cannot observe query counts.
  The evidence is the measurement above.
