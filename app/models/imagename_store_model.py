from db import db


class ImageNameStore(db.Model):
    #you can actually change the name of the class and the table name if you have a more suitable one
    __tablename__ = "imagenamestore"

    #you are also free to change these variable names
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    image_name = db.Column(db.String(255), nullable=False) #name of the image
    found_under = db.Column(db.String(255), nullable=False)#the place the image is found i.e products,chat,e.t.c
    image_use_origin_id = db.Column(db.String(255), nullable=False)#id of the place (chat,product) where the image is found
    
    def __init__(self,image_name,found_under,image_use_origin_id):
        self.image_name = image_name
        self.found_under = found_under
        self.image_use_origin_id = image_use_origin_id

    
    
    def save_to_db(self):
        db.session.add(self)
        db.session.commit()

    def delete_from_db(self):
        db.session.delete(self)
        db.session.commit()
