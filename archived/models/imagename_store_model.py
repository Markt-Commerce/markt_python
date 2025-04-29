from db import db


class ImageNameStore(db.Model):
    # you can actually change the name of the class and the table name if you have a more suitable one
    __tablename__ = "imagenamestore"

    # you are also free to change these variable names
    id = db.Column(db.Integer, primary_key=True)
    image_name = db.Column(db.String(255), nullable=False)  # name of the image
    found_under = db.Column(
        db.String(255), nullable=False
    )  # the place the image is found i.e products,chat,e.t.c
    image_use_origin_id = db.Column(
        db.String(255), nullable=False
    )  # id of the place (chat,product) where the image is found

    # Define a many-to-one relationship between ImageNameStore and Product
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    product = db.relationship("Product", back_populates="image_name_store")

    """
    def __init__(self, image_name, found_under, image_use_origin_id):
        self.image_name = image_name
        self.found_under = found_under
        self.image_use_origin_id = image_use_origin_id
    """

    @classmethod
    def get_product_thumbnail(cls, product_id):
        return cls.query.filter_by(image_use_origin_id=product_id).first()

    @classmethod
    def get_product_images(cls, product_id):
        return cls.query.filter_by(image_use_origin_id=product_id).all()

    @classmethod
    def get_chat_images(cls, chat_id):
        return cls.query.filter_by(image_use_origin_id=chat_id).all()

    def save_to_db(self):
        db.session.add(self)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e

    def delete_from_db(self):
        db.session.delete(self)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e
