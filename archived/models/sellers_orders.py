from db import db

sellers_orders = db.Table(
    "sellers_orders",
    db.Column("seller_id", db.Integer, db.ForeignKey("sellers.id"), primary_key=True),
    db.Column("order_id", db.Integer, db.ForeignKey("orders.id"), primary_key=True),
)
