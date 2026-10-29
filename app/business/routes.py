# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask_login import login_required, current_user

# project imports
from app.libs.decorators import seller_required
from app.libs.errors import APIError

# app imports
from .features import business_config
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
    SubscriptionPlanSchema,
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
