"""DeliveryRun batching, capacity, and pricing (10.1-10.4). Kept out of
services.py -- like fees.py/shipping.py/events.py elsewhere in this
codebase -- since this is a genuinely separate concern from the existing
single-order rider-assignment machinery that file already carries.

Scope note: this only builds the RUN's own container -- batching,
capacity, cutoff, base pricing. The rider-facing accept/decline/pickup/
POD flow that actually drives a run from PLANNING through to COMPLETED
is Phase 10, and the thin-volume buyer wait-vs-pay prompt + its
wait-deadline fallback (10.3) is deliberately a separate, later
increment -- both flagged in the Implementation Checklist rather than
half-built here.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.fulfilment.models import FulfilmentAllocation, FulfilmentAllocationStatus
from app.libs.session import session_scope
from app.orders.models import Order, OrderItem, OrderStatus, ShippingAddress
from app.products.models import Product
from app.users.models import Seller

from .models import DeliveryRun, DeliveryRunOrder, DeliveryRunStatus

logger = logging.getLogger(__name__)

# Phase 0: run cadence ~2h, load-dependent -- how far out a freshly
# created run's cutoff sits.
RUN_CADENCE_HOURS = 2

# Phase 0: capacity constraint (10.4).
RUN_MAX_PACKAGES = 30
RUN_MAX_WEIGHT_GRAMS = 50_000

# 10.3: "numbers TBD later" (Phase 0), doesn't block build -- placeholder
# flat fee per market-area pair until a real configurable zone-rate table
# exists (11.4/13.1's own "Distance/Delivery Cost" gaps get the same
# neutral-placeholder treatment elsewhere in this codebase).
DEFAULT_BASE_PRICE = 500.0

# 10.1: items whose current fulfilment allocation means the seller has
# genuinely committed -- "fully routed and confirmed."
READY_ALLOCATION_STATUSES = (
    FulfilmentAllocationStatus.ACCEPTED,
    FulfilmentAllocationStatus.PREPARING,
)


class DeliveryRunService:
    @staticmethod
    def get_or_create_open_run(session, market_id: int, area_id: int) -> DeliveryRun:
        """Returns the current OPEN run for this market/area pair that
        still has package-count capacity, creating one if none exists or
        every existing one is full (10.4's "next compatible run"
        overflow)."""
        candidates = (
            session.query(DeliveryRun)
            .filter_by(
                market_id=market_id,
                area_id=area_id,
                status=DeliveryRunStatus.OPEN,
            )
            .order_by(DeliveryRun.created_at.asc())
            .all()
        )
        for run in candidates:
            package_count = (
                session.query(DeliveryRunOrder)
                .filter_by(delivery_run_id=run.id)
                .count()
            )
            if package_count < run.max_packages:
                return run

        return DeliveryRunService._create_open_run(session, market_id, area_id)

    @staticmethod
    def _create_open_run(session, market_id: int, area_id: int) -> DeliveryRun:
        run = DeliveryRun(
            market_id=market_id,
            area_id=area_id,
            status=DeliveryRunStatus.OPEN,
            max_packages=RUN_MAX_PACKAGES,
            max_weight_grams=RUN_MAX_WEIGHT_GRAMS,
            cutoff_at=datetime.utcnow() + timedelta(hours=RUN_CADENCE_HOURS),
        )
        session.add(run)
        session.flush()
        return run

    @staticmethod
    def _order_weight_grams(session, order_id: str) -> float:
        items = session.query(OrderItem).filter_by(order_id=order_id).all()
        total = 0.0
        for item in items:
            if item.status == OrderItem.Status.CANCELLED:
                continue
            product = session.query(Product).get(item.product_id)
            weight = (product.weight or 0.0) if product else 0.0
            total += weight * item.quantity
        return total

    @staticmethod
    def _order_is_ready(session, order: Order) -> bool:
        """10.1: "fully routed and confirmed" -- every non-cancelled item
        has at least one FulfilmentAllocation, and its most recent one is
        ACCEPTED/PREPARING (the seller has committed). An item with no
        allocation at all means this order predates Phase 5/9 tracking
        (the pre-existing order-first checkout flow never creates
        FulfilmentAllocation rows) -- not eligible for a run via this
        path, since there's nothing here to confirm "routed" against."""
        active_items = [
            item for item in order.items if item.status != OrderItem.Status.CANCELLED
        ]
        if not active_items:
            return False

        for item in active_items:
            latest = (
                session.query(FulfilmentAllocation)
                .filter_by(order_item_id=item.id)
                .order_by(FulfilmentAllocation.id.desc())
                .first()
            )
            if not latest or latest.status not in READY_ALLOCATION_STATUSES:
                return False
        return True

    @staticmethod
    def _resolve_single_market(session, order: Order) -> Optional[int]:
        """A DeliveryRun serves exactly one market. An order's items can
        (rarely) span more than one -- rerouting is within-market only
        (ADR 18.2), so any spread can only come from the buyer's own
        original cart spanning markets, not from a reroute. Splitting one
        order's delivery across two runs (one per market) is real,
        unbuilt work -- flagged here, not faked (see Phase 13's own
        "multi-market basket UI" item). Returns None for that case, same
        as an unresolved market -- attach_eligible_orders treats both as
        "not yet eligible"."""
        active_items = [
            item for item in order.items if item.status != OrderItem.Status.CANCELLED
        ]
        market_ids = set()
        for item in active_items:
            seller = session.query(Seller).get(item.seller_id)
            if not seller or not seller.market_id:
                return None
            market_ids.add(seller.market_id)

        if len(market_ids) != 1:
            return None
        return market_ids.pop()

    @staticmethod
    def attach_eligible_orders() -> dict:
        """10.1: attach every not-yet-attached, fully-routed-and-confirmed
        order to the current open run for its market/area, applying the
        capacity/overflow rule (10.4). Safe to call repeatedly -- an order
        already in DeliveryRunOrder is skipped via the unique order_id
        constraint's backing query below."""
        attached = 0
        skipped_unresolved = 0

        with session_scope() as session:
            attached_order_ids = {
                row[0] for row in session.query(DeliveryRunOrder.order_id).all()
            }

            query = (
                session.query(Order)
                .join(ShippingAddress, ShippingAddress.order_id == Order.id)
                .filter(
                    Order.status == OrderStatus.READY_FOR_DELIVERY,
                    ShippingAddress.area_id.isnot(None),
                )
            )
            if attached_order_ids:
                query = query.filter(~Order.id.in_(attached_order_ids))
            candidate_orders = query.all()

            for order in candidate_orders:
                if not DeliveryRunService._order_is_ready(session, order):
                    continue

                market_id = DeliveryRunService._resolve_single_market(session, order)
                area_id = (
                    order.shipping_address.area_id if order.shipping_address else None
                )
                if not market_id or not area_id:
                    skipped_unresolved += 1
                    continue

                weight = DeliveryRunService._order_weight_grams(session, order.id)
                run = DeliveryRunService.get_or_create_open_run(
                    session, market_id, area_id
                )

                # Weight can push a run over capacity even under the
                # package-count limit get_or_create_open_run already
                # checked -- re-check and roll to a fresh run rather than
                # re-running the package-count search, which would just
                # return this same weight-full run again.
                current_weight = sum(
                    DeliveryRunService._order_weight_grams(session, ro.order_id)
                    for ro in run.run_orders
                )
                if current_weight + weight > run.max_weight_grams:
                    run = DeliveryRunService._create_open_run(
                        session, market_id, area_id
                    )

                session.add(DeliveryRunOrder(delivery_run_id=run.id, order_id=order.id))
                attached += 1

        logger.info(
            "Attached %s order(s) to delivery runs, %s skipped "
            "(unresolved market/area)",
            attached,
            skipped_unresolved,
        )
        return {"attached": attached, "skipped_unresolved": skipped_unresolved}

    @staticmethod
    def close_runs_past_cutoff() -> dict:
        """10.2: OPEN -> CUTOFF_REACHED once cutoff_at passes, priced
        (10.3) and advanced to PLANNING -- Phase 10 takes it from there
        (rider assignment). An empty run at cutoff ("with little or no
        order volume, a run may not run at all", 10.1) is cancelled
        instead of planned with nothing to plan."""
        closed = 0
        cancelled_empty = 0
        now = datetime.utcnow()

        with session_scope() as session:
            due = (
                session.query(DeliveryRun)
                .filter(
                    DeliveryRun.status == DeliveryRunStatus.OPEN,
                    DeliveryRun.cutoff_at <= now,
                )
                .all()
            )

            for run in due:
                order_count = (
                    session.query(DeliveryRunOrder)
                    .filter_by(delivery_run_id=run.id)
                    .count()
                )
                if order_count == 0:
                    run.transition_to(DeliveryRunStatus.CANCELLED)
                    run.cancel_reason = "No orders joined before cutoff"
                    cancelled_empty += 1
                    continue

                run.transition_to(DeliveryRunStatus.CUTOFF_REACHED)
                # 10.3: cost-sharing -- the flat run-level base price
                # split across however many orders actually joined, so
                # the per-order share naturally drops as a run fills.
                run.base_price = DEFAULT_BASE_PRICE
                run.price_per_order = round(run.base_price / order_count, 2)
                run.transition_to(DeliveryRunStatus.PLANNING)
                closed += 1

        logger.info(
            "Closed %s delivery run(s) into planning, cancelled %s empty run(s)",
            closed,
            cancelled_empty,
        )
        return {"closed": closed, "cancelled_empty": cancelled_empty}
