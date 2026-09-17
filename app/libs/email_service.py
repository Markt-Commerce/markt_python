import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import resend

from app.libs import email_layout as L
from main.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Email service using Resend API"""

    def __init__(self):
        self.api_key = settings.RESEND_API_KEY
        self.from_email = settings.RESEND_FROM_EMAIL
        self.from_name = settings.RESEND_FROM_NAME

        if self.api_key:
            resend.api_key = self.api_key
        else:
            logger.warning(
                "Resend API key not configured - email features will not work"
            )

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict]] = None,
    ) -> bool:
        """Send an email using Resend"""
        try:
            if not self.api_key:
                logger.error("Resend API key not configured")
                return False

            params = {
                "from": f"{from_name or self.from_name} <{from_email or self.from_email}>",
                "to": [to_email],
                "subject": subject,
                "html": html_content,
            }

            if text_content:
                params["text"] = text_content

            if reply_to:
                params["reply_to"] = reply_to

            if attachments:
                params["attachments"] = attachments

            response = resend.Emails.send(params)
            logger.info(f"Email sent successfully to {to_email}: {response.get('id')}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False

    def send_verification_email(
        self, email: str, verification_code: str, username: str
    ) -> bool:
        """Send email verification code"""
        subject = "Verify your Markt account"

        html_content = self._get_verification_email_template(
            username=username, verification_code=verification_code
        )

        text_content = f"""
        Hi {username},

        Welcome to Markt! Please verify your email address by entering this code:

        {verification_code}

        This code will expire in 10 minutes.

        If you didn't create an account, please ignore this email.

        Best regards,
        The Markt Team
        """

        return self.send_email(
            to_email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
        )

    def send_otp_email(self, email: str, otp_code: str) -> bool:
        """Send OTP code for delivery partner login"""
        subject = "Your OTP Code for Markt Delivery Login"

        html_content = f"""
        <p>Hi,</p>
        <p>Your OTP code for logging into the Markt Delivery Partner app is:</p>
        <h2>{otp_code}</h2>
        <p>This code is valid for 10 minutes.</p>
        <p>If you didn't request this, please ignore this email.</p>
        <p>Best regards,<br>The Markt Team</p>
        """

        text_content = f"""
        Hi,

        Your OTP code for logging into the Markt Delivery Partner app is:

        {otp_code}

        This code is valid for 10 minutes.

        If you didn't request this, please ignore this email.

        Best regards,
        The Markt Team
        """

        return self.send_email(
            to_email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
        )

    def send_password_reset_email(
        self, email: str, reset_code: str, username: str
    ) -> bool:
        """Send password reset code"""
        subject = "Reset your Markt password"

        html_content = self._get_password_reset_template(
            username=username, reset_code=reset_code
        )

        text_content = f"""
        Hi {username},

        You requested to reset your password. Please use this code:

        {reset_code}

        This code will expire in 10 minutes.

        If you didn't request this, please ignore this email.

        Best regards,
        The Markt Team
        """

        return self.send_email(
            to_email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
        )

    def send_order_confirmation_email(
        self, email: str, order_data: Dict[str, Any]
    ) -> bool:
        """Send order confirmation email"""
        subject = f"Order Confirmation - {order_data.get('order_number', '')}"

        html_content = self._get_order_confirmation_template(order_data)

        return self.send_email(
            to_email=email, subject=subject, html_content=html_content
        )

    def send_order_status_update_email(
        self, email: str, order_data: Dict[str, Any]
    ) -> bool:
        """Send order status update email"""
        subject = f"Order Update - {order_data.get('order_number', '')}"

        html_content = self._get_order_status_update_template(order_data)

        return self.send_email(
            to_email=email, subject=subject, html_content=html_content
        )

    def send_seller_order_notification_email(
        self, email: str, order_data: Dict[str, Any]
    ) -> bool:
        """Send notification to seller about new order"""
        subject = f"New Order Received - {order_data.get('order_number', '')}"

        html_content = self._get_seller_order_notification_template(order_data)

        return self.send_email(
            to_email=email, subject=subject, html_content=html_content
        )

    def send_payment_success_email(
        self, email: str, payment_data: Dict[str, Any]
    ) -> bool:
        """Send payment success email"""
        subject = f"Payment Successful - {payment_data.get('order_number', '')}"

        html_content = self._get_payment_success_template(payment_data)

        return self.send_email(
            to_email=email, subject=subject, html_content=html_content
        )

    def send_payment_failed_email(
        self, email: str, payment_data: Dict[str, Any]
    ) -> bool:
        """Send payment failed email"""
        subject = f"Payment Failed - {payment_data.get('order_number', '')}"

        html_content = self._get_payment_failed_template(payment_data)

        return self.send_email(
            to_email=email, subject=subject, html_content=html_content
        )

    def send_seller_analytics_report(
        self, email: str, report_data: Dict[str, Any]
    ) -> bool:
        """Send monthly/quarterly analytics report to seller"""
        subject = f"Your Markt Analytics Report - {report_data.get('period', '')}"

        html_content = self._get_seller_analytics_report_template(report_data)

        return self.send_email(
            to_email=email, subject=subject, html_content=html_content
        )

    def _get_verification_email_template(
        self, username: str, verification_code: str
    ) -> str:
        """Get email verification template"""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Verify your Markt account</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ color: #E94C2A; font-size: 32px; font-weight: bold; }}
                .code-box {{
                    background: #f8f9fa;
                    border: 2px solid #E94C2A;
                    border-radius: 8px;
                    padding: 20px;
                    text-align: center;
                    margin: 20px 0;
                    font-size: 24px;
                    font-weight: bold;
                    letter-spacing: 4px;
                }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
                .button {{
                    background: #E94C2A;
                    color: white;
                    padding: 12px 24px;
                    text-decoration: none;
                    border-radius: 6px;
                    display: inline-block;
                    margin: 20px 0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">Markt</div>
                </div>

                <h2>Welcome to Markt, {username}!</h2>

                <p>Thank you for creating your account. To complete your registration, please verify your email address by entering the code below:</p>

                <div class="code-box">
                    {verification_code}
                </div>

                <p><strong>This code will expire in 10 minutes.</strong></p>

                <p>If you didn't create an account with Markt, please ignore this email.</p>

                <div class="footer">
                    <p>Best regards,<br>The Markt Team</p>
                    <p>© 2025 Markt. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

    def _get_password_reset_template(self, username: str, reset_code: str) -> str:
        """Get password reset template"""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Reset your Markt password</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ color: #E94C2A; font-size: 32px; font-weight: bold; }}
                .code-box {{
                    background: #f8f9fa;
                    border: 2px solid #E94C2A;
                    border-radius: 8px;
                    padding: 20px;
                    text-align: center;
                    margin: 20px 0;
                    font-size: 24px;
                    font-weight: bold;
                    letter-spacing: 4px;
                }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">Markt</div>
                </div>

                <h2>Password Reset Request</h2>

                <p>Hi {username},</p>

                <p>We received a request to reset your password. Please use the code below to reset your password:</p>

                <div class="code-box">
                    {reset_code}
                </div>

                <p><strong>This code will expire in 10 minutes.</strong></p>

                <p>If you didn't request a password reset, please ignore this email and your password will remain unchanged.</p>

                <div class="footer">
                    <p>Best regards,<br>The Markt Team</p>
                    <p>© 2025 Markt. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

    # The buyer-facing ladder an order climbs. Deliberately four steps and
    # not the seven OrderStatus values: "ready_for_delivery" and "shipped"
    # are warehouse words, and a buyer only wants to know whether it is
    # packed, moving, or here.
    ORDER_STEPS = ["Confirmed", "Packed", "On the way", "Delivered"]

    _STEP_FOR_STATUS = {
        "pending_payment": 0,
        "pending": 0,
        "processing": 0,
        "ready_for_delivery": 1,
        "shipped": 2,
        "delivered": 3,
    }

    # What the status means for the person who bought the thing, in the second
    # person. The old email said "Order #X is now Ready For Delivery", which
    # is the database's words shown to a customer.
    _STATUS_COPY = {
        "processing": ("Your order is confirmed", "The seller is getting it ready."),
        "ready_for_delivery": (
            "Your order is packed",
            "It is waiting for a rider to collect it.",
        ),
        "shipped": (
            "Your order is on the way",
            "A rider has picked it up and is heading to you.",
        ),
        "delivered": ("Your order arrived", "Thanks for shopping on Markt."),
        "cancelled": (
            "Your order was cancelled",
            "Any payment you made is being refunded.",
        ),
        "returned": ("Your return is confirmed", "Your refund is on its way."),
        "failed": (
            "Your order could not be completed",
            "You have not been charged. Please try again.",
        ),
    }

    def _get_order_confirmation_template(self, order_data: Dict[str, Any]) -> str:
        """Order confirmation: what was bought, what it cost, what happens next."""
        order_number = order_data.get("order_number", "")
        total = order_data.get("total", 0) or 0
        items = order_data.get("items", []) or []
        buyer_name = order_data.get("buyer_name", "")
        address = order_data.get("delivery_address", "")
        order_url = order_data.get("order_url", "")

        rows = [
            [
                str(item.get("product_name", "")),
                str(item.get("quantity", 0)),
                f"\u20a6{float(item.get('price', 0) or 0):,.2f}",
            ]
            for item in items
        ]

        greeting = f"Thanks{', ' + buyer_name if buyer_name else ''} \u2014 "
        body = (
            L.header("Order confirmed", "We have your order")
            + L.progress(self.ORDER_STEPS, 0)
            + L.note(
                greeting + "the seller is getting your order ready. "
                "We will email you when it is packed and again when a rider "
                "picks it up."
            )
            + L.detail_rows(
                [
                    ["Order", f"#{order_number}"],
                    ["Placed", datetime.now().strftime("%d %B %Y")],
                    ["Delivering to", address],
                    ["Total", f"\u20a6{float(total):,.2f}"],
                ]
            )
            + L.table_block(["Item", "Qty", "Price"], rows, title="What you ordered")
            + (L.button("Track this order", order_url) if order_url else "")
        )

        return L.shell(
            title=f"Order #{order_number} confirmed",
            preheader=(
                f"\u20a6{float(total):,.2f} \u2014 we will let you know "
                "when it is on the way."
            ),
            body=body,
            footer_note="You are receiving this because you placed an order on Markt.",
        )

    def _get_order_status_update_template(self, order_data: Dict[str, Any]) -> str:
        """Where the order has got to, with the ladder drawn in."""
        order_number = order_data.get("order_number", "")
        status = str(order_data.get("status", "") or "").lower()
        order_url = order_data.get("order_url", "")
        eta = order_data.get("eta", "")
        rider_name = order_data.get("rider_name", "")

        headline, explain = self._STATUS_COPY.get(
            status,
            ("Your order was updated", f"It is now {status.replace('_', ' ')}."),
        )

        # A cancelled or failed order has left the ladder; drawing a tracker
        # for it would imply it is still coming.
        step = self._STEP_FOR_STATUS.get(status)
        tracker = L.progress(self.ORDER_STEPS, step) if step is not None else ""

        body = (
            L.header(f"Order #{order_number}", headline)
            + tracker
            + L.note(explain)
            + L.detail_rows(
                [
                    ["Order", f"#{order_number}"],
                    ["Expected", eta],
                    ["Your rider", rider_name],
                ]
            )
            + (L.button("See your order", order_url) if order_url else "")
        )

        return L.shell(
            title=headline,
            preheader=f"{headline} \u2014 order #{order_number}.",
            body=body,
            footer_note="You are receiving this because you placed an order on Markt.",
        )

    def _get_seller_order_notification_template(
        self, order_data: Dict[str, Any]
    ) -> str:
        """Tell a seller they sold something, and what to do about it."""
        order_number = order_data.get("order_number", "")
        total = float(order_data.get("total", 0) or 0)
        items = order_data.get("items", []) or []
        buyer_name = order_data.get("buyer_name", "")
        dashboard_url = order_data.get("dashboard_url", "")

        rows = [
            [
                str(item.get("product_name", "")),
                str(item.get("quantity", 0)),
                f"\u20a6{float(item.get('price', 0) or 0):,.2f}",
            ]
            for item in items
        ]

        body = (
            L.header("New order", f"You sold \u20a6{total:,.2f}")
            + L.note(
                "Mark it as packed once it is ready and a rider will be sent "
                "to collect it. The sooner you do, the sooner you are paid."
            )
            + L.detail_rows(
                [
                    ["Order", f"#{order_number}"],
                    ["Buyer", buyer_name],
                    ["Total", f"\u20a6{total:,.2f}"],
                ]
            )
            + L.table_block(["Item", "Qty", "Price"], rows, title="What to pack")
            + (L.button("Open this order", dashboard_url) if dashboard_url else "")
        )

        return L.shell(
            title=f"New order #{order_number}",
            preheader=f"\u20a6{total:,.2f} \u2014 pack it to get a rider sent.",
            body=body,
            footer_note="You are receiving this because you sell on Markt.",
        )

    def _get_payment_success_template(self, payment_data: Dict[str, Any]) -> str:
        """Payment receipt."""
        order_number = payment_data.get("order_number", "")
        amount = float(payment_data.get("amount", 0) or 0)
        reference = payment_data.get("reference", "")
        method = payment_data.get("method", "")
        order_url = payment_data.get("order_url", "")

        body = (
            L.header("Payment received", f"\u20a6{amount:,.2f} paid")
            + L.detail_rows(
                [
                    ["Order", f"#{order_number}" if order_number else ""],
                    ["Paid", datetime.now().strftime("%d %B %Y")],
                    ["Method", str(method).replace("_", " ").title() if method else ""],
                    ["Reference", reference],
                ]
            )
            + L.note(
                "Your order is with the seller now. We will email you when it "
                "is packed and when it is on the way."
            )
            + (L.button("Track this order", order_url) if order_url else "")
        )

        return L.shell(
            title="Payment received",
            preheader=f"\u20a6{amount:,.2f} paid for order #{order_number}.",
            body=body,
            footer_note="Keep this email as your receipt.",
        )

    def _get_payment_failed_template(self, payment_data: Dict[str, Any]) -> str:
        """Payment failed -- say plainly that no money moved."""
        order_number = payment_data.get("order_number", "")
        amount = float(payment_data.get("amount", 0) or 0)
        reason = payment_data.get("reason", "")
        retry_url = payment_data.get("retry_url", "")

        body = (
            L.header("Payment failed", "We could not take that payment")
            + L.note(
                "You have not been charged. Your order is held for you \u2014 "
                "trying again, or using a different card, is usually all it takes."
            )
            + L.detail_rows(
                [
                    ["Order", f"#{order_number}" if order_number else ""],
                    ["Amount", f"\u20a6{amount:,.2f}"],
                    ["Reason", str(reason) if reason else ""],
                ]
            )
            + (L.button("Try payment again", retry_url) if retry_url else "")
        )

        return L.shell(
            title="Payment failed",
            preheader=f"No charge was made \u2014 order #{order_number} is still held.",
            body=body,
            footer_note="If you were charged, reply to this email and we will look into it.",
        )

    def _get_seller_analytics_report_template(self, report_data: Dict[str, Any]) -> str:
        """The seller's period report.

        Rewritten because the old one laid its figures out with `display:
        grid`, which Gmail and Outlook do not support -- so the two-column
        panel readers were meant to see collapsed into a stack of unstyled
        divs, and the `<style>` block carrying the rest of it was stripped on
        the way in.

        The shape follows what a report like this is for: one number the
        seller actually cares about, the supporting ones underneath with
        something to compare each against, what sold, and a way back into the
        shop. Comparisons appear only when the caller supplies the previous
        period -- an invented delta would be worse than none.
        """
        period = report_data.get("period", "")
        shop_name = report_data.get("shop_name") or "your shop"
        total_sales = float(report_data.get("total_sales", 0) or 0)
        total_orders = int(report_data.get("total_orders", 0) or 0)
        total_products = int(report_data.get("total_products", 0) or 0)
        top_products = report_data.get("top_products") or []
        dashboard_url = report_data.get("dashboard_url", "https://marktcommerce.com")

        previous = report_data.get("previous") or {}
        noun = "quarter" if period.strip().upper().startswith("Q") else "month"

        body = L.header(period, f"How {shop_name} did")

        if total_orders == 0:
            # A report of nothing is the one most likely to read as a mistake,
            # so it says plainly that nothing is broken and what usually helps.
            body += L.lead_stat("No sales yet", period)
            body += L.note(
                f"Nothing sold this {noun}. That is usually a listing without "
                "a photo or a price that has drifted -- both take a minute to "
                "fix from your dashboard."
            )
            body += L.button("Open your shop", dashboard_url)
            return L.shell(
                f"Your Markt report - {period}",
                f"No sales this {noun} - here is what usually helps.",
                body,
            )

        body += L.lead_stat(
            f"\u20a6{total_sales:,.2f}",
            f"You earned in {period}",
            L.change_line(
                total_sales, previous.get("total_sales"), noun, prefix="\u20a6"
            ),
        )
        body += L.stat_row(
            "Orders",
            f"{total_orders:,}",
            L.change_line(total_orders, previous.get("total_orders"), noun),
        )
        body += L.stat_row(
            "Average order",
            f"\u20a6{(total_sales / total_orders):,.2f}",
            f"Across every order this {noun}.",
        )
        body += L.stat_row("Live listings", f"{total_products:,}")

        rows = [
            [
                p.get("name", ""),
                f"{p.get('sales', 0):,}",
                f"\u20a6{float(p.get('revenue', 0) or 0):,.2f}",
            ]
            for p in top_products[:5]
        ]
        body += L.table_block(["Product", "Sold", "Revenue"], rows, "What sold most")
        body += L.button("Open your dashboard", dashboard_url)

        return L.shell(
            f"Your Markt report - {period}",
            f"\u20a6{total_sales:,.2f} from {total_orders:,} orders in {period}.",
            body,
        )


# Global email service instance
email_service = EmailService()
