from marshmallow import Schema, fields, validate, ValidationError, EXCLUDE
from app.libs.schemas import PaginationSchema
from app.categories.schemas import CategorySchema

from .models import RefundPreference, SellerVerificationStatus

from .addresses import BuildingType


# Helper validators
def validate_nigerian_phone(value):
    if value and not value.startswith("+234") and len(value) != 11:
        raise ValidationError("Invalid Nigerian phone format. Use +234 or local format")


class NormalisedEmail(fields.Email):
    """An email address, lowercased on the way in.

    `users.email` is unique, but uniqueness is over the *string* -- so
    "Ada@example.com" and "ada@example.com" are two different rows and the
    duplicate check in register_user never fires. Signing up twice with what
    anyone would call the same address produced two unrelated accounts, and
    then signing in with the other capitalisation silently landed on the wrong
    one.

    Normalising here rather than in each service means every entry point gets
    it: register, login, both verification endpoints and both password-reset
    endpoints. The local part of an address is technically case-sensitive per
    RFC 5321, but no mail provider anyone uses treats it that way, and a
    marketplace that lets one person hold two accounts on one inbox is a
    worse problem than that edge case.
    """

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        return value.strip().lower() if isinstance(value, str) else value


class UserSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    id = fields.Str(dump_only=True)
    email = NormalisedEmail(required=True)
    phone_number = fields.Str(validate=validate_nigerian_phone)
    username = fields.Str(
        required=True,
        validate=[validate.Length(min=3, max=20), validate.Regexp(r"^[a-zA-Z0-9_]+$")],
    )
    profile_picture = fields.Str(dump_only=True)
    profile_picture_url = fields.Method("get_profile_picture_url", dump_only=True)
    is_buyer = fields.Bool(dump_only=True)
    is_seller = fields.Bool(dump_only=True)
    email_verified = fields.Bool(dump_only=True)
    current_role = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
    last_login_at = fields.DateTime(dump_only=True)
    # Bearer token, only populated on login/register responses (see routes).
    # Absent elsewhere, so marshmallow omits it from other user payloads.
    access_token = fields.Str(dump_only=True)

    def get_profile_picture_url(self, obj):
        """Get profile picture URL with fallback to default"""
        if hasattr(obj, "profile_picture") and obj.profile_picture:
            # The profile_picture field should already contain the thumbnail URL
            return obj.profile_picture
        return "/static/images/default-avatar.jpg"


class AddressSchema(Schema):
    longitude = fields.Float()
    latitude = fields.Float()
    house_number = fields.Str()
    street = fields.Str()
    city = fields.Str()
    state = fields.Str()
    country = fields.Str()
    postal_code = fields.Str()


class AddressUpdateSchema(AddressSchema):
    """Schema for updating the current user's address."""


class BuyerCreateSchema(Schema):
    buyername = fields.Str(required=True)
    shipping_address = fields.Dict()


class SellerCreateSchema(Schema):
    shop_name = fields.Str(required=True)
    description = fields.Str(required=True)
    category_ids = fields.List(
        fields.Int(), required=True, description="List of category IDs"
    )
    policies = fields.Dict(required=False)


class UserRegisterSchema(UserSchema):
    password = fields.Str(
        required=True,
        load_only=True,
        validate=[
            validate.Length(
                min=8, error="Password must be at least 8 characters long."
            ),
            validate.Regexp(
                r"(?=.*\d)(?=.*[a-z])(?=.*[A-Z])",
                error="Password must contain at least one digit, one lowercase letter, and one uppercase letter.",
            ),
        ],
    )
    account_type = fields.Str(
        required=True, validate=validate.OneOf(["buyer", "seller"])
    )

    # Overrides UserSchema's `required=True`. Registration now happens on the
    # first screen, which asks for an email and a password and nothing else --
    # so there is no username to send, and the server mints one. A client that
    # does have one (the old flow, or a "pick your handle" screen later) can
    # still supply it and it is honoured.
    username = fields.Str(
        required=False,
        validate=[
            validate.Length(min=3, max=20),
            validate.Regexp(r"^[a-zA-Z0-9_]+$"),
        ],
    )

    # Likewise optional. The profile is filled in afterwards, through
    # PATCH /users/profile/buyer and /users/profile/seller, by which point the
    # account exists and the request is authenticated. Still accepted here so
    # a caller that has the data up front is not forced into two round trips.
    buyer_data = fields.Nested(BuyerCreateSchema)
    seller_data = fields.Nested(SellerCreateSchema)


class UserUpdateSchema(Schema):
    phone_number = fields.Str(validate=validate_nigerian_phone)
    profile_picture = fields.Str()  # URL or media ID

    # Registration mints a handle when the client does not send one, and the
    # signup screen that asks for one now runs *after* the account exists --
    # so without this the field would be collected and dropped. It also means
    # a handle is finally changeable at all, which it never was.
    username = fields.Str(
        validate=[
            validate.Length(min=3, max=20),
            validate.Regexp(r"^[a-zA-Z0-9_]+$"),
        ]
    )


class BuyerUpdateSchema(Schema):
    buyername = fields.Str()
    shipping_address = fields.Dict()
    #: Where money owed back should land -- today, the saving when a delivery
    #: is shared. "card" sends it back to the card that paid (days, and it is
    #: genuinely their money leaving Markt); "wallet" is instant and
    #: withdrawable. Defaults to "card" and is only ever changed by the buyer.
    refund_preference = fields.Str(
        validate=validate.OneOf([p.value for p in RefundPreference])
    )


class SellerUpdateSchema(Schema):
    shop_name = fields.Str(validate=validate.Length(min=2, max=100))
    description = fields.Str()
    category_ids = fields.List(fields.Int(), description="List of category IDs")
    policies = fields.Dict()

    # Where the shop actually is. The columns existed but nothing could set
    # them -- the only writes in the codebase were to None, on account
    # deletion -- so every seller was unlocated and the proximity feed could
    # never rank anyone. This is what gives it data.
    #
    # Sent as a pair or not at all: one coordinate without the other is not a
    # location, and storing half of one would place the shop in the ocean.
    shop_latitude = fields.Float(validate=validate.Range(-90, 90))
    shop_longitude = fields.Float(validate=validate.Range(-180, 180))
    shop_address = fields.Dict()


class UserLoginSchema(Schema):
    email = NormalisedEmail(required=True)
    password = fields.Str(required=True, load_only=True)
    account_type = fields.Str(
        required=False,
        validate=validate.OneOf(["buyer", "seller"]),
        description="Optional: If not provided, will use current_role or default to available account type",
    )


class PasswordResetSchema(Schema):
    email = NormalisedEmail(required=True)


class PasswordResetConfirmSchema(Schema):
    email = NormalisedEmail(required=True)
    code = fields.Str(required=True, validate=validate.Length(equal=6))
    new_password = fields.Str(
        required=True,
        validate=[
            validate.Length(
                min=8, error="Password must be at least 8 characters long."
            ),
            validate.Regexp(
                r"(?=.*\d)(?=.*[a-z])(?=.*[A-Z])",
                error="Password must contain at least one digit, one lowercase letter, and one uppercase letter.",
            ),
        ],
    )


class PasswordResetResponseSchema(Schema):
    """Schema for password reset responses"""

    message = fields.Str(required=True)


class EmailVerificationSendSchema(Schema):
    email = NormalisedEmail(required=True)


class EmailVerificationSchema(Schema):
    email = NormalisedEmail(required=True)
    verification_code = fields.Str(required=True, validate=validate.Length(equal=6))


class UserPaginationQueryArgs(Schema):
    page = fields.Int(required=False, default=1)
    per_page = fields.Int(required=False, default=20)
    search = fields.Str(required=False)
    sort = fields.Str(required=False)
    filters = fields.Dict(required=False)


class UserPaginationSchema(Schema):
    items = fields.List(fields.Nested(UserSchema))
    pagination = fields.Nested(PaginationSchema)


class OnboardingStateSchema(Schema):
    """Where this account stands in signup, so the client knows where to
    resume after an interruption instead of inferring it from blank fields."""

    email_verified = fields.Bool(dump_only=True)
    profile_complete = fields.Bool(dump_only=True)
    next_step = fields.Str(dump_only=True, allow_none=True)


class UserProfileSchema(UserSchema):
    address = fields.Nested(lambda: AddressSchema(), dump_only=True)
    buyer_account = fields.Nested(lambda: BuyerProfileSchema(), dump_only=True)
    seller_account = fields.Nested(lambda: SellerProfileSchema(), dump_only=True)
    onboarding = fields.Method("get_onboarding", dump_only=True)

    def get_onboarding(self, obj):
        from .onboarding import state

        return state(obj)

    # media_uploads = fields.List(fields.Nested("MediaSchema"), dump_only=True)


class BuyerProfileSchema(BuyerCreateSchema):
    id = fields.Int(dump_only=True)
    #: So the settings screen can show what is currently chosen rather than
    #: guessing at the default.
    refund_preference = fields.Str(dump_only=True)
    total_orders = fields.Int(dump_only=True)
    pending_orders = fields.Int(dump_only=True)
    last_order_date = fields.DateTime(dump_only=True)
    is_active = fields.Bool(dump_only=True)
    created_at = fields.DateTime(dump_only=True)


def shop_address_line(seller) -> dict:
    """The shop's address as something a person can read.

    `Seller.shop_address` is a free-form JSON column that was written by one
    caller as ``{"street": ...}`` and read by nobody, so it had no agreed
    shape and would have drifted the moment a second writer appeared. This
    settles on ``{formatted, city, state}`` and keeps understanding the old
    single-key form, because rows written before this exist.

    The coordinate remains the authority on where the shop *is*; this is only
    what gets shown. A buyer deciding whether to order from a shop two streets
    away should not have to read a latitude.
    """
    raw = getattr(seller, "shop_address", None)
    if isinstance(raw, dict):
        formatted = (
            raw.get("formatted")
            or raw.get("street")
            or raw.get("street_address")
            or None
        )
        return {
            "formatted": formatted,
            "city": raw.get("city"),
            "state": raw.get("state"),
        }
    return {"formatted": None, "city": None, "state": None}


class ShopAddressSchema(Schema):
    """Where a shop is, in words. Every field nullable: plenty of real places
    come back from a geocoder with no city and no state, and a shop whose
    seller has not set an address at all is normal rather than broken."""

    formatted = fields.Str(allow_none=True)
    city = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)


class SellerProfileSchema(Schema):
    id = fields.Int(dump_only=True)
    shop_name = fields.Str()
    shop_slug = fields.Str(dump_only=True)
    shop_address = fields.Method("get_shop_address", dump_only=True)

    def get_shop_address(self, obj):
        return shop_address_line(obj)

    description = fields.Str()
    banner_url = fields.Str(dump_only=True, allow_none=True)
    verification_status = fields.Enum(
        SellerVerificationStatus, by_value=True, dump_only=True
    )
    total_products = fields.Int(dump_only=True)
    total_sales = fields.Float(dump_only=True)
    average_rating = fields.Float(dump_only=True)
    total_rating = fields.Int(dump_only=True)
    total_raters = fields.Int(dump_only=True)
    joined_date = fields.DateTime(dump_only=True)
    is_active = fields.Bool(dump_only=True)
    categories = fields.Method("get_categories", dump_only=True)
    policies = fields.Dict(dump_only=True)

    def get_categories(self, obj):
        """Extract category data from SellerCategory objects"""
        if hasattr(obj, "categories") and obj.categories:
            # Create a CategorySchema instance to serialize the categories
            from app.categories.schemas import CategorySchema

            category_schema = CategorySchema()
            return [
                category_schema.dump(seller_category.category)
                for seller_category in obj.categories
                if seller_category.category
            ]
        return []


class UsernameCheckSchema(Schema):
    username = fields.Str(
        required=True,
        validate=[
            validate.Length(min=3, max=20, error="Must be between 3-20 characters"),
            validate.Regexp(
                r"^[a-zA-Z0-9_]+$",
                error="Only letters, numbers and underscores allowed",
            ),
        ],
    )


class UsernameAvailableSchema(Schema):
    available = fields.Bool(required=True)
    message = fields.Str()


class RoleSwitchSchema(Schema):
    """Schema for role switching responses"""

    success = fields.Bool(required=True)
    previous_role = fields.Str(required=True)
    current_role = fields.Str(required=True)
    message = fields.Str(required=True)
    user = fields.Nested(UserSchema, dump_only=True)


class BuyerSimpleSchema(Schema):
    id = fields.Int(dump_only=True)
    buyername = fields.Str()
    profile_picture_url = fields.Method("get_profile_picture_url", dump_only=True)

    def get_profile_picture_url(self, obj):
        """Get profile picture URL with fallback to default"""
        if hasattr(obj, "user") and obj.user and obj.user.profile_picture:
            return obj.user.profile_picture
        return "/static/images/default-avatar.jpg"


class UserSimpleSchema(Schema):
    id = fields.Str(dump_only=True)
    username = fields.Str()
    profile_picture_url = fields.Method("get_profile_picture_url", dump_only=True)

    def get_profile_picture_url(self, obj):
        """Get profile picture URL with fallback to default"""
        if hasattr(obj, "profile_picture") and obj.profile_picture:
            return obj.profile_picture
        return "/static/images/default-avatar.jpg"


class SellerSimpleSchema(Schema):
    id = fields.Int(dump_only=True)
    shop_name = fields.Str(dump_only=True)
    shop_slug = fields.Str(dump_only=True)
    # Where the shop is, so a client can ask whether we deliver from there
    # before letting someone fill a basket they could never check out. Already
    # public in effect -- distance-ranked discovery is built on it -- and a
    # shop is a business address, not a home one.
    shop_latitude = fields.Float(dump_only=True, allow_none=True)
    shop_longitude = fields.Float(dump_only=True, allow_none=True)
    shop_address = fields.Method("get_shop_address", dump_only=True)

    def get_shop_address(self, obj):
        return shop_address_line(obj)

    verification_status = fields.Method("get_verification_status", dump_only=True)
    average_rating = fields.Method("get_average_rating", dump_only=True)
    total_products = fields.Method("get_total_products", dump_only=True)
    profile_picture_url = fields.Method("get_profile_picture_url", dump_only=True)

    def get_verification_status(self, obj):
        """Get verification status, handling both enum objects and string values"""
        if isinstance(obj, dict):
            # Already serialized dict from ShopService (already a string)
            return obj.get("verification_status")
        elif hasattr(obj, "verification_status"):
            # Seller model object with enum
            status = obj.verification_status
            if isinstance(status, SellerVerificationStatus):
                return status.value
            return status
        return None

    def get_average_rating(self, obj):
        """Get average rating, handling both dict and model objects"""
        if isinstance(obj, dict):
            return obj.get("average_rating", 0.0)
        # For model objects, calculate from total_rating and total_raters
        total_rating = getattr(obj, "total_rating", 0) or 0
        total_raters = getattr(obj, "total_raters", 0) or 0
        if total_raters > 0:
            return float(total_rating) / total_raters
        return 0.0

    def get_total_products(self, obj):
        """Get total products, handling both dict and model objects"""
        if isinstance(obj, dict):
            # Check stats dict first (from ShopService.search_shops)
            stats = obj.get("stats", {})
            if isinstance(stats, dict):
                return stats.get("product_count", 0)
            return 0
        # For model objects, return 0 if not available as property
        return getattr(obj, "total_products", 0) or 0

    def get_profile_picture_url(self, obj):
        """Get profile picture URL with fallback to default"""
        if isinstance(obj, dict):
            # Already serialized dict from ShopService
            user = obj.get("user", {})
            return user.get("profile_picture") or "/static/images/default-avatar.jpg"
        elif hasattr(obj, "user") and obj.user and obj.user.profile_picture:
            return obj.user.profile_picture
        return "/static/images/default-avatar.jpg"


class ShopSearchArgs(Schema):
    """Query arguments for GET /users/shops.

    The route was declared with the generic PaginationQueryArgs, which knows
    about page/per_page/search/sort/filters and nothing else -- while the
    service reads `category`, `verified_only`, `active_only` and `sort_by`.
    Marshmallow's default for unknown fields is RAISE, so every one of those
    was a 422 waiting to happen the moment a client actually sent it.

    This is the real contract, including the two that make proximity work.
    """

    class Meta:
        unknown = EXCLUDE

    page = fields.Int(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Int(load_default=20, validate=validate.Range(min=1, max=100))
    search = fields.Str()
    category = fields.Str()
    verified_only = fields.Bool(load_default=False)
    active_only = fields.Bool(load_default=False)
    sort_by = fields.Str(
        load_default="rating",
        validate=validate.OneOf(["rating", "name", "recent", "followers", "nearby"]),
    )

    # Where the shopper is. Sent as a pair or not at all -- a lone latitude is
    # not a location. `sort_by=nearby` without them falls back to rating
    # rather than erroring: a denied location permission must not break
    # browsing.
    latitude = fields.Float(validate=validate.Range(-90, 90))
    longitude = fields.Float(validate=validate.Range(-180, 180))


class SettingsSchema(Schema):
    pass


class SettingsUpdateSchema(Schema):
    pass


class PublicShopSchema(Schema):
    id = fields.Int()
    shop_name = fields.Str(allow_none=True)
    shop_slug = fields.Str(allow_none=True)
    description = fields.Str(allow_none=True)
    products_count = fields.Int()
    average_rating = fields.Float(allow_none=True)
    total_raters = fields.Int()
    verification_status = fields.Str(allow_none=True)


class PublicProfileSchema(Schema):
    """What anyone may see about another user.

    Deliberately narrow: no email, no phone, no address, no order history.
    Adding a field here makes it public to every caller, authenticated or not.
    """

    id = fields.Str()
    username = fields.Str()
    profile_picture = fields.Str(allow_none=True)
    is_seller = fields.Bool()
    joined_at = fields.Str(allow_none=True)

    followers_count = fields.Int()
    following_count = fields.Int()
    posts_count = fields.Int()

    # Viewer-relative; False for anonymous callers.
    is_followed = fields.Bool()
    is_self = fields.Bool()

    shop = fields.Nested(PublicShopSchema, allow_none=True)


# Legacy schema for backward compatibility
class SellerSchema(SellerCreateSchema):
    """Legacy schema alias"""


# Seller Start Cards Schemas
class StartCardCTASchema(Schema):
    label = fields.Str(required=True)
    href = fields.Str(required=True)


class StartCardProgressSchema(Schema):
    current = fields.Int(required=True)
    target = fields.Int(required=True)


class StartCardSchema(Schema):
    key = fields.Str(required=True)
    title = fields.Str(required=True)
    description = fields.Str(required=True)
    cta = fields.Nested(StartCardCTASchema, required=True)
    completed = fields.Bool(required=True)
    progress = fields.Nested(StartCardProgressSchema, allow_none=True)


class StartCardsMetadataSchema(Schema):
    seller_id = fields.Int(required=True)
    generated_at = fields.Str(required=True)


class StartCardsResponseSchema(Schema):
    items = fields.List(fields.Nested(StartCardSchema), required=True)
    metadata = fields.Nested(StartCardsMetadataSchema, required=True)


# Seller Analytics Schemas
class AnalyticsOverviewSchema(Schema):
    revenue_30d = fields.Float(required=True)
    orders_30d = fields.Int(required=True)
    views_30d = fields.Int(required=True)
    conversion_30d = fields.Float(required=True)


class AnalyticsTimeseriesPointSchema(Schema):
    bucket_start = fields.Str(required=True)
    value = fields.Float(required=True)


class AnalyticsTimeseriesTotalsSchema(Schema):
    value = fields.Float(required=True)
    count = fields.Int(required=True)


class AnalyticsTimeseriesResponseSchema(Schema):
    metric = fields.Str(required=True)
    bucket = fields.Str(required=True)
    series = fields.List(fields.Nested(AnalyticsTimeseriesPointSchema), required=True)
    totals = fields.Nested(AnalyticsTimeseriesTotalsSchema, required=True)


# Query parameter schemas
class AnalyticsTimeseriesQuerySchema(Schema):
    metric = fields.Str(
        required=True,
        validate=validate.OneOf(["sales", "orders", "views", "conversion"]),
    )
    bucket = fields.Str(
        required=True, validate=validate.OneOf(["day", "week", "month"])
    )
    start_date = fields.DateTime(required=True)
    end_date = fields.DateTime(required=True)


class AnalyticsOverviewQuerySchema(Schema):
    window_days = fields.Int(missing=30, validate=validate.Range(min=1, max=365))


# Account deletion (Apple App Store 5.1.1(v))
class AccountDeletionBlockerSchema(Schema):
    code = fields.Str()
    message = fields.Str()
    detail = fields.Dict()


class AccountDeletionPreviewSchema(Schema):
    can_delete = fields.Bool()
    blockers = fields.List(fields.Nested(AccountDeletionBlockerSchema))


class AccountDeletionRequestSchema(Schema):
    """Deletion is irreversible, so it takes the password rather than relying
    on the 30-day bearer token alone, plus a typed confirmation the UI makes
    the user enter."""

    password = fields.Str(required=True, load_only=True)
    confirmation = fields.Str(
        required=True,
        validate=validate.Equal(
            "DELETE", error="Type DELETE to confirm account deletion"
        ),
    )


class AccountDeletionResponseSchema(Schema):
    deleted = fields.Bool()
    user_id = fields.Str()
    message = fields.Str()


class OAuthSignInSchema(Schema):
    """POST /users/auth/oauth.

    `identity_token` is the JWT the provider handed the app. It is a carrier,
    not a credential we trust -- see app/users/oauth.py.
    """

    class Meta:
        unknown = EXCLUDE

    provider = fields.Str(required=True, validate=validate.OneOf(["google", "apple"]))
    identity_token = fields.Str(required=True, load_only=True)

    # Apple echoes the nonce the app generated for this attempt; checking it
    # stops a token captured from an earlier sign-in being replayed.
    nonce = fields.Str(load_default=None, allow_none=True)

    # Apple returns the user's name exactly once, on first authorisation, and
    # never inside the token -- so the app forwards it separately or it is
    # lost for good.
    full_name = fields.Str(load_default=None, allow_none=True)

    account_type = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(["buyer", "seller"]),
    )


class SavedAddressSchema(Schema):
    """A place in the buyer's address book.

    Shaped around what a rider needs rather than what a postal system wants:
    a coordinate plus a landmark finds a door in Ogbomoso, a street number
    and a postcode frequently do not.
    """

    id = fields.Int(dump_only=True)
    label = fields.Str(allow_none=True, validate=validate.Length(max=60))
    formatted_address = fields.Str(
        required=True, validate=validate.Length(min=3, max=500)
    )
    latitude = fields.Float(required=True, validate=validate.Range(-90, 90))
    longitude = fields.Float(required=True, validate=validate.Range(-180, 180))
    city = fields.Str(allow_none=True, validate=validate.Length(max=100))
    state = fields.Str(allow_none=True, validate=validate.Length(max=100))
    building_type = fields.Enum(BuildingType, by_value=True, load_default=None)
    entry_code = fields.Str(allow_none=True, validate=validate.Length(max=40))
    directions = fields.Str(allow_none=True)
    contact_name = fields.Str(allow_none=True, validate=validate.Length(max=100))
    contact_phone = fields.Str(allow_none=True, validate=validate.Length(max=20))
    is_default = fields.Bool(load_default=False)
    last_used_at = fields.DateTime(dump_only=True, allow_none=True)
    display_label = fields.Str(dump_only=True)


class SavedAddressUpdateSchema(SavedAddressSchema):
    """Everything optional -- editing only the label should not require
    re-sending the coordinates."""

    formatted_address = fields.Str(validate=validate.Length(min=3, max=500))
    latitude = fields.Float(validate=validate.Range(-90, 90))
    longitude = fields.Float(validate=validate.Range(-180, 180))
