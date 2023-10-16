from db import db


class BuyerQuery(db.Model):
    __tablename__ = "buyer_query"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    buyer_id = db.Column(db.String(400), db.ForeignKey('buyers.unique_id'), nullable=False)
    description = db.Column(db.String(400), nullable=False)
    category = db.Column(db.String(255))
    created_at = db.Column(db.TIMESTAMP, nullable=False)

    # Define relationship
    buyer = db.relationship("Buyer", back_populates="queries")

    def save_to_db(self):
        db.session.add(self)
        db.session.commit()

    def delete_from_db(self):
        db.session.delete(self)
        db.session.commit()
