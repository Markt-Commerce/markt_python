from flask_smorest import Blueprint
from flask.views import MethodView
from flask import abort, request
from ..schemas import CommentSchema, CommentRateSchema
from ..models import Comments, Seller

comment_bp = Blueprint(
    "comments",
    "comment",
    description="Endpoint for all API calls related to comments",
    url_prefix="/comments",
)


@comment_bp.route("/new")
class CreateComment(MethodView):
    @comment_bp.arguments(CommentSchema)
    @comment_bp.response(201, description="Comment created successfully.")
    def post(self, comment_data):
        try:
            comment = Comments(
                comment_title=comment_data["comment_title"],
                buyer_id=comment_data["buyer_id"],
                content=comment_data["content"],
                seller_id=comment_data["seller_id"],
                product_id=comment_data["product_id"],
            )
            comment.save_to_db()
            return {"message": "comment created successfully."}, 201
        except Exception:
            abort(500, "could not create comment")


@comment_bp.route("/rate_and_comment")
class RateAndComment(MethodView):
    @comment_bp.arguments(CommentRateSchema)
    @comment_bp.response(201, description="Comment created successfully.")
    def post(self, comment_data):
        try:
            comment = Comments(
                comment_title=comment_data["comment_title"],
                buyer_id=comment_data["buyer_id"],
                content=comment_data["content"],
                seller_id=comment_data["seller_id"],
                product_id=comment_data["product_id"],
            )
            seller = Seller.query.filter_by(unique_id=comment_data["seller_id"]).first()
            if seller is not None:
                seller.update_rating(comment_data["rating"])
            comment.save_to_db()
            return {"message": "comment created successfully."}, 201
        except Exception as e:
            abort(500, "could not create comment")


@comment_bp.route("/<product_id>")
class ProductComment(MethodView):
    @comment_bp.arguments(CommentSchema)
    @comment_bp.response(200, CommentSchema)
    def get(self, product_id):
        try:
            return [
                comments.parse_comment()
                for comments in Comments.get_product_comments(product_id)
            ]
        except Exception:
            abort(404, "not found")


@comment_bp.route("/<seller_id>")
class CommentOnSeller(MethodView):
    @comment_bp.arguments(CommentSchema)
    @comment_bp.response(200, CommentSchema)
    def get(self, seller_id):
        try:
            return [
                comments.parse_comment()
                for comments in Comments.get_seller_comments(seller_id)
            ]
        except Exception:
            abort(404, "not found")


@comment_bp.route("/<comment_id>")
class Comment(MethodView):
    @comment_bp.arguments(CommentSchema)
    @comment_bp.response(201, CommentSchema)
    def delete(self, comment_id):
        try:
            comment = Comments(comment_id=comment_id)
            comment.delete_from_db()
        except Exception:
            abort(404, "not found")
