from db import db

# Association table for many-to-many relationship between seller and buyer queries
seller_buyer_query = db.Table(
    "seller_buyer_query",
    db.Column("seller_id", db.Integer, db.ForeignKey("sellers.id"), primary_key=True),
    db.Column(
        "buyer_request_id",
        db.Integer,
        db.ForeignKey("buyer_request.id"),
        primary_key=True,
    ),
)
