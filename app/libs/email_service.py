import logging
import html
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

    def send_notification_email(
        self,
        email: str,
        title: str,
        message: str,
        notification_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        transactional: bool = True,
        sender_profile: Optional[str] = None,
    ) -> bool:
        """Send the common branded email for notification events.

        Keeping this as a single resilient template means every new in-app
        event can also have a useful email without another fragile method map.
        Values are escaped because notification metadata can contain user text.
        """
        safe_title = html.escape(str(title or "Markt notification"))
        safe_message = html.escape(str(message or ""))
        metadata = metadata or {}
        order_id = metadata.get("order_id") or metadata.get("order_number")
        reference = (
            f'<p style="color:#6b7280;font-size:13px">Reference: '
            f"{html.escape(str(order_id))}</p>"
            if order_id
            else ""
        )
        unsubscribe = ""
        if not transactional and settings.EMAIL_UNSUBSCRIBE_URL:
            unsubscribe = (
                f'<a href="{html.escape(settings.EMAIL_UNSUBSCRIBE_URL, quote=True)}" '
                'style="color:#B8371B">Manage preferences</a>'
            )
        html_content = f"""<!doctype html><html><body style="margin:0;background:#f6f7f9;font-family:Arial,sans-serif;color:#222">
        <div style="max-width:600px;margin:32px auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #ececec">
          <div style="background:#E94C2A;padding:24px 32px;color:#fff;font-size:28px;font-weight:700">Markt</div>
          <div style="padding:32px"><div style="font-size:12px;color:#B8371B;text-transform:uppercase;letter-spacing:1px;font-weight:700">{html.escape(str(notification_type).replace('_',' '))}</div>
          <h1 style="font-size:24px;margin:10px 0 16px">{safe_title}</h1>
          <p style="font-size:16px;line-height:1.6;white-space:pre-line">{safe_message}</p>{reference}
          <p style="margin-top:32px;color:#6b7280;font-size:14px">Open the Markt app to view more details and take action.</p></div>
          <div style="padding:20px 32px;background:#fafafa;color:#6b7280;font-size:12px">You’re receiving this because it relates to your Markt account. {unsubscribe}</div>
        </div></body></html>"""
        text_content = f"{title}\n\n{message}\n\nOpen the Markt app for details."
        profile = sender_profile or ("transactional" if transactional else "marketing")
        if profile == "notification":
            from_email, from_name = (
                settings.RESEND_NOTIFICATION_FROM_EMAIL,
                settings.RESEND_NOTIFICATION_FROM_NAME,
            )
        elif profile == "marketing":
            from_email, from_name = (
                settings.RESEND_MARKETING_FROM_EMAIL,
                settings.RESEND_MARKETING_FROM_NAME,
            )
        else:
            from_email, from_name = (
                settings.RESEND_TRANSACTIONAL_FROM_EMAIL,
                settings.RESEND_TRANSACTIONAL_FROM_NAME,
            )
        return self.send_email(
            to_email=email,
            subject=f"{safe_title} · Markt",
            html_content=html_content,
            text_content=text_content,
            from_email=from_email,
            from_name=from_name,
            reply_to=settings.EMAIL_REPLY_TO or None,
        )

    def send_promotional_campaign_email(
        self, email: str, campaign: Dict[str, Any]
    ) -> bool:
        """Send a commerce campaign email with a hero, categories and products."""
        headline = html.escape(str(campaign.get("headline", "Big deals, made for you")))
        subheadline = html.escape(
            str(campaign.get("subheadline", "Discover something good today."))
        )
        cta = html.escape(str(campaign.get("cta_label", "Shop now")))
        cta_url = html.escape(
            str(campaign.get("cta_url", settings.WEB_APP_BASE_URL)), quote=True
        )
        hero_url = campaign.get("hero_url")
        hero = (
            f'<img src="{html.escape(str(hero_url), quote=True)}" alt="{headline}" '
            'style="display:block;width:100%;max-height:280px;object-fit:cover;border-radius:12px">'
            if hero_url
            else '<div style="background:#FFF1E9;border-radius:12px;padding:36px 24px;text-align:center">'
            '<div style="font-size:12px;letter-spacing:2px;color:#B8371B;font-weight:700">MARKT PICKS</div>'
            f'<div style="font-size:32px;line-height:1.1;font-weight:800;margin-top:10px;color:#231F20">{headline}</div>'
            f'<div style="font-size:16px;margin-top:12px;color:#5f6368">{subheadline}</div></div>'
        )
        products = ""
        for product in campaign.get("products", [])[:4]:
            name = html.escape(str(product.get("name", "Product")))
            price = html.escape(str(product.get("price", "")))
            image = product.get("image_url")
            image_html = (
                f'<img src="{html.escape(str(image), quote=True)}" alt="{name}" '
                'style="width:100%;height:130px;object-fit:contain">'
                if image
                else ""
            )
            products += f'<td style="width:50%;padding:8px;vertical-align:top"><div style="border:1px solid #eee;border-radius:10px;padding:10px">{image_html}<div style="font-weight:700;font-size:14px">{name}</div><div style="color:#B8371B;font-size:16px;margin-top:6px">{price}</div></div></td>'
        products_html = (
            f'<table role="presentation" style="width:100%;border-collapse:collapse"><tr>{products}</tr></table>'
            if products
            else ""
        )
        html_content = f"""<!doctype html><html><body style="margin:0;background:#f6f7f9;font-family:Arial,sans-serif;color:#231F20"><div style="max-width:620px;margin:24px auto;background:#fff;border:1px solid #eee;border-radius:16px;overflow:hidden"><div style="padding:22px 28px;font-size:28px;font-weight:800">Markt<span style="color:#E94C2A">●</span></div><div style="padding:0 24px 28px">{hero}<div style="text-align:center;margin:24px 0"><a href="{cta_url}" style="display:inline-block;background:#E94C2A;color:#fff;text-decoration:none;font-weight:700;padding:14px 28px;border-radius:8px">{cta}</a></div>{products_html}</div><div style="padding:18px 28px;background:#fafafa;color:#6b7280;font-size:12px;text-align:center">You’re receiving Markt offers because you opted in to deals and recommendations. <a href="{html.escape(settings.EMAIL_UNSUBSCRIBE_URL, quote=True)}" style="color:#B8371B">Manage preferences</a></div></div></body></html>"""
        return self.send_email(
            email,
            str(campaign.get("subject", headline)),
            html_content,
            text_content=f"{headline}\n\n{subheadline}\n\n{cta_url}",
            from_email=settings.RESEND_MARKETING_FROM_EMAIL,
            from_name=settings.RESEND_MARKETING_FROM_NAME,
            reply_to=settings.EMAIL_REPLY_TO or None,
        )

    def send_order_tracking_email(self, email: str, order_data: Dict[str, Any]) -> bool:
        """Send a visual order-progress email, including pickup/delivery details."""
        order_number = html.escape(str(order_data.get("order_number", "")))
        status = str(order_data.get("status", "processing")).replace("_", " ").title()
        steps = order_data.get("tracking_steps") or [
            "Order placed",
            "Confirmed",
            "Shipped",
            "Out for delivery",
            "Delivered",
        ]
        current = int(order_data.get("current_step", 1))
        step_html = ""
        for index, step in enumerate(steps):
            active = index <= current
            color = "#E94C2A" if active else "#D9DDE2"
            step_html += f'<td style="width:{100 // len(steps)}%;text-align:center;color:{color};font-size:11px;font-weight:700"><div style="margin:auto;width:24px;height:24px;border-radius:50%;background:{color};color:#fff;line-height:24px">{"✓" if active else index + 1}</div><div style="margin-top:7px">{html.escape(str(step))}</div></td>'
        details = html.escape(
            str(
                order_data.get(
                    "delivery_note", "We’ll keep you updated as your order moves."
                )
            )
        )
        html_content = f"""<!doctype html><html><body style="margin:0;background:#f6f7f9;font-family:Arial,sans-serif;color:#231F20"><div style="max-width:620px;margin:24px auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #eee"><div style="background:#E94C2A;padding:24px 30px;color:#fff;font-size:28px;font-weight:800">Markt</div><div style="padding:30px"><div style="color:#B8371B;font-size:12px;font-weight:700;letter-spacing:1px">ORDER {order_number}</div><h1 style="font-size:26px;margin:10px 0">Your order is {html.escape(status.lower())}</h1><p style="color:#5f6368;line-height:1.6">{details}</p><table role="presentation" style="width:100%;margin:32px 0;border-collapse:collapse"><tr>{step_html}</tr></table><div style="background:#FFF1E9;border-radius:10px;padding:18px"><strong>Order number</strong><br>{order_number}</div><p style="font-size:13px;color:#6b7280;margin-top:30px">Open the Markt app to view full tracking details, contact support, or update your delivery information.</p></div><div style="padding:18px 30px;background:#fafafa;color:#6b7280;font-size:12px">This is a transactional update about your Markt order.</div></div></body></html>"""
        return self.send_email(
            email,
            f"Order {order_number} · {status} · Markt",
            html_content,
            text_content=f"Order {order_number} is {status}. {details}",
            from_email=settings.RESEND_TRANSACTIONAL_FROM_EMAIL,
            from_name=settings.RESEND_TRANSACTIONAL_FROM_NAME,
            reply_to=settings.EMAIL_REPLY_TO or None,
        )

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
