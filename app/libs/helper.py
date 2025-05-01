import string
import random
from sqlalchemy import event
from external.database import db


def generate_random_string(length=8):
    """Generate a random alphanumeric string"""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def get_unique_id(model_class, field="id", length=8, max_attempts=100):
    """
    Generate a unique ID and ensure no collision for any model
    Args:
        model_class: SQLAlchemy model class to check against
        field: Field name to check uniqueness (default 'id')
        length: Length of generated ID
        max_attempts: Maximum attempts to try before raising error
    """
    for _ in range(max_attempts):
        _id = generate_random_string(length)
        if (
            not db.session.query(model_class)
            .filter(getattr(model_class, field) == _id)
            .first()
        ):
            return _id
    raise ValueError(f"Failed to generate unique ID after {max_attempts} attempts")


class UniqueIdMixin:
    """Mixin to add unique string ID generation"""

    id_prefix = None  # Should be defined in subclass

    @classmethod
    def __declare_last__(cls):
        """Hook into SQLAlchemy after mappings are complete."""

        @event.listens_for(cls, "before_insert")
        def _set_unique_id(mapper, connection, target):
            if not target.id and target.id_prefix:
                target.id = f"{target.id_prefix}{get_unique_id(cls)}"

    __abstract__ = True
