"""Builds the business configuration every client reads.

GET /api/v1/business/config returns this, so the web app, the mobile app and
the public site all show or hide business and subscription UI from the same
answer instead of each keeping its own flag.
"""

from main.config import settings

from .constants import BUSINESS_TYPES, INDUSTRIES, UNITS


def business_features() -> dict:
    mode = bool(settings.BUSINESS_MODE_ENABLED)
    return {
        # Everything else is off when business mode itself is off.
        "enabled": mode,
        "registration_enabled": mode and bool(settings.BUSINESS_REGISTRATION_ENABLED),
        "discovery_enabled": mode and bool(settings.BUSINESS_DISCOVERY_ENABLED),
        "procurement_enabled": mode and bool(settings.BUSINESS_PROCUREMENT_ENABLED),
        "subscriptions_enabled": mode and bool(settings.BUSINESS_SUBSCRIPTIONS_ENABLED),
        "verification_enabled": mode and bool(settings.BUSINESS_VERIFICATION_ENABLED),
    }


def business_config() -> dict:
    return {
        "features": business_features(),
        "business_types": BUSINESS_TYPES,
        "industries": INDUSTRIES,
        "units": UNITS,
    }
