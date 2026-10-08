#!/usr/bin/env python
"""Put a seller in a market, so their orders can join a delivery run.

A run is grouped by (market, area). A seller with no `market_id` is
skipped by DeliveryRunService._resolve_single_market, so every order
they ever receive is silently ineligible for batching -- and
seed_markets_and_areas.py --backfill cannot help, because it picks the
nearest market by the shop's own coordinates and a seller who never set
a shop location has none.

That is the real gap this exists for: on the test server, two of the
four sellers have neither a market nor a coordinate, so a
multi-shop run could not be assembled from their orders at all.

This is `dev_` because placing a shop somewhere is a claim about the
world. In production a seller sets their own shop location and the
market follows from it; here you are asserting both on their behalf,
which is fine for a fixture and nowhere else.

    python scripts/dev_place_seller.py --seller 1 \
        --market akobo-market --lat 7.4445 --lng 3.9520 --allow-remote

Refuses to overwrite a seller that already has a market unless
--replace is given, so re-running it is safe.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller", type=int, required=True)
    parser.add_argument(
        "--market", required=True, help="Market slug, e.g. akobo-market."
    )
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lng", type=float)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Move a seller that is already in a market.",
    )
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()

    from main.setup import create_flask_app
    from external.database import db
    from app.markets.models import Market
    from app.users.models import Seller

    app = create_flask_app()
    with app.app_context():
        url = str(db.engine.url)
        print(f"Database: {url}")
        if not any(h in url for h in ("localhost", "127.0.0.1")):
            if not args.allow_remote:
                print(
                    "\nRefusing a non-local database. This asserts where a "
                    "real shop is, which is the seller's to say anywhere but "
                    "a test server. Re-run with --allow-remote if this is "
                    "that server.",
                    file=sys.stderr,
                )
                return 1
            print("  (remote database, --allow-remote given)")

        session = db.session
        seller = session.query(Seller).get(args.seller)
        if seller is None:
            print(f"No seller {args.seller}.", file=sys.stderr)
            return 1

        market = session.query(Market).filter_by(slug=args.market).first()
        if market is None:
            print(f"No market with slug {args.market!r}.", file=sys.stderr)
            return 1

        if seller.market_id and not args.replace:
            print(
                f"{seller.shop_name} is already in market {seller.market_id}. "
                "Pass --replace to move them."
            )
            return 0

        seller.market_id = market.id
        if args.lat is not None and args.lng is not None:
            seller.shop_latitude = args.lat
            seller.shop_longitude = args.lng

        session.commit()
        print(
            f"\n{seller.shop_name} -> {market.name} "
            f"({seller.shop_latitude}, {seller.shop_longitude})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
