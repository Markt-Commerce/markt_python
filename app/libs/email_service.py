import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import resend
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

    def _get_order_confirmation_template(self, order_data: Dict[str, Any]) -> str:
        """Get order confirmation template"""
        order_number = order_data.get("order_number", "")
        total = order_data.get("total", 0)
        items = order_data.get("items", [])

        items_html = ""
        for item in items:
            items_html += f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">{item.get('product_name', '')}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">{item.get('quantity', 0)}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">₦{item.get('price', 0):,.2f}</td>
            </tr>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Order Confirmation</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ color: #E94C2A; font-size: 32px; font-weight: bold; }}
                .order-details {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .items-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                .items-table th {{ background: #E94C2A; color: white; padding: 10px; text-align: left; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">Markt</div>
                </div>

                <h2>Order Confirmation</h2>

                <p>Thank you for your order! We've received your order and it's being processed.</p>

                <div class="order-details">
                    <h3>Order Details</h3>
                    <p><strong>Order Number:</strong> {order_number}</p>
                    <p><strong>Order Date:</strong> {datetime.now().strftime('%B %d, %Y')}</p>
                    <p><strong>Total Amount:</strong> ₦{total:,.2f}</p>
                </div>

                <h3>Order Items</h3>
                <table class="items-table">
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Quantity</th>
                            <th>Price</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items_html}
                    </tbody>
                </table>

                <p>We'll send you updates as your order progresses.</p>

                <div class="footer">
                    <p>Best regards,<br>The Markt Team</p>
                    <p>© 2025 Markt. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

    def _get_order_status_update_template(self, order_data: Dict[str, Any]) -> str:
        """Get order status update template"""
        order_number = order_data.get("order_number", "")
        status = order_data.get("status", "")
        status_display = status.replace("_", " ").title()

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Order Status Update</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ color: #E94C2A; font-size: 32px; font-weight: bold; }}
                .status-box {{
                    background: #E94C2A;
                    color: white;
                    padding: 15px;
                    border-radius: 8px;
                    text-align: center;
                    margin: 20px 0;
                    font-size: 18px;
                    font-weight: bold;
                }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">Markt</div>
                </div>

                <h2>Order Status Update</h2>

                <p>Your order status has been updated!</p>

                <div class="status-box">
                    Order #{order_number} is now {status_display}
                </div>

                <p>We'll continue to keep you updated on your order progress.</p>

                <div class="footer">
                    <p>Best regards,<br>The Markt Team</p>
                    <p>© 2025 Markt. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

    def _get_seller_order_notification_template(
        self, order_data: Dict[str, Any]
    ) -> str:
        """Get seller order notification template"""
        order_number = order_data.get("order_number", "")
        total = order_data.get("total", 0)
        items = order_data.get("items", [])

        items_html = ""
        for item in items:
            items_html += f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">{item.get('product_name', '')}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">{item.get('quantity', 0)}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">₦{item.get('price', 0):,.2f}</td>
            </tr>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>New Order Received</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ color: #E94C2A; font-size: 32px; font-weight: bold; }}
                .order-details {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .items-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                .items-table th {{ background: #E94C2A; color: white; padding: 10px; text-align: left; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">Markt</div>
                </div>

                <h2>New Order Received!</h2>

                <p>Congratulations! You have received a new order.</p>

                <div class="order-details">
                    <h3>Order Details</h3>
                    <p><strong>Order Number:</strong> {order_number}</p>
                    <p><strong>Order Date:</strong> {datetime.now().strftime('%B %d, %Y')}</p>
                    <p><strong>Total Amount:</strong> ₦{total:,.2f}</p>
                </div>

                <h3>Order Items</h3>
                <table class="items-table">
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Quantity</th>
                            <th>Price</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items_html}
                    </tbody>
                </table>

                <p>Please process this order as soon as possible.</p>

                <div class="footer">
                    <p>Best regards,<br>The Markt Team</p>
                    <p>© 2025 Markt. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

    def _get_payment_success_template(self, payment_data: Dict[str, Any]) -> str:
        """Get payment success template"""
        order_number = payment_data.get("order_number", "")
        amount = payment_data.get("amount", 0)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Payment Successful</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ color: #E94C2A; font-size: 32px; font-weight: bold; }}
                .success-box {{
                    background: #d4edda;
                    border: 1px solid #c3e6cb;
                    color: #155724;
                    padding: 15px;
                    border-radius: 8px;
                    text-align: center;
                    margin: 20px 0;
                }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">Markt</div>
                </div>

                <h2>Payment Successful!</h2>

                <div class="success-box">
                    <h3>Payment Confirmed</h3>
                    <p>Your payment of ₦{amount:,.2f} for order #{order_number} has been processed successfully.</p>
                </div>

                <p>Your order is now being processed and you'll receive updates as it progresses.</p>

                <div class="footer">
                    <p>Best regards,<br>The Markt Team</p>
                    <p>© 2025 Markt. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

    def _get_payment_failed_template(self, payment_data: Dict[str, Any]) -> str:
        """Get payment failed template"""
        order_number = payment_data.get("order_number", "")
        amount = payment_data.get("amount", 0)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Payment Failed</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ color: #E94C2A; font-size: 32px; font-weight: bold; }}
                .error-box {{
                    background: #f8d7da;
                    border: 1px solid #f5c6cb;
                    color: #721c24;
                    padding: 15px;
                    border-radius: 8px;
                    text-align: center;
                    margin: 20px 0;
                }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">Markt</div>
                </div>

                <h2>Payment Failed</h2>

                <div class="error-box">
                    <h3>Payment Unsuccessful</h3>
                    <p>We were unable to process your payment of ₦{amount:,.2f} for order #{order_number}.</p>
                </div>

                <p>Please try again or contact our support team if the issue persists.</p>

                <div class="footer">
                    <p>Best regards,<br>The Markt Team</p>
                    <p>© 2025 Markt. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

    def _get_seller_analytics_report_template(self, report_data: Dict[str, Any]) -> str:
        """Get seller analytics report template"""
        period = report_data.get("period", "")
        total_sales = report_data.get("total_sales", 0)
        total_orders = report_data.get("total_orders", 0)
        total_products = report_data.get("total_products", 0)
        top_products = report_data.get("top_products", [])

        top_products_html = ""
        for i, product in enumerate(top_products[:5], 1):
            top_products_html += f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">{i}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">{product.get('name', '')}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">{product.get('sales', 0)}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">₦{product.get('revenue', 0):,.2f}</td>
            </tr>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Your Markt Analytics Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .logo {{ color: #E94C2A; font-size: 32px; font-weight: bold; }}
                .stats-grid {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 20px;
                    margin: 20px 0;
                }}
                .stat-box {{
                    background: #f8f9fa;
                    padding: 20px;
                    border-radius: 8px;
                    text-align: center;
                    border-left: 4px solid #E94C2A;
                }}
                .stat-number {{ font-size: 24px; font-weight: bold; color: #E94C2A; }}
                .items-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                .items-table th {{ background: #E94C2A; color: white; padding: 10px; text-align: left; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">Markt</div>
                </div>

                <h2>Your Analytics Report - {period}</h2>

                <p>Here's a summary of your performance on Markt for {period}:</p>

                <div class="stats-grid">
                    <div class="stat-box">
                        <div class="stat-number">₦{total_sales:,.2f}</div>
                        <div>Total Sales</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-number">{total_orders}</div>
                        <div>Total Orders</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-number">{total_products}</div>
                        <div>Active Products</div>
                    </div>
                </div>

                <h3>Top Performing Products</h3>
                <table class="items-table">
                    <thead>
                        <tr>
                            <th>Rank</th>
                            <th>Product</th>
                            <th>Units Sold</th>
                            <th>Revenue</th>
                        </tr>
                    </thead>
                    <tbody>
                        {top_products_html}
                    </tbody>
                </table>

                <p>Keep up the great work! Continue optimizing your products and customer service to grow your business.</p>

                <div class="footer">
                    <p>Best regards,<br>The Markt Team</p>
                    <p>© 2025 Markt. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """


# Global email service instance
email_service = EmailService()
