from datetime import datetime
from sqlalchemy.ext.declarative import declared_attr
from external.database import db


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


class BaseModel(db.Model, TimestampMixin):
    __abstract__ = True

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
