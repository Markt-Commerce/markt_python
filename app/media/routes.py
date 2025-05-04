from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from werkzeug.utils import secure_filename
from .services import MediaService
from .schemas import MediaSchema

bp = Blueprint("media", __name__, description="Media operations", url_prefix="/media")


@bp.route("/upload")
class MediaUpload(MethodView):
    @bp.response(201, MediaSchema)
    def post(self):
        if "file" not in request.files:
            abort(400, message="No file uploaded")

        file = request.files["file"]
        if file.filename == "":
            abort(400, message="No selected file")

        filename = secure_filename(file.filename)
        media_service = MediaService()
        media, variants = media_service.upload_image(
            file.stream, filename, file.content_type
        )

        return media
