# python imports
import logging

# project imports
from external.database import db
from app.libs.session import session_scope
from app.libs.pagination import Paginator

# app imports
from .models import Category, ProductCategory, Tag, ProductTag

logger = logging.getLogger(__name__)


class CategoryService:
    @staticmethod
    def get_category_tree():
        """Get hierarchical category structure"""
        with session_scope() as session:
            root_categories = (
                session.query(Category)
                .filter(Category.parent_id.is_(None), Category.is_active.is_(True))
                .all()
            )

            def build_tree(category):
                return {
                    "id": category.id,
                    "name": category.name,
                    "slug": category.slug,
                    "image_url": category.image_url,
                    "children": [
                        build_tree(child)
                        for child in sorted(
                            [c for c in category.children if c.is_active],
                            key=lambda x: x.name,
                        )
                    ],
                }

            return [build_tree(cat) for cat in root_categories]

    @staticmethod
    def get_category(category_id):
        """Get single category with products"""
        with session_scope() as session:
            return (
                session.query(Category)
                .options(
                    db.joinedload(Category.products).joinedload(ProductCategory.product)
                )
                .get(category_id)
            )

    @staticmethod
    def create_category(category_data):
        """Create new category"""
        with session_scope() as session:
            category = Category(
                name=category_data["name"],
                description=category_data.get("description"),
                parent_id=category_data.get("parent_id"),
                is_active=category_data.get("is_active", True),
            )
            session.add(category)
            return category

    @staticmethod
    def update_category(category_id, update_data):
        """Update category details"""
        with session_scope() as session:
            category = session.query(Category).get(category_id)
            if not category:
                raise ValueError("Category not found")

            for key, value in update_data.items():
                setattr(category, key, value)

            return category


class TagService:
    @staticmethod
    def get_popular_tags(limit=20):
        """Get most used tags"""
        with session_scope() as session:
            return (
                session.query(Tag)
                .order_by(db.func.array_length(Tag.products, 1).desc())
                .limit(limit)
                .all()
            )

    @staticmethod
    def create_tag(tag_data):
        """Create new product tag"""
        with session_scope() as session:
            tag = Tag(name=tag_data["name"], description=tag_data.get("description"))
            session.add(tag)
            return tag

    @staticmethod
    def tag_product(product_id, tag_id):
        """Add tag to product"""
        with session_scope() as session:
            existing = (
                session.query(ProductTag)
                .filter_by(product_id=product_id, tag_id=tag_id)
                .first()
            )

            if not existing:
                product_tag = ProductTag(product_id=product_id, tag_id=tag_id)
                session.add(product_tag)

            return True
