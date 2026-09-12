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
            # Akobo covers a real corridor rather than a point: the OSM
            # landmark on Akobo-Olorunda Abba Road and the part of Akobo
            # where shops and buyers actually are sit 3km apart, so the
            # centroid is between them. Added after a staging check found
            # two shops, a buyer and a saved address all sitting 4.5km
            # outside the nearest zone -- a hole big enough that nobody in
            # Akobo could order anything.
            ("ibadan-akobo", "Akobo", 7.4430, 3.9500, 3.5),
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
    {
        "name": "Lagos",
        "slug": "lagos",
        # Mainland only, around UNILAG. These areas sit on top of each other
        # -- Iwaya is 800m from the campus gate -- so the radii are tighter
        # here than upcountry. Anywhere across the lagoon (the Island, Lekki)
        # is deliberately absent until there is a reason to price a bridge
        # crossing, which the distance bands cannot currently express.
        "zones": [
            ("lagos-unilag", "University of Lagos", 6.5120, 3.3935, 2.5),
            ("lagos-akoka", "Akoka", 6.5287, 3.3906, 2.0),
            ("lagos-iwaya", "Iwaya", 6.5051, 3.3904, 2.0),
            ("lagos-yaba", "Yaba", 6.5068, 3.3755, 2.0),
            ("lagos-shomolu", "Shomolu", 6.5336, 3.3842, 2.0),
            ("lagos-bariga", "Bariga", 6.5407, 3.3880, 2.0),
        ],
    },
    {
        "name": "Ile-Ife",
        "slug": "ile-ife",
        # The OAU campus is large and sits well outside the town -- nearly
        # 6km from the centre -- so the campus zone is wider than most and
        # there is real distance between it and town. That gap is honest:
        # a delivery from Lagere to a hall of residence is a proper trip and
        # should be priced as one.
        "zones": [
            ("ife-oau", "Obafemi Awolowo University", 7.5272, 4.5331, 3.5),
            ("ife-oduduwa", "Oduduwa Hall", 7.5189, 4.5221, 2.0),
            ("ife-mayfair", "Mayfair", 7.4910, 4.5339, 2.5),
            ("ife-town", "Ile-Ife town", 7.4828, 4.5604, 3.0),
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
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help=(
            "Seed a database that is not on localhost. Needed for a staging "
            "or test server: this is served-area configuration, not test "
            "data, and without it every address reads as unserviceable."
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
        is_local = any(h in url for h in ("localhost", "127.0.0.1"))
        if not is_local and not args.allow_remote:
            print(
                "\nRefusing to seed a database that is not local.\n\n"
                "This is served areas, not throwaway test data -- without it "
                "every address in the app reads as 'we don't deliver here', "
                "so a staging or test server does need it.\n\n"
                "If this is that server, re-run with --allow-remote.",
                file=sys.stderr,
            )
            return 1
        if not is_local:
            print("  (remote database, --allow-remote given)")

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
