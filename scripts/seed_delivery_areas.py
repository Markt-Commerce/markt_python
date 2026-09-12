#!/usr/bin/env python
"""Seed the served areas delivery quoting needs, for local and staging use.

The migration that created these tables deliberately ships no rows. Which
areas Markt serves is an operational decision that changes without a schema
change, and baking a city list into a migration means every environment --
including production -- silently inherits whatever was true the day it was
written.

So: a script, run deliberately, idempotent, safe to re-run.

    DB_NAME=markt_db python scripts/seed_delivery_areas.py

Idempotent by natural key (city slug, zone slug, zone pair), so re-running
updates the existing rows rather than duplicating them. Nothing is deleted --
deactivating an area is a deliberate act, not a side effect of a seed.

The coordinates below are real Ibadan landmarks, because serviceability is
distance-based and made-up coordinates produce made-up distances that hide
real bugs. Everything else here is obviously a placeholder: the zone radii are
round numbers and the lane fees come from the default fee config rather than
any negotiated rate.
"""

import argparse
import os
import sys

# Run as `python scripts/seed_delivery_areas.py` from anywhere, without
# needing PYTHONPATH set first.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Ibadan, where Markt is starting. Centroid and a radius per zone: a circle is
# a crude approximation of a neighbourhood, and ServiceZone documents itself as
# replaceable by real polygons once there is a reason to draw them.
CITY = {"name": "Ibadan", "slug": "ibadan"}

ZONES = [
    # (slug, name, lat, lng, radius_km)
    ("ibadan-bodija", "Bodija", 7.4305, 3.9047, 3.0),
    ("ibadan-ui", "University of Ibadan", 7.4441, 3.8964, 2.5),
    ("ibadan-dugbe", "Dugbe", 7.3878, 3.8783, 2.5),
    ("ibadan-challenge", "Challenge", 7.3547, 3.8703, 3.0),
    ("ibadan-akobo", "Akobo", 7.4479, 3.9391, 3.5),
]

# Every zone pair, both directions, including a zone to itself (a delivery
# within Bodija is a real delivery). No fee overrides: the zone-band strategy
# prices these from distance, and an override is for a lane that genuinely
# costs something the bands cannot express -- a bridge toll, a ferry -- not
# for routine tuning.
def _lane_pairs(slugs):
    return [(a, b) for a in slugs for b in slugs]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--activate",
        action="store_true",
        help=(
            "Mark the city live. Without this the city is seeded inactive, so "
            "quoting refuses it -- which is what you want everywhere except a "
            "test environment you are about to exercise."
        ),
    )
    args = parser.parse_args()

    from main.setup import create_flask_app
    from external.database import db
    from app.delivery_pricing.models import ServiceCity, ServiceZone, DeliveryLane

    app = create_flask_app()
    with app.app_context():
        url = str(db.engine.url)
        print(f"Database: {url}")
        if not any(h in url for h in ("localhost", "127.0.0.1")):
            print(
                "Refusing to seed a database that is not local. Seed data is "
                "for disposable environments.",
                file=sys.stderr,
            )
            return 1

        session = db.session

        city = session.query(ServiceCity).filter_by(slug=CITY["slug"]).first()
        if city is None:
            city = ServiceCity(**CITY)
            session.add(city)
            print(f"  + city {CITY['slug']}")
        else:
            print(f"  = city {CITY['slug']} (exists)")
        city.name = CITY["name"]
        if args.activate:
            city.is_active = True
        session.flush()

        zones = {}
        for slug, name, lat, lng, radius in ZONES:
            zone = session.query(ServiceZone).filter_by(slug=slug).first()
            if zone is None:
                zone = ServiceZone(slug=slug)
                session.add(zone)
                print(f"  + zone {slug}")
            else:
                print(f"  = zone {slug} (exists)")
            zone.city_id = city.id
            zone.name = name
            zone.centroid_lat = lat
            zone.centroid_lng = lng
            zone.radius_km = radius
            zone.is_active = True
            zones[slug] = zone
        session.flush()

        created = existing = 0
        for from_slug, to_slug in _lane_pairs(list(zones)):
            from_id, to_id = zones[from_slug].id, zones[to_slug].id
            lane = (
                session.query(DeliveryLane)
                .filter_by(from_zone_id=from_id, to_zone_id=to_id)
                .first()
            )
            if lane is None:
                lane = DeliveryLane(from_zone_id=from_id, to_zone_id=to_id)
                session.add(lane)
                created += 1
            else:
                existing += 1
            lane.is_active = True

        session.commit()
        print(f"  lanes: {created} created, {existing} already present")
        print(
            f"\nSeeded {len(ZONES)} zones in {CITY['name']}"
            f"{' (live)' if args.activate else ' (inactive -- pass --activate)'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
