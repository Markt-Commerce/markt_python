from external.database import db
from app.libs.models import BaseModel


class Follow(BaseModel):
    __tablename__ = "follows"

    follower_id = db.Column(db.String(12), db.ForeignKey("users.id"), primary_key=True)
    followee_id = db.Column(db.String(12), db.ForeignKey("users.id"), primary_key=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class ProductLike(BaseModel):
    __tablename__ = "product_likes"

    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), primary_key=True)
    product_id = db.Column(
        db.String(12), db.ForeignKey("products.id"), primary_key=True
    )
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    product = db.relationship("Product", back_populates="likes")
    user = db.relationship("User", back_populates="product_likes")


class ProductComment(BaseModel):
    __tablename__ = "product_comments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    content = db.Column(db.Text)
    parent_id = db.Column(
        db.Integer, db.ForeignKey("product_comments.id"), nullable=True
    )

    product = db.relationship("Product", back_populates="comments")
    user = db.relationship("User", back_populates="product_comments")
    replies = db.relationship(
        "ProductComment", back_populates="parent", remote_side=[parent_id]
    )
    parent = db.relationship(
        "ProductComment", back_populates="replies", remote_side=[id]
    )


class ProductView(BaseModel):
    __tablename__ = "product_views"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=True)
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    ip_address = db.Column(db.String(45))
    viewed_at = db.Column(db.DateTime, server_default=db.func.now())

    product = db.relationship("Product", back_populates="views")


class Notification(BaseModel):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    message = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False)
    notification_type = db.Column(db.String(50))  # 'like', 'comment', 'order', etc.
    reference_id = db.Column(db.Integer)  # ID of related entity
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", back_populates="notifications")
