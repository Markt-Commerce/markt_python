from marshmallow import Schema, fields, validate


class AdminMeSchema(Schema):
    """The signed-in staff member's own admin standing -- a sanity/bootstrap
    endpoint the web admin can hit to render a role-scoped menu."""

    user_id = fields.Str()
    email = fields.Str()
    is_admin = fields.Bool()
    is_super_admin = fields.Bool()
    admin_role = fields.Str(allow_none=True)
    permissions = fields.List(fields.Str())


# --- §1 user management --------------------------------------------------

STATUSES = ["active", "suspended", "banned", "deactivated", "deleted"]
ROLES = ["buyer", "seller", "admin", "staff"]


class AdminUserListQuerySchema(Schema):
    q = fields.Str(required=False, metadata={"description": "Search email/username/id/phone"})
    role = fields.Str(required=False, validate=validate.OneOf(ROLES))
    status = fields.Str(required=False, validate=validate.OneOf(STATUSES))
    page = fields.Int(required=False, load_default=1)
    per_page = fields.Int(required=False, load_default=20)


class AdminUserListItemSchema(Schema):
    id = fields.Str()
    email = fields.Str()
    username = fields.Str(allow_none=True)
    phone_number = fields.Str(allow_none=True)
    profile_picture = fields.Str(allow_none=True)
    is_buyer = fields.Bool()
    is_seller = fields.Bool()
    is_admin = fields.Bool()
    admin_role = fields.Str(allow_none=True)
    email_verified = fields.Bool()
    status = fields.Str()
    created_at = fields.Str(allow_none=True)
    last_login_at = fields.Str(allow_none=True)


class AdminBuyerSubSchema(Schema):
    id = fields.Int()
    buyername = fields.Str(allow_none=True)
    is_active = fields.Bool()
    refund_preference = fields.Str(allow_none=True)


class AdminSellerSubSchema(Schema):
    id = fields.Int()
    shop_name = fields.Str(allow_none=True)
    shop_slug = fields.Str(allow_none=True)
    is_active = fields.Bool()
    verification_status = fields.Str(allow_none=True)
    market_verification_status = fields.Str(allow_none=True)


class AdminUserDetailSchema(AdminUserListItemSchema):
    is_active = fields.Bool()
    suspension_reason = fields.Str(allow_none=True)
    ban_reason = fields.Str(allow_none=True)
    suspended_at = fields.Str(allow_none=True)
    banned_at = fields.Str(allow_none=True)
    deactivated_at = fields.Str(allow_none=True)
    deleted_at = fields.Str(allow_none=True)
    buyer = fields.Nested(AdminBuyerSubSchema, allow_none=True)
    seller = fields.Nested(AdminSellerSubSchema, allow_none=True)


class AdminUserListResponseSchema(Schema):
    items = fields.List(fields.Nested(AdminUserListItemSchema))
    page = fields.Int()
    per_page = fields.Int()
    total_items = fields.Int()
    total_pages = fields.Int()


class AdminReasonSchema(Schema):
    """Body for actions that carry an optional operator reason (audited)."""

    reason = fields.Str(
        required=False, allow_none=True, validate=validate.Length(max=255)
    )


class AdminUserEditSchema(Schema):
    phone_number = fields.Str(required=False, validate=validate.Length(max=20))
    username = fields.Str(required=False, validate=validate.Length(min=1, max=50))
    profile_picture = fields.Str(required=False, validate=validate.Length(max=255))


class AdminUserRolesSchema(Schema):
    is_buyer = fields.Bool(required=False, allow_none=True)
    is_seller = fields.Bool(required=False, allow_none=True)


class AdminResendVerificationResponseSchema(Schema):
    sent = fields.Bool()
    email = fields.Str()
