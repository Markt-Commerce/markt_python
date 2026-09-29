from marshmallow import Schema, fields


class AdminMeSchema(Schema):
    """The signed-in staff member's own admin standing -- a sanity/bootstrap
    endpoint the web admin can hit to render a role-scoped menu."""

    user_id = fields.Str()
    email = fields.Str()
    is_admin = fields.Bool()
    is_super_admin = fields.Bool()
    admin_role = fields.Str(allow_none=True)
    permissions = fields.List(fields.Str())
