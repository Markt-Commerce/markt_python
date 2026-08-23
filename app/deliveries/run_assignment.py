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

            return {
                "run_id": run_id,
                "status": run.status.value,
                "assignment_id": assignment.id,
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
