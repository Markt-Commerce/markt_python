"""The single answer to "does this account get business treatment?".

Every check goes through here so the subscription flag controls enforcement in
one place. With BUSINESS_SUBSCRIPTIONS_ENABLED off, the is_business tag is all
that matters and nothing is ever blocked for want of a subscription. With it
on, the tag counts only while the account holds an active subscription whose
plan grants the feature.
"""

from datetime import datetime

from sqlalchemy import and_, exists, or_

from external.database import db
from main.config import settings

from .constants import FEATURE_BUSINESS_ACCOUNT
from .models import (
    BusinessSubscription,
    BusinessSubscriptionFeature,
    BusinessSubscriptionStatus,
)


class EntitlementService:
    @staticmethod
    def subscriptions_enabled() -> bool:
        return bool(settings.BUSINESS_SUBSCRIPTIONS_ENABLED)

    @staticmethod
    def _active_clause(now=None):
        now = now or datetime.utcnow()
        return and_(
            BusinessSubscription.status.in_(
                [
                    BusinessSubscriptionStatus.ACTIVE,
                    # Cancelled still runs to its end_date.
                    BusinessSubscriptionStatus.CANCELLED,
                ]
            ),
            or_(
                BusinessSubscription.end_date.is_(None),
                BusinessSubscription.end_date > now,
            ),
        )

    @classmethod
    def has_feature(cls, user_id: str, feature_key: str) -> bool:
        """True when the user may use `feature_key`. Always true while
        subscriptions are off."""
        if not cls.subscriptions_enabled():
            return True
        return db.session.query(
            exists().where(
                and_(
                    BusinessSubscription.user_id == user_id,
                    cls._active_clause(),
                    BusinessSubscriptionFeature.plan_id == BusinessSubscription.plan_id,
                    BusinessSubscriptionFeature.feature_key == feature_key,
                )
            )
        ).scalar()

    @classmethod
    def is_business(cls, user) -> bool:
        """Whether `user` currently counts as a business account."""
        if user is None or not getattr(user, "is_business", False):
            return False
        return cls.has_feature(user.id, FEATURE_BUSINESS_ACCOUNT)

    @classmethod
    def business_user_filter(cls, user_model):
        """A SQL criterion selecting users that count as business accounts,
        for list queries that cannot call is_business row by row."""
        criterion = user_model.is_business.is_(True)
        if not cls.subscriptions_enabled():
            return criterion
        return and_(
            criterion,
            exists().where(
                and_(
                    BusinessSubscription.user_id == user_model.id,
                    cls._active_clause(),
                    BusinessSubscriptionFeature.plan_id == BusinessSubscription.plan_id,
                    BusinessSubscriptionFeature.feature_key == FEATURE_BUSINESS_ACCOUNT,
                )
            ),
        )
