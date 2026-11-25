"""Payment notifications carry JSON-serializable metadata.

Notification metadata is stored as JSON. The buyer's PAYMENT_SUCCESS put the
PaymentMethod enum member in it, so creating it raised for every payment --
and, raised first, it also stopped the seller's ORDER_PLACED from being sent.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

from app.payments.models import PaymentMethod, PaymentStatus
from app.payments.services import PaymentService


def test_success_notifications_are_json_serializable():
    product = SimpleNamespace(
        name="Shea butter", seller=SimpleNamespace(user_id="USR_S")
    )
    order = SimpleNamespace(
        order_number="ORD-1",
        total=6500.0,
        buyer=SimpleNamespace(user=SimpleNamespace(id="USR_B", username="temi")),
        items=[SimpleNamespace(product=product, quantity=1, price=6500.0)],
    )
    payment = SimpleNamespace(
        id="PAY_1",
        order=order,
        order_id="ORD_1",
        amount=6962.5,
        currency="NGN",
        transaction_id="WALLET_PAY_1",
        method=PaymentMethod.WALLET,
    )
    sent = []
    with patch(
        "app.notifications.services.NotificationService.create_notification",
        side_effect=lambda **kw: sent.append(kw),
    ):
        PaymentService._send_payment_notifications(payment, PaymentStatus.COMPLETED)

    assert [n["user_id"] for n in sent] == ["USR_B", "USR_S"]
    for n in sent:
        json.dumps(n["metadata_"])  # raises if anything is not serializable
    assert sent[0]["metadata_"]["method"] == "wallet"
