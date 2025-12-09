from marshmallow import Schema, fields, validate, ValidationError, EXCLUDE
from app.libs.schemas import PaginationSchema
from app.categories.schemas import CategorySchema

from .models import SellerVerificationStatus


# Helper validators
def validate_nigerian_phone(value):
    if value and not value.startswith("+234") and len(value) != 11:
        raise ValidationError("Invalid Nigerian phone format. Use +234 or local format")


class UserSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    id = fields.Str(dump_only=True)
    email = fields.Email(required=True)
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
    buyer_data = fields.Nested(BuyerCreateSchema)
    seller_data = fields.Nested(SellerCreateSchema)


class UserUpdateSchema(Schema):
    phone_number = fields.Str(validate=validate_nigerian_phone)
    profile_picture = fields.Str()  # URL or media ID


class BuyerUpdateSchema(Schema):
    buyername = fields.Str()
    shipping_address = fields.Dict()


class SellerUpdateSchema(Schema):
    shop_name = fields.Str(validate=validate.Length(min=2, max=100))
    description = fields.Str()
    category_ids = fields.List(fields.Int(), description="List of category IDs")
    policies = fields.Dict()


class UserLoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.Str(required=True, load_only=True)
    account_type = fields.Str(
        required=False,
        validate=validate.OneOf(["buyer", "seller"]),
        description="Optional: If not provided, will use current_role or default to available account type",
    )


class PasswordResetSchema(Schema):
    email = fields.Email(required=True)


class PasswordResetConfirmSchema(Schema):
    email = fields.Email(required=True)
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
    email = fields.Email(required=True)


class EmailVerificationSchema(Schema):
    email = fields.Email(required=True)
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


class UserProfileSchema(UserSchema):
    address = fields.Nested(lambda: AddressSchema(), dump_only=True)
    buyer_account = fields.Nested(lambda: BuyerProfileSchema(), dump_only=True)
    seller_account = fields.Nested(lambda: SellerProfileSchema(), dump_only=True)
    # media_uploads = fields.List(fields.Nested("MediaSchema"), dump_only=True)


class BuyerProfileSchema(BuyerCreateSchema):
    id = fields.Int(dump_only=True)
    total_orders = fields.Int(dump_only=True)
    pending_orders = fields.Int(dump_only=True)
    last_order_date = fields.DateTime(dump_only=True)
    is_active = fields.Bool(dump_only=True)
    created_at = fields.DateTime(dump_only=True)


class SellerProfileSchema(Schema):
    id = fields.Int(dump_only=True)
    shop_name = fields.Str()
    shop_slug = fields.Str(dump_only=True)
    description = fields.Str()
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


class SettingsSchema(Schema):
    pass


class SettingsUpdateSchema(Schema):
    pass


class PublicProfileSchema(Schema):
    pass


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
