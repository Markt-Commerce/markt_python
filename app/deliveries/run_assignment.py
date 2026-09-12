"""Rider discovery/acceptance/failure for a DeliveryRun (10.6-10.7,
Phase 10). A genuinely parallel structure to DeliveryService's existing
single-order get_available_orders/accept_order/reject_order -- same
shape (a rider browses, atomically accepts one at a time, first-come-
first-served, no ranking/offer step), just keyed by DeliveryRun instead
of Order. Kept in its own module rather than folded into runs.py (which
owns batching/pricing, not rider assignment) or services.py (which owns
the existing single-order machinery this deliberately doesn't touch).

Scope note: this only covers run-level discovery/accept/decline/failure
-- getting a run from RIDER_ASSIGNMENT to RIDER_ACCEPTED, and recovering
from RIDER_FAILED. Per-seller pickup confirmation and per-order POD
*within* an accepted run are a separate, larger increment (flagged in the
Implementation Checklist), not built here.
"""

import logging
from typing import Dict

from sqlalchemy.orm import joinedload

from app.libs.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.libs.session import session_scope

from .models import (
    AssignmentStatus,
    DeliveryRun,
    DeliveryRunAssignment,
    DeliveryRunOrder,
    DeliveryRunStatus,
    DeliveryStatus,
    DeliveryUser,
)

logger = logging.getLogger(__name__)


class DeliveryRunAssignmentService:
    @staticmethod
    def get_available_runs(
        user_id: str,
        search_radius: int = 5000,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict:
        """Runs at RIDER_ASSIGNMENT within range of the rider's last known
        location, ranked by nothing in particular (paginated in id order)
        -- same first-come-first-served simplicity as the existing
        single-order get_available_orders. Distance is measured against
        the run's Area reference location (10.1: a run serves one
        market -> one area), not any individual order's own address --
        good enough at MVP's zone-based granularity."""
        from app.deliveries.services import DeliveryService

        per_page = min(max(1, per_page), 50)
        page = max(1, page)

        with session_scope() as session:
            delivery_user = session.query(DeliveryUser).filter_by(id=user_id).first()
            if not delivery_user:
                raise NotFoundError("Delivery partner not found")
            if delivery_user.status == DeliveryStatus.SUSPENDED:
                raise ForbiddenError("Your account has been suspended")
            if (
                not delivery_user.last_location
                or delivery_user.last_location.latitude is None
                or delivery_user.last_location.longitude is None
            ):
                raise ValidationError(
                    "Location not set. Please update your location before "
                    "browsing available runs."
                )

            rider_lat = delivery_user.last_location.latitude
            rider_lng = delivery_user.last_location.longitude

            runs = (
                session.query(DeliveryRun)
                .filter(DeliveryRun.status == DeliveryRunStatus.RIDER_ASSIGNMENT)
                .options(joinedload(DeliveryRun.area), joinedload(DeliveryRun.market))
                .order_by(DeliveryRun.id.asc())
                .all()
            )

            available = []
            for run in runs:
                area = run.area
                if area is None or area.latitude is None or area.longitude is None:
                    continue
                distance = DeliveryService.haversine_distance(
                    rider_lat, rider_lng, area.latitude, area.longitude
                )
                if distance > search_radius:
                    continue

                order_count = (
                    session.query(DeliveryRunOrder)
                    .filter_by(delivery_run_id=run.id)
                    .count()
                )
                available.append(
                    {
                        "run_id": run.id,
                        "market": run.market.name if run.market else None,
                        "area": area.name,
                        "order_count": order_count,
                        "price_per_order": run.price_per_order,
                        "distance_meters": round(distance, 2),
                    }
                )

            total = len(available)
            start = (page - 1) * per_page
            end = start + per_page
            page_runs = available[start:end]

            return {
                "range_meters": search_radius,
                "runs": page_runs,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page if total else 0,
            }

    @staticmethod
    def accept_run(user_id: str, run_id: str) -> Dict:
        """Atomically accept a run -- row-locks the run so two riders
        racing for the same one can't both succeed (the existing
        single-order accept_order relies only on a status re-check
        without a row lock; this is a real gap worth closing here, given
        one run carries several orders' worth of consequence if double-
        assigned)."""
        with session_scope() as session:
            run = (
                session.query(DeliveryRun)
                .filter_by(id=run_id)
                .with_for_update()
                .first()
            )
            if not run:
                raise NotFoundError("Delivery run not found")

            delivery_user = session.query(DeliveryUser).filter_by(id=user_id).first()
            if not delivery_user:
                raise NotFoundError("Delivery partner not found")
            if delivery_user.status == DeliveryStatus.SUSPENDED:
                raise ForbiddenError("Your account has been suspended")

            already_rejected = (
                session.query(DeliveryRunAssignment)
                .filter_by(
                    delivery_run_id=run_id,
                    delivery_user_id=user_id,
                    status=AssignmentStatus.REJECTED,
                )
                .first()
            )
            if already_rejected:
                raise ConflictError("You have already declined this run")

            try:
                run.transition_to(DeliveryRunStatus.RIDER_ACCEPTED)
            except ValueError:
                raise ConflictError("Run already accepted or no longer available")

            assignment = DeliveryRunAssignment(
                delivery_run_id=run_id,
                delivery_user_id=user_id,
                status=AssignmentStatus.ACCEPTED,
            )
            session.add(assignment)
            session.flush()

            # 10.6: one DeliveryRunStop per distinct seller across the
            # run's orders, ready for the rider to work through.
            from .pickup import create_stops_for_run

            create_stops_for_run(session, run_id)

            return {
                "run_id": run_id,
                "status": run.status.value,
                "assignment_id": assignment.id,
            }

    @staticmethod
    def get_active_run(user_id: str) -> Dict:
        """Rider-facing "do I have a run in progress" lookup, mirroring
        the existing single-order get_active_assignment. Previously
        nothing let the app find its own current run without already
        knowing the run_id (e.g. after a restart) -- accept_run's own
        response is the only place a run_id was ever returned."""
        with session_scope() as session:
            assignment = (
                session.query(DeliveryRunAssignment)
                .join(
                    DeliveryRun, DeliveryRun.id == DeliveryRunAssignment.delivery_run_id
                )
                .filter(
                    DeliveryRunAssignment.delivery_user_id == user_id,
                    DeliveryRunAssignment.status == AssignmentStatus.ACCEPTED,
                    DeliveryRun.status.in_(
                        (
                            DeliveryRunStatus.RIDER_ACCEPTED,
                            DeliveryRunStatus.PICKUP_IN_PROGRESS,
                            DeliveryRunStatus.DELIVERY_IN_PROGRESS,
                        )
                    ),
                )
                .order_by(DeliveryRunAssignment.id.desc())
                .first()
            )
            if not assignment:
                return {"run_id": None}
            run_id = assignment.delivery_run_id

        return DeliveryRunAssignmentService.get_run_detail(user_id, run_id)

    @staticmethod
    def get_run_detail(user_id: str, run_id: str) -> Dict:
        """Rider-facing full detail for a run they've accepted -- per-
        seller pickup progress (stops) and per-order POD progress
        (orders). Previously nothing let a rider re-fetch this after the
        initial accept_run response, which only returns a thin
        {run_id, status, assignment_id} -- no way to recover the stop/
        order list on app restart or after navigating away."""
        from app.orders.models import Order

        from .pickup import _accepted_assignment
        from .models import DeliveryRunOrder, DeliveryRunStop

        with session_scope() as session:
            if not _accepted_assignment(session, run_id, user_id):
                raise NotFoundError("No accepted assignment found for this run")

            run = (
                session.query(DeliveryRun)
                .options(joinedload(DeliveryRun.area), joinedload(DeliveryRun.market))
                .filter_by(id=run_id)
                .first()
            )
            if not run:
                raise NotFoundError("Delivery run not found")

            stops = (
                session.query(DeliveryRunStop)
                .options(joinedload(DeliveryRunStop.seller))
                .filter_by(delivery_run_id=run_id)
                .all()
            )
            run_orders = (
                session.query(DeliveryRunOrder).filter_by(delivery_run_id=run_id).all()
            )

            orders_detail = []
            for run_order in run_orders:
                order = (
                    session.query(Order)
                    .options(
                        joinedload(Order.buyer),
                        joinedload(Order.shipping_address),
                    )
                    .get(run_order.order_id)
                )
                shipping = order.shipping_address if order else None
                orders_detail.append(
                    {
                        "order_id": run_order.order_id,
                        "order_number": order.order_number if order else None,
                        "buyer_name": (
                            order.buyer.buyername if order and order.buyer else None
                        ),
                        "delivery_address": (
                            {
                                "street_address": shipping.street_address,
                                "city": shipping.city,
                                "state": shipping.state,
                            }
                            if shipping
                            else None
                        ),
                        "pod_status": run_order.pod_status.value,
                        "delivered_at": (
                            run_order.delivered_at.isoformat()
                            if run_order.delivered_at
                            else None
                        ),
                    }
                )

            return {
                "run_id": run.id,
                "status": run.status.value,
                "market": run.market.name if run.market else None,
                "area": run.area.name if run.area else None,
                "price_per_order": run.price_per_order,
                "stops": [
                    {
                        "seller_id": stop.seller_id,
                        "seller_name": stop.seller.shop_name if stop.seller else None,
                        "shop_address": (
                            stop.seller.shop_address if stop.seller else None
                        ),
                        "status": stop.status.value,
                        "arrived_at": (
                            stop.arrived_at.isoformat() if stop.arrived_at else None
                        ),
                        "picked_up_at": (
                            stop.picked_up_at.isoformat() if stop.picked_up_at else None
                        ),
                    }
                    for stop in stops
                ],
                "orders": orders_detail,
            }

    @staticmethod
    def reject_run(user_id: str, run_id: str) -> Dict:
        """Records a decline -- doesn't change the run's own status
        (nothing was committed), matching reject_order's behaviour. A
        rider who declines can't be offered the same run again (the
        already_rejected check in accept_run)."""
        with session_scope() as session:
            run = session.query(DeliveryRun).filter_by(id=run_id).first()
            if not run:
                raise NotFoundError("Delivery run not found")

            assignment = DeliveryRunAssignment(
                delivery_run_id=run_id,
                delivery_user_id=user_id,
                status=AssignmentStatus.REJECTED,
            )
            session.add(assignment)
            session.flush()

            return {"run_id": run_id, "status": AssignmentStatus.REJECTED.value}

    @staticmethod
    def fail_run(user_id: str, run_id: str, reason: str = None) -> Dict:
        """10.7: the accepted rider can't continue (breakdown, emergency,
        etc.) after already committing -- distinct from reject_run
        (pre-commitment decline). Marks their DeliveryRunAssignment
        FAILED, transitions the run to RIDER_FAILED, and immediately
        attempts reassignment (10.7: "a failed run triggers reassignment
        where possible") by reopening it at RIDER_ASSIGNMENT for another
        rider to pick up -- the failed rider's own assignment row stays
        FAILED, distinguishing them from someone who never got the
        chance."""
        with session_scope() as session:
            assignment = (
                session.query(DeliveryRunAssignment)
                .filter_by(
                    delivery_run_id=run_id,
                    delivery_user_id=user_id,
                    status=AssignmentStatus.ACCEPTED,
                )
                .first()
            )
            if not assignment:
                raise NotFoundError("No accepted assignment found for this run")

            run = (
                session.query(DeliveryRun)
                .filter_by(id=run_id)
                .with_for_update()
                .first()
            )
            if not run:
                raise NotFoundError("Delivery run not found")

            assignment.status = AssignmentStatus.FAILED

            try:
                run.transition_to(DeliveryRunStatus.RIDER_FAILED)
            except ValueError:
                raise ConflictError(f"Cannot fail a run at status {run.status.value}")

            # 10.7: reassignment where possible -- reopen immediately
            # rather than leaving it stranded at RIDER_FAILED for a
            # separate worker to notice (no periodic sweep exists for
            # this yet; the transition itself is what makes the run
            # visible to get_available_runs again).
            run.transition_to(DeliveryRunStatus.RIDER_ASSIGNMENT)

            logger.warning(
                "Rider %s failed run %s (%s) -- reopened for reassignment",
                user_id,
                run_id,
                reason or "no reason given",
            )

            return {"run_id": run_id, "status": run.status.value}
