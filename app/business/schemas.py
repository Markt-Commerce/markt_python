from marshmallow import Schema, fields, validate, validates, ValidationError

from app.libs.schemas import PaginationSchema

from .constants import BUSINESS_TYPE_KEYS, INDUSTRY_KEYS, UNIT_KEYS
from .models import BusinessSubscriptionStatus, BusinessVerificationStatus


# --- config ---------------------------------------------------------------


class _OptionSchema(Schema):
    key = fields.Str()
    label = fields.Str()


class BusinessFeaturesSchema(Schema):
    enabled = fields.Bool()
    registration_enabled = fields.Bool()
    discovery_enabled = fields.Bool()
    procurement_enabled = fields.Bool()
    subscriptions_enabled = fields.Bool()
    verification_enabled = fields.Bool()


class BusinessConfigSchema(Schema):
    features = fields.Nested(BusinessFeaturesSchema)
    business_types = fields.List(fields.Nested(_OptionSchema))
    industries = fields.List(fields.Nested(_OptionSchema))
    units = fields.List(fields.Nested(_OptionSchema))


# --- profile --------------------------------------------------------------


class BusinessProfileUpsertSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=2, max=150))
    description = fields.Str(allow_none=True, validate=validate.Length(max=2000))
    business_types = fields.List(
        fields.Str(), required=True, validate=validate.Length(min=1, max=5)
    )
    industry = fields.Str(allow_none=True)
    contact_email = fields.Email(allow_none=True)
    contact_phone = fields.Str(allow_none=True, validate=validate.Length(max=20))
    website = fields.Url(allow_none=True)
    # logo_url / cover_image_url are deliberately absent: they are set only by
    # uploading through POST /business/me/logo and /me/cover (app.business.images).
    address = fields.Str(allow_none=True, validate=validate.Length(max=255))
    city = fields.Str(allow_none=True, validate=validate.Length(max=100))
    state = fields.Str(allow_none=True, validate=validate.Length(max=100))
    country = fields.Str(allow_none=True, validate=validate.Length(max=100))
    registration_number = fields.Str(allow_none=True, validate=validate.Length(max=50))
    # verification_status is deliberately absent: users cannot set it.

    @validates("business_types")
    def validate_business_types(self, value, **kwargs):
        unknown = [v for v in value if v not in BUSINESS_TYPE_KEYS]
        if unknown:
            raise ValidationError(f"Unknown business type(s): {', '.join(unknown)}")

    @validates("industry")
    def validate_industry(self, value, **kwargs):
        if value and value not in INDUSTRY_KEYS:
            raise ValidationError(f"Unknown industry: {value}")


class BusinessProfileSchema(Schema):
    user_id = fields.Str()
    name = fields.Str()
    description = fields.Str(allow_none=True)
    business_types = fields.List(fields.Str())
    industry = fields.Str(allow_none=True)
    contact_email = fields.Str(allow_none=True)
    contact_phone = fields.Str(allow_none=True)
    website = fields.Str(allow_none=True)
    logo_url = fields.Str(allow_none=True)
    cover_image_url = fields.Str(allow_none=True)
    address = fields.Str(allow_none=True)
    city = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    country = fields.Str(allow_none=True)
    registration_number = fields.Str(allow_none=True)
    verification_status = fields.Enum(BusinessVerificationStatus)
    created_at = fields.DateTime()
    updated_at = fields.DateTime()

    # Which sides of the business are set up, from the user's existing
    # buyer and seller accounts.
    username = fields.Function(lambda p: p.user.username if p.user else None)
    buys = fields.Function(lambda p: bool(p.user and p.user.is_buyer))
    sells = fields.Function(lambda p: bool(p.user and p.user.is_seller))
    shop_slug = fields.Function(
        lambda p: p.user.seller_account.shop_slug
        if p.user and p.user.seller_account
        else None
    )


class BusinessPublicProfileSchema(BusinessProfileSchema):
    """What other users see. The registration number is the owner's alone."""

    class Meta:
        exclude = ("registration_number",)


class MyBusinessSchema(Schema):
    """The signed-in user's own business state."""

    is_business = fields.Bool()  # effective: tag and, if required, subscription
    business_tag = fields.Bool()  # the raw tag the user set
    requires_subscription = fields.Bool()  # tag is set but not entitled
    profile = fields.Nested(BusinessProfileSchema, allow_none=True)


class BusinessDiscoverArgs(Schema):
    search = fields.Str(allow_none=True)
    business_type = fields.Str(allow_none=True)
    industry = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    city = fields.Str(allow_none=True)
    side = fields.Str(
        allow_none=True, validate=validate.OneOf(["buys", "sells"])
    )  # business buyers (manufacturers) or business sellers (producers)
    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))


class BusinessProfilePageSchema(Schema):
    items = fields.List(fields.Nested(BusinessPublicProfileSchema))
    pagination = fields.Nested(PaginationSchema)


# --- listings -------------------------------------------------------------


class BusinessListingUpsertSchema(Schema):
    unit = fields.Str(required=True)
    available_quantity = fields.Float(allow_none=True, validate=validate.Range(min=0))
    min_order_quantity = fields.Float(allow_none=True, validate=validate.Range(min=0))
    price_negotiable = fields.Bool(load_default=False)
    production_capacity = fields.Str(allow_none=True, validate=validate.Length(max=150))
    availability = fields.Str(allow_none=True, validate=validate.Length(max=150))
    specifications = fields.Dict(
        keys=fields.Str(), values=fields.Str(), allow_none=True
    )
    city = fields.Str(allow_none=True, validate=validate.Length(max=100))
    state = fields.Str(allow_none=True, validate=validate.Length(max=100))

    @validates("unit")
    def validate_unit(self, value, **kwargs):
        if value not in UNIT_KEYS:
            raise ValidationError(f"Unknown unit: {value}")


class BusinessListingSchema(Schema):
    product_id = fields.Str()
    unit = fields.Str()
    available_quantity = fields.Float(allow_none=True)
    min_order_quantity = fields.Float(allow_none=True)
    price_negotiable = fields.Bool()
    production_capacity = fields.Str(allow_none=True)
    availability = fields.Str(allow_none=True)
    specifications = fields.Dict(allow_none=True)
    city = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    updated_at = fields.DateTime()


class BusinessListingResultSchema(Schema):
    """A product as a B2B listing: the product, its B2B terms and who sells it."""

    id = fields.Str()
    name = fields.Str()
    description = fields.Str(allow_none=True)
    price = fields.Float()
    image_url = fields.Method("get_image_url")
    business_listing = fields.Nested(BusinessListingSchema)
    seller_user_id = fields.Function(lambda p: p.seller.user_id if p.seller else None)
    business_name = fields.Function(
        lambda p: p.seller.user.business_profile.name
        if p.seller and p.seller.user and p.seller.user.business_profile
        else (p.seller.shop_name if p.seller else None)
    )

    def get_image_url(self, obj):
        try:
            images = getattr(obj, "images", None) or []
            media = getattr(images[0], "media", None) if images else None
            return media.get_url() if media else None
        except Exception:
            return None


class BusinessListingSearchArgs(Schema):
    search = fields.Str(allow_none=True)
    category_id = fields.Int(allow_none=True)
    unit = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    city = fields.Str(allow_none=True)
    min_available = fields.Float(allow_none=True, validate=validate.Range(min=0))
    # Listings whose minimum order is at most this much.
    max_min_order = fields.Float(allow_none=True, validate=validate.Range(min=0))
    seller_user_id = fields.Str(allow_none=True)
    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))


class BusinessListingPageSchema(Schema):
    items = fields.List(fields.Nested(BusinessListingResultSchema))
    pagination = fields.Nested(PaginationSchema)


# --- subscriptions --------------------------------------------------------


class SubscriptionFeatureSchema(Schema):
    feature_key = fields.Str()
    limit_value = fields.Int(allow_none=True)


class SubscriptionPlanSchema(Schema):
    id = fields.Int()
    key = fields.Str()
    name = fields.Str()
    description = fields.Str(allow_none=True)
    price = fields.Float()
    currency = fields.Str()
    billing_interval = fields.Str()
    features = fields.List(fields.Nested(SubscriptionFeatureSchema))


class SubscriptionCheckoutSchema(Schema):
    plan_id = fields.Int(required=True)
    # Where Paystack's browser redirect should land afterwards.
    platform = fields.Str(
        load_default="web", validate=validate.OneOf(["web", "mobile"])
    )


class SubscriptionCheckoutResultSchema(Schema):
    subscription_id = fields.Int()
    status = fields.Str()
    # Null for a free plan, which is active immediately.
    authorization_url = fields.Str(allow_none=True)
    reference = fields.Str()


class SubscriptionVerifyResultSchema(Schema):
    subscription_id = fields.Int()
    status = fields.Str()
    verified = fields.Bool()


class MySubscriptionSchema(Schema):
    id = fields.Int()
    status = fields.Enum(BusinessSubscriptionStatus)
    start_date = fields.DateTime(allow_none=True)
    end_date = fields.DateTime(allow_none=True)
    renewal_date = fields.DateTime(allow_none=True)
    plan = fields.Nested(SubscriptionPlanSchema)
