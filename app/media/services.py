import boto3
from io import BytesIO
from PIL import Image
from main.config import settings
from .models import Media, MediaVariant, MediaType
from .errors import MediaUploadError


class MediaService:
    def __init__(self):
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY,
            aws_secret_access_key=settings.AWS_SECRET_KEY,
            region_name=settings.AWS_REGION,
        )
        self.bucket = settings.AWS_S3_BUCKET

    def upload_image(self, file_stream, filename, content_type):
        """Upload and process image"""
        try:
            # Upload original
            original_key = f"originals/{filename}"
            self.s3.upload_fileobj(
                file_stream,
                self.bucket,
                original_key,
                ExtraArgs={"ContentType": content_type},
            )

            # Create media record
            with Image.open(file_stream) as img:
                width, height = img.size

            media = Media(
                storage_key=original_key,
                media_type=MediaType.IMAGE,
                mime_type=content_type,
                width=width,
                height=height,
                file_size=file_stream.getbuffer().nbytes,
            )

            # Generate variants
            variants = self._generate_variants(file_stream, filename)

            return media, variants

        except Exception as e:
            raise MediaUploadError(str(e))

    def _generate_variants(self, file_stream, filename):
        """Generate different image sizes"""
        variants = []
        sizes = [
            (MediaVariant.THUMBNAIL, (300, 300)),
            (MediaVariant.MEDIUM, (800, 800)),
            (MediaVariant.LARGE, (1200, 1200)),
        ]

        for variant_type, dimensions in sizes:
            with Image.open(file_stream) as img:
                img.thumbnail(dimensions)
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                buffer.seek(0)

                key = f"{variant_type.value}/{filename}"
                self.s3.upload_fileobj(
                    buffer, self.bucket, key, ExtraArgs={"ContentType": "image/jpeg"}
                )

                variants.append(
                    MediaVariant(
                        variant_type=variant_type,
                        storage_key=key,
                        width=img.width,
                        height=img.height,
                    )
                )

        return variants
