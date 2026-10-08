"""Concurrency smoke test for the wallet row-lock fix.

This is the test the unit suite structurally cannot do: it needs real parallel
transactions against a real database, because what is being validated is a
`SELECT ... FOR UPDATE` on the wallet row.

Deliberately does NOT import main.run. That module calls gevent's patch_all(),
which turns threads into greenlets — and because psycopg2 blocks in C, every
"concurrent" DB call would serialise and the test would pass vacuously without
proving anything. Importing the app factory directly keeps real OS threads.

    PYTHONPATH=. python tests/smoke/smoke_concurrency.py
"""

import concurrent.futures
import sys
import threading
import uuid
from decimal import Decimal


def money(value):
    """Compare balances without caring whether they're float or Decimal.

    Balances are Decimal once the NUMERIC(12,2) migration lands and float
    before it, and this script has to run either side of that. Going through
    str() keeps the value exact in both cases.
    """
    return Decimal(str(value)).quantize(Decimal("0.01"))


WORKERS = 12

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


def main():
    from main.setup import create_app  # NOT main.run — see module docstring
    from main.config import settings

    section("Safety preconditions")
    if not check(
        "DB is a *_smoke database",
        settings.DB_NAME.endswith("_smoke"),
        settings.DB_NAME,
    ):
        sys.exit(1)
    if not check(
        "DB host is local",
        settings.DB_HOST in ("127.0.0.1", "localhost"),
        settings.DB_HOST,
    ):
        sys.exit(1)
    check(
        "threading is not gevent-patched",
        not getattr(threading, "_gevent_patched", False)
        and "gevent" not in str(type(threading.current_thread())).lower(),
        "real OS threads",
    )

    app, _ = create_app()

    from app.libs.session import session_scope
    from app.users.models import User
    from app.wallet.models import (
        WalletAccount,
        WalletEntry,
        WalletReferenceType,
        WithdrawalRequest,
    )
    from app.wallet.services import WalletService
    from app.libs.errors import APIError

    with app.app_context():
        with session_scope() as session:
            user = (
                session.query(User).filter(User.email.like("smoke.seller.a@%")).first()
            )
            if not user:
                print("  seed data missing — run tests/smoke/seed_smoke_data.py")
                sys.exit(1)
            user_id = user.id

    def balance():
        with app.app_context():
            return WalletService.get_balance(user_id)["available_balance"]

    def ledger_rows(key_prefix):
        with app.app_context():
            with session_scope() as session:
                acct = (
                    session.query(WalletAccount)
                    .filter_by(user_id=user_id, currency="NGN")
                    .first()
                )
                return (
                    session.query(WalletEntry)
                    .filter(
                        WalletEntry.wallet_account_id == acct.id,
                        WalletEntry.idempotency_key.like(f"{key_prefix}%"),
                    )
                    .count()
                )

    # ---------------------------------------------------------------------
    # 1. N concurrent DISTINCT credits — the lost-update case.
    #    Each has its own idempotency key, so all N must land and the balance
    #    must move by exactly N * amount. An unlocked read-modify-write drops
    #    some of them.
    # ---------------------------------------------------------------------
    section(f"Concurrent distinct credits ({WORKERS} threads)")
    run = uuid.uuid4().hex[:8]
    amount = 100.0
    start = money(balance())

    def do_credit(i):
        with app.app_context():
            WalletService.credit(
                user_id,
                amount,
                WalletReferenceType.ADJUSTMENT,
                f"conc-{run}-{i}",
                description="smoke-fixture: concurrent credit",
                idempotency_key=f"smoke:conc:{run}:{i}",
            )

    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for f in concurrent.futures.as_completed(
            [ex.submit(do_credit, i) for i in range(WORKERS)]
        ):
            try:
                f.result()
            except Exception as e:
                errors.append(repr(e))

    end = money(balance())
    expected = money(money(start) + money(WORKERS * amount))
    check("no errors raised under concurrent credit", not errors, "; ".join(errors[:2]))
    check(
        f"balance moved by exactly {WORKERS} x {amount} (no lost updates)",
        end == expected,
        f"{start} -> {end}, expected {expected}",
    )
    check(
        f"exactly {WORKERS} ledger rows written",
        ledger_rows(f"smoke:conc:{run}:") == WORKERS,
        f"{ledger_rows(f'smoke:conc:{run}:')} rows",
    )

    # ---------------------------------------------------------------------
    # 2. N concurrent credits sharing ONE idempotency key — the webhook-replay
    #    case. Exactly one must land.
    # ---------------------------------------------------------------------
    section(f"Concurrent replay of one event ({WORKERS} threads, same key)")
    run2 = uuid.uuid4().hex[:8]
    start2 = money(balance())
    key = f"smoke:replay:{run2}"

    def do_replay(_):
        with app.app_context():
            WalletService.credit(
                user_id,
                250.0,
                WalletReferenceType.WALLET_TOPUP,
                f"replay-{run2}",
                description="smoke-fixture: replayed webhook",
                idempotency_key=key,
            )

    errors2 = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for f in concurrent.futures.as_completed(
            [ex.submit(do_replay, i) for i in range(WORKERS)]
        ):
            try:
                f.result()
            except Exception as e:
                errors2.append(repr(e))

    end2 = balance()
    check(
        "no errors raised under concurrent replay", not errors2, "; ".join(errors2[:2])
    )
    check(
        "balance moved exactly once despite N simultaneous deliveries",
        money(end2) == money(money(start2) + money(250.0)),
        f"{start2} -> {end2}, expected {money(money(start2) + money(250.0))}",
    )
    check(
        "exactly one ledger row for the replayed key",
        ledger_rows(key) == 1,
        f"{ledger_rows(key)} rows",
    )

    # ---------------------------------------------------------------------
    # 3. N concurrent withdrawals that together exceed the balance — the
    #    overdraw case. The wallet must never go negative and the successes
    #    must be exactly what the balance could fund.
    # ---------------------------------------------------------------------
    section(f"Concurrent over-withdrawal ({WORKERS} threads)")
    bal3 = money(balance())
    per = 1000.0  # MIN_WITHDRAWAL_AMOUNT
    affordable = int(bal3 // money(per))
    attempts = affordable + WORKERS  # deliberately more than can be funded

    def do_withdraw(i):
        with app.app_context():
            try:
                WalletService.request_withdrawal(
                    user_id,
                    {
                        "amount": per,
                        "currency": "NGN",
                        "bank_code": "058",
                        "account_number": "0000000000",
                        "account_name": "Smoke Fixture",
                    },
                )
                return True
            except APIError:
                return False
            except Exception:
                # Paystack transfer dispatch may fail in test mode; the debit
                # has already been applied by then, so still counts as taken.
                return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        outcomes = [
            f.result()
            for f in concurrent.futures.as_completed(
                [ex.submit(do_withdraw, i) for i in range(attempts)]
            )
        ]

    end3 = money(balance())
    granted = sum(1 for o in outcomes if o)
    print(
        f"    attempted {attempts} x {per} against a balance of {bal3}; {granted} granted"
    )
    check("wallet never went negative", end3 >= 0, f"final balance {end3}")
    check(
        "granted withdrawals did not exceed what the balance could fund",
        granted <= affordable,
        f"granted={granted} affordable={affordable}",
    )
    check(
        "balance decreased by exactly the granted amount",
        money(end3) == money(money(bal3) - money(granted * per)),
        f"{bal3} -> {end3}, expected {money(money(bal3) - money(granted * per))}",
    )

    with app.app_context():
        with session_scope() as session:
            acct = (
                session.query(WalletAccount)
                .filter_by(user_id=user_id, currency="NGN")
                .first()
            )
            rows = (
                session.query(WalletEntry)
                .filter_by(wallet_account_id=acct.id)
                .order_by(WalletEntry.id)
                .all()
            )
            running = Decimal("0.00")
            consistent = True
            for r in rows:
                delta = money(r.amount)
                running += delta if r.entry_type.value == "credit" else -delta
                if money(running) != money(r.balance_after):
                    consistent = False
                    break
            negative = any(r.balance_after < 0 for r in rows)
    check(
        "every ledger row's balance_after matches the running total",
        consistent,
        f"{len(rows)} rows replayed",
    )
    check("no ledger row ever recorded a negative balance", not negative)

    section("Summary")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"  {passed}/{len(results)} checks passed")
    for n, d in failed:
        print(f"    - FAIL {n} ({d})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
