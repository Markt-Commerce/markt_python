from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from main.config import settings
import logging

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URI, pool_size=20, max_overflow=30, pool_recycle=3600
)

Session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

Base = declarative_base()
Base.query = Session.query_property()


def init_db():
    import app.users.models  # noqa - imports all models

    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized")


def shutdown_session(exception=None):
    Session.remove()
    logger.info("Database session closed")
