from enum import Enum
from sqlalchemy import text, func, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.declarative import declared_attr

from external.database import db
from app.libs.models import BaseModel, ReactionMixin, BaseReaction, ReactionType
from app.libs.helpers import UniqueIdMixin


class FollowType(Enum):
    CUSTOMER = "customer"  # Buyer following seller
    PEER = "peer"  # Seller following another seller


class PostStatus(Enum):
    DRAFT = "draft"  # Created but not published
    ACTIVE = "active"  # Live and visible
    ARCHIVED = "archived"  # Hidden but preserved
    DELETED = "deleted"  # Deleted


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


# Niche/Community Models
class NicheStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MODERATED = "moderated"
    ARCHIVED = "archived"


class NicheVisibility(Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    RESTRICTED = "restricted"


class NicheMembershipRole(Enum):
    MEMBER = "member"
    MODERATOR = "moderator"
    ADMIN = "admin"
    OWNER = "owner"


class Niche(BaseModel, UniqueIdMixin):
    __tablename__ = "niches"
    id_prefix = "NCH_"

    id = db.Column(db.String(12), primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.Enum(NicheStatus), default=NicheStatus.ACTIVE)
    visibility = db.Column(db.Enum(NicheVisibility), default=NicheVisibility.PUBLIC)

    # Community settings
    allow_buyer_posts = db.Column(db.Boolean, default=True)
    allow_seller_posts = db.Column(db.Boolean, default=True)
    require_approval = db.Column(db.Boolean, default=False)
    max_members = db.Column(db.Integer, default=10000)

    # Metadata
    tags = db.Column(db.JSON)  # Array of tags
    rules = db.Column(db.JSON)  # Community rules
    settings = db.Column(db.JSON)  # Additional settings

    # Statistics
    member_count = db.Column(db.Integer, default=0)
    post_count = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, onupdate=db.func.now())

    # Relationships
    categories = db.relationship("NicheCategory", back_populates="niche")
    members = db.relationship(
        "NicheMembership", back_populates="niche", cascade="all, delete-orphan"
    )
    posts = db.relationship(
        "NichePost", back_populates="niche", cascade="all, delete-orphan"
    )
    moderation_actions = db.relationship(
        "NicheModerationAction", back_populates="niche", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.Index("idx_niche_slug", "slug"),
        db.Index("idx_niche_status", "status"),
        db.Index("idx_niche_visibility", "visibility"),
    )


class NicheMembership(BaseModel):
    __tablename__ = "niche_memberships"

    id = db.Column(db.Integer, primary_key=True)
    niche_id = db.Column(db.String(12), db.ForeignKey("niches.id"), nullable=False)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.Enum(NicheMembershipRole), default=NicheMembershipRole.MEMBER)

    # Membership details
    joined_at = db.Column(db.DateTime, server_default=db.func.now())
    invited_by = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    # Moderation flags
    is_banned = db.Column(db.Boolean, default=False)
    banned_until = db.Column(db.DateTime, nullable=True)
    ban_reason = db.Column(db.Text, nullable=True)

    # Activity tracking
    last_activity = db.Column(db.DateTime, server_default=db.func.now())
    post_count = db.Column(db.Integer, default=0)
    comment_count = db.Column(db.Integer, default=0)

    # Relationships
    niche = db.relationship("Niche", back_populates="members")
    user = db.relationship("User", foreign_keys=[user_id])
    inviter = db.relationship("User", foreign_keys=[invited_by])

    __table_args__ = (
        db.UniqueConstraint("niche_id", "user_id", name="uq_niche_membership"),
        db.Index("idx_niche_membership_user", "user_id"),
        db.Index("idx_niche_membership_role", "role"),
        db.Index("idx_niche_membership_active", "is_active"),
    )


class NichePost(BaseModel):
    __tablename__ = "niche_posts"

    id = db.Column(db.Integer, primary_key=True)
    niche_id = db.Column(db.String(12), db.ForeignKey("niches.id"), nullable=False)
    post_id = db.Column(db.String(12), db.ForeignKey("posts.id"), nullable=False)

    # Post status within niche
    status = db.Column(db.Enum(PostStatus), default=PostStatus.ACTIVE)
    is_pinned = db.Column(db.Boolean, default=False)
    is_featured = db.Column(db.Boolean, default=False)

    # Moderation
    is_approved = db.Column(db.Boolean, default=True)  # For communities with approval
    moderated_by = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=True)
    moderated_at = db.Column(db.DateTime, nullable=True)

    # Engagement within niche
    niche_likes = db.Column(db.Integer, default=0)
    niche_comments = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, onupdate=db.func.now())

    # Relationships
    niche = db.relationship("Niche", back_populates="posts")
    post = db.relationship("Post")
    moderator = db.relationship("User", foreign_keys=[moderated_by])

    __table_args__ = (
        db.UniqueConstraint("niche_id", "post_id", name="uq_niche_post"),
        db.Index("idx_niche_post_status", "status"),
        db.Index("idx_niche_post_pinned", "is_pinned"),
        db.Index("idx_niche_post_featured", "is_featured"),
    )


class NicheModerationAction(BaseModel):
    __tablename__ = "niche_moderation_actions"

    id = db.Column(db.Integer, primary_key=True)
    niche_id = db.Column(db.String(12), db.ForeignKey("niches.id"), nullable=False)
    moderator_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=False)
    target_user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=False)

    # Action details
    action_type = db.Column(
        db.String(50), nullable=False
    )  # ban, warn, remove_post, etc.
    reason = db.Column(db.Text, nullable=False)
    duration = db.Column(db.Interval, nullable=True)  # For temporary actions

    # Target details
    target_type = db.Column(db.String(50), nullable=False)  # user, post, comment
    target_id = db.Column(db.String(12), nullable=True)  # ID of affected content

    # Action metadata
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relationships
    niche = db.relationship("Niche", back_populates="moderation_actions")
    moderator = db.relationship("User", foreign_keys=[moderator_id])
    target_user = db.relationship("User", foreign_keys=[target_user_id])

    __table_args__ = (
        db.Index("idx_moderation_niche", "niche_id"),
        db.Index("idx_moderation_target", "target_user_id"),
        db.Index("idx_moderation_type", "action_type"),
        db.Index("idx_moderation_active", "is_active"),
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


class Post(BaseModel, UniqueIdMixin):
    __tablename__ = "posts"
    id_prefix = "PST_"

    id = db.Column(db.String(12), primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=False)
    caption = db.Column(db.Text)
    status = db.Column(db.Enum(PostStatus), default=PostStatus.DRAFT, nullable=False)

    # Categories and tags
    tags = db.Column(db.JSON)  # Array of tag strings

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relationships
    user = db.relationship("User", back_populates="posts")
    categories = db.relationship("PostCategory", back_populates="post")
    social_media = db.relationship(
        "SocialMediaPost", back_populates="post", cascade="all, delete-orphan"
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
    niche_posts = db.relationship(
        "NichePost", back_populates="post", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # User post history
        db.Index("idx_user_posts", "user_id", "created_at"),
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
        if hasattr(self, "likes") and self.likes is not None:
            return len(self.likes)
        return 0

    @like_count.expression
    def like_count(cls):
        """SQL expression for like count"""
        return (
            select(func.count(PostLike.id))
            .where(PostLike.post_id == cls.id)
            .correlate(None)
            .scalar_subquery()
        )

    @hybrid_property
    def comment_count(self):
        """Get the count of comments for this post"""
        if hasattr(self, "comments") and self.comments is not None:
            return len(self.comments)
        return 0

    @comment_count.expression
    def comment_count(cls):
        """SQL expression for comment count"""
        return (
            select(func.count(PostComment.id))
            .where(PostComment.post_id == cls.id)
            .correlate(None)
            .scalar_subquery()
        )

    def get_niche_context(self):
        """Get niche context for this post if it's posted in a niche"""
        if hasattr(self, "niche_posts") and self.niche_posts:
            niche_post = self.niche_posts[0]  # Assuming one niche per post for now
            return {
                "niche_id": niche_post.niche_id,
                "niche_name": niche_post.niche.name,
                "niche_slug": niche_post.niche.slug,
                "is_pinned": niche_post.is_pinned,
                "is_featured": niche_post.is_featured,
                "is_approved": niche_post.is_approved,
                "niche_likes": niche_post.niche_likes,
                "niche_comments": niche_post.niche_comments,
                "niche_visibility": niche_post.niche.visibility.value,
            }
        return None

    @hybrid_property
    def is_niche_post(self):
        """Check if this post is posted in a niche"""
        if hasattr(self, "niche_posts") and self.niche_posts:
            return True
        return False

    @is_niche_post.expression
    def is_niche_post(cls):
        """SQL expression to check if post is in a niche"""
        from sqlalchemy import exists

        return exists().where(NichePost.post_id == cls.id)


# PostMedia model removed - replaced by SocialMediaPost in media module


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


class PostComment(BaseModel, ReactionMixin):
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


class PostCommentReaction(BaseReaction):
    __tablename__ = "post_comment_reactions"

    comment_id = db.Column(
        db.Integer, db.ForeignKey("post_comments.id"), nullable=False
    )

    # Relationships
    @declared_attr
    def content(cls):
        return db.relationship("PostComment", back_populates="reactions")

    __table_args__ = (
        db.UniqueConstraint(
            "comment_id", "user_id", "reaction_type", name="uq_comment_reaction"
        ),
        db.Index("idx_comment_reaction_comment", "comment_id"),
        db.Index("idx_comment_reaction_user", "user_id"),
        db.Index("idx_comment_reaction_type", "reaction_type"),
    )
