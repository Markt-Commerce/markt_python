#!/usr/bin/env python
"""Seed the markets and areas that batched delivery runs are grouped by.

A DeliveryRun serves exactly one (market, area) pair: sellers belong to a
market, delivery addresses belong to an area, and
DeliveryRunService.attach_eligible_orders refuses any order where either
is unresolved. Both tables ship empty, nothing in the app writes to them,
and no seed script covered them -- so on a fresh database every order is
counted in `skipped_unresolved`, no run is ever created, and batched
delivery cannot be exercised at all. That is what this fixes.

Deliberately separate from seed_delivery_areas.py, which seeds
ServiceCity/ServiceZone/DeliveryLane -- the *pricing and serviceability*
geography. Those answer "do we deliver there and what does it cost";
these answer "which orders can share one rider". Same city names, two
different questions, two different tables.

    DB_NAME=markt_db python scripts/seed_markets_and_areas.py --allow-remote

Idempotent by slug, like its sibling. Nothing is deleted.

Coordinates are the same real Ibadan landmarks seed_delivery_areas.py
uses, for the same reason: grouping is distance-based, and made-up
centroids produce made-up groupings that hide real bugs.
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Markets are where sellers are: a physical trading cluster a rider
# collects from. Areas are where buyers are. They are separate lists
# because a run collects from one market and delivers into one area, and
# those are rarely the same place.
MARKETS = [
    ("bodija-market", "Bodija Market", 7.4399, 3.9202),
    ("ui-market", "UI Market", 7.4477, 3.8967),
    ("agbowo-market", "Agbowo Market", 7.4467, 3.9137),
    ("akobo-market", "Akobo Market", 7.4430, 3.9500),
    ("sango-market", "Sango Market", 7.4237, 3.8993),
]

AREAS = [
    ("ui-campus", "University of Ibadan", 7.4477, 3.8967),
    ("agbowo", "Agbowo", 7.4467, 3.9137),
    ("bodija", "Bodija", 7.4399, 3.9202),
    ("sango", "Sango", 7.4237, 3.8993),
    ("mokola", "Mokola", 7.3988, 3.8883),
    ("ojoo", "Ojoo", 7.4710, 3.9182),
    ("akobo", "Akobo", 7.4430, 3.9500),
]


def _km(lat1, lng1, lat2, lng2):
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _nearest(rows, lat, lng):
    """The closest seeded row, and how far away it is."""
    best, best_km = None, None
    for row in rows:
        if row.latitude is None or row.longitude is None:
            continue
        distance = _km(lat, lng, row.latitude, row.longitude)
        if best_km is None or distance < best_km:
            best, best_km = row, distance
    return best, best_km


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help=(
            "Seed a database that is not on localhost. Needed for a staging "
            "or test server: without markets and areas, batching is dead "
            "code there."
        ),
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "Also attach existing sellers and delivery addresses to the "
            "nearest seeded market/area. Only fills in rows that have none; "
            "an existing assignment is left alone, because it may have been "
            "made deliberately."
        ),
    )
    parser.add_argument(
        "--max-km",
        type=float,
        default=10.0,
        help=(
            "How far a seller or address may be from a centroid and still be "
            "attached to it during --backfill. Beyond this it is left "
            "unassigned rather than being filed under somewhere it is not."
        ),
    )
    args = parser.parse_args()

    from main.setup import create_flask_app
    from external.database import db
    from app.markets.models import Area, Market
    from app.orders.models import ShippingAddress
    from app.users.models import Seller

    app = create_flask_app()
    with app.app_context():
        url = str(db.engine.url)
        print(f"Database: {url}")
        is_local = any(h in url for h in ("localhost", "127.0.0.1"))
        if not is_local and not args.allow_remote:
            print(
                "\nRefusing to seed a database that is not local.\n\n"
                "Markets and areas are configuration, not throwaway test "
                "data -- a staging or test server does need them, or no "
                "order can ever join a delivery run.\n\n"
                "If this is that server, re-run with --allow-remote.",
                file=sys.stderr,
            )
            return 1
        if not is_local:
            print("  (remote database, --allow-remote given)")

        session = db.session

        for slug, name, lat, lng in MARKETS:
            market = session.query(Market).filter_by(slug=slug).first()
            if market is None:
                market = Market(slug=slug)
                session.add(market)
                print(f"  + market {slug}")
            else:
                print(f"  = market {slug}")
            market.name = name
            market.latitude = lat
            market.longitude = lng
            market.is_active = True

        for slug, name, lat, lng in AREAS:
            area = session.query(Area).filter_by(slug=slug).first()
            if area is None:
                area = Area(slug=slug)
                session.add(area)
                print(f"  + area {slug}")
            else:
                print(f"  = area {slug}")
            area.name = name
            area.latitude = lat
            area.longitude = lng
            area.is_active = True

        session.flush()

        if args.backfill:
            markets = session.query(Market).all()
            areas = session.query(Area).all()

            sellers = (
                session.query(Seller)
                .filter(
                    Seller.market_id.is_(None),
                    Seller.shop_latitude.isnot(None),
                    Seller.shop_longitude.isnot(None),
                )
                .all()
            )
            attached_sellers = skipped_sellers = 0
            for seller in sellers:
                market, distance = _nearest(
                    markets, seller.shop_latitude, seller.shop_longitude
                )
                if market is None or distance > args.max_km:
                    skipped_sellers += 1
                    continue
                seller.market_id = market.id
                attached_sellers += 1
            print(
                f"\n  sellers: {attached_sellers} attached, "
                f"{skipped_sellers} too far (> {args.max_km}km)"
            )

            addresses = (
                session.query(ShippingAddress)
                .filter(
                    ShippingAddress.area_id.is_(None),
                    ShippingAddress.latitude.isnot(None),
                    ShippingAddress.longitude.isnot(None),
                )
                .all()
            )
            attached_addresses = skipped_addresses = 0
            for address in addresses:
                area, distance = _nearest(areas, address.latitude, address.longitude)
                if area is None or distance > args.max_km:
                    skipped_addresses += 1
                    continue
                address.area_id = area.id
                attached_addresses += 1
            print(
                f"  addresses: {attached_addresses} attached, "
                f"{skipped_addresses} too far (> {args.max_km}km)"
            )

        session.commit()
        print(
            f"\n{len(MARKETS)} markets, {len(AREAS)} areas."
            + (
                ""
                if args.backfill
                else "\nNothing was attached to them -- re-run with --backfill "
                "to assign existing sellers and addresses."
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
