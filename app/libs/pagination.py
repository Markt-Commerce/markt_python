from typing import Any, Dict, List, Optional, Union, TypeVar, Callable
from sqlalchemy import asc, desc, and_, or_, not_
from sqlalchemy.orm import Query
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList
from flask_smorest import abort
from math import ceil
from .schemas import FiltersSchema

# Type variables for SQLAlchemy columns and models
T = TypeVar("T")  # Model type
C = TypeVar("C")  # Column type


class Paginator:
    # Type hints for operator dictionary
    OPERATORS: Dict[
        str, Callable[[C, Any], Union[BinaryExpression, BooleanClauseList]]
    ] = {
        "eq": lambda c, v: c == v,
        "ne": lambda c, v: c != v,
        "gt": lambda c, v: c > v,
        "lt": lambda c, v: c < v,
        "gte": lambda c, v: c >= v,
        "lte": lambda c, v: c <= v,
        "in": lambda c, v: c.in_(v),
        "like": lambda c, v: c.ilike(f"%{v}%"),
        "startswith": lambda c, v: c.ilike(f"{v}%"),
        "endswith": lambda c, v: c.ilike(f"%{v}"),
        "is_null": lambda c, v: c.is_(None) if v else c.isnot(None),
    }

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
        self.filters_schema: FiltersSchema = FiltersSchema()

    def paginate(self, request_args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply pagination to the query

        Args:
            request_args: Dictionary of request arguments

        Returns:
            Dictionary containing:
            - items: List of paginated items
            - page: Current page number
            - per_page: Items per page
            - total_items: Total number of items
            - total_pages: Total number of pages
        """
        self._validate_pagination_params()

        # Parse filters from request args
        filters: Optional[Dict[str, Any]] = self._parse_filters(
            request_args.get("filters")
        )

        # Apply filters if any
        if filters:
            self._apply_filters(filters)

        # Apply sorting
        sort: Optional[str] = request_args.get("sort")
        if sort:
            self._apply_sorting(sort)
        elif hasattr(self.query.column_descriptions[0]["entity"], "created_at"):
            # Fix: Get the actual column reference instead of using string
            entity = self.query.column_descriptions[0]["entity"]
            created_at_column = getattr(entity, "created_at")
            self.query = self.query.order_by(desc(created_at_column))

        # Execute paginated query
        items: List[T] = (
            self.query.limit(self.per_page)
            .offset((self.page - 1) * self.per_page)
            .all()
        )

        total: int = self.query.order_by(None).count()

        return {
            "items": items,
            "page": self.page,
            "per_page": self.per_page,
            "total_items": total,
            "total_pages": ceil(total / self.per_page) if total else 0,
        }

    def _parse_filters(self, filters_str: Optional[str]) -> Optional[Dict[str, Any]]:
        """Parse and validate filters from string"""
        try:
            parsed: Dict[str, Any] = self.filters_schema.parse_filters(filters_str)
            return parsed
        except Exception as e:
            abort(400, message=f"Invalid filters: {str(e)}")

    def _apply_filters(self, filters: Dict[str, Any]) -> None:
        """Apply filters to query"""
        conditions: List[Union[BinaryExpression, BooleanClauseList]] = []

        for field, value in filters.items():
            if not hasattr(self.query.column_descriptions[0]["entity"], field):
                continue

            column = getattr(self.query.column_descriptions[0]["entity"], field)

            if isinstance(value, dict):
                # Handle operator syntax: {"field": {"operator": value}}
                for op, op_value in value.items():
                    if op in self.OPERATORS:
                        conditions.append(self.OPERATORS[op](column, op_value))
            else:
                # Simple equality filter
                conditions.append(self.OPERATORS["eq"](column, value))

        if conditions:
            self.query = self.query.filter(and_(*conditions))

    def _apply_sorting(self, sort_str: str) -> None:
        """Apply sorting to query"""
        sort_fields: List[str] = [s.strip() for s in sort_str.split(",") if s.strip()]
        sort_conditions: List[Union[asc, desc]] = []

        for field in sort_fields:
            if field.startswith("-"):
                direction = desc
                field_name = field[1:]
            else:
                direction = asc
                field_name = field

            if hasattr(self.query.column_descriptions[0]["entity"], field_name):
                column = getattr(
                    self.query.column_descriptions[0]["entity"], field_name
                )
                sort_conditions.append(direction(column))

        if sort_conditions:
            self.query = self.query.order_by(*sort_conditions)

    def _validate_pagination_params(self) -> None:
        """Validate pagination parameters"""
        if self.page < 1:
            abort(400, message="Page must be positive integer")

        if self.per_page < 1 or self.per_page > self.max_per_page:
            abort(400, message=f"per_page must be between 1 and {self.max_per_page}")
