from marshmallow import Schema, fields, validate, validates, ValidationError
from datetime import datetime

from app.business.constants import UNIT_KEYS

# import pytz

from app.categories.schemas import CategorySchema
from app.libs.schemas import PaginationSchema

# app imports
from .models import RequestStatus, OfferStatus


class SellerOfferSchema(Schema):
    """Schema for seller offers"""

    id = fields.Int(dump_only=True)
    request_id = fields.Str(dump_only=True)
    seller_id = fields.Int(dump_only=True)
    product_id = fields.Str(allow_none=True)
    price = fields.Float(validate=validate.Range(min=0))
    message = fields.Str(validate=validate.Length(max=1000))
    proposed_quantity = fields.Float(allow_none=True, dump_only=True)
    status = fields.Enum(OfferStatus, dump_only=True)
    created_at = fields.DateTime(dump_only=True)

    # Nested relationships
    seller = fields.Nested("SellerSchema", dump_only=True)
    product = fields.Nested("ProductSchema", dump_only=True)


class SellerOfferCreateSchema(Schema):
    """Schema for creating seller offers"""

    product_id = fields.Str(allow_none=True)
    price = fields.Float(required=True, validate=validate.Range(min=0))
    message = fields.Str(validate=validate.Length(max=1000))
    proposed_quantity = fields.Float(allow_none=True, validate=validate.Range(min=0))


class ProcurementFieldsMixin(Schema):
    """Markt Business procurement details. Optional on every request; a
    business account's request is a procurement request whether or not it
    fills them in."""

    quantity = fields.Float(allow_none=True, validate=validate.Range(min=0))
    unit = fields.Str(allow_none=True)
    specifications = fields.Dict(
        keys=fields.Str(), values=fields.Str(), allow_none=True
    )
    delivery_location = fields.Str(allow_none=True, validate=validate.Length(max=255))
    required_delivery_date = fields.Date(allow_none=True)

    @validates("unit")
    def validate_unit(self, value, **kwargs):
        if value and value not in UNIT_KEYS:
            raise ValidationError(f"Unknown unit: {value}")


class BuyerRequestSchema(Schema):
    """Schema for buyer requests"""

    id = fields.Str(dump_only=True)
    user_id = fields.Str(dump_only=True)
    title = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    description = fields.Str(required=True, validate=validate.Length(min=10, max=2000))
    budget = fields.Float(validate=validate.Range(min=0))
    status = fields.Enum(RequestStatus, dump_only=True)
    request_metadata = fields.Dict(dump_only=True)
    is_business = fields.Bool(dump_only=True)
    quantity = fields.Float(allow_none=True, dump_only=True)
    unit = fields.Str(allow_none=True, dump_only=True)
    specifications = fields.Dict(allow_none=True, dump_only=True)
    delivery_location = fields.Str(allow_none=True, dump_only=True)
    required_delivery_date = fields.Date(allow_none=True, dump_only=True)
    expires_at = fields.DateTime(dump_only=True)
    upvotes = fields.Int(dump_only=True)
    views = fields.Int(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    # Nested relationships
    user = fields.Nested("UserSchema", dump_only=True)
    categories = fields.Method("get_categories", dump_only=True)

    def get_categories(self, obj):
        """Extract category data from RequestCategory objects"""
        if hasattr(obj, "categories") and obj.categories:
            from app.categories.schemas import CategorySchema

            category_schema = CategorySchema()
            return [
                category_schema.dump(request_category.category)
                for request_category in obj.categories
                if request_category.category
            ]
        return []

    images = fields.Nested("RequestImageSchema", many=True, dump_only=True)
    offers = fields.Nested(SellerOfferSchema, many=True, dump_only=True)
    media_ids = fields.List(fields.Int(), dump_only=True)


class BuyerRequestSearchResultSchema(Schema):
    items = fields.List(fields.Nested(BuyerRequestSchema))
    pagination = fields.Nested(PaginationSchema)


class BuyerRequestCreateSchema(ProcurementFieldsMixin):
    """Schema for creating buyer requests"""

    title = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    description = fields.Str(required=True, validate=validate.Length(min=10, max=2000))
    category_ids = fields.List(fields.Int(), allow_none=True)
    budget = fields.Float(validate=validate.Range(min=0))
    expires_at = fields.DateTime(allow_none=True)
    metadata = fields.Dict(allow_none=True)
    media_ids = fields.List(
        fields.Int(), description="List of media IDs to link to request"
    )
    # Note: Images can also be uploaded separately via media endpoints

    @validates("expires_at")
    def validate_expires_at(self, value):
        if value:
            # Convert to UTC naive datetime for comparison
            if value.tzinfo is not None:
                value = value.replace(tzinfo=None)

            current_time = datetime.utcnow()
            if value <= current_time:
                raise ValidationError("Expiration date must be in the future")


class BuyerRequestUpdateSchema(ProcurementFieldsMixin):
    """Schema for updating buyer requests"""

    title = fields.Str(validate=validate.Length(min=1, max=100))
    description = fields.Str(validate=validate.Length(min=10, max=2000))
    category_ids = fields.List(fields.Int(), allow_none=True)
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
    category_ids = fields.List(fields.Int(), allow_none=True)
    min_budget = fields.Float(validate=validate.Range(min=0), allow_none=True)
    max_budget = fields.Float(validate=validate.Range(min=0), allow_none=True)
    status = fields.Enum(RequestStatus, allow_none=True)
    # True: procurement requests from business accounts only. False: consumer
    # requests only. Absent: both, as before.
    is_business = fields.Bool(allow_none=True)
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
