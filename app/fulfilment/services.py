"""Seller fulfilment: accept/decline/timeout of an item allocation
(12.1-12.2).

Distinct from OrderItem's own PENDING/PROCESSING/SHIPPED/DELIVERED/
CANCELLED lifecycle (Phase 1) -- this tracks the seller-facing negotiation
for who fulfils an item, which OrderItem's state machine knows nothing
about. Deliberately NOT wired to affect OrderItem.status.

decline(), expire_stale_allocations(), and buyer_reject_reroute() each
land the allocation at DECLINED/TIMEOUT/BUYER_REJECTED first (so that
terminal state is durably recorded for Seller Reliability's Response Rate
component -- see app.fulfilment.rerouting's module docstring), then call
ReroutingService.attempt_reroute() against that same allocation id in its
own session. attempt_reroute() is a no-op if the allocation isn't at one
of those three statuses when it looks it up, so this is safe to call
unconditionally rather than needing its own success check here.

accept()'s 6.1 ASK gate (AWAITING_BUYER_APPROVAL) and its resolution
(buyer_approve_reroute()/buyer_reject_reroute()) are the buyer-facing
counterpart to the seller-facing accept/decline/timeout negotiation above
-- see accept()'s own docstring for why the gate lives there rather than
in the rerouting engine itself.
"""

from datetime import datetime, timedelta
from typing import Optional

from external.database import db
from app.libs.errors import ConflictError, ForbiddenError, NotFoundError
from app.libs.session import session_scope
from app.notifications.models import NotificationType
from app.notifications.services import NotificationService
from app.orders.events import ActorType, OrderEventService, OrderEventType
from app.orders.models import FulfilmentPreference, Order, OrderItem
from app.payments.models import PaymentStatus
from app.products.models import Product
from app.users.models import Seller

from .models import FulfilmentAllocation, FulfilmentAllocationStatus

# Phase 0 decision.
SELLER_RESPONSE_TIMEOUT_MINUTES = 3

# 9.1: how long an ASK buyer is given to approve/reject a material
# substitution before Markt gives up on it (spec's own example figure).
ASK_APPROVAL_TIMEOUT_MINUTES = 5


class FulfilmentService:
    @staticmethod
    def create_allocation(
        order_item_id: int,
        seller_id: int,
        quantity: int,
        product_id: Optional[str] = None,
        reservation_id: Optional[str] = None,
    ) -> FulfilmentAllocation:
        """Open the seller-acceptance window for an order item. The seller
        is already determined (set on the item at listing time in this
        codebase for the original allocation -- there's no seller-
        ranking/selection step yet outside of rerouting), so this starts
        directly at AWAITING_SELLER rather than the spec's PENDING/
        SELLER_SELECTION pre-states.

        product_id defaults to the order item's own product -- pass it
        explicitly when this allocation is for a REROUTED replacement
        seller, whose Product row is a different id (see
        FulfilmentAllocation.product_id's docstring). reservation_id, if
        given, is released automatically if this allocation ends up
        DECLINED/TIMEOUT (see decline()/expire_stale_allocations())."""
        with session_scope() as session:
            # Captured before product_id is possibly overwritten below --
            # an explicitly-passed product_id is exactly what marks this as
            # a reroute-created allocation rather than the original one.
            is_reroute = product_id is not None

            order_item = session.query(OrderItem).get(order_item_id)
            if product_id is None:
                product_id = order_item.product_id if order_item else None
            order_id = order_item.order_id if order_item else None

            allocation = FulfilmentAllocation(
                order_item_id=order_item_id,
                seller_id=seller_id,
                product_id=product_id,
                reservation_id=reservation_id,
                quantity=quantity,
                status=FulfilmentAllocationStatus.AWAITING_SELLER,
                seller_response_deadline=datetime.utcnow()
                + timedelta(minutes=SELLER_RESPONSE_TIMEOUT_MINUTES),
            )
            session.add(allocation)
            session.flush()

            seller = session.query(Seller).get(seller_id)
            seller_user_id = seller.user_id if seller else None
            allocation_id = allocation.id

            if order_id:
                OrderEventService.emit(
                    session,
                    order_id=order_id,
                    order_item_id=order_item_id,
                    event_type=(
                        OrderEventType.ITEM_REROUTED
                        if is_reroute
                        else OrderEventType.ITEM_ALLOCATED
                    ),
                    actor_type=ActorType.SYSTEM,
                    actor_id=str(seller_id),
                    metadata={"quantity": quantity, "product_id": product_id},
                )

        if seller_user_id:
            NotificationService.create_notification(
                user_id=seller_user_id,
                notification_type=NotificationType.FULFILMENT_REQUEST,
                reference_type="fulfilment_allocation",
                reference_id=str(allocation_id),
                metadata_={
                    "message": (
                        f"New order item to fulfil: {quantity} unit(s). "
                        f"Respond within {SELLER_RESPONSE_TIMEOUT_MINUTES} minutes."
                    )
                },
            )

        with session_scope() as session:
            return session.query(FulfilmentAllocation).get(allocation_id)

    @staticmethod
    def accept(allocation_id: int, seller_id: int) -> FulfilmentAllocation:
        """12.2 row 1: seller accepts. Required conditions ("reservation
        still active; item not already owned") are enforced structurally --
        the transition guard only allows this from AWAITING_SELLER, and the
        partial unique index guarantees at most one active allocation ever
        exists per item, so there's nothing else to double-own.

        6.1 ASK gate: if the buyer's preference is ASK and this seller's
        product price differs from the item's originally negotiated price,
        this is a material substitution (6.1's own definition also covers
        a product/variant change or a second delivery fee, but those can't
        happen here -- the eligibility filter already enforces the same
        variant, and a second delivery fee doesn't exist as a concept for a
        within-market reroute -- so price is the only real signal this
        engine can check). It lands at AWAITING_BUYER_APPROVAL instead of
        ACCEPTED, and the buyer is notified; nothing about the seller's own
        side of this changes, and the reservation stays held either way.
        A same-price substitution (the spec's own non-material example)
        proceeds straight to ACCEPTED even for an ASK buyer.
        """
        with session_scope() as session:
            allocation = (
                session.query(FulfilmentAllocation)
                .filter_by(id=allocation_id, seller_id=seller_id)
                .first()
            )
            if not allocation:
                raise NotFoundError("Fulfilment allocation not found")

            order_item = session.query(OrderItem).get(allocation.order_item_id)
            requires_approval = False
            if (
                order_item
                and order_item.fulfilment_preference == FulfilmentPreference.ASK
            ):
                product = session.query(Product).get(allocation.product_id)
                if product and product.price != order_item.price:
                    requires_approval = True

            if requires_approval:
                allocation.transition_to(
                    FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL
                )
                allocation.buyer_response_deadline = datetime.utcnow() + timedelta(
                    minutes=ASK_APPROVAL_TIMEOUT_MINUTES
                )
            else:
                allocation.transition_to(FulfilmentAllocationStatus.ACCEPTED)

            if order_item:
                OrderEventService.emit(
                    session,
                    order_id=order_item.order_id,
                    order_item_id=order_item.id,
                    event_type=(
                        OrderEventType.ITEM_SUBSTITUTION_PENDING
                        if requires_approval
                        else OrderEventType.ITEM_ACCEPTED
                    ),
                    actor_type=ActorType.SELLER,
                    actor_id=str(seller_id),
                )

            session.flush()

            buyer_user_id = None
            if requires_approval and order_item and order_item.order:
                buyer = order_item.order.buyer
                buyer_user_id = buyer.user_id if buyer else None
            allocation_id_result = allocation.id

        if requires_approval and buyer_user_id:
            NotificationService.create_notification(
                user_id=buyer_user_id,
                notification_type=NotificationType.SUBSTITUTION_APPROVAL_REQUIRED,
                reference_type="fulfilment_allocation",
                reference_id=str(allocation_id_result),
                metadata_={
                    "message": (
                        "Your original seller couldn't fulfil an item -- "
                        "a replacement was found at a different price. "
                        "Approve or reject the substitution."
                    )
                },
            )

        return allocation

    @staticmethod
    def cancel_after_accept(allocation_id: int, seller_id: int) -> FulfilmentAllocation:
        """13.4 anti-gaming: a seller backs out of an ACCEPTED or
        PREPARING allocation -- the "accept-then-cancel" pattern the spec
        names explicitly, worse than a plain decline() because the buyer
        (and Markt's own downstream sequencing) already relied on the
        commitment. Still safe pre-dispatch (10.1: nothing dispatches
        until fulfilment is locked), so this always reroutes rather than
        needing to unwind a rider/pickup. No `reason` param yet -- the
        14.2 event log now exists, but its `metadata` still needs a
        reason to actually put there; add the param when a route surfaces
        one rather than accepting and silently dropping it now.

        Deliberately its own status (CANCELLED_BY_SELLER) rather than
        DECLINED -- reliability.py's cancellation-penalty component reads
        this specifically, on top of the 13.2 formula's own Acceptance
        Rate (which would otherwise keep counting this as a plain "yes,
        they accepted" with no memory of the later reversal)."""
        with session_scope() as session:
            allocation = (
                session.query(FulfilmentAllocation)
                .filter_by(id=allocation_id, seller_id=seller_id)
                .first()
            )
            if not allocation:
                raise NotFoundError("Fulfilment allocation not found")

            allocation.transition_to(FulfilmentAllocationStatus.CANCELLED_BY_SELLER)
            reservation_id = allocation.reservation_id

            order_item = session.query(OrderItem).get(allocation.order_item_id)
            if order_item:
                OrderEventService.emit(
                    session,
                    order_id=order_item.order_id,
                    order_item_id=order_item.id,
                    event_type=OrderEventType.ITEM_CANCELLED_BY_SELLER,
                    actor_type=ActorType.SELLER,
                    actor_id=str(seller_id),
                )

            session.flush()

        if reservation_id:
            from app.inventory.services import InventoryService

            InventoryService.release_reservations([reservation_id])

        from .rerouting import ReroutingService

        ReroutingService.attempt_reroute(allocation_id)

        return allocation

    @staticmethod
    def decline(allocation_id: int, seller_id: int) -> FulfilmentAllocation:
        """12.2 row 2: seller declines. Stops at DECLINED rather than
        auto-advancing to REROUTING (an earlier version of this did, but
        that made a decline and a timeout indistinguishable at rest --
        both landed on REROUTING with nothing left recording *how* the
        allocation got there. Seller Reliability's Response Rate component
        (13.2) needs that distinction: declining is a response, timing
        out is the absence of one. The reroute loop itself is what moves
        this on to REROUTING once it actually picks the item up."""
        with session_scope() as session:
            allocation = (
                session.query(FulfilmentAllocation)
                .filter_by(id=allocation_id, seller_id=seller_id)
                .first()
            )
            if not allocation:
                raise NotFoundError("Fulfilment allocation not found")

            allocation.transition_to(FulfilmentAllocationStatus.DECLINED)
            reservation_id = allocation.reservation_id

            order_item = session.query(OrderItem).get(allocation.order_item_id)
            if order_item:
                OrderEventService.emit(
                    session,
                    order_id=order_item.order_id,
                    order_item_id=order_item.id,
                    event_type=OrderEventType.ITEM_DECLINED,
                    actor_type=ActorType.SELLER,
                    actor_id=str(seller_id),
                )

            session.flush()

        if reservation_id:
            from app.inventory.services import InventoryService

            InventoryService.release_reservations([reservation_id])

        from .rerouting import ReroutingService

        ReroutingService.attempt_reroute(allocation_id)

        return allocation

    @staticmethod
    def buyer_approve_reroute(
        allocation_id: int, buyer_id: int
    ) -> FulfilmentAllocation:
        """6.1: buyer approves a material substitution -- AWAITING_BUYER_APPROVAL
        -> ACCEPTED. The reservation was never released, so nothing else
        needs to happen; the allocation just continues as any other
        accepted one would (start_preparing etc.)."""
        with session_scope() as session:
            allocation = (
                session.query(FulfilmentAllocation).filter_by(id=allocation_id).first()
            )
            if not allocation:
                raise NotFoundError("Fulfilment allocation not found")

            order_item = session.query(OrderItem).get(allocation.order_item_id)
            if (
                not order_item
                or not order_item.order
                or order_item.order.buyer_id != buyer_id
            ):
                raise ForbiddenError("Not authorized to act on this allocation")

            allocation.transition_to(FulfilmentAllocationStatus.ACCEPTED)

            OrderEventService.emit(
                session,
                order_id=order_item.order_id,
                order_item_id=order_item.id,
                event_type=OrderEventType.ITEM_SUBSTITUTION_APPROVED,
                actor_type=ActorType.BUYER,
                actor_id=str(buyer_id),
            )

            session.flush()
            return allocation

    @staticmethod
    def buyer_reject_reroute(allocation_id: int, buyer_id: int) -> FulfilmentAllocation:
        """6.1: buyer rejects a material substitution --
        AWAITING_BUYER_APPROVAL -> BUYER_REJECTED, release the reservation
        (same discipline as decline()), and let the reroute loop try the
        next candidate. Distinct status from DECLINED specifically so this
        never counts against the accepting seller's reliability (see
        FulfilmentAllocationStatus.BUYER_REJECTED's docstring) -- they did
        nothing wrong; the buyer just didn't want this particular swap."""
        with session_scope() as session:
            allocation = (
                session.query(FulfilmentAllocation).filter_by(id=allocation_id).first()
            )
            if not allocation:
                raise NotFoundError("Fulfilment allocation not found")

            order_item = session.query(OrderItem).get(allocation.order_item_id)
            if (
                not order_item
                or not order_item.order
                or order_item.order.buyer_id != buyer_id
            ):
                raise ForbiddenError("Not authorized to act on this allocation")

            allocation.transition_to(FulfilmentAllocationStatus.BUYER_REJECTED)
            reservation_id = allocation.reservation_id

            OrderEventService.emit(
                session,
                order_id=order_item.order_id,
                order_item_id=order_item.id,
                event_type=OrderEventType.ITEM_SUBSTITUTION_REJECTED,
                actor_type=ActorType.BUYER,
                actor_id=str(buyer_id),
            )

            session.flush()

        if reservation_id:
            from app.inventory.services import InventoryService

            InventoryService.release_reservations([reservation_id])

        from .rerouting import ReroutingService

        ReroutingService.attempt_reroute(allocation_id)

        return allocation

    @staticmethod
    def start_preparing(allocation_id: int, seller_id: int) -> FulfilmentAllocation:
        """12.2: ACCEPTED -> PREPARING. Gated on Payment.status ==
        COMPLETED rather than the spec's "escrow authorized" -- re-scoped
        per the Phase 4 cross-cutting blocker: Markt captures the full
        payment before the order even exists, so by the time any
        allocation exists at all, payment is already COMPLETED. This check
        is a defensive invariant, not a real gate in practice."""
        with session_scope() as session:
            allocation = (
                session.query(FulfilmentAllocation)
                .options(
                    db.joinedload(FulfilmentAllocation.order_item)
                    .joinedload(OrderItem.order)
                    .joinedload(Order.payments)
                )
                .filter_by(id=allocation_id, seller_id=seller_id)
                .first()
            )
            if not allocation:
                raise NotFoundError("Fulfilment allocation not found")

            order = allocation.order_item.order
            has_completed_payment = any(
                p.status == PaymentStatus.COMPLETED for p in (order.payments or [])
            )
            if not has_completed_payment:
                raise ConflictError("Cannot start preparing before payment is captured")

            allocation.transition_to(FulfilmentAllocationStatus.PREPARING)
            session.flush()
            return allocation

    @staticmethod
    def expire_stale_allocations() -> dict:
        """Worker (12.2 row 3): AWAITING_SELLER past its response
        deadline -> TIMEOUT. Stops there rather than auto-advancing to
        REROUTING -- see decline()'s docstring for why: the reroute loop
        itself makes that transition once it actually picks the item up,
        so DECLINED/TIMEOUT stay distinguishable for reliability scoring
        until then."""
        now = datetime.utcnow()
        timed_out = 0
        reservation_ids_to_release = []
        timed_out_allocation_ids = []
        with session_scope() as session:
            stale = (
                session.query(FulfilmentAllocation)
                .filter(
                    FulfilmentAllocation.status
                    == FulfilmentAllocationStatus.AWAITING_SELLER,
                    FulfilmentAllocation.seller_response_deadline < now,
                )
                .all()
            )
            for allocation in stale:
                allocation.transition_to(FulfilmentAllocationStatus.TIMEOUT)
                if allocation.reservation_id:
                    reservation_ids_to_release.append(allocation.reservation_id)
                timed_out_allocation_ids.append(allocation.id)
                timed_out += 1

                order_item = session.query(OrderItem).get(allocation.order_item_id)
                if order_item:
                    OrderEventService.emit(
                        session,
                        order_id=order_item.order_id,
                        order_item_id=allocation.order_item_id,
                        event_type=OrderEventType.ITEM_TIMED_OUT,
                        actor_type=ActorType.SYSTEM,
                        actor_id=str(allocation.seller_id),
                        idempotency_key=f"event:item_timed_out:{allocation.id}",
                    )

        if reservation_ids_to_release:
            from app.inventory.services import InventoryService

            InventoryService.release_reservations(reservation_ids_to_release)

        if timed_out_allocation_ids:
            from .rerouting import ReroutingService

            for allocation_id in timed_out_allocation_ids:
                ReroutingService.attempt_reroute(allocation_id)

        return {"timed_out": timed_out}

    @staticmethod
    def expire_stale_buyer_approvals() -> dict:
        """9.1 ASK timeout worker: AWAITING_BUYER_APPROVAL past its
        buyer_response_deadline -> UNFULFILLED. Deliberately does NOT call
        ReroutingService.attempt_reroute -- the MVP policy is "do not
        substitute after an ASK timeout," so unlike a seller TIMEOUT/DECLINE
        or an explicit BUYER_REJECTED, there's no next-candidate retry here.
        Instead: release the reservation (nothing more to hold it for) and
        refund just this item (OrderService.refund_unresolved_item),
        leaving the rest of the order untouched. "This never violates the
        buyer's explicit choice" (spec's own reasoning) -- an ASK buyer who
        never responded doesn't get auto-substituted regardless.

        Push notifications are unreliable (spec's own caveat) -- the
        in-app surfacing this implies (a visible pending-approval banner,
        not just a notification) is a mobile-side concern, out of scope
        here."""
        from app.orders.services import OrderService

        now = datetime.utcnow()
        timed_out = 0
        with session_scope() as session:
            stale = (
                session.query(FulfilmentAllocation)
                .filter(
                    FulfilmentAllocation.status
                    == FulfilmentAllocationStatus.AWAITING_BUYER_APPROVAL,
                    FulfilmentAllocation.buyer_response_deadline < now,
                )
                .all()
            )
            resolved = [
                (allocation.id, allocation.order_item_id, allocation.reservation_id)
                for allocation in stale
            ]
            for allocation in stale:
                allocation.transition_to(FulfilmentAllocationStatus.UNFULFILLED)
                timed_out += 1

                order_item = session.query(OrderItem).get(allocation.order_item_id)
                if order_item:
                    OrderEventService.emit(
                        session,
                        order_id=order_item.order_id,
                        order_item_id=allocation.order_item_id,
                        event_type=OrderEventType.ITEM_UNFULFILLED,
                        actor_type=ActorType.SYSTEM,
                        metadata={"reason": "ask_approval_timeout"},
                        idempotency_key=f"event:item_unfulfilled_ask_timeout:{allocation.id}",
                    )
            session.flush()

        for _allocation_id, order_item_id, reservation_id in resolved:
            if reservation_id:
                from app.inventory.services import InventoryService

                InventoryService.release_reservations([reservation_id])

            OrderService.refund_unresolved_item(
                order_item_id,
                reason="Buyer did not respond to the substitution approval "
                "request in time (9.1 ASK timeout)",
            )

        return {"timed_out": timed_out}
