from typing import Any, Dict, List, Optional, TypeVar, Union
from sqlalchemy import asc, desc, and_, or_
from sqlalchemy.orm import Query
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList
from flask_smorest import abort
from math import ceil

# Type variable for SQLAlchemy model
T = TypeVar("T")


class Paginator:
    def __init__(self, query: Query[T], page: int = 1, per_page: int = 20) -> None:
        """
        Initialize paginator with SQLAlchemy query

        Args:
            query: SQLAlchemy query object
            page: Current page number (default: 1)
            per_page: Items per page (default: 20)
        """
        self.query: Query[T] = query
        self.page: int = page
        self.per_page: int = per_page
        self.max_per_page: int = 100  # Safety limit

    def paginate(
        self,
        filters: Optional[Dict[str, Union[Any, Dict[str, Any]]]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Union[List[T], int]]:
        """
        Apply pagination to the query

        Args:
            filters: Dict of filter conditions where values can be either direct values
                    or dicts for advanced operations (e.g., {"price": {"gt": 100}})
            sort: Sort criteria string (e.g. "name,-created_at")

        Returns:
            dict: Paginated response with metadata containing:
                - items: List of paginated results
                - page: Current page number
                - per_page: Items per page
                - total_items: Total items matching query
                - total_pages: Total pages available
        """
        # Validate inputs
        self._validate_pagination_params()

        # Apply filters
        if filters:
            self._apply_filters(filters)

        # Apply sorting
        if sort:
            self._apply_sorting(sort)
        else:
            # Default sort by created_at desc if available
            if hasattr(self.query.column_descriptions[0]["entity"], "created_at"):
                self.query = self.query.order_by(desc("created_at"))

        # Execute paginated query
        items: List[T] = (
            self.query.limit(self.per_page)
            .offset((self.page - 1) * self.per_page)
            .all()
        )

        # Get total count (without pagination)
        total: int = self.query.order_by(None).count()

        return {
            "items": items,
            "page": self.page,
            "per_page": self.per_page,
            "total_items": total,
            "total_pages": ceil(total / self.per_page) if total else 0,
        }

    def _validate_pagination_params(self) -> None:
        """Validate pagination parameters"""
        if self.page < 1:
            abort(400, message="Page must be positive integer")
        if self.per_page < 1 or self.per_page > self.max_per_page:
            abort(400, message=f"per_page must be between 1 and {self.max_per_page}")

    def _apply_filters(self, filters: Dict[str, Union[Any, Dict[str, Any]]]) -> None:
        """Apply filters to the query"""
        filter_conditions: List[Union[BinaryExpression, BooleanClauseList]] = []

        for field, value in filters.items():
            if not hasattr(self.query.column_descriptions[0]["entity"], field):
                continue

            column = getattr(self.query.column_descriptions[0]["entity"], field)

            if isinstance(value, dict):
                # Handle advanced filters (gt, lt, in, etc.)
                for op, op_value in value.items():
                    if op == "gt":
                        filter_conditions.append(column > op_value)
                    elif op == "lt":
                        filter_conditions.append(column < op_value)
                    elif op == "in":
                        filter_conditions.append(column.in_(op_value))
                    # Add more operations as needed
            else:
                # Simple equality filter
                filter_conditions.append(column == value)

        if filter_conditions:
            self.query = self.query.filter(and_(*filter_conditions))

    def _apply_sorting(self, sort_str: str) -> None:
        """Apply sorting to the query"""
        sort_fields: List[str] = [s.strip() for s in sort_str.split(",") if s.strip()]
        sort_conditions: List[Union[asc, desc]] = []

        for field in sort_fields:
            if field.startswith("-"):
                direction = desc
                field_name = field[1:]
            else:
                direction = asc
                field_name = field

            if not hasattr(self.query.column_descriptions[0]["entity"], field_name):
                continue

            sort_conditions.append(
                direction(
                    getattr(self.query.column_descriptions[0]["entity"], field_name)
                )
            )

        if sort_conditions:
            self.query = self.query.order_by(*sort_conditions)
