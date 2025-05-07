from marshmallow import Schema, fields, validate, ValidationError
from app.libs.schemas import PaginationSchema


class UserSchema(Schema):
    id = fields.Str(dump_only=True)
    email = fields.Email(required=True)
    phone_number = fields.Str()
    username = fields.Str(required=True)
    profile_picture = fields.Str()
    created_at = fields.DateTime(dump_only=True)


class AddressSchema(Schema):
    longitude = fields.Float()
    latitude = fields.Float()
    house_number = fields.Str()
    street = fields.Str()
    city = fields.Str()
    state = fields.Str()
    country = fields.Str()
    postal_code = fields.Str()


class BuyerSchema(Schema):
    buyername = fields.Str(required=True)
    shipping_address = fields.Dict()


class SellerSchema(Schema):
    shop_name = fields.Str(required=True)
    description = fields.Str(required=True)
    category = fields.Str(required=True)


class UserRegisterSchema(Schema):
    email = fields.Email(required=True)
    username = fields.Str(required=True)
    phone_number = fields.Str()
    password = fields.Str(required=True, load_only=True)
    account_type = fields.Str(
        required=True, validate=validate.OneOf(["buyer", "seller"])
    )
    address = fields.Nested(AddressSchema)
    buyer_data = fields.Nested(BuyerSchema)
    seller_data = fields.Nested(SellerSchema)


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
    current_role = fields.Str(dump_only=True)
    address = fields.Nested(lambda: AddressSchema())
    buyer_account = fields.Nested(lambda: BuyerProfileSchema(), dump_only=True)
    seller_account = fields.Nested(lambda: SellerProfileSchema(), dump_only=True)


class BuyerProfileSchema(Schema):
    buyername = fields.Str()
    shipping_address = fields.Dict()


class SellerProfileSchema(Schema):
    shop_name = fields.Str()
    description = fields.Str()
    category = fields.Str()
    total_rating = fields.Int()
    total_raters = fields.Int()


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


class BuyerSimpleSchema(Schema):
    id = fields.Int(dump_only=True)
    buyername = fields.Str()


class FeedSchema(Schema):
    pass


class PublicProfileSchema(Schema):
    pass
