import time
from db import db


class PasswordRetrievalData(db.Model):
    __tablename__ = "retrieve_password"

    id = db.Column(db.Integer, primary_key=True)
    recovery_code = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.String(400), nullable=False, unique=True)
    email = db.Column(db.String(400), nullable=False, unique=True)
    expiration_time = db.Column(
        db.Integer, default=time.time() + (60 * 10), nullable=False
    )

    def is_expired(self):
        if self.expiration_time < time.time():
            self.delete_from_db()
            return True
        return False

    def is_code_right(self, code):
        return code == self.recovery_code

    @classmethod
    def get_all_other_recovery_attempts(cls, email):
        return cls.query.filter_by(email=email).count()

    @classmethod
    def get_recovery_data(cls, email):
        return cls.query.filter_by(email=email).first()

    @classmethod
    def delete_all_other_recovery_attempts(cls, email):
        return cls.query.filter_by(email=email).delete(synchronize_session=False)

    def save_to_db(self):
        db.session.add(self)
        db.session.commit()

    def delete_from_db(self):
        db.session.delete(self)
        db.session.commit()

    # Add Buyer-specific methods here
