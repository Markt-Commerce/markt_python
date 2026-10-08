from marshmallow import Schema, fields


class FulfilmentAllocationSchema(Schema):
    id = fields.Int(dump_only=True)
    order_item_id = fields.Int(dump_only=True)
    seller_id = fields.Int(dump_only=True)
    quantity = fields.Int(dump_only=True)
    status = fields.Str(dump_only=True)
    seller_response_deadline = fields.DateTime(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
