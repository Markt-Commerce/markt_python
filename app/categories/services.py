from app.libs.session import session_scope
from .models import Category, Tag, ProductTag
from sqlalchemy import func
from sqlalchemy.orm import joinedload


class CategoryService:
    @staticmethod
    def get_category_tree():
        with session_scope() as session:
            return session.query(Category).filter(Category.parent_id == None).all()

    @staticmethod
    def get_category_with_children(category_id):
        with session_scope() as session:
            return (
                session.query(Category)
                .options(joinedload(Category.children))
                .get(category_id)
            )


class TagService:
    @staticmethod
    def get_popular_tags(limit=20):
        with session_scope() as session:
            return (
                session.query(Tag)
                .order_by(func.count(ProductTag.tag_id).desc())
                .limit(limit)
                .all()
            )
