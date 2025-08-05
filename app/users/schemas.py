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
        required=True, validate=validate.OneOf(["buyer", "seller"])
    )


class PasswordResetSchema(Schema):
    email = fields.Email(required=True)


class PasswordResetConfirmSchema(Schema):
    email = fields.Email(required=True)
    code = fields.Str(required=True)
    new_password = fields.Str(required=True)


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
    previous_role = fields.Str(dump_only=True)
    current_role = fields.Bool(required=True)
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
    verification_status = fields.Str(dump_only=True)
    average_rating = fields.Float(dump_only=True)
    total_products = fields.Int(dump_only=True)
    profile_picture_url = fields.Method("get_profile_picture_url", dump_only=True)

    def get_profile_picture_url(self, obj):
        """Get profile picture URL with fallback to default"""
        if hasattr(obj, "user") and obj.user and obj.user.profile_picture:
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
