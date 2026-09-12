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


# Where Markt delivers, one entry per city.
#
# Universities first: a campus and the student areas around it are dense,
# walkable-adjacent, and full of people ordering small things -- which is the
# only shape of demand a shared delivery run actually works for. Scaling up
# means adding zones to these cities, or adding a city, not changing code.
#
# Every coordinate below is a real, looked-up location (OpenStreetMap), not an
# approximation. Serviceability and pricing are both distance-based, so a
# made-up centroid produces a made-up fee and hides real bugs.
#
# Radii are round numbers and deliberately overlap at the edges: zones resolve
# by nearest centroid, so an overlap is answered deterministically rather than
# leaving a gap between them that nobody can order from.
CITIES = [
    {
        "name": "Ibadan",
        "slug": "ibadan",
        "zones": [
            # (slug, name, lat, lng, radius_km)
            ("ibadan-ui", "University of Ibadan", 7.4477, 3.8967, 3.0),
            ("ibadan-agbowo", "Agbowo", 7.4467, 3.9137, 2.5),
            ("ibadan-bodija", "Bodija", 7.4399, 3.9202, 3.0),
            ("ibadan-sango", "Sango", 7.4237, 3.8993, 2.5),
            ("ibadan-mokola", "Mokola", 7.3988, 3.8883, 2.5),
            ("ibadan-ojoo", "Ojoo", 7.4710, 3.9182, 3.0),
        ],
    },
    {
        "name": "Ogbomoso",
        "slug": "ogbomoso",
        "zones": [
            ("ogbomoso-lautech", "LAUTECH", 8.1673, 4.2670, 3.0),
            ("ogbomoso-sabo", "Sabo", 8.1467, 4.2516, 2.5),
            ("ogbomoso-takie", "Takie", 8.1364, 4.2376, 2.5),
            ("ogbomoso-north", "Ogbomoso North", 8.1400, 4.2414, 2.5),
            ("ogbomoso-buth", "Bowen Teaching Hospital", 8.1336, 4.2336, 2.5),
        ],
    },
]


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
        total_zones = total_lanes = 0

        for spec in CITIES:
            city = session.query(ServiceCity).filter_by(slug=spec["slug"]).first()
            if city is None:
                city = ServiceCity(slug=spec["slug"])
                session.add(city)
                print(f"  + city {spec['slug']}")
            else:
                print(f"  = city {spec['slug']} (exists)")
            city.name = spec["name"]
            if args.activate:
                city.is_active = True
            session.flush()

            zones = {}
            for slug, name, lat, lng, radius in spec["zones"]:
                zone = session.query(ServiceZone).filter_by(slug=slug).first()
                if zone is None:
                    zone = ServiceZone(slug=slug)
                    session.add(zone)
                    print(f"      + zone {slug}")
                else:
                    print(f"      = zone {slug}")
                zone.city_id = city.id
                zone.name = name
                zone.centroid_lat = lat
                zone.centroid_lng = lng
                zone.radius_km = radius
                zone.is_active = True
                zones[slug] = zone
            session.flush()
            total_zones += len(zones)

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
            total_lanes += created + existing
            print(f"      lanes: {created} new, {existing} already there")

        session.commit()
        state = "live" if args.activate else "inactive -- pass --activate"
        print(
            f"\n{total_zones} zones across {len(CITIES)} cities, "
            f"{total_lanes} lanes ({state})."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
