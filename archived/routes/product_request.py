from flask_smorest import Blueprint
from flask.views import MethodView
from flask import abort
from flask_login import login_required, current_user

from app.schemas import ProductRequestSchema, CreateProductRequestSchema
from ..models import BuyerRequest, Seller, Buyer, User, UserAddress
from ..utils import parse_requests

product_request_bp = Blueprint(
    "Product Request",
    "request",
    description="Api calls to buyer product request apis",
    url_prefix="/product_request",
)


@product_request_bp.route("/new")
class NewProductRequest(MethodView):
    @login_required  # Ensure only authenticated users can create a product request
    @product_request_bp.arguments(CreateProductRequestSchema)
    @product_request_bp.response(
        200, description="Product request created successfully."
    )
    def post(self, product_request_data):
        try:
            # Use current_user to get the buyer_id instead of passing from the client
            request = BuyerRequest(
                buyer_id=current_user.buyer.id,  # Replace with current_user's buyer_id
                product_description=product_request_data["product_description"],
                category=product_request_data["category"],
            )
            request.save_to_db()
            return {"message": "Product request created successfully."}, 201
        except Exception as e:
            abort(500, "Could not create request")


@product_request_bp.route("/<string:unique_id>")
class ProductRequest(MethodView):
    @login_required
    @product_request_bp.response(200, ProductRequestSchema)
    def get(self, unique_id):

        buyer = Buyer.query.filter_by(unique_id=unique_id).first()
        user_details = UserAddress.query.filter_by(user_id=buyer.user_id)
        return parse_requests(
            BuyerRequest.get_requests_through_id(unique_id), buyer, user_details
        )

    @login_required
    def delete(self, unique_id):
        try:
            request_to_delete = BuyerRequest(unique_id=unique_id)
            request_to_delete.delete_from_db()
        except Exception:
            abort(500, "Could not delete product request")


@product_request_bp.route("/<string:buyer_id>")
class BuyerProductRequest(MethodView):
    @login_required
    @product_request_bp.response(200, ProductRequestSchema)
    def get(self, buyer_id):
        return [
            parse_requests(
                request=request,
                buyer=Buyer.find_by_unique_id(request.buyer_id),
                user_details=User.query.filter_by(request.buyer.user_id).first(),
            )
            for request in BuyerRequest.get_requests_through_buyer_id(buyer_id=buyer_id)
        ]  # TODO: TBD


@product_request_bp.route("/<string:seller_id>")
class SellerProductRequest(MethodView):
    @login_required
    @product_request_bp.response(200, ProductRequestSchema)
    def get(self, seller_id):
        seller = Seller.find_by_unique_id(seller_id)
        seller_category = seller.category
        return [
            parse_requests(
                request=request,
                buyer=Buyer.find_by_unique_id(request.buyer_id),
                user_details=User.query.filter_by(request.buyer.user_id).first(),
            )
            for request in BuyerRequest.get_requests_using_category(seller_category)
        ]  # TODO: TBD


@product_request_bp.route("/category/<string:name>")
class ProductRequestFromCategory(MethodView):
    @login_required
    @product_request_bp.response(200, ProductRequestSchema)
    def get(self, name):
        return [
            parse_requests(
                request=request,
                buyer=Buyer.find_by_unique_id(request.buyer_id),
                user_details=User.query.filter_by(request.buyer.user_id).first(),
            )
            for request in BuyerRequest.get_requests_using_category(name)
        ]  # TODO: TBD
