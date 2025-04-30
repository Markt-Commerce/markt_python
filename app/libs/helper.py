import string
import random
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

    id_prefix = None  # Should be overridden by subclasses

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.id and self.id_prefix:
            self.id = f"{self.id_prefix}{get_unique_id(self.__class__)}"

    __abstract__ = True
