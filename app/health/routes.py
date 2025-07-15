# package imports
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, current_app
import time
import psutil
import os
from sqlalchemy import text

# project imports
from external.redis import redis_client
from external.database import db

bp = Blueprint(
    "health", __name__, description="Health check endpoints", url_prefix="/health"
)


@bp.route("/")
class HealthCheck(MethodView):
    def get(self):
        """Basic health check endpoint"""
        return {
            "status": "healthy",
            "timestamp": time.time(),
            "version": "1.0.0",
            "environment": current_app.config.get("ENV", "development"),
        }


@bp.route("/detailed")
class DetailedHealthCheck(MethodView):
    def get(self):
        """Detailed health check with all system components"""
        health_status = {
            "status": "healthy",
            "timestamp": time.time(),
            "version": "1.0.0",
            "environment": current_app.config.get("ENV", "development"),
            "components": {},
        }

        # Database health check
        try:
            db.session.execute(text("SELECT 1"))
            health_status["components"]["database"] = {
                "status": "healthy",
                "response_time": self._measure_db_response_time(),
            }
        except Exception as e:
            health_status["components"]["database"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            health_status["status"] = "unhealthy"

        # Redis health check
        try:
            # Use the Redis client's ping method properly
            redis_client.client.ping()
            health_status["components"]["redis"] = {
                "status": "healthy",
                "response_time": self._measure_redis_response_time(),
            }
        except Exception as e:
            health_status["components"]["redis"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            health_status["status"] = "unhealthy"

        # System resources
        health_status["components"]["system"] = {
            "cpu_usage": psutil.cpu_percent(interval=1),
            "memory_usage": psutil.virtual_memory().percent,
            "disk_usage": psutil.disk_usage("/").percent,
            "load_average": os.getloadavg() if hasattr(os, "getloadavg") else None,
        }

        # Application metrics
        health_status["components"]["application"] = {
            "uptime": time.time() - current_app.start_time
            if hasattr(current_app, "start_time")
            else None,
            "active_connections": self._get_active_connections(),
            "request_count": self._get_request_count(),
        }

        return health_status

    def _measure_db_response_time(self):
        """Measure database response time"""
        start_time = time.time()
        try:
            db.session.execute(text("SELECT 1"))
            return round((time.time() - start_time) * 1000, 2)  # milliseconds
        except:
            return None

    def _measure_redis_response_time(self):
        """Measure Redis response time"""
        start_time = time.time()
        try:
            redis_client.client.ping()
            return round((time.time() - start_time) * 1000, 2)  # milliseconds
        except:
            return None

    def _get_active_connections(self):
        """Get number of active database connections"""
        try:
            result = db.session.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
            )
            return result.scalar()
        except:
            return None

    def _get_request_count(self):
        """Get request count from Redis"""
        try:
            return redis_client.get("request_count") or 0
        except:
            return None


@bp.route("/ready")
class ReadinessCheck(MethodView):
    def get(self):
        """Readiness check for Kubernetes/container orchestration"""
        readiness_status = {"ready": True, "timestamp": time.time(), "checks": {}}

        # Database readiness
        try:
            db.session.execute(text("SELECT 1"))
            readiness_status["checks"]["database"] = True
        except Exception:
            readiness_status["checks"]["database"] = False
            readiness_status["ready"] = False

        # Redis readiness
        try:
            redis_client.client.ping()
            readiness_status["checks"]["redis"] = True
        except Exception:
            readiness_status["checks"]["redis"] = False
            readiness_status["ready"] = False

        # Application readiness
        readiness_status["checks"]["application"] = True

        return readiness_status


@bp.route("/live")
class LivenessCheck(MethodView):
    def get(self):
        """Liveness check for Kubernetes/container orchestration"""
        return {"alive": True, "timestamp": time.time()}


@bp.route("/metrics")
class MetricsEndpoint(MethodView):
    def get(self):
        """Prometheus-style metrics endpoint"""
        metrics = {
            "http_requests_total": self._get_request_metrics(),
            "http_request_duration_seconds": self._get_duration_metrics(),
            "database_connections_active": self._get_db_connection_metrics(),
            "redis_connections_active": self._get_redis_connection_metrics(),
            "system_cpu_usage_percent": psutil.cpu_percent(interval=1),
            "system_memory_usage_percent": psutil.virtual_memory().percent,
            "system_disk_usage_percent": psutil.disk_usage("/").percent,
        }

        return metrics

    def _get_request_metrics(self):
        """Get request count metrics"""
        try:
            return {
                "total": redis_client.get("request_count") or 0,
                "by_status": {
                    "200": redis_client.get("requests_200") or 0,
                    "400": redis_client.get("requests_400") or 0,
                    "401": redis_client.get("requests_401") or 0,
                    "403": redis_client.get("requests_403") or 0,
                    "404": redis_client.get("requests_404") or 0,
                    "429": redis_client.get("requests_429") or 0,
                    "500": redis_client.get("requests_500") or 0,
                },
            }
        except:
            return {"total": 0, "by_status": {}}

    def _get_duration_metrics(self):
        """Get request duration metrics"""
        try:
            return {
                "average": redis_client.get("avg_request_duration") or 0,
                "p95": redis_client.get("p95_request_duration") or 0,
                "p99": redis_client.get("p99_request_duration") or 0,
            }
        except:
            return {"average": 0, "p95": 0, "p99": 0}

    def _get_db_connection_metrics(self):
        """Get database connection metrics"""
        try:
            result = db.session.execute(text("SELECT count(*) FROM pg_stat_activity"))
            return result.scalar()
        except:
            return 0

    def _get_redis_connection_metrics(self):
        """Get Redis connection metrics"""
        try:
            info = redis_client.client.info()
            return info.get("connected_clients", 0)
        except:
            return 0


@bp.route("/status")
class StatusEndpoint(MethodView):
    def get(self):
        """Comprehensive status endpoint with business metrics"""
        status = {
            "status": "operational",
            "timestamp": time.time(),
            "version": "1.0.0",
            "environment": current_app.config.get("ENV", "development"),
            "uptime": time.time() - current_app.start_time
            if hasattr(current_app, "start_time")
            else None,
            "business_metrics": self._get_business_metrics(),
            "system_metrics": self._get_system_metrics(),
            "dependencies": self._get_dependency_status(),
        }

        return status

    def _get_business_metrics(self):
        """Get business-related metrics"""
        try:
            return {
                "total_users": redis_client.get("total_users") or 0,
                "total_products": redis_client.get("total_products") or 0,
                "total_orders": redis_client.get("total_orders") or 0,
                "active_sellers": redis_client.get("active_sellers") or 0,
                "active_buyers": redis_client.get("active_buyers") or 0,
                "total_revenue": redis_client.get("total_revenue") or 0,
            }
        except:
            return {
                "total_users": 0,
                "total_products": 0,
                "total_orders": 0,
                "active_sellers": 0,
                "active_buyers": 0,
                "total_revenue": 0,
            }

    def _get_system_metrics(self):
        """Get system performance metrics"""
        try:
            return {
                "cpu_usage": psutil.cpu_percent(interval=1),
                "memory_usage": psutil.virtual_memory().percent,
                "disk_usage": psutil.disk_usage("/").percent,
                "network_io": self._get_network_io(),
                "load_average": os.getloadavg() if hasattr(os, "getloadavg") else None,
            }
        except:
            return {
                "cpu_usage": 0,
                "memory_usage": 0,
                "disk_usage": 0,
                "network_io": {},
                "load_average": None,
            }

    def _get_network_io(self):
        """Get network I/O statistics"""
        try:
            net_io = psutil.net_io_counters()
            return {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv,
            }
        except:
            return {}

    def _get_dependency_status(self):
        """Get dependency health status"""
        dependencies = {}

        # Database status
        try:
            db.session.execute(text("SELECT 1"))
            dependencies["database"] = "healthy"
        except Exception as e:
            dependencies["database"] = f"unhealthy: {str(e)}"

        # Redis status
        try:
            redis_client.client.ping()
            dependencies["redis"] = "healthy"
        except Exception as e:
            dependencies["redis"] = f"unhealthy: {str(e)}"

        # Application status
        dependencies["application"] = "healthy"

        return dependencies
