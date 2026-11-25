"""Paying for a Markt Business plan through Paystack.

Same shape as a wallet top-up (app.wallet.services): a PENDING
BusinessSubscription is created, Paystack is initialised with reference
``SUB_<id>``, and the subscription goes ACTIVE only when Paystack confirms the
money moved — via the charge.success webhook (app.payments.services
dispatches ``SUB_`` references here) or a server-side verify call. The client
is never the authority on payment, and completion checks status, amount and
currency against what was asked for.

A subscription runs for one billing period and does not auto-renew: renewal
is a new checkout. Recurring billing (Paystack plans) is a later step.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests

from app.libs.errors import APIError, ForbiddenError, NotFoundError, ValidationError
from app.libs.session import session_scope
from main.config import settings

from .features import business_features
from .models import (
    BusinessSubscription,
    BusinessSubscriptionPlan,
    BusinessSubscriptionStatus,
)

logger = logging.getLogger(__name__)

REFERENCE_PREFIX = "SUB_"

PERIOD_DAYS = {
    "weekly": 7,
    "monthly": 30,
    "quarterly": 91,
    "yearly": 365,
    "annual": 365,
}


def period_end(start: datetime, billing_interval: str) -> datetime:
    return start + timedelta(days=PERIOD_DAYS.get((billing_interval or "").lower(), 30))


def _require_enabled():
    if not business_features()["subscriptions_enabled"]:
        raise NotFoundError("Subscriptions are not available")


def _activate(
    session, subscription: BusinessSubscription, plan: BusinessSubscriptionPlan
) -> None:
    """Make `subscription` the user's one live plan.

    Renewing the same plan early adds a period on top of the time already
    paid for. Switching to a different plan replaces the old one from now:
    there is no proration, so the unused part of the old plan is not
    carried over.
    """
    now = datetime.utcnow()
    others = (
        session.query(BusinessSubscription)
        .filter(
            BusinessSubscription.user_id == subscription.user_id,
            BusinessSubscription.id != subscription.id,
            BusinessSubscription.status.in_(
                [
                    BusinessSubscriptionStatus.ACTIVE,
                    BusinessSubscriptionStatus.CANCELLED,
                ]
            ),
        )
        .all()
    )
    paid_until = max(
        (
            o.end_date
            for o in others
            if o.plan_id == plan.id and o.end_date and o.end_date > now
        ),
        default=now,
    )
    for other in others:
        other.status = BusinessSubscriptionStatus.CANCELLED
        other.end_date = now
        other.renewal_date = None

    subscription.status = BusinessSubscriptionStatus.ACTIVE
    subscription.start_date = now
    subscription.end_date = period_end(paid_until, plan.billing_interval)
    subscription.renewal_date = subscription.end_date


def start_checkout(user_id: str, plan_id: int, platform: str = "web") -> Dict[str, Any]:
    """Begin paying for a plan. A free plan activates straight away; a paid one
    returns Paystack's authorization_url for the client to open."""
    from app.payments.services import PaymentService, to_subunit
    from app.users.models import User

    _require_enabled()
    with session_scope() as session:
        user = session.query(User).get(user_id)
        if not user or not user.is_business or not user.business_profile:
            raise ForbiddenError("Set up your business profile before choosing a plan")
        plan = session.query(BusinessSubscriptionPlan).get(plan_id)
        if not plan or not plan.is_active:
            raise ValidationError("Unknown plan")

        subscription = BusinessSubscription(
            user_id=user_id, plan_id=plan.id, status=BusinessSubscriptionStatus.PENDING
        )
        session.add(subscription)
        session.flush()
        subscription.payment_reference = f"{REFERENCE_PREFIX}{subscription.id}"

        if not plan.price or plan.price <= 0:
            _activate(session, subscription, plan)
            return {
                "subscription_id": subscription.id,
                "status": subscription.status.name,
                "authorization_url": None,
                "reference": subscription.payment_reference,
            }

        subscription_id = subscription.id
        reference = subscription.payment_reference
        amount = plan.price
        currency = plan.currency
        email = user.email
        plan_key = plan.key

    base_url = settings.API_BASE_URL or "http://localhost:8000"
    payload = {
        "amount": to_subunit(amount),
        "email": email,
        "currency": currency,
        "reference": reference,
        "callback_url": f"{base_url}/api/v1/business/subscriptions/callback/{subscription_id}?platform={platform}",
        "metadata": {
            "type": "business_subscription",
            "subscription_id": subscription_id,
            "user_id": user_id,
            "plan": plan_key,
        },
    }
    try:
        response = requests.post(
            f"{PaymentService.PAYSTACK_BASE_URL}/transaction/initialize",
            json=payload,
            headers={"Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"},
            timeout=30,
        )
        data = response.json()
    except Exception:
        logger.exception(
            "Paystack initialize failed for subscription %s", subscription_id
        )
        data, response = {}, None

    if response is None or response.status_code != 200 or not data.get("status"):
        with session_scope() as session:
            sub = session.query(BusinessSubscription).get(subscription_id)
            if sub and sub.status == BusinessSubscriptionStatus.PENDING:
                sub.status = BusinessSubscriptionStatus.EXPIRED
        raise APIError("Could not start the payment. Please try again.", 502)

    return {
        "subscription_id": subscription_id,
        "status": BusinessSubscriptionStatus.PENDING.name,
        "authorization_url": data["data"]["authorization_url"],
        "reference": data["data"].get("reference", reference),
    }


def complete_subscription(
    reference: str, gateway_data: Optional[Dict[str, Any]] = None
) -> bool:
    """Idempotently activate the subscription a successful charge paid for."""
    with session_scope() as session:
        subscription = (
            session.query(BusinessSubscription)
            .filter_by(payment_reference=reference)
            .first()
        )
        if not subscription:
            logger.warning("Subscription not found for reference %s", reference)
            return False
        if subscription.status in (
            BusinessSubscriptionStatus.ACTIVE,
            BusinessSubscriptionStatus.CANCELLED,
        ):
            return True  # already settled; webhook and verify can both arrive

        plan = subscription.plan
        if gateway_data is not None:
            # Never give value on the event name alone: check what was paid.
            expected = int(round(float(plan.price) * 100))
            if gateway_data.get("status") not in (None, "success"):
                return False
            paid = gateway_data.get("amount")
            if paid is not None and int(paid) != expected:
                logger.error(
                    "Subscription %s amount mismatch: expected %s, got %s -- not activating",
                    subscription.id,
                    expected,
                    paid,
                )
                return False
            currency = gateway_data.get("currency")
            if currency is not None and currency != plan.currency:
                logger.error(
                    "Subscription %s currency mismatch: expected %s, got %s -- not activating",
                    subscription.id,
                    plan.currency,
                    currency,
                )
                return False

        _activate(session, subscription, plan)
        return True


def verify_subscription(
    subscription_id: int, user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Confirm a payment directly with Paystack (the webhook can be late) and
    activate the subscription if the money landed."""
    from app.payments.services import PaymentService

    with session_scope() as session:
        subscription = session.query(BusinessSubscription).get(subscription_id)
        if not subscription or (user_id and subscription.user_id != user_id):
            raise NotFoundError("Subscription not found")
        status = subscription.status
        reference = subscription.payment_reference

    if status in (
        BusinessSubscriptionStatus.ACTIVE,
        BusinessSubscriptionStatus.CANCELLED,
    ):
        return {
            "subscription_id": subscription_id,
            "status": status.name,
            "verified": True,
        }
    if status == BusinessSubscriptionStatus.EXPIRED:
        return {
            "subscription_id": subscription_id,
            "status": status.name,
            "verified": False,
        }

    try:
        response = requests.get(
            f"{PaymentService.PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {PaymentService.PAYSTACK_SECRET_KEY}"},
            timeout=20,
        )
        body = response.json()
    except Exception:
        logger.exception("Paystack verify failed for subscription %s", subscription_id)
        raise APIError("Could not confirm the payment with Paystack", 502)

    gateway = (body or {}).get("data") or {}
    if response.status_code != 200 or not body.get("status"):
        raise APIError("Could not confirm the payment with Paystack", 502)

    if gateway.get("status") == "success":
        activated = complete_subscription(reference, gateway)
        return {
            "subscription_id": subscription_id,
            "status": "ACTIVE" if activated else "PENDING",
            "verified": activated,
        }
    if gateway.get("status") in ("failed", "abandoned", "reversed"):
        with session_scope() as session:
            sub = session.query(BusinessSubscription).get(subscription_id)
            if sub and sub.status == BusinessSubscriptionStatus.PENDING:
                sub.status = BusinessSubscriptionStatus.EXPIRED
        return {
            "subscription_id": subscription_id,
            "status": "EXPIRED",
            "verified": False,
        }
    return {"subscription_id": subscription_id, "status": "PENDING", "verified": False}
