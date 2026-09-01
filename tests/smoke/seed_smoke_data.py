"""Seed clearly-fake, idempotent data for the local smoke run.

Refuses to run against anything that is not a local disposable database, and
refuses to run with a Paystack live key present. Re-running is a no-op for
anything that already exists, so it can be used to top the environment back up
between smoke passes.

    python -m tests.smoke.seed_smoke_data

Every record it creates is marked with SMOKE_TAG so it is obvious in the DB and
trivial to find, and every email is on a reserved documentation domain so none
of it can ever reach a real inbox.
"""

import sys

SMOKE_TAG = "smoke-fixture"
PASSWORD = "SmokeTest!2026"

# example.com is IANA-reserved for documentation and has no MX record, so none
# of this can reach a real inbox. (A .invalid TLD would be even more inert, but
# Paystack rejects it as a malformed email at transaction/initialize.)
USERS = [
    {
        "key": "seller_a",
        "email": "smoke.seller.a@markt-smoke.example.com",
        "username": "smoke_seller_a",
        "account_type": "seller",
        "seller_data": {
            "shop_name": "Smoke Test Threads",
            "description": f"{SMOKE_TAG}: fake seller for local smoke runs.",
        },
    },
    {
        "key": "seller_b",
        "email": "smoke.seller.b@markt-smoke.example.com",
        "username": "smoke_seller_b",
        "account_type": "seller",
        "seller_data": {
            "shop_name": "Smoke Test Ceramics",
            "description": f"{SMOKE_TAG}: fake seller for local smoke runs.",
        },
    },
    {
        "key": "buyer_a",
        "email": "smoke.buyer.a@markt-smoke.example.com",
        "username": "smoke_buyer_a",
        "account_type": "buyer",
        "buyer_data": {"buyername": "Smoke Buyer A"},
    },
    {
        "key": "buyer_b",
        "email": "smoke.buyer.b@markt-smoke.example.com",
        "username": "smoke_buyer_b",
        "account_type": "buyer",
        "buyer_data": {"buyername": "Smoke Buyer B"},
    },
    # Deleted in the account-deletion smoke test; recreated by re-seeding.
    {
        "key": "disposable",
        "email": "smoke.disposable@markt-smoke.example.com",
        "username": "smoke_disposable",
        "account_type": "buyer",
        "buyer_data": {"buyername": "Smoke Disposable"},
    },
]

PRODUCTS = [
    ("seller_a", "Smoke Linen Shirt", 12500.50, 40),
    ("seller_a", "Smoke Canvas Tote", 7800.00, 25),
    ("seller_b", "Smoke Stoneware Mug", 4500.75, 60),
    ("seller_b", "Smoke Glazed Bowl", 9900.25, 15),
]

POSTS = [
    ("seller_a", f"{SMOKE_TAG}: new linen just landed."),
    ("seller_b", f"{SMOKE_TAG}: kiln opening this week."),
    ("buyer_a", f"{SMOKE_TAG}: looking for a good everyday mug."),
]

# Given to seller_a so withdrawal paths have something to draw against.
SEED_BALANCE = 25_000.00


def _guard(settings):
    """Refuse to seed anywhere that isn't a local disposable database."""
    problems = []
    if settings.DB_HOST not in ("127.0.0.1", "localhost", "::1"):
        problems.append(f"DB_HOST is {settings.DB_HOST!r}, not local")
    if not settings.DB_NAME.endswith("_smoke"):
        problems.append(
            f"DB_NAME is {settings.DB_NAME!r}; refusing anything not *_smoke"
        )
    secret = settings.PAYSTACK_SECRET_KEY or ""
    if secret and not secret.startswith("sk_test_"):
        problems.append("PAYSTACK_SECRET_KEY is not a test key")
    if problems:
        print("REFUSING TO SEED:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print(f"Target: {settings.DB_USER}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    print(f"Paystack key mode: {secret[:8] or '(unset)'}")


def seed():
    from main.run import app
    from main.config import settings

    _guard(settings)

    with app.app_context():
        from external.database import db
        from app.libs.session import session_scope
        from app.users.models import User, Seller
        from app.users.services import AuthService
        from app.products.models import Product
        from app.socials.models import Post, PostStatus
        from app.wallet.services import WalletService
        from app.wallet.models import WalletReferenceType

        created = {"users": 0, "products": 0, "posts": 0}
        by_key = {}

        for spec in USERS:
            with session_scope() as session:
                existing = (
                    session.query(User).filter(User.email == spec["email"]).first()
                )
                if existing:
                    by_key[spec["key"]] = existing.id
                    continue

            payload = {
                "email": spec["email"],
                "username": spec["username"],
                "password": PASSWORD,
                "account_type": spec["account_type"],
            }
            if "seller_data" in spec:
                payload["seller_data"] = spec["seller_data"]
            if "buyer_data" in spec:
                payload["buyer_data"] = spec["buyer_data"]

            user = AuthService.register_user(payload)
            by_key[spec["key"]] = user.id
            created["users"] += 1

        # Login is gated on email verification and these addresses have no
        # inbox, so mark the fixtures verified directly.
        with session_scope() as session:
            for spec in USERS:
                row = session.query(User).filter(User.email == spec["email"]).first()
                if row and not row.email_verified:
                    row.email_verified = True

        # Products need the seller row id, not the user id.
        seller_ids = {}
        with session_scope() as session:
            for key, user_id in by_key.items():
                seller = session.query(Seller).filter_by(user_id=user_id).first()
                if seller:
                    seller_ids[key] = seller.id

        for owner, name, price, stock in PRODUCTS:
            if owner not in seller_ids:
                continue
            with session_scope() as session:
                if session.query(Product).filter_by(name=name).first():
                    continue
                session.add(
                    Product(
                        name=name,
                        description=f"{SMOKE_TAG}: not a real product.",
                        price=price,
                        stock=stock,
                        seller_id=seller_ids[owner],
                        status=Product.Status.ACTIVE,
                    )
                )
                created["products"] += 1

        for owner, caption in POSTS:
            if owner not in by_key:
                continue
            with session_scope() as session:
                if session.query(Post).filter_by(caption=caption).first():
                    continue
                session.add(
                    Post(
                        user_id=by_key[owner],
                        caption=caption,
                        status=PostStatus.ACTIVE,
                    )
                )
                created["posts"] += 1

        # Idempotent by construction: the ledger's unique idempotency_key means
        # re-seeding returns the existing entry instead of crediting again.
        WalletService.credit(
            by_key["seller_a"],
            SEED_BALANCE,
            WalletReferenceType.ADJUSTMENT,
            "smoke-seed",
            description=f"{SMOKE_TAG}: opening balance",
            idempotency_key="smoke:seed:opening-balance:seller_a",
        )
        balance = WalletService.get_balance(by_key["seller_a"])

        print(f"Created this run: {created}")
        print("User ids:")
        for key, uid in sorted(by_key.items()):
            print(f"  {key:12s} {uid}")
        print(f"seller_a wallet: {balance['currency']} {balance['available_balance']}")
        print(f"Password for all seeded users: {PASSWORD}")
        return by_key


if __name__ == "__main__":
    seed()
