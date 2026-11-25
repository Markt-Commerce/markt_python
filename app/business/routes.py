# package imports
from flask import current_app, redirect, request
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.libs.decorators import seller_required
from app.libs.errors import APIError

# app imports
from .features import business_config
from .images import remove_business_image, upload_business_image
from .subscription_checkout import start_checkout, verify_subscription
from .services import (
    BusinessListingService,
    BusinessService,
    BusinessSubscriptionService,
)
from .schemas import (
    BusinessConfigSchema,
    BusinessDiscoverArgs,
    BusinessListingPageSchema,
    BusinessListingSchema,
    BusinessListingSearchArgs,
    BusinessListingUpsertSchema,
    BusinessProfilePageSchema,
    BusinessPublicProfileSchema,
    BusinessProfileUpsertSchema,
    MyBusinessSchema,
    MySubscriptionSchema,
    SubscriptionCheckoutResultSchema,
    SubscriptionCheckoutSchema,
    SubscriptionPlanSchema,
    SubscriptionVerifyResultSchema,
)

bp = Blueprint(
    "business",
    __name__,
    description="Markt Business: business profiles, B2B listings, subscriptions",
    url_prefix="/business",
)


@bp.route("/config")
class BusinessConfig(MethodView):
    @bp.response(200, BusinessConfigSchema)
    def get(self):
        """Business feature flags and lookup lists. Public: every client
        decides what business and subscription UI to show from this."""
        return business_config()


@bp.route("/me")
class MyBusiness(MethodView):
    @login_required
    @bp.response(200, MyBusinessSchema)
    def get(self):
        """The signed-in user's business tag and profile"""
        try:
            return BusinessService.my_business(current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @bp.arguments(BusinessProfileUpsertSchema)
    @bp.response(200, MyBusinessSchema)
    def put(self, data):
        """Create or update the business profile; sets the is_business tag"""
        try:
            return BusinessService.upsert_profile(current_user.id, data)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @bp.response(200, MyBusinessSchema)
    def delete(self):
        """Turn the business tag off (the profile is kept)"""
        try:
            return BusinessService.disable_business(current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/me/<any(logo, cover):kind>")
class MyBusinessImage(MethodView):
    @login_required
    @bp.response(200, MyBusinessSchema)
    def post(self, kind):
        """Upload the business logo or cover image (multipart field "file")"""
        from io import BytesIO

        from werkzeug.utils import secure_filename

        file = request.files.get("file")
        if not file or not file.filename:
            abort(400, message="No file provided")
        filename = secure_filename(file.filename)
        if not filename:
            abort(400, message="Invalid filename")
        try:
            upload_business_image(current_user.id, kind, BytesIO(file.read()), filename)
            return BusinessService.my_business(current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @bp.response(200, MyBusinessSchema)
    def delete(self, kind):
        """Remove the business logo or cover image"""
        try:
            remove_business_image(current_user.id, kind)
            return BusinessService.my_business(current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/me/verification")
class MyBusinessVerification(MethodView):
    @login_required
    @bp.response(200, MyBusinessSchema)
    def post(self):
        """Ask the Markt team to verify your business (moves it to pending)"""
        try:
            return BusinessService.request_verification(current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/discover")
class BusinessDiscover(MethodView):
    @bp.arguments(BusinessDiscoverArgs, location="query")
    @bp.response(200, BusinessProfilePageSchema)
    def get(self, args):
        """Find business buyers and sellers"""
        try:
            return BusinessService.discover(args)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/listings")
class BusinessListings(MethodView):
    @bp.arguments(BusinessListingSearchArgs, location="query")
    @bp.response(200, BusinessListingPageSchema)
    def get(self, args):
        """Search products offered with B2B terms"""
        try:
            return BusinessListingService.search(args)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/listings/<product_id>")
class BusinessListingDetail(MethodView):
    @bp.response(200, BusinessListingSchema)
    def get(self, product_id):
        """B2B terms for one product"""
        try:
            return BusinessListingService.get_listing(product_id)
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @seller_required
    @bp.arguments(BusinessListingUpsertSchema)
    @bp.response(200, BusinessListingSchema)
    def put(self, data, product_id):
        """Add or update B2B terms on one of your products"""
        try:
            return BusinessListingService.upsert_listing(
                current_user.id, product_id, data
            )
        except APIError as e:
            abort(e.status_code, message=e.message)

    @login_required
    @seller_required
    @bp.response(204)
    def delete(self, product_id):
        """Remove B2B terms from one of your products"""
        try:
            BusinessListingService.remove_listing(current_user.id, product_id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/subscriptions/plans")
class SubscriptionPlans(MethodView):
    @bp.response(200, SubscriptionPlanSchema(many=True))
    def get(self):
        """Available plans (404 while subscriptions are disabled)"""
        try:
            return BusinessSubscriptionService.list_plans()
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/subscriptions/me")
class MySubscription(MethodView):
    @login_required
    @bp.response(200, MySubscriptionSchema)
    def get(self):
        """Your current subscription (404 while disabled or when you have none)"""
        try:
            subscription = BusinessSubscriptionService.current_subscription(
                current_user.id
            )
        except APIError as e:
            abort(e.status_code, message=e.message)
        if subscription is None:
            abort(404, message="No active subscription")
        return subscription


@bp.route("/subscriptions/checkout")
class SubscriptionCheckout(MethodView):
    @login_required
    @bp.arguments(SubscriptionCheckoutSchema)
    @bp.response(200, SubscriptionCheckoutResultSchema)
    def post(self, data):
        """Start paying for a plan; open authorization_url to pay (404 while
        subscriptions are disabled)"""
        try:
            return start_checkout(current_user.id, data["plan_id"], data["platform"])
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/subscriptions/<int:subscription_id>/verify")
class SubscriptionVerify(MethodView):
    @login_required
    @bp.response(200, SubscriptionVerifyResultSchema)
    def post(self, subscription_id):
        """Confirm a plan payment with Paystack and activate it if it landed"""
        try:
            return verify_subscription(subscription_id, current_user.id)
        except APIError as e:
            abort(e.status_code, message=e.message)


@bp.route("/subscriptions/callback/<int:subscription_id>")
class SubscriptionCallback(MethodView):
    def get(self, subscription_id):
        """Paystack's browser redirect after paying for a plan: verify, then
        send the person back to the app's subscription screen."""
        from urllib.parse import urlencode

        from main.config import settings

        platform = request.args.get("platform", "web")

        def back(payment: str):
            query = urlencode({"payment": payment, "subscription_id": subscription_id})
            if platform == "mobile":
                return redirect(
                    f"{settings.MOBILE_APP_SCHEME}business/subscription?{query}"
                )
            return redirect(
                f"{settings.WEB_APP_BASE_URL}/business/subscription?{query}"
            )

        try:
            result = verify_subscription(subscription_id)
        except Exception:
            # A gateway hiccup is not a failed payment; the webhook may still
            # settle it, and the screen re-checks on load.
            current_app.logger.exception(
                "Subscription callback verify failed for %s", subscription_id
            )
            return back("pending")
        if result.get("verified"):
            return back("success")
        return back("failed" if result.get("status") == "EXPIRED" else "pending")


# Last, so the fixed paths above win over this catch-all.
@bp.route("/<user_id>")
class BusinessProfileDetail(MethodView):
    @bp.response(200, BusinessPublicProfileSchema)
    def get(self, user_id):
        """A business's public profile"""
        try:
            return BusinessService.get_public_profile(user_id)
        except APIError as e:
            abort(e.status_code, message=e.message)
