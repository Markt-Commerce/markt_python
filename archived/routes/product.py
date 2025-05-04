from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import request
from flask_login import login_required, current_user

from ..schemas import ProductSchema, CreateProductSchema, CategorySchema

from ..models import (
    Product,
    ImageNameStore,
    get_all_categories_and_tags,
    get_all_tags,
    get_all_tags_in_category,
    get_category_names,
)
from ..utils import parse_dict, ImageSaver
import tempfile

product_bp = Blueprint(
    "products",
    "product",
    description="Endpoint for all API calls related to products",
    url_prefix="/products",
)


@product_bp.route("/new")
class Products(MethodView):
    @login_required  # Ensure only authenticated users can create a product
    @product_bp.arguments(CreateProductSchema)
    @product_bp.response(201, description="product created successfully")
    def post(self, product_data):
        """
        Creates a new product
        Args: product_data (_dict_): a dictionary containing information about the product
        Returns:_dict_ | bool: the product
        """
        try:
            # Use current_user to get the seller_id instead of passing from the client
            product = Product(
                seller_id=current_user.seller.id,  # Replace with current_user's seller_id
                name=product_data["name"],
                description=product_data["description"],
                price=product_data["price"],
                stock_quantity=product_data["stock_quantity"],
                category=product_data["category"],
            )
            product.set_product_id()
            product_images = request.files
            for key, file in product_images.items():
                if (
                    ImageSaver.is_valid_file(file.filename)
                    and ImageSaver.is_valid_file_size(file.content_length)
                    and ImageSaver.is_valid_mime(file.mimetype)
                ):
                    location = tempfile.gettempdir() + "/" + file.filename
                    saved_image_name = ImageSaver.compress_image_and_remove_background(
                        location
                    )
                    if saved_image_name is not False and type(saved_image_name) == str:
                        new_image = ImageNameStore(
                            saved_image_name, "products", product.product_id
                        )
                        new_image.save_to_db()
            product.save_to_db()
            return parse_dict(product=product, images=list(product_images)), 200

        except Exception as e:
            abort(500, message="An error occurred processing your request " + str(e))


@product_bp.route("/<string:product_id>")
class Products(MethodView):
    @product_bp.response(200, ProductSchema)
    def get(self, product_id):
        """
        gets a particular product using its id, along with its images
        seller description, e.t.c
        """
        product = Product.get_product_using_id(product_id)

        return parse_dict(
            product=product,
            images=ImageNameStore.getproductimages(product_id=product_id),
        )

    # edit product
    @login_required
    @product_bp.response(201, ProductSchema)
    def put(self, product_id, product_data):
        """
        product_data is a dictionary containing the product data to update
        """
        try:
            product = Product(product_id=product_id)
            return product.update_product(product_data)
        except Exception:
            abort(404, message="Item not found.")

    @login_required
    @product_bp.response(200, ProductSchema)
    def delete(self, product_id):
        try:
            product_to_delete = Product.query.filter_by(product_id=product_id).first()
            product_to_delete.delete_from_db()
            return True
        except Exception:
            abort(404, message="Item not found.")


@product_bp.route("/categories/<type>")
class Categories(MethodView):
    @product_bp.response(200, CategorySchema)
    def get(self, type):
        """
        gets a
        """
        # Response.headers.add("Access-Control-Allow-Origin", "*")
        # Response.headers.add("Access-Control-Allow-Headers", "*")
        # Response.headers.add("Access-Control-Allow-Methods", "*")
        match type:
            case "tags":
                return get_all_tags()
            case "categorynames":
                return get_category_names()
            case "all":
                return get_all_categories_and_tags()
            case _:
                return get_all_categories_and_tags()


@product_bp.route("/random/<int:amount>")
class RandomProducts(MethodView):
    @product_bp.response(200, ProductSchema)
    def get(self, amount):
        return [
            parse_dict(
                product=product,
                images=[ImageNameStore.get_product_thumbnail(product.product_id)],
            )
            for product in Product.get_random_products(amount)
        ]


@product_bp.route("/seller/<string:seller_id>")
class SellerProducts(MethodView):
    @product_bp.response(200, ProductSchema)
    def get(self, seller_id):
        return [
            parse_dict(
                product=product,
                images=ImageNameStore.get_product_thumbnail(product.product_id),
            )
            for product in Product.get_products_using_sellerid(seller_id)
        ]


@product_bp.route("/search/<string:name>")
class ProductSearch(MethodView):
    @product_bp.response(200, ProductSchema)
    def get(self, name):
        return [
            parse_dict(
                product=product,
                images=ImageNameStore.get_product_thumbnail(product.product_id),
            )
            for product in Product.search_product_using_name(name)
        ]


@product_bp.route("/category/search/<string:name>")
class ProductSearch(MethodView):
    @product_bp.response(200, ProductSchema)
    def get(self, name):
        return [
            parse_dict(
                product=product,
                images=ImageNameStore.get_product_thumbnail(product.product_id),
            )
            for product in Product.search_product_using_category(name)
        ]


# TODO: searchproductwithcategory
