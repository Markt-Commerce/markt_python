from app.libs.models import BaseModel
from external.database import db


class AdminAuditLog(BaseModel):
    """Append-only record of every staff action against the admin surface.

    Nearly all admin actions are money- or trust-sensitive and mostly
    irreversible, so each one writes a row here: who did it, to what, why, and
    the before/after of whatever changed. Written inside the same transaction
    as the action it describes (see AdminAuditService.record) so an action and
    its audit row commit or roll back together -- there is no "did it but did
    not log it" state.

    Never updated or deleted in normal operation; there is deliberately no
    service method to mutate a row.
    """

    __tablename__ = "admin_audit_logs"

    id = db.Column(db.Integer, primary_key=True)

    # The staff member who acted. Kept as a plain column (not a FK cascade
    # target) so purging a user never erases the audit trail of what they did.
    actor_id = db.Column(
        db.String(12), db.ForeignKey("users.id"), nullable=False, index=True
    )
    # Their role at the time of the action, captured because a role can change
    # later and the audit trail must reflect the authority actually used.
    actor_role = db.Column(db.String(32), nullable=True)

    # Namespaced action string, e.g. "seller.verify" -- mirrors the permission
    # that gated it (app.admin.permissions.Permission).
    action = db.Column(db.String(64), nullable=False, index=True)

    # What was acted on. Polymorphic by (type, id) for the same reason the
    # moderation ContentReport is: a single pair beats a nullable FK per domain.
    target_type = db.Column(db.String(40), nullable=True, index=True)
    target_id = db.Column(db.String(64), nullable=True, index=True)

    reason = db.Column(db.Text, nullable=True)

    # Snapshots of the changed fields only (not whole rows) as JSON, so a later
    # reader can see exactly what a mutation did without a second lookup.
    before = db.Column(db.JSON, nullable=True)
    after = db.Column(db.JSON, nullable=True)

    ip_address = db.Column(db.String(45), nullable=True)

    actor = db.relationship("User", foreign_keys=[actor_id])

    __table_args__ = (
        db.Index("ix_admin_audit_target", "target_type", "target_id"),
        db.Index("ix_admin_audit_actor_created", "actor_id", "created_at"),
    )
