from decouple import AutoConfig
from pathlib import Path

config = AutoConfig()


class Config:
    def __init__(self):
        # Environment
        self.ENV = config("ENV", default="development")

        # Database
        self.DB_HOST = config("DB_HOST", default="localhost")
        self.DB_PORT = config("DB_PORT", default=5432, cast=int)
        self.DB_USER = config("DB_USER", default="markt")
        self.DB_PASSWORD = config("DB_PASSWORD", default="markt123")
        self.DB_NAME = config("DB_NAME", default="markt_db")

        # Redis
        self.REDIS_HOST = config("REDIS_HOST", default="localhost")
        self.REDIS_PORT = config("REDIS_PORT", default=6379, cast=int)

        # Auth
        self.SECRET_KEY = config("SECRET_KEY", default="dev-secret-key")
        self.SESSION_COOKIE_NAME = "markt_session"

        # App
        self.BIND = config("BIND", default="127.0.0.1:8000")
        self.DEBUG = config("DEBUG", default=True, cast=bool)

        # Logging
        self.LOG_DIR = Path(config("LOG_DIR", default="logs"))
        self.LOG_LEVEL = config("LOG_LEVEL", default="INFO")

    @property
    def SQLALCHEMY_DATABASE_URI(self):
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Config()
