from flask_smorest import Blueprint
from flask.views import MethodView

from app.libs.decorators import admin_required

from .schemas import MetricsDashboardQuerySchema, MetricsDashboardResponseSchema
from .services import MetricsService

bp = Blueprint(
    "metrics",
    __name__,
    description="Business metrics & observability dashboards (15)",
    url_prefix="/metrics",
)


@bp.route("/dashboard")
class MetricsDashboard(MethodView):
    @admin_required
    @bp.arguments(MetricsDashboardQuerySchema, location="query")
    @bp.response(200, MetricsDashboardResponseSchema)
    def get(self, args):
        """15: fulfilment latency, rerouting success rate, reservation/
        payment failure rates, substitution rate, worker failures, stuck
        orders -- admin-only. See MetricsService's own docstring for the
        two items (delivery_delays, missed pickups) that are genuinely
        blocked or reinterpreted rather than guessed at."""
        return MetricsService.get_dashboard(since_hours=args["since_hours"])
