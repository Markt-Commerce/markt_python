#!/usr/bin/env python
"""Why is this address not serviceable?

Serviceability has three moving parts -- the served areas, where the buyer's
address actually is, and where the shop actually is -- and the app only ever
reports the conclusion. This prints all three so the answer stops being a
guess.

    python scripts/diagnose_serviceability.py
    python scripts/diagnose_serviceability.py --address 12 --seller 3

The usual culprit is not the zones. It is a saved address whose *label* looks
right while its coordinate is somewhere else: a geocoder that could not find
"Bodija Central Mosque" may still return a point, and the app stores the name
the buyer typed next to it. That is invisible in the UI and obvious here.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", type=int, help="Check one saved address by id")
    parser.add_argument("--seller", type=int, help="Check one shop by seller id")
    parser.add_argument("--limit", type=int, default=15)
    args = parser.parse_args()

    from main.setup import create_flask_app
    from external.database import db
    from app.delivery_pricing.models import ServiceCity, ServiceZone, DeliveryLane
    from app.delivery_pricing.services import ServiceabilityService
    from app.users.addresses import SavedAddress
    from app.users.models import Seller

    app = create_flask_app()
    with app.app_context():
        s = db.session

        print("\n=== SERVED AREAS ===")
        cities = s.query(ServiceCity).all()
        if not cities:
            print("  none. Every address will read as unserviceable.")
            print("  Fix: python scripts/seed_delivery_areas.py --activate")
            return 1
        for c in cities:
            zones = s.query(ServiceZone).filter_by(city_id=c.id, is_active=True).all()
            flag = "live" if c.is_active else "INACTIVE -- nothing here is serviceable"
            print(f"  {c.name} ({flag}): {len(zones)} active zone(s)")
            for z in zones:
                print(
                    f"      {z.name:28} {z.centroid_lat:.4f},{z.centroid_lng:.4f} r={z.radius_km}km"
                )
        print(f"  lanes: {s.query(DeliveryLane).filter_by(is_active=True).count()}")

        def resolve(label, lat, lng):
            if lat is None or lng is None:
                print(f"  {label:46} NO COORDINATE -- cannot be delivered to/from")
                return
            zone = ServiceabilityService.zone_for_point(s, lat, lng)
            where = f"{lat:.4f},{lng:.4f}"
            if zone is None:
                print(f"  {label:46} {where:20} OUTSIDE every zone")
            else:
                city = zone.city.name if zone.city else "?"
                print(f"  {label:46} {where:20} -> {city} / {zone.name}")

        print("\n=== SAVED ADDRESSES (buyer dropoffs) ===")
        q = s.query(SavedAddress)
        if args.address:
            q = q.filter_by(id=args.address)
        rows = q.order_by(SavedAddress.id.desc()).limit(args.limit).all()
        if not rows:
            print("  none saved yet.")
        for a in rows:
            name = (a.label or a.formatted_address or "")[:44]
            resolve(f"#{a.id} {name}", a.latitude, a.longitude)

        print("\n=== SHOPS (pickups) ===")
        q = s.query(Seller)
        if args.seller:
            q = q.filter_by(id=args.seller)
        shops = q.order_by(Seller.id.desc()).limit(args.limit).all()
        if not shops:
            print("  none.")
        for shop in shops:
            resolve(
                f"#{shop.id} {(shop.shop_name or '')[:41]}",
                shop.shop_latitude,
                shop.shop_longitude,
            )

        print(
            "\nA row reading OUTSIDE every zone is the answer. If its label\n"
            "looks like a place we do serve, the coordinate stored with it is\n"
            "wrong -- re-pin that address, or re-set the shop location.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
