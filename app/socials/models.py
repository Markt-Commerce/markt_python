from enum import Enum
from sqlalchemy import text, func, select
from sqlalchemy.ext.hybrid import hybrid_property

from external.database import db
from app.libs.models import BaseModel
from app.libs.helpers import UniqueIdMixin


class FollowType(Enum):
    CUSTOMER = "customer"  # Buyer following seller
    PEER = "peer"  # Seller following another seller


class Follow(BaseModel):
    __tablename__ = "follows"
    follower_id = db.Column(db.String(12), db.ForeignKey("users.id"), primary_key=True)
    followee_id = db.Column(db.String(12), db.ForeignKey("users.id"), primary_key=True)
    follow_type = db.Column(db.Enum(FollowType))
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (db.Index("idx_followee_follower", "followee_id", "follower_id"),)

    follower = db.relationship(
        "User", foreign_keys=[follower_id], back_populates="following"
    )
    followee = db.relationship(
        "User", foreign_keys=[followee_id], back_populates="followers"
    )


class ProductReview(BaseModel):
    __tablename__ = "product_reviews"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    order_id = db.Column(
        db.String(12), db.ForeignKey("orders.id"), nullable=True
    )  # Optional purchase verification
    rating = db.Column(db.Integer)  # 1-5, nullable for questions
    title = db.Column(db.String(100))
    content = db.Column(db.Text)
    upvotes = db.Column(db.Integer, default=0)
    is_verified = db.Column(db.Boolean, default=False)

    # Relationships
    user = db.relationship("User", back_populates="product_reviews")
    product = db.relationship("Product", back_populates="reviews")
    order = db.relationship("Order")


class ProductView(BaseModel):
    __tablename__ = "product_views"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=True)
    product_id = db.Column(db.String(12), db.ForeignKey("products.id"))
    ip_address = db.Column(db.String(45))
    viewed_at = db.Column(db.DateTime, server_default=db.func.now())

    product = db.relationship("Product", back_populates="views")


class PostStatus(Enum):
    DRAFT = "draft"  # Created but not published
    ACTIVE = "active"  # Live and visible
    ARCHIVED = "archived"  # Hidden but preserved
    DELETED = "deleted"  # Deleted


class Post(BaseModel, UniqueIdMixin):
    __tablename__ = "posts"
    id_prefix = "PST_"

    id = db.Column(db.String(12), primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("sellers.id"))
    caption = db.Column(db.Text)
    status = db.Column(db.Enum(PostStatus), default=PostStatus.DRAFT, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relationships
    seller = db.relationship("Seller", back_populates="posts")
    media = db.relationship(
        "PostMedia", back_populates="post", cascade="all, delete-orphan"
    )
    tagged_products = db.relationship(
        "PostProduct", back_populates="post", cascade="all, delete-orphan"
    )
    likes = db.relationship(
        "PostLike", back_populates="post", cascade="all, delete-orphan"
    )
    comments = db.relationship(
        "PostComment", back_populates="post", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Seller post history
        db.Index("idx_seller_posts", "seller_id", "created_at"),
        # Full-text search for captions - using text() to handle REGCONFIG
        db.Index(
            "idx_post_search",
            text("to_tsvector('english', caption)"),
            postgresql_using="gin",
        ),
    )

    # Computed count properties
    @hybrid_property
    def like_count(self):
        """Get the count of likes for this post"""
        return len(self.likes) if self.likes else 0

    @like_count.expression
    def like_count(cls):
        """SQL expression for like count"""
        return (
            select(func.count(PostLike.id))
            .where(PostLike.post_id == cls.id)
            .correlate(cls)
            .scalar_subquery()
        )

    @hybrid_property
    def comment_count(self):
        """Get the count of comments for this post"""
        return len(self.comments) if self.comments else 0

    @comment_count.expression
    def comment_count(cls):
        """SQL expression for comment count"""
        return (
            select(func.count(PostComment.id))
            .where(PostComment.post_id == cls.id)
            .correlate(cls)
            .scalar_subquery()
        )


class PostMedia(BaseModel):
    __tablename__ = "post_media"
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.String(12), db.ForeignKey("posts.id"))
    media_url = db.Column(db.String(255))
    media_type = db.Column(db.String(20))  # 'image', 'video'
    sort_order = db.Column(db.Integer, default=0)

    post = db.relationship("Post", back_populates="media")


class PostProduct(BaseModel):
    __tablename__ = "post_products"
    post_id = db.Column(db.String(12), db.ForeignKey("posts.id"), primary_key=True)
    product_id = db.Column(
        db.String(12), db.ForeignKey("products.id"), primary_key=True
    )

    post = db.relationship("Post", back_populates="tagged_products")
    product = db.relationship("Product")


class PostLike(BaseModel):
    __tablename__ = "post_likes"
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), primary_key=True)
    post_id = db.Column(db.String(12), db.ForeignKey("posts.id"), primary_key=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    post = db.relationship("Post", back_populates="likes")
    user = db.relationship("User")


class PostComment(BaseModel):
    __tablename__ = "post_comments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"))
    post_id = db.Column(db.String(12), db.ForeignKey("posts.id"))
    content = db.Column(db.Text)
    parent_id = db.Column(db.Integer, db.ForeignKey("post_comments.id"), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    post = db.relationship("Post", back_populates="comments")
    user = db.relationship("User")
    replies = db.relationship(
        "PostComment", back_populates="parent", remote_side=[parent_id]
    )
    parent = db.relationship("PostComment", back_populates="replies", remote_side=[id])
