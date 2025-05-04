from db import db

# Association table for many-to-many relationship between favorites and sellers/products
favorites_seller_product = db.Table(
    "favorites_seller_product",
    db.Column(
        "favorite_id", db.Integer, db.ForeignKey("favorites.id"), primary_key=True
    ),
    db.Column("seller_id", db.Integer, db.ForeignKey("sellers.id"), primary_key=True),
    db.Column("product_id", db.Integer, db.ForeignKey("products.id"), primary_key=True),
)
