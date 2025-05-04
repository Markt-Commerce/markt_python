from marshmallow import Schema, fields, validate, post_load, pre_load
from flask_login import current_user


class ExampleSchema(Schema):
    message = fields.String()


class UserSchema(Schema):
    id = fields.Int(dump_only=True)
    username = fields.Str(required=True)
    email = fields.Str(required=True)
    phone_number = fields.Str()
    profile_picture = fields.Str()


class BuyerSchema(UserSchema):
    buyername = fields.Str(required=True)
    password = fields.Str(required=True, load_only=True)
    shipping_address = fields.Str(
        required=True
    )  # We haven't thought of any buyer specific attr
    user_status = fields.Str()


class BuyerUpdateSchema(UserSchema):
    # We need to fill with info a buyer can update
    username = fields.Str()
    shipping_address = fields.Str()


class SellerSchema(UserSchema):
    password = fields.Str(required=True, load_only=True)
    shop_name = fields.Str(required=True)
    description = fields.Str(required=True)
    directions = fields.Str(required=True)
    category = fields.Str(required=True)
    total_rating = fields.Int(dump_only=True)
    total_raters = fields.Int(dump_only=True)
    user_status = fields.Str()


class SellerUpdateSchema(UserSchema):
    # We need to fill with info a seller can update
    username = fields.Str()
    shop_name = fields.Str()


class AddressSchema(Schema):
    longtitude = fields.Float()
    latitude = fields.Float()
    house_number = fields.Int()
    street = fields.Str()
    city = fields.Str()
    state = fields.Str()
    country = fields.Str()
    postal_code = fields.Int()


class BuyerRegisterSchema(BuyerSchema):
    address = fields.Nested(AddressSchema, required=False)


class SellerRegisterSchema(SellerSchema):
    address = fields.Nested(AddressSchema, required=False)


class CreateBuyerResponseSchema(Schema):
    user = fields.Nested(UserSchema)
    buyer = fields.Nested(BuyerSchema)


class CreateSellerResponseSchema(Schema):
    user = fields.Nested(UserSchema)
    seller = fields.Nested(SellerSchema)


class RoleSchema(Schema):
    is_buyer = fields.Bool()
    is_seller = fields.Bool()


class UserLoginSchema(Schema):
    email = fields.Str(required=True)
    # username = fields.Str(required=True)
    password = fields.Str(required=True)
    account_type = fields.Str(required=True)


class UserLoginResponseSchema(Schema):
    message = fields.Str()
    current_role = fields.Str()


class UserProfileSchema(Schema):
    username = fields.Str(required=True)
    email = fields.Str(required=True)
    profile_picture = fields.Str()
    phone_number = fields.Str()
    shipping_address = fields.Str()
    shop_name = fields.Str()
    description = fields.Str()
    category = fields.Str()
    total_rating = fields.Int()
    total_raters = fields.Int()

    @classmethod
    def dump_buyer_info(cls, buyer_info):
        return cls().dump(
            {
                "username": buyer_info.username,
                "email": buyer_info.user.email,
                "profile_picture": buyer_info.profile_picture,
                "phone_number": buyer_info.user.phone_number,
                "shipping_address": buyer_info.shipping_address,
            }
        )

    @classmethod
    def dump_seller_info(cls, seller_info):
        return cls().dump(
            {
                "username": seller_info.username,
                "email": seller_info.user.email,
                "profile_picture": seller_info.profile_picture,
                "shop_name": seller_info.shop_name,
                "description": seller_info.description,
                "category": seller_info.category,
                "total_rating": seller_info.total_rating,
                "total_raters": seller_info.total_raters,
            }
        )


class RoleArgSchema(Schema):
    role = fields.Str()  # optional - buyer or seller


class UserProfileUpdateSchema(Schema):
    # Common fields
    id = fields.Int(dump_only=True)
    email = fields.Str(required=True)
    phone_number = fields.Str()

    # Buyer-specific fields
    buyer_info = fields.Nested(BuyerUpdateSchema, allow_none=True)

    # Seller-specific fields
    seller_info = fields.Nested(SellerUpdateSchema, allow_none=True)

    # Additional fields if needed

    @pre_load
    def process_input(self, data, **kwargs):
        # Remove buyer_info or seller_info based on the user's current role
        if current_user.is_buyer:
            data.pop("seller_info", None)
        elif current_user.is_seller:
            data.pop("buyer_info", None)
        return data


class UpdateProfilePictureSchema(Schema):
    profile_picture = fields.Raw(
        required=True, validate=validate.Length(max=10 * 1024 * 1024)
    )  # Assuming a maximum size of 10 MB


class ProductSchema(Schema):
    id = fields.Int(strict=True)
    seller_id = fields.String()
    name = fields.String()
    description = fields.String()
    price = fields.Float()
    stock_quantity = fields.Int(strict=True)
    category = fields.String()
    # product_image = fields.String()


class CreateProductSchema(Schema):
    id = fields.Int(strict=True)
    name = fields.String()
    description = fields.String()
    price = fields.Float()
    stock_quantity = fields.Int(strict=True)
    category = fields.String()
    # product_image = fields.String()


class CategorySchema(Schema):
    categories = fields.List(fields.Raw(required=True))


class CartSchema(Schema):
    cart_id = fields.String()
    buyer_id = fields.String()
    product_id = fields.String()
    quantity = fields.Int(strict=True)
    has_discount = fields.Bool()
    discount_price = fields.Float()
    discount_percent = fields.Float()
    product_image = fields.String()
    # order_status = db.Column(db.String(255), default='pending')


class CartResponseSchema(Schema):
    cart_id = fields.String()
    buyer_id = fields.String()
    product_id = fields.String()
    quantity = fields.Int(strict=True)
    has_discount = fields.Bool()
    discount_price = fields.Float()
    discount_percent = fields.Float()


class ProductRequestSchema(Schema):
    buyer_id = fields.String()
    product_description = fields.String()
    category = fields.String()
    created_at = fields.DateTime()
    status = fields.String()


class CreateProductRequestSchema(Schema):
    product_description = fields.String()
    category = fields.String()
    created_at = fields.DateTime()
    status = fields.String()


class CodeForPasswordRetrievalSchema(Schema):
    user_id = fields.String()
    email = fields.String()


class PasswordRetrievalSchema(CodeForPasswordRetrievalSchema):
    recovery_code = fields.Int(strict=True)


class OrderSchema(Schema):
    buyer_id = fields.String()
    seller_id = fields.String()
    product_id = fields.String()
    quantity = fields.Int(strict=True)
    total_price = fields.Float()
    order_status = fields.String()
    order_date = fields.DateTime()
    delivery_address = fields.String()


class CommentSchema(Schema):
    comment_title = fields.String()
    buyer_id = fields.String()
    product_id = fields.String()
    seller_id = fields.String()
    content = fields.String()


class CommentRateSchema(CommentSchema):
    rating = fields.Int()


class FavoriteSchema(Schema):
    buyer_id = fields.String()
    favorite_item_id = (
        fields.String()
    )  # the id of the buyer favorite (seller or product)
    favorite_type = fields.String()  # seller or product


class ChatMessageSchema(Schema):
    id = fields.Int(dump_only=True)
    room_id = fields.Int(required=True)
    sender_id = fields.Int(required=True)
    content = fields.Str(required=True)
    timestamp = fields.DateTime(dump_only=True)
    is_product_share = fields.Bool(default=False)
    product_id = fields.Int(allow_none=True)


class ChatRoomSchema(Schema):
    id = fields.Int(dump_only=True)
    buyer_id = fields.Int(required=True)
    seller_id = fields.Int(required=True)
    created_at = fields.DateTime(dump_only=True)
