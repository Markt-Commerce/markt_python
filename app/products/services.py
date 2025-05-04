# project imports
from app.libs.session import session_scope
from app.libs.errors import NotFoundError

# app imports
from .models import Product


class ProductService:
    @staticmethod
    def create_product(product_data):
        with session_scope() as session:
            product = Product(**product_data)
            session.add(product)
            return product

    @staticmethod
    def get_product(product_id):
        with session_scope() as session:
            product = session.query(Product).get(product_id)
            if not product:
                raise NotFoundError("Product not found")
            return product

    # TODO: Add search, filtering, pagination
    # TODO: Add inventory management methods
