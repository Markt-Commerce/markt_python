"""Pytest configuration for Markt backend tests."""

import pytest


def pytest_configure():
    """Eager-import ORM modules so string-based relationships resolve in unit tests."""
    import app.cart.models  # noqa: F401
    import app.chats.models  # noqa: F401
    import app.deliveries.models  # noqa: F401
    import app.media.models  # noqa: F401
    import app.notifications.models  # noqa: F401
    import app.orders.models  # noqa: F401
    import app.payments.models  # noqa: F401
    import app.products.models  # noqa: F401
    import app.requests.models  # noqa: F401
    import app.users.models  # noqa: F401
    import app.wallet.models  # noqa: F401


@pytest.fixture
def sample_shipping_address():
    return {
        "recipient_name": "Ada Lovelace",
        "street_address": "12 Broad Street",
        "city": "Lagos",
        "state": "Lagos",
        "postal_code": "100001",
        "country": "Nigeria",
        "latitude": 6.45,
        "longitude": 3.39,
    }
