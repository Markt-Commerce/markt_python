from marshmallow import Schema, fields, validate, validates, ValidationError
from datetime import datetime

# import pytz

from app.categories.schemas import CategorySchema
from app.libs.schemas import PaginationSchema

# app imports
from .models import RequestStatus


class RequestImageSchema(Schema):
    """Schema for request images"""

    id = fields.Int(dump_only=True)
    url = fields.Str(required=True, validate=validate.URL())
    is_primary = fields.Bool(allow_none=True)


class SellerOfferSchema(Schema):
    """Schema for seller offers"""

    id = fields.Int(dump_only=True)
    request_id = fields.Str(dump_only=True)
    seller_id = fields.Int(dump_only=True)
    product_id = fields.Str(allow_none=True)
    price = fields.Float(validate=validate.Range(min=0))
    message = fields.Str(validate=validate.Length(max=1000))
    status = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)

    # Nested relationships
    seller = fields.Nested("SellerSchema", dump_only=True)
    product = fields.Nested("ProductSchema", dump_only=True)


class SellerOfferCreateSchema(Schema):
    """Schema for creating seller offers"""

    product_id = fields.Str(allow_none=True)
    price = fields.Float(required=True, validate=validate.Range(min=0))
    message = fields.Str(validate=validate.Length(max=1000))


class BuyerRequestSchema(Schema):
    """Schema for buyer requests"""

    id = fields.Str(dump_only=True)
    user_id = fields.Str(dump_only=True)
    title = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    description = fields.Str(required=True, validate=validate.Length(min=10, max=2000))
    category_id = fields.Int(allow_none=True)
    budget = fields.Float(validate=validate.Range(min=0))
    status = fields.Enum(RequestStatus, dump_only=True)
    request_metadata = fields.Dict(dump_only=True)
    expires_at = fields.DateTime(dump_only=True)
    upvotes = fields.Int(dump_only=True)
    views = fields.Int(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    # Nested relationships
    user = fields.Nested("UserSchema", dump_only=True)
    category = fields.Nested("CategorySchema", dump_only=True)
    images = fields.Nested(RequestImageSchema, many=True, dump_only=True)
    offers = fields.Nested(SellerOfferSchema, many=True, dump_only=True)


class BuyerRequestSearchResultSchema(Schema):
    items = fields.List(fields.Nested(BuyerRequestSchema))
    pagination = fields.Nested(PaginationSchema)


class BuyerRequestCreateSchema(Schema):
    """Schema for creating buyer requests"""

    title = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    description = fields.Str(required=True, validate=validate.Length(min=10, max=2000))
    category_id = fields.Int(allow_none=True)
    budget = fields.Float(validate=validate.Range(min=0))
    expires_at = fields.DateTime(allow_none=True)
    metadata = fields.Dict(allow_none=True)
    images = fields.Nested(RequestImageSchema, many=True, allow_none=True)

    @validates("expires_at")
    def validate_expires_at(self, value):
        if value:
            # Convert to UTC naive datetime for comparison
            if value.tzinfo is not None:
                value = value.replace(tzinfo=None)

            current_time = datetime.utcnow()
            if value <= current_time:
                raise ValidationError("Expiration date must be in the future")


class BuyerRequestUpdateSchema(Schema):
    """Schema for updating buyer requests"""

    title = fields.Str(validate=validate.Length(min=1, max=100))
    description = fields.Str(validate=validate.Length(min=10, max=2000))
    category_id = fields.Int(allow_none=True)
    budget = fields.Float(validate=validate.Range(min=0))
    expires_at = fields.DateTime(allow_none=True)
    metadata = fields.Dict(allow_none=True)

    @validates("expires_at")
    def validate_expires_at(self, value):
        if value:
            # Convert to UTC naive datetime for comparison
            if value.tzinfo is not None:
                value = value.replace(tzinfo=None)

            current_time = datetime.utcnow()
            if value <= current_time:
                raise ValidationError("Expiration date must be in the future")


class BuyerRequestSearchSchema(Schema):
    """Schema for searching buyer requests"""

    search = fields.Str(allow_none=True)
    category_id = fields.Int(allow_none=True)
    min_budget = fields.Float(validate=validate.Range(min=0), allow_none=True)
    max_budget = fields.Float(validate=validate.Range(min=0), allow_none=True)
    status = fields.Enum(RequestStatus, allow_none=True)
    page = fields.Int(validate=validate.Range(min=1), missing=1)
    per_page = fields.Int(validate=validate.Range(min=1, max=100), missing=20)

    @validates("max_budget")
    def validate_max_budget(self, value, **kwargs):
        min_budget = kwargs.get("data", {}).get("min_budget")
        if value and min_budget and value < min_budget:
            raise ValidationError("max_budget must be greater than min_budget")


class RequestStatusUpdateSchema(Schema):
    """Schema for updating request status"""

    status = fields.Enum(RequestStatus, required=True)


class RequestUpvoteSchema(Schema):
    """Schema for request upvotes"""

    upvotes = fields.Int(dump_only=True)


# Legacy schema for backward compatibility
class RequestSchema(BuyerRequestSchema):
    """Legacy schema alias"""
