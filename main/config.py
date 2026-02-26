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
        self.REDIS_DB = config("REDIS_DB", default=0, cast=int)

        # Auth
        self.SECRET_KEY = config("SECRET_KEY", default="dev-secret-key")
        self.SESSION_COOKIE_NAME = "markt_session"

        # Session/Cookie settings
        self.SESSION_COOKIE_SAMESITE = config("SESSION_COOKIE_SAMESITE", default="Lax")
        self.SESSION_COOKIE_SECURE = config(
            "SESSION_COOKIE_SECURE", default=False, cast=bool
        )

        # App
        self.BIND = config("BIND", default="127.0.0.1:8000")
        self.DEBUG = config("DEBUG", default=True, cast=bool)

        # CORS Configuration
        cors_origins = config(
            "ALLOWED_ORIGINS", default="http://localhost:3000,http://127.0.0.1:3000"
        )
        self.ALLOWED_ORIGINS = [origin.strip() for origin in cors_origins.split(",")]

        # Logging
        self.LOG_DIR = Path(config("LOG_DIR", default="logs"))
        self.LOG_LEVEL = config("LOG_LEVEL", default="INFO")

        # API Docs
        self.API_TITLE = config("API_TITLE", default="Markt API")
        self.API_VERSION = config("API_VERSION", default="v1")
        self.OPENAPI_VERSION = config("OPENAPI_VERSION", default="3.0.3")
        self.OPENAPI_URL_PREFIX = config("OPENAPI_URL_PREFIX", default="/api/v1")
        self.OPENAPI_SWAGGER_UI_PATH = config(
            "OPENAPI_SWAGGER_UI_PATH", default="/swagger-ui"
        )
        self.OPENAPI_SWAGGER_UI_URL = config(
            "OPENAPI_SWAGGER_UI_URL",
            default="https://cdn.jsdelivr.net/npm/swagger-ui-dist/",
        )

        # Payment Gateway Configuration (Paystack for Nigeria)
        self.PAYSTACK_SECRET_KEY = config("PAYSTACK_SECRET_KEY", default="")
        self.PAYSTACK_PUBLIC_KEY = config("PAYSTACK_PUBLIC_KEY", default="")
        self.PAYMENT_CURRENCY = config("PAYMENT_CURRENCY", default="NGN")
        self.PAYMENT_GATEWAY = config("PAYMENT_GATEWAY", default="paystack")

        # API Base URL for callbacks and redirects
        # For production: https://api.yourdomain.com
        # For development: http://localhost:8000
        # For staging: https://staging-api.yourdomain.com
        self.API_BASE_URL = config(
            "API_BASE_URL",
            default="http://localhost:8000" if self.ENV == "development" else "",
        )

        # Frontend Base URL for payment redirects
        # For production: https://yourdomain.com or https://app.yourdomain.com
        # For development: http://localhost:3000
        self.FRONTEND_BASE_URL = config(
            "FRONTEND_BASE_URL",
            default="http://localhost:3000" if self.ENV == "development" else "",
        )

        # AWS Configuration
        self.AWS_ACCESS_KEY = config("AWS_ACCESS_KEY", default="")
        self.AWS_SECRET_KEY = config("AWS_SECRET_KEY", default="")
        self.AWS_REGION = config("AWS_REGION", default="us-east-1")
        self.AWS_S3_BUCKET = config("AWS_S3_BUCKET", default="markt-media")
        self.CDN_DOMAIN = config("CDN_DOMAIN", default="")

        # Email Configuration (Resend)
        self.RESEND_API_KEY = config("RESEND_API_KEY", default="")
        self.RESEND_FROM_EMAIL = config(
            "RESEND_FROM_EMAIL", default="noreply@markt.com"
        )
        self.RESEND_FROM_NAME = config("RESEND_FROM_NAME", default="Markt")

        # Build Redis URL
        REDIS_URL = f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

        # Celery Configuration
        self.CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=REDIS_URL)
        self.CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default=REDIS_URL)
        self.CELERY_TASK_SERIALIZER = "json"
        self.CELERY_RESULT_SERIALIZER = "json"
        self.CELERY_ACCEPT_CONTENT = ["json"]
        self.CELERY_TIMEZONE = "UTC"
        self.CELERY_TASK_TRACK_STARTED = True
        self.CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
        self.CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes (grace period)
        self.CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Better for long-running tasks
        self.CELERY_TASK_ACKS_LATE = True  # Acknowledge after completion
        self.CELERY_WORKER_DISABLE_RATE_LIMITS = False
        self.CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

    @property
    def SQLALCHEMY_DATABASE_URI(self):
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def CELERY_CONFIG(self):
        """Explicit config dict for Celery"""
        return {
            "broker_url": self.CELERY_BROKER_URL,
            "result_backend": self.CELERY_RESULT_BACKEND,
            "task_serializer": self.CELERY_TASK_SERIALIZER,
            "result_serializer": self.CELERY_RESULT_SERIALIZER,
            "accept_content": self.CELERY_ACCEPT_CONTENT,
            "timezone": self.CELERY_TIMEZONE,
            "task_track_started": self.CELERY_TASK_TRACK_STARTED,
            "task_time_limit": self.CELERY_TASK_TIME_LIMIT,
            "task_soft_time_limit": self.CELERY_TASK_SOFT_TIME_LIMIT,
            "worker_prefetch_multiplier": self.CELERY_WORKER_PREFETCH_MULTIPLIER,
            "task_acks_late": self.CELERY_TASK_ACKS_LATE,
            "worker_disable_rate_limits": self.CELERY_WORKER_DISABLE_RATE_LIMITS,
            "broker_connection_retry_on_startup": self.CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP,
            "task_routes": {
                "app.media.tasks.*": {"queue": "media"},
                "app.socials.tasks.*": {"queue": "social"},
                "app.notifications.tasks.*": {"queue": "notifications"},
            },
        }

    @property
    def PAYMENT_CONFIG(self):
        """Payment gateway configuration"""
        return {
            "gateway": self.PAYMENT_GATEWAY,
            "currency": self.PAYMENT_CURRENCY,
            "paystack": {
                "secret_key": self.PAYSTACK_SECRET_KEY,
                "public_key": self.PAYSTACK_PUBLIC_KEY,
            },
        }


settings = Config()
