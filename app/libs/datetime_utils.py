"""
Datetime utilities for timezone handling and date comparisons
Handles offset-naive vs offset-aware datetime issues
"""
from datetime import datetime, timezone
from typing import Union, Optional


def ensure_timezone_aware(
    dt: Union[datetime, str], default_tz=timezone.utc
) -> datetime:
    """
    Ensure a datetime object is timezone-aware

    Args:
        dt: datetime object or ISO string that needs to be timezone-aware
        default_tz: timezone to use if dt is naive (defaults to UTC)

    Returns:
        timezone-aware datetime object

    Example:
        >>> ensure_timezone_aware(datetime.utcnow())
        >>> ensure_timezone_aware("2025-09-27T12:00:00Z")
        >>> ensure_timezone_aware(datetime.now(timezone.utc))
    """
    if isinstance(dt, str):
        # Handle ISO string format
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))

    # If already timezone-aware, return as-is
    if dt.tzinfo is not None:
        return dt

    # Convert naive datetime to timezone-aware
    return dt.replace(tzinfo=default_tz)


def utcnow_aware() -> datetime:
    """
    Get current UTC time as timezone-aware datetime

    Returns:
        Current UTC time as timezone-aware datetime

    Example:
        >>> now = utcnow_aware()
        >>> expires_at = ensure_timezone_aware("2025-12-31T23:59:59Z")
        >>> print(expires_at > now)
        True
    """
    return datetime.utcnow().replace(tzinfo=timezone.utc)


def safe_datetime_compare(
    dt1: Union[datetime, str], dt2: Union[datetime, str], operator: str
) -> bool:
    """
    Safely compare two datetime objects regardless of timezone awareness

    Args:
        dt1: First datetime (supports string/object)
        dt2: Second datetime (supports string/object)
        operator: Comparison operator ("gt", "lt", "eq", "gte", "lte", "ne")

    Returns:
        Boolean result of the comparison

    Example:
        >>> result = safe_datetime_compare("2025-12-31T00:00:00Z", datetime.utcnow(), "gt")
        >>> safe_datetime_compare(expires, datetime.utcnow(), "lte")
    """
    dt1_aware = ensure_timezone_aware(dt1)
    dt2_aware = ensure_timezone_aware(dt2)

    op_map = {
        "gt": dt1_aware > dt2_aware,
        "lt": dt1_aware < dt2_aware,
        "eq": dt1_aware == dt2_aware,
        "gte": dt1_aware >= dt2_aware,
        "lte": dt1_aware <= dt2_aware,
        "ne": dt1_aware != dt2_aware,
    }

    if operator not in op_map:
        raise ValueError(
            f"Invalid operator: {operator}. Use one of: {list(op_map.keys())}"
        )

    return op_map[operator]


def is_past_datetime(dt: Union[datetime, str]) -> bool:
    """
    Check if a datetime is in the past (timezone-aware comparison)

    Args:
        dt: datetime to check

    Returns:
        True if datetime is in the past, False otherwise
    """
    return safe_datetime_compare(dt, utcnow_aware(), "lt")


def is_future_datetime(dt: Union[datetime, str]) -> bool:
    """
    Check if a datetime is in the future (timezone-aware comparison)

    Args:
        dt: datetime to check

    Returns:
        True if datetime is in the future, False otherwise
    """
    return safe_datetime_compare(dt, utcnow_aware(), "gt")


class TimezoneAware:
    """
    Context manager and utility class for handling datetime operations
    """

    @staticmethod
    def prepare_for_db(dt: Union[datetime, str, None]) -> Optional[datetime]:
        """
        Prepare datetime for database storage with consistent timezone handling

        Args:
            dt: datetime to be stored (null-safe)

        Returns:
            timezone-aware datetime or None
        """
        if dt is None:
            return None
        return ensure_timezone_aware(dt)

    @staticmethod
    def serialize_for_json(dt: datetime) -> str:
        """
        Convert datetime to JSON-serializable ISO string

        Args:
            dt: datetime object

        Returns:
            ISO format string
        """
        if dt is None:
            return None
        return dt.isoformat()

    @staticmethod
    def create_with_timezone(
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        tzinfo: Optional[timezone] = None,
    ) -> datetime:
        """
        Create timezone-aware datetime with specified values

        Args:
            year, month, day, hour, minute, second: datetime components
            tzinfo: timezone info (defaults to UTC if None)

        Returns:
            timezone-aware datetime object
        """
        dt = datetime(year, month, day, hour, minute, second)
        if tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.replace(tzinfo=tzinfo)
