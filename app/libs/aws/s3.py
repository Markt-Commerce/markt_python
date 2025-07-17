import logging
import boto3
import os
from typing import Any, Dict, Optional
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
from io import BytesIO
from PIL import Image
import mimetypes
from datetime import datetime

from main.config import settings

logger = logging.getLogger(__name__)


class S3Service:
    """S3 service for handling media uploads and management"""

    def __init__(self):
        """Initialize S3 client with credentials from settings"""
        try:
            self.s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY,
                aws_secret_access_key=settings.AWS_SECRET_KEY,
                region_name=settings.AWS_REGION,
            )
            self.bucket = settings.AWS_S3_BUCKET
            self.cdn_domain = getattr(settings, "CDN_DOMAIN", None)
            self.default_acl = "public-read"

        except (NoCredentialsError, PartialCredentialsError) as e:
            logger.error(f"AWS credentials not found: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            raise

    def upload_file(
        self,
        file_path: str,
        bucket_name: str,
        s3_key: str,
        content_type: Optional[str] = None,
        acl: str = None,
    ) -> str:
        """
        Upload a file to S3

        Args:
            file_path: Local path to the file
            bucket_name: S3 bucket name
            s3_key: S3 object key
            content_type: MIME type of the file
            acl: Access control list (default: public-read)

        Returns:
            S3 URL of the uploaded file
        """
        try:
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
            if acl:
                extra_args["ACL"] = acl
            else:
                extra_args["ACL"] = self.default_acl

            self.s3.upload_file(file_path, bucket_name, s3_key, ExtraArgs=extra_args)
            s3_url = self._generate_url(bucket_name, s3_key)
            logger.info(f"Successfully uploaded {file_path} to {s3_url}")
            return s3_url

        except ClientError as e:
            logger.error(f"Failed to upload file {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error uploading file {file_path}: {e}")
            raise

    def upload_fileobj(
        self,
        file_obj: BytesIO,
        bucket_name: str,
        s3_key: str,
        content_type: Optional[str] = None,
        acl: str = None,
    ) -> str:
        """
        Upload a file object to S3

        Args:
            file_obj: File-like object (BytesIO, file handle, etc.)
            bucket_name: S3 bucket name
            s3_key: S3 object key
            content_type: MIME type of the file
            acl: Access control list

        Returns:
            S3 URL of the uploaded file
        """
        try:
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
            if acl:
                extra_args["ACL"] = acl
            else:
                extra_args["ACL"] = self.default_acl

            self.s3.upload_fileobj(file_obj, bucket_name, s3_key, ExtraArgs=extra_args)
            s3_url = self._generate_url(bucket_name, s3_key)
            logger.info(f"Successfully uploaded file object to {s3_url}")
            return s3_url

        except ClientError as e:
            logger.error(f"Failed to upload file object: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error uploading file object: {e}")
            raise

    def delete_file(self, bucket_name: str, s3_key: str) -> bool:
        """
        Delete a file from S3

        Args:
            bucket_name: S3 bucket name
            s3_key: S3 object key

        Returns:
            True if successful, False otherwise
        """
        try:
            self.s3.delete_object(Bucket=bucket_name, Key=s3_key)
            logger.info(f"Successfully deleted {s3_key} from {bucket_name}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete {s3_key}: {e}")
            return False

    def generate_presigned_url(
        self,
        bucket_name: str,
        s3_key: str,
        expiration: int = 3600,
        operation: str = "get_object",
    ) -> str:
        """
        Generate a presigned URL for temporary access

        Args:
            bucket_name: S3 bucket name
            s3_key: S3 object key
            expiration: URL expiration time in seconds (default: 1 hour)
            operation: S3 operation (default: get_object)

        Returns:
            Presigned URL
        """
        try:
            url = self.s3.generate_presigned_url(
                operation,
                Params={"Bucket": bucket_name, "Key": s3_key},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise

    def file_exists(self, bucket_name: str, s3_key: str) -> bool:
        """
        Check if a file exists in S3

        Args:
            bucket_name: S3 bucket name
            s3_key: S3 object key

        Returns:
            True if file exists, False otherwise
        """
        try:
            self.s3.head_object(Bucket=bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def get_file_info(self, bucket_name: str, s3_key: str) -> Dict[str, Any]:
        """
        Get file metadata from S3

        Args:
            bucket_name: S3 bucket name
            s3_key: S3 object key

        Returns:
            Dictionary containing file metadata
        """
        try:
            response = self.s3.head_object(Bucket=bucket_name, Key=s3_key)
            return {
                "content_type": response.get("ContentType"),
                "content_length": response.get("ContentLength"),
                "last_modified": response.get("LastModified"),
                "etag": response.get("ETag"),
                "metadata": response.get("Metadata", {}),
            }
        except ClientError as e:
            logger.error(f"Failed to get file info for {s3_key}: {e}")
            raise

    def _generate_url(self, bucket_name: str, s3_key: str) -> str:
        """
        Generate URL for S3 object

        Args:
            bucket_name: S3 bucket name
            s3_key: S3 object key

        Returns:
            Full URL to the S3 object
        """
        if self.cdn_domain:
            return f"https://{self.cdn_domain}/{s3_key}"
        else:
            return f"https://{bucket_name}.s3.amazonaws.com/{s3_key}"

    def generate_s3_key(
        self,
        media_type: str,
        filename: str,
        variant: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """
        Generate S3 key for media upload

        Args:
            media_type: Type of media (images, videos, documents, etc.)
            filename: Original filename
            variant: Image variant (thumbnail, small, medium, large)
            user_id: User ID for organization

        Returns:
            S3 key path
        """
        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(filename)
        unique_filename = f"{name}_{timestamp}{ext}"

        # Build path
        path_parts = [media_type]

        if user_id:
            path_parts.append(f"user_{user_id}")

        if variant:
            path_parts.append(variant)

        path_parts.append(unique_filename)

        return "/".join(path_parts)

    def optimize_image(
        self,
        image_data: BytesIO,
        max_width: int,
        max_height: int,
        quality: int = 85,
        format: str = "JPEG",
    ) -> BytesIO:
        """
        Optimize image for web delivery

        Args:
            image_data: Image data as BytesIO
            max_width: Maximum width
            max_height: Maximum height
            quality: JPEG quality (1-100)
            format: Output format (JPEG, PNG, WEBP)

        Returns:
            Optimized image as BytesIO
        """
        try:
            with Image.open(image_data) as img:
                # Convert to RGB if necessary
                if img.mode in ("RGBA", "LA", "P"):
                    # Create white background for transparent images
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    background.paste(
                        img, mask=img.split()[-1] if img.mode == "RGBA" else None
                    )
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")

                # Resize if necessary
                if img.width > max_width or img.height > max_height:
                    img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

                # Save optimized image
                output = BytesIO()
                img.save(output, format=format, quality=quality, optimize=True)
                output.seek(0)
                return output

        except Exception as e:
            logger.error(f"Failed to optimize image: {e}")
            raise

    def get_content_type(self, filename: str) -> str:
        """
        Get MIME type for filename

        Args:
            filename: Name of the file

        Returns:
            MIME type string
        """
        content_type, _ = mimetypes.guess_type(filename)
        return content_type or "application/octet-stream"


# Global S3 service instance
s3_service = S3Service()
