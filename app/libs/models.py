from datetime import datetime
from sqlalchemy.ext.declarative import declared_attr
from external.database import db
from enum import Enum


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class StatusMixin:
    """Adds a status column that uses an Enum defined in the model class"""

    __abstract__ = True

    @declared_attr
    def status(cls):
        status_enum = cls.Status
        default_value = next(iter(status_enum))  # First enum member
        # Create a unique enum name based on the table name
        enum_name = f"{cls.__tablename__}_status"

        return db.Column(
            db.Enum(status_enum, name=enum_name), default=default_value, nullable=False
        )


class ReactionMixin:
    """Mixin to add reaction functionality to any model"""

    __abstract__ = True

    @declared_attr
    def reactions(cls):
        """Relationship to reactions for this model"""
        return db.relationship(
            f"{cls.__name__}Reaction",
            back_populates="content",
            cascade="all, delete-orphan",
        )


class ReactionType(Enum):
    """Base reaction types - can be extended by specific modules"""

    THUMBS_UP = "THUMBS_UP"
    THUMBS_DOWN = "THUMBS_DOWN"
    HEART = "HEART"
    FIRE = "FIRE"
    STAR = "STAR"
    MONEY = "MONEY"
    SHOPPING = "SHOPPING"
    CHECK = "CHECK"
    EYES = "EYES"
    CLAP = "CLAP"
    ROCKET = "ROCKET"
    SMILE = "SMILE"


class BaseModel(db.Model, TimestampMixin):
    __abstract__ = True

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class BaseReaction(BaseModel):
    """Base reaction model that can be inherited by specific reaction models"""

    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(12), db.ForeignKey("users.id"), nullable=False)
    reaction_type = db.Column(db.Enum(ReactionType), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relationships
    @declared_attr
    def user(cls):
        return db.relationship("User")

    @declared_attr
    def content(cls):
        """Relationship to the content this reaction belongs to"""
        # This will be overridden by concrete classes
        return None

    def __repr__(self):
        return f"<{self.__class__.__name__}(user_id={self.user_id}, reaction_type={self.reaction_type.value})>"
