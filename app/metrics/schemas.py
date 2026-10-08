from marshmallow import Schema, fields, validate


class MetricsDashboardQuerySchema(Schema):
    since_hours = fields.Int(validate=validate.Range(min=1, max=24 * 30), missing=24)


class FulfilmentLatencySchema(Schema):
    sample_size = fields.Integer()
    average_seconds = fields.Float(allow_none=True)
    median_seconds = fields.Float(allow_none=True)


class ReroutingStatsSchema(Schema):
    attempts_succeeded = fields.Integer()
    attempts_failed = fields.Integer()
    success_rate = fields.Float(allow_none=True)


class ReservationStatsSchema(Schema):
    confirmed = fields.Integer()
    expired = fields.Integer()
    failure_rate = fields.Float(allow_none=True)


class PaymentStatsSchema(Schema):
    completed = fields.Integer()
    failed = fields.Integer()
    failure_rate = fields.Float(allow_none=True)


class SubstitutionStatsSchema(Schema):
    delivered_items = fields.Integer()
    substituted_items = fields.Integer()
    rate = fields.Float(allow_none=True)


class MissedSellerResponseWindowsSchema(Schema):
    seller_response_timeouts = fields.Integer()


class StuckOrdersSchema(Schema):
    stuck_fulfilment_allocations = fields.Integer()
    stuck_delivery_runs = fields.Integer()


class WorkerTaskFailuresSchema(Schema):
    runs = fields.Integer()
    failures = fields.Integer()


class WorkerFailuresSchema(Schema):
    runs = fields.Integer()
    failures = fields.Integer()
    by_task = fields.Dict(
        keys=fields.String(), values=fields.Nested(WorkerTaskFailuresSchema)
    )


class MetricsDashboardResponseSchema(Schema):
    window_hours = fields.Integer()
    fulfilment_latency = fields.Nested(FulfilmentLatencySchema)
    rerouting = fields.Nested(ReroutingStatsSchema)
    reservations = fields.Nested(ReservationStatsSchema)
    payments = fields.Nested(PaymentStatsSchema)
    substitution = fields.Nested(SubstitutionStatsSchema)
    missed_seller_response_windows = fields.Nested(MissedSellerResponseWindowsSchema)
    stuck_orders = fields.Nested(StuckOrdersSchema)
    worker_failures = fields.Nested(WorkerFailuresSchema)
    # Genuinely blocked (no promised-delivery-time concept exists) --
    # always null, never a fabricated number. See MetricsService's own
    # docstring.
    delivery_delays = fields.Raw(allow_none=True)
