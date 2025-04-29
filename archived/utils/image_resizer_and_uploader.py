from PIL import Image
import uuid
from rembg import remove
import os


def generate_image_name():
    return str(uuid.uuid5)


class ImageSaver:
    # images can only be of type image with .jpg, .png and .webp extensions
    allowed_extensions = ["jpg", "png", "webp"]

    allowed_mimes = ["image/jpeg", "image/png", "image/webp"]

    # 5mb max file size
    max_file_size = 5 * 1024 * 1024

    """
    This class contains functions for reducing image file sizes, storing the images in
    the upload folder or storage bucket, and also unlinking(deleting) image files from
    the upload folder or storage bucket. It also contains functions to change the image
    from one format to another, rasterize and change the image structure and a whole lot of
    other stuff
    """

    @classmethod
    def compress_image(cls, image_location):
        """compress an image

        Keyword arguments:
        image_location - the directory where the image is located
        Return: a boolean
        """
        try:
            with Image.open(image_location) as image:
                width, height = image.size
                new_width = width * 0.3
                new_height = height * 0.3
                image.resize((new_width, new_height))
                image_name = generate_image_name()
                image.save(
                    "app/uploads/" + image_name + ".jpg",
                    "JPEG",
                    optimize=True,
                    quality=50,
                )
                return image_name
        except OSError:
            return False

    @classmethod
    def compress_image_and_remove_background(cls, image_location):
        """compress an image

        Keyword arguments:
        image_location - the directory where the image is located
        Return: a boolean
        """
        try:
            with Image.open(image_location) as image:
                width, height = image.size
                new_width = width * 0.3
                new_height = height * 0.3
                image.resize((new_width, new_height))
                image_name = generate_image_name()
                image_with_background_removed = remove(image)
                image_with_background_removed.save(
                    "app/uploads/" + image_name + ".jpg",
                    "JPEG",
                    optimize=True,
                    quality=50,
                )
                return image_name
        except OSError:
            return False

    @classmethod
    def is_valid_file(cls, name):
        return "." in name and name.rsplit(".", 1)[1].lower() in cls.allowed_extensions

    @classmethod
    def is_valid_mime(cls, mime_to_check):
        return mime_to_check in cls.allowed_mimes

    @classmethod
    def is_valid_file_size(cls, file_size):
        return file_size < cls.max_file_size

    @staticmethod
    def delete_image(self, image_name):
        try:
            os.unlink("app/routes/" + image_name + ".jpg")
            return True
        except OSError:
            return False
