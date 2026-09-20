#!/usr/bin/env python
"""Make existing paid orders eligible to join a delivery run, then run the
attach pass -- so batched delivery can actually be exercised on a test
server.

Three separate things stop an order joining a run, and a test database
built by clicking through the app typically fails all three:

  1. no market/area rows, and no seller or address attached to any
     -> fixed by scripts/seed_markets_and_areas.py --backfill
  2. the order is not "fully routed and confirmed"
  3. nothing has run the attach pass

(2) is the awkward one and the reason this script is `dev_`.
DeliveryRunService._order_is_ready requires every item to have a
FulfilmentAllocation in ACCEPTED or PREPARING -- the seller-side "yes, I
will fulfil this" -- and says so in its own docstring: the order-first
checkout path never creates allocations at all, so orders placed that way
can *never* batch. That is a real gap in the product, not a bug this
script papers over; what it does is stand in for the seller having
accepted, which on a test server nobody is going to do by hand for a
dozen orders.

    python scripts/dev_make_orders_batchable.py --seller 11
    python scripts/dev_make_orders_batchable.py ORD_TRSB5YTD ORD_2FVWH5SJ

Refuses a non-local database unless --allow-remote, and never touches an
order that already has a live allocation: it fills a gap, it does not
overwrite a seller's real answer.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "order_ids", nargs="*", help="Specific orders. Default: every candidate."
    )
    parser.add_argument(
        "--seller", type=int, help="Only orders containing this seller's items."
    )
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Say what would change and change nothing.",
    )
    parser.add_argument(
        "--close-now",
        action="store_true",
        help=(
            "Push the resulting run all the way to RIDER_ASSIGNMENT, which "
            "is the only status riders can see. Attaching an order leaves "
            "the run OPEN until its cutoff (two hours out), and a run with "
            "fewer than THIN_VOLUME_THRESHOLD orders is cancelled at that "
            "cutoff unless its buyers consented to the single-drop "
            "fallback -- so a two-order test run left alone quietly "
            "disappears instead of reaching anybody. This records that "
            "consent, brings the cutoff forward, and runs the close pass."
        ),
    )
    args = parser.parse_args()

    from main.setup import create_flask_app
    from external.database import db
    from app.deliveries.runs import DeliveryRunService
    from app.fulfilment.models import FulfilmentAllocation, FulfilmentAllocationStatus
    from app.orders.models import Order, OrderItem, OrderStatus

    app = create_flask_app()
    with app.app_context():
        url = str(db.engine.url)
        print(f"Database: {url}")
        if not any(h in url for h in ("localhost", "127.0.0.1")):
            if not args.allow_remote:
                print(
                    "\nRefusing a non-local database. This writes seller "
                    "acceptances nobody actually gave, which is fine on a "
                    "test server and nowhere else. Re-run with "
                    "--allow-remote if this is that server.",
                    file=sys.stderr,
                )
                return 1
            print("  (remote database, --allow-remote given)")

        session = db.session

        query = session.query(Order).filter(
            Order.status == OrderStatus.READY_FOR_DELIVERY
        )
        if args.order_ids:
            query = query.filter(Order.id.in_(args.order_ids))
        orders = query.all()

        if args.seller is not None:
            orders = [
                order
                for order in orders
                if any(item.seller_id == args.seller for item in order.items)
            ]

        if not orders:
            print("\nNo READY_FOR_DELIVERY orders matched.")
            return 0

        print(f"\n{len(orders)} candidate order(s):")
        created = 0
        for order in orders:
            notes = []
            for item in order.items:
                if item.status == OrderItem.Status.CANCELLED:
                    continue
                latest = (
                    session.query(FulfilmentAllocation)
                    .filter_by(order_item_id=item.id)
                    .order_by(FulfilmentAllocation.id.desc())
                    .first()
                )
                if latest and latest.status in (
                    FulfilmentAllocationStatus.ACCEPTED,
                    FulfilmentAllocationStatus.PREPARING,
                ):
                    notes.append(f"item {item.id} already accepted")
                    continue
                if latest:
                    # A real seller answer -- declined, timed out, awaiting.
                    # Not ours to overwrite.
                    notes.append(
                        f"item {item.id} has {latest.status.value}, left alone"
                    )
                    continue
                if not args.dry_run:
                    session.add(
                        FulfilmentAllocation(
                            order_item_id=item.id,
                            seller_id=item.seller_id,
                            product_id=item.product_id,
                            quantity=item.quantity or 1,
                            status=FulfilmentAllocationStatus.ACCEPTED,
                            # Already answered, so the clock is moot; a
                            # past deadline would read as a timeout.
                            seller_response_deadline=datetime.utcnow()
                            + timedelta(days=1),
                        )
                    )
                created += 1
                notes.append(f"item {item.id} -> ACCEPTED")
            print(f"  {order.id}: " + "; ".join(notes))

        if args.dry_run:
            print(f"\nDry run: would create {created} allocation(s).")
            return 0

        session.commit()
        print(f"\nCreated {created} allocation(s).")

        result = DeliveryRunService.attach_eligible_orders()
        print(
            f"Attach pass: {result.get('attached')} attached, "
            f"{result.get('skipped_unresolved')} still unresolved."
        )
        if result.get("skipped_unresolved"):
            print(
                "  Unresolved means no market on the seller or no area on "
                "the address -- run scripts/seed_markets_and_areas.py "
                "--backfill first."
            )

        if args.close_now:
            _close_now(session, [order.id for order in orders])

        from app.deliveries.models import DeliveryRun, DeliveryRunOrder

        for run in session.query(DeliveryRun).all():
            count = (
                session.query(DeliveryRunOrder)
                .filter_by(delivery_run_id=run.id)
                .count()
            )
            print(
                f"  {run.id}: {run.status.value}, {count} order(s), "
                f"base_price={run.base_price}"
            )
    return 0


def _close_now(session, order_ids):
    """Take the runs these orders landed in as far as RIDER_ASSIGNMENT."""
    from datetime import datetime as dt

    from app.deliveries.models import DeliveryRun, DeliveryRunOrder, DeliveryRunStatus
    from app.deliveries.runs import DeliveryRunService, THIN_VOLUME_THRESHOLD

    run_orders = (
        session.query(DeliveryRunOrder)
        .filter(DeliveryRunOrder.order_id.in_(order_ids))
        .all()
    )
    run_ids = {run_order.delivery_run_id for run_order in run_orders}
    if not run_ids:
        print("\nNothing attached, so nothing to close.")
        return

    for run_id in run_ids:
        attached = (
            session.query(DeliveryRunOrder).filter_by(delivery_run_id=run_id).all()
        )
        if len(attached) < THIN_VOLUME_THRESHOLD:
            # Without this every order on a thin run is free-cancelled at
            # cutoff and the run is cancelled with it. Recording consent
            # is what a buyer choosing "go now" in the app would do.
            print(
                f"\n  {run_id} has {len(attached)} order(s), under the "
                f"thin-volume threshold of {THIN_VOLUME_THRESHOLD} -- "
                "recording fallback consent so it survives its cutoff."
            )
            for run_order in attached:
                run_order.fallback_consent = True

        run = session.query(DeliveryRun).filter_by(id=run_id).first()
        if run and run.status == DeliveryRunStatus.OPEN:
            run.cutoff_at = dt.utcnow()

    session.commit()

    closed = DeliveryRunService.close_runs_past_cutoff()
    print(f"  Close pass: {closed}")


if __name__ == "__main__":
    raise SystemExit(main())
