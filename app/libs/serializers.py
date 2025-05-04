from datetime import datetime
from uuid import UUID
import json


class EnhancedJSONEncoder(json.JSONEncoder):
    """Handles common Python to JSON conversions"""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


def model_to_dict(model, exclude=None):
    """Convert SQLAlchemy model to dict with enhanced serialization"""
    if exclude is None:
        exclude = []
    return {
        c.name: getattr(model, c.name)
        for c in model.__table__.columns
        if c.name not in exclude
    }
