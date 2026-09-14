# Merge runbook — validated end to end

Every step below was executed in a disposable git worktree against a throwaway
Postgres, in this order, and the results are the ones observed. This is not a
plan; it's a transcript with the noise removed.

**Outcome:** 11 backend branches merged, 2 conflicts (both trivial), 22
migrations up / 4 down / 4 back up cleanly, **550 unit tests**, **60/60 HTTP
smoke**, **14/14 concurrency**, flake8 and black clean.

*(Counts revised 2026-09-02: 22/4/4 rather than 23/5/5 — chaining the migrations
removed the generated merge revision that used to sit at the head.)*

---

## Before you start

Three things below are **not optional** and none of them are discoverable from
the branches themselves:

1. Two merge conflicts need hand resolution (step 3 and step 5).
2. ~~Alembic ends with four heads~~ — **fixed at the source, see below.**
3. ~~One unit fixture fails only after the merge~~ — **fixed on the branch.**

> ### Revision 2026-09-02 — read this instead of steps 6 and 7
>
> **The four heads are gone.** The three feature migrations were re-pointed to
> form a single linear chain, because develop deploys to the test server on
> merge and multiple heads make `flask db upgrade` fail outright:
>
> ```
> 72bf175405d5 → 64666e7872bc (money, on develop)
>              → e143139d1aef (deleted_at, #79)
>              → 60c8535881c4 (moderation, #83)
>              → 4875f47262d6 (saved items, #84)
> ```
>
> **Skip step 6 entirely** — do not run `flask db merge heads`; there is nothing
> to merge, and generating a merge revision now would add a pointless node.
>
> **The cost:** #79 → #83 → #84 must merge **in that order**. Out of order leaves
> a dangling `down_revision` and the deploy fails. The ordering constraint is
> commented on all three PRs. The migrations touch disjoint schema (a users
> column, two new tables, one new table), so this is bookkeeping, not a data
> dependency — the order is arbitrary but must be respected once chosen.
>
> **Skip step 7** — the `to_money("1000.00")` fixture fix is already on the
> branch. The merged tree runs 550 passed / 2 skipped with no hand edits.
>
> Verified on a merged worktree against a throwaway Postgres: single head at all
> ten intermediate merge states; 22 migrations applied from zero; `flask db
> check` reports no new operations; 4 down / 4 up / 4 down / 4 up with zero
> orphan enum types and every money column back to `numeric(12,2)`; `flake8`
> clean tree-wide; `black --check` clean on all changed non-migration files
> (CI excludes `migrations/**`).

---

## 1. Worktree

```bash
git worktree add -b integration/release <path> develop
cd <path>
```

## 2. Merge the two that must go first

```bash
git merge --no-edit chore/toolchain-gevent      # 0 conflicts
git merge --no-edit refactor/money-numeric      # 0 conflicts
```

`refactor/money-numeric` **must** precede `feature/wallet-audit`. Reversed, you
resolve the same conflicts against a float baseline and can silently keep the
float arithmetic.

## 3. Merge the wallet audit — 2 conflicts

```bash
git merge --no-edit feature/wallet-audit
# CONFLICT: app/wallet/services.py
# CONFLICT: tests/test_wallet.py
```

**`app/wallet/services.py`** — two hunks, both "take both sides":

- Imports: keep **both** `from datetime import datetime` (wallet-audit) and
  `from decimal import Decimal` (money).
- In `credit()`: keep wallet-audit's `_get_or_create_account(..., for_update=True)`
  call that already sits *above* the idempotency check, and take money's
  `to_money(...)` for the balance assignment. The correct result is:

  ```python
  account.available_balance = to_money(account.available_balance + amount)
  ```

  Do **not** keep the HEAD side's second `_get_or_create_account(...)` call — it
  re-fetches without the lock and silently undoes the concurrency fix.

**`tests/test_wallet.py`** — one import hunk, take both:

```python
from app.libs.money import to_money
from app.wallet.models import TopUpStatus, WalletReferenceType
```

```bash
git add -A && git commit --no-edit
```

## 4. Merge the clean ones

```bash
for b in feature/account-deletion fix/post-detail-liked-by-me \
         feat/content-reporting feat/saved-items feat/product-share \
         perf/feed-hydration-n1 perf/shop-search-n1; do
  git merge --no-edit $b        # 0 conflicts each
done
```

## 5. Merge the public profile — 1 conflict

```bash
git merge --no-edit feat/public-profile
# CONFLICT: app/users/routes.py
```

Three hunks in `app/users/routes.py`, **all "take both"** — the two branches add
different imports to the same blocks:

- `from flask import jsonify, make_response` (deletion) — keep it
- `ConflictError` in the `app.libs.errors` import list — keep it
- `AccountDeletionService` **and** `PublicProfileService` in the `.services`
  import — keep both

```bash
git add -A && git commit --no-edit
```

## 6. ~~Collapse the alembic heads~~ — OBSOLETE, SKIP

*Superseded 2026-09-02: the migrations are now a linear chain and there is a
single head at every step. Do not run `flask db merge heads`. Kept below only so
the old instruction isn't followed from memory.*

<details><summary>Former step 6 (do not run)</summary>

Four branches each added a migration off `72bf175405d5`, so:

```bash
export FLASK_APP=main.run:app
flask db heads
# 4875f47262d6 (head)   saved items
# 60c8535881c4 (head)   content reports and user blocks
# 64666e7872bc (head)   money -> NUMERIC(12,2)
# e143139d1aef (head)   users.deleted_at

flask db merge heads -m "merge schema branches"
flask db heads
# <new id> (head)       single head
```

Commit the generated merge revision. Without it `flask db upgrade` dies with
*"Multiple head revisions are present"*.

</details>

## 7. ~~Fix the one post-merge test failure~~ — OBSOLETE, SKIP

*Superseded 2026-09-02: the fix is on the branch. The merged tree runs
550 passed / 2 skipped with no hand edits.*

<details><summary>Former step 7 (already applied)</summary>

```bash
pytest -q
# FAILED tests/test_wallet.py::test_balance_mutations_lock_the_wallet_row
# TypeError: unsupported operand type(s) for +: 'decimal.Decimal' and 'float'
```

The fixture builds a float balance that now meets a Decimal amount. In
`tests/test_wallet.py`:

```python
-        id=1, currency="NGN", available_balance=1000.0
+        id=1, currency="NGN", available_balance=to_money("1000.00")
```

This passes on either branch alone and fails only merged, so it cannot be fixed
before the merge.

```bash
pytest -q      # 550 passed, 2 skipped
```

</details>

## 8. Migrate — up, down, up

Against a scratch database:

```bash
flask db upgrade                    # 22 applied, from zero
flask db check                      # No new upgrade operations detected

flask db downgrade 72bf175405d5     # 4 reverted
flask db upgrade                    # 4 re-applied
flask db check                      # No new upgrade operations detected

# and once more, which is what used to fail on leftover enum types:
flask db downgrade 72bf175405d5     # 4 reverted
flask db upgrade                    # 4 re-applied
```

Verified after the downgrade: `wallet_accounts.available_balance` is back to
`double precision`, `users.deleted_at` is gone, all three new tables are
dropped, and **zero orphan enum types** remain.

**Do not run `flask db downgrade base`** — see gotcha 3.

## 9. Run everything

```bash
pytest -q                                   # 550 passed, 2 skipped
flake8 .                                    # clean
black --check <changed .py, excluding migrations>   # clean

# with the server up against the scratch DB:
python tests/smoke/smoke_api.py             # 60/60
python tests/smoke/smoke_concurrency.py     # 14/14
```

---

## Gotchas — the five that actually bit

**1. Merge order matters — and now in two ways.** `refactor/money-numeric`
before `feature/wallet-audit`, as always. *Additionally, since 2026-09-02:*
**#79 → #83 → #84 in that order**, because their migrations are chained.

**2. ~~Four alembic heads.~~ Fixed at the source** — the migrations are chained
linearly, single head throughout. Step 6 no longer applies.

**3. `flask db downgrade base` is broken — pre-existing, not from this work.**

```
CompileError: Can't emit DROP CONSTRAINT for constraint
ForeignKeyConstraint(..., table=Table('shipping_addresses', ...)); it has no name
```

An unnamed FK in `72bf175405d5` (v3.0 spec schema) can't be dropped. Alembic
runs the downgrade in a transaction, so the whole thing **rolls back silently** —
the log prints "Running downgrade …" lines that never committed, and
`alembic_version` doesn't move. Downgrading *to* `72bf175405d5` (the release
boundary) works fine, which is the rollback you'd actually want. Worth fixing
separately by naming that constraint.

**4. Migrations left ENUM types behind on downgrade — fixed.** `sa.Enum` creates
the Postgres type implicitly but `op.drop_table` doesn't drop it, so
downgrade-then-upgrade died on `type "reportedcontenttype" already exists`. The
moderation and saved-items migrations now `DROP TYPE IF EXISTS` in `downgrade()`.
Only reachable on a rollback-and-retry, which is exactly when you'd least want a
surprise.

**5. The concurrency smoke script did float arithmetic — fixed.** It compared
balances with floats, which raises `TypeError` once balances are Decimal. Passed
on each branch alone, failed merged. Amounts passed to the service stay floats
(both worlds coerce); only comparisons go through a local `money()` helper.

---

## Environment note

The smoke scripts read `PAYSTACK_SECRET_KEY` from config, and `settings.ini` is
gitignored — so it does **not** exist in a fresh worktree. Export the test keys
into the environment before running them, or `smoke_api.py` stops at its own
safety guard with "Paystack key is TEST mode: FAIL".
