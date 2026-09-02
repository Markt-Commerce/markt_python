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
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional

from app.fulfilment.models import FulfilmentAllocation, FulfilmentAllocationStatus
from app.inventory.models import HandlingClass, ProductHandling
from app.libs.errors import ForbiddenError, NotFoundError, ValidationError
from app.libs.session import session_scope
from app.libs.money import to_money
from app.notifications.models import NotificationType
from app.notifications.services import NotificationService
from app.orders.models import Order, OrderItem, OrderStatus, ShippingAddress
from app.products.models import Product
from app.users.models import Seller

from .models import (
    DeliveryRun,
    DeliveryRunOrder,
    DeliveryRunStatus,
    DeliveryRunWaitChoice,
)

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

# 10.3: not spec-mandated (the spec gives no number for "thin") -- a run
# with fewer than this many orders counts as not having "enough sharing
# available" yet. A judgment call, flagged the same way
# MAX_REROUTE_ATTEMPTS was in Phase 6.
THIN_VOLUME_THRESHOLD = 3

# 10.3 "surge-aware" pricing (Phase 11): the spec names this in 10.3's
# own section heading but never gives a formula or trigger in the body
# text -- entirely a judgment call, same treatment as THIN_VOLUME_THRESHOLD
# above. Load signal: how many OTHER runs are simultaneously active for
# the same market/area right now. This is a real, already-computable
# signal (not invented) -- it only happens when demand within one
# cadence window genuinely exceeds a single run's capacity (10.4
# overflow, see get_or_create_open_run) or multiple cutoff-timed runs
# are concurrently mid-flight for the same zone -- rather than a fake
# time-of-day heuristic with no data behind it.
SURGE_MULTIPLIER_PER_CONCURRENT_RUN = 0.15
SURGE_MULTIPLIER_CAP = 2.0

# Run statuses that represent real, still-active demand for a market/area
# -- excludes terminal states (COMPLETED/CANCELLED/PARTIALLY_COMPLETED/
# RIDER_FAILED is itself non-terminal, see the model, but a genuinely
# stuck run isn't a demand signal worth surging on) and, deliberately,
# the run being priced itself (see calculate_surge_multiplier).
ACTIVE_RUN_STATUSES_FOR_SURGE = (
    DeliveryRunStatus.OPEN,
    DeliveryRunStatus.CUTOFF_REACHED,
    DeliveryRunStatus.PLANNING,
    DeliveryRunStatus.RIDER_ASSIGNMENT,
    DeliveryRunStatus.RIDER_ACCEPTED,
    DeliveryRunStatus.PICKUP_IN_PROGRESS,
    DeliveryRunStatus.DELIVERY_IN_PROGRESS,
)


class DeliveryRunService:
    @staticmethod
    def get_or_create_open_run(session, market_id: int, area_id: int) -> DeliveryRun:
        """Returns the current OPEN run for this market/area pair that
        still has package-count capacity, creating one if none exists or
        every existing one is full (10.4's "next compatible run"
        overflow).

        Row-locks every OPEN candidate for this market/area (FOR UPDATE)
        so two concurrent callers can't both read "29 of 30, fits" for
        the same run and both attach, pushing it over capacity -- a
        real race this module didn't originally close (unlike
        InventoryService.reserve_stock/DeliveryRunAssignmentService.accept_run,
        which already lock the row they're checking). The second caller
        blocks until the first's transaction commits, then re-counts
        with that attach already reflected. Doesn't lock against a
        *duplicate new run* being created by two simultaneous first-ever
        callers for a market/area with no OPEN run yet -- that's not a
        capacity violation (multiple concurrent runs for one zone is a
        legitimate, expected state once overflow happens), just a minor
        efficiency loss, not worth the extra locking complexity here."""
        candidates = (
            session.query(DeliveryRun)
            .filter_by(
                market_id=market_id,
                area_id=area_id,
                status=DeliveryRunStatus.OPEN,
            )
            .order_by(DeliveryRun.created_at.asc())
            .with_for_update()
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
    def _tighten_cutoff_for_perishables(
        session, run: DeliveryRun, order: Order
    ) -> None:
        """10.5: "a run respects the strictest constraint among its load."
        If this order carries a perishable item with a dwell cap, and that
        cap would be exceeded before the run's own planned cutoff, pull
        the run's cutoff in to match -- reusing the existing cutoff worker
        (close_runs_past_cutoff) to actually dispatch it in time, rather
        than building a separate perishable-specific path. The dwell
        clock starts now (the moment the order joins this run), matching
        10.5's "next viable shared run" framing.

        Deliberately does NOT implement true single-drop dispatch (a
        genuinely different delivery mechanism) -- Phase 10 owns real
        dispatch. This only makes sure the run carrying a perishable item
        can never sit open longer than that item's dwell window allows."""
        active_items = [
            item for item in order.items if item.status != OrderItem.Status.CANCELLED
        ]
        product_ids = {item.product_id for item in active_items}
        if not product_ids:
            return

        handling_rows = (
            session.query(ProductHandling)
            .filter(
                ProductHandling.product_id.in_(product_ids),
                ProductHandling.handling_class == HandlingClass.PERISHABLE,
                ProductHandling.max_dwell_minutes.isnot(None),
            )
            .all()
        )
        if not handling_rows:
            return

        tightest_dwell_minutes = min(h.max_dwell_minutes for h in handling_rows)
        dwell_deadline = datetime.utcnow() + timedelta(minutes=tightest_dwell_minutes)
        if dwell_deadline < run.cutoff_at:
            run.cutoff_at = dwell_deadline

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
                DeliveryRunService._tighten_cutoff_for_perishables(session, run, order)
                attached += 1

        logger.info(
            "Attached %s order(s) to delivery runs, %s skipped "
            "(unresolved market/area)",
            attached,
            skipped_unresolved,
        )
        return {"attached": attached, "skipped_unresolved": skipped_unresolved}

    @staticmethod
    def notify_thin_volume_orders() -> dict:
        """10.3: notify the buyer of every order attached to a still-OPEN
        run that doesn't have "enough sharing available" yet
        (< THIN_VOLUME_THRESHOLD orders), offering the wait-vs-pay-now
        choice. Only ever notifies once per order (notified_thin_volume_at
        guards it) -- safe to call repeatedly on a schedule."""
        notified = 0

        with session_scope() as session:
            thin_runs = (
                session.query(DeliveryRun)
                .filter(DeliveryRun.status == DeliveryRunStatus.OPEN)
                .all()
            )
            to_notify = []
            for run in thin_runs:
                run_orders = (
                    session.query(DeliveryRunOrder)
                    .filter_by(delivery_run_id=run.id)
                    .all()
                )
                if not run_orders or len(run_orders) >= THIN_VOLUME_THRESHOLD:
                    continue
                for run_order in run_orders:
                    if run_order.notified_thin_volume_at is not None:
                        continue
                    order = session.query(Order).get(run_order.order_id)
                    buyer_user_id = (
                        order.buyer.user_id if order and order.buyer else None
                    )
                    if not buyer_user_id:
                        continue
                    run_order.notified_thin_volume_at = datetime.utcnow()
                    to_notify.append((buyer_user_id, run_order.order_id, run.cutoff_at))

        for buyer_user_id, order_id, cutoff_at in to_notify:
            NotificationService.create_notification(
                user_id=buyer_user_id,
                notification_type=NotificationType.THIN_VOLUME_DELIVERY_CHOICE,
                reference_type="order",
                reference_id=order_id,
                metadata_={
                    "message": (
                        "Not many orders heading your way right now. We'll "
                        f"wait for a fuller run (held until {cutoff_at.isoformat()}) "
                        "unless you choose to pay now for single/near-single "
                        "delivery."
                    ),
                    "wait_deadline": cutoff_at.isoformat(),
                },
            )
            notified += 1

        logger.info("Notified %s order(s) of thin delivery volume (10.3)", notified)
        return {"notified": notified}

    @staticmethod
    def set_wait_choice(
        order_id: str,
        buyer_id: int,
        choice: DeliveryRunWaitChoice,
        fallback_consent: bool = False,
    ) -> DeliveryRunOrder:
        """10.3: record the buyer's wait-vs-pay-now choice (and, if
        waiting, whether they consent to being charged the single-drop
        rate as the fallback if the run still hasn't filled by cutoff --
        see close_runs_past_cutoff's fallback handling)."""
        with session_scope() as session:
            run_order = (
                session.query(DeliveryRunOrder).filter_by(order_id=order_id).first()
            )
            if not run_order:
                raise NotFoundError("Order is not attached to a delivery run")

            order = session.query(Order).get(order_id)
            if not order or order.buyer_id != buyer_id:
                raise ForbiddenError("Not authorized to act on this order")

            if choice not in (
                DeliveryRunWaitChoice.WAIT,
                DeliveryRunWaitChoice.PAY_NOW,
            ):
                raise ValidationError("choice must be 'wait' or 'pay_now'")

            run_order.wait_choice = choice
            run_order.fallback_consent = bool(fallback_consent) and (
                choice == DeliveryRunWaitChoice.WAIT
            )
            session.flush()
            return run_order

    @staticmethod
    def calculate_surge_multiplier(session, run: DeliveryRun) -> float:
        """10.3 "surge-aware" pricing (Phase 11) -- see the module-level
        SURGE_* constants' own comment for why this formula (concurrent
        active runs for the same market/area, not a time-of-day guess)
        and why it's a documented judgment call rather than a spec
        number. 1.0 = no surge; capped at SURGE_MULTIPLIER_CAP."""
        concurrent_active_runs = (
            session.query(DeliveryRun)
            .filter(
                DeliveryRun.market_id == run.market_id,
                DeliveryRun.area_id == run.area_id,
                DeliveryRun.id != run.id,
                DeliveryRun.status.in_(ACTIVE_RUN_STATUSES_FOR_SURGE),
            )
            .count()
        )
        multiplier = 1.0 + (
            concurrent_active_runs * SURGE_MULTIPLIER_PER_CONCURRENT_RUN
        )
        return min(multiplier, SURGE_MULTIPLIER_CAP)

    @staticmethod
    def close_runs_past_cutoff() -> dict:
        """10.2: OPEN -> CUTOFF_REACHED once cutoff_at passes, priced
        (10.3), advanced to PLANNING and then straight to RIDER_ASSIGNMENT
        (opening it up for any rider to browse/accept -- see
        DeliveryRunAssignmentService.get_available_runs/accept_run; no
        separate rider-ranking/offer step exists, matching the existing
        single-order accept_order's own first-come-first-served
        simplicity). An empty run at cutoff ("with little or no order
        volume, a run may not run at all", 10.1) is cancelled instead of
        planned with nothing to plan.

        10.3 wait-deadline fallback: if the run is STILL thin at cutoff,
        every attached order that didn't consent to the single-drop
        fallback (the default -- PENDING/WAIT with no consent) gets a
        free cancellation, per the spec's own "or offer free cancellation"
        alternative. An order that DID consent (or explicitly chose
        PAY_NOW) proceeds in the run -- but actually collecting the
        single-drop upcharge is a real payment-flow gap, not built here
        (see this module's own docstring); flagged via a warning log
        rather than silently pretending it was charged."""
        closed = 0
        cancelled_empty = 0
        free_cancellations = 0
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

            run_ids = [run.id for run in due]
            run_orders_by_run = {}
            for run_id in run_ids:
                run_orders_by_run[run_id] = (
                    session.query(DeliveryRunOrder)
                    .filter_by(delivery_run_id=run_id)
                    .all()
                )

            to_cancel = []
            for run in due:
                run_orders = run_orders_by_run[run.id]
                if not run_orders:
                    run.transition_to(DeliveryRunStatus.CANCELLED)
                    run.cancel_reason = "No orders joined before cutoff"
                    cancelled_empty += 1
                    continue

                # 10.3 wait-deadline fallback: still thin at cutoff -- an
                # order without fallback consent gets a free cancellation
                # (removed from `surviving_orders` before pricing, so the
                # ones left behind never share the cost with someone who
                # was just refunded out). A consenting order stays in --
                # see the module docstring on why the actual upcharge
                # isn't collected yet.
                surviving_orders = run_orders
                if len(run_orders) < THIN_VOLUME_THRESHOLD:
                    surviving_orders = []
                    for run_order in run_orders:
                        consented = (
                            run_order.wait_choice == DeliveryRunWaitChoice.PAY_NOW
                            or run_order.fallback_consent
                        )
                        if consented:
                            logger.warning(
                                "Order %s consented to the single-drop fallback "
                                "rate, but collecting it is not implemented -- "
                                "proceeding without an extra charge (10.3 gap)",
                                run_order.order_id,
                            )
                            surviving_orders.append(run_order)
                        else:
                            to_cancel.append(run_order.order_id)

                if not surviving_orders:
                    run.transition_to(DeliveryRunStatus.CANCELLED)
                    run.cancel_reason = (
                        "All orders free-cancelled on wait-deadline fallback"
                    )
                    cancelled_empty += 1
                    continue

                run.transition_to(DeliveryRunStatus.CUTOFF_REACHED)
                # 10.3: cost-sharing -- the flat run-level base price
                # split across however many orders actually survived to
                # this point, so the per-order share naturally drops as a
                # run fills. Surge-adjusted (Phase 11) by how much other
                # concurrent demand exists for this same market/area.
                surge_multiplier = DeliveryRunService.calculate_surge_multiplier(
                    session, run
                )
                run.surge_multiplier = surge_multiplier
                run.base_price = to_money(
                    to_money(DEFAULT_BASE_PRICE) * Decimal(str(surge_multiplier))
                )
                run.price_per_order = to_money(run.base_price / len(surviving_orders))
                run.transition_to(DeliveryRunStatus.PLANNING)
                # 10.2/Phase 10: no separate rider-ranking/offer step exists
                # (matching the existing single-order accept_order's own
                # first-come-first-served simplicity) -- a priced run opens
                # straight up for any online rider to browse and accept.
                run.transition_to(DeliveryRunStatus.RIDER_ASSIGNMENT)
                closed += 1

            order_buyer_ids = {}
            if to_cancel:
                for order_id, buyer_id in (
                    session.query(Order.id, Order.buyer_id)
                    .filter(Order.id.in_(to_cancel))
                    .all()
                ):
                    order_buyer_ids[order_id] = buyer_id

        if to_cancel:
            from app.orders.services import OrderService

            for order_id in to_cancel:
                buyer_id = order_buyer_ids.get(order_id)
                if not buyer_id:
                    continue
                try:
                    OrderService.cancel_order(
                        order_id,
                        buyer_id,
                        reason=(
                            "Delivery run didn't fill by the wait deadline "
                            "(10.3) -- free cancellation, no fallback consent "
                            "on file"
                        ),
                    )
                    free_cancellations += 1
                except Exception:
                    logger.exception(
                        "Failed to auto-cancel order %s on thin-volume "
                        "wait-deadline fallback",
                        order_id,
                    )

            with session_scope() as session:
                session.query(DeliveryRunOrder).filter(
                    DeliveryRunOrder.order_id.in_(to_cancel)
                ).delete(synchronize_session=False)

        logger.info(
            "Closed %s delivery run(s) into planning, cancelled %s empty run(s), "
            "%s order(s) free-cancelled on wait-deadline fallback",
            closed,
            cancelled_empty,
            free_cancellations,
        )
        return {
            "closed": closed,
            "cancelled_empty": cancelled_empty,
            "free_cancellations": free_cancellations,
        }
