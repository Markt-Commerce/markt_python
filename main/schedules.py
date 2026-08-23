from celery.schedules import crontab

CELERYBEAT_SCHEDULE = {
    # Feed generation tasks
    "generate-personalized-feeds": {
        "task": "app.socials.tasks.generate_all_feeds",
        "schedule": crontab(hour="1", minute="0"),  # Daily at 1 AM
        "options": {"queue": "social"},
    },
    "generate-discovery-feeds": {
        "task": "app.socials.tasks.generate_discovery_feeds",
        "schedule": crontab(hour="3", minute="0"),  # Daily at 3 AM
        "options": {"queue": "social"},
    },
    # Content trending updates
    "update-trending-content": {
        "task": "app.socials.tasks.update_popular_content",
        "schedule": crontab(minute="*/30"),  # Every 30 minutes
        "options": {"queue": "social"},
    },
    "update-category-trending": {
        "task": "app.socials.tasks.update_category_trending",
        "schedule": crontab(hour="*/2"),  # Every 2 hours
        "options": {"queue": "social"},
    },
    # Analytics and cleanup tasks
    "update-feed-analytics": {
        "task": "app.socials.tasks.update_feed_analytics",
        "schedule": crontab(hour="*/6"),  # Every 6 hours
        "options": {"queue": "analytics"},
    },
    "cleanup-old-feed-cache": {
        "task": "app.socials.tasks.cleanup_old_feed_cache",
        "schedule": crontab(hour="2", minute="30"),  # Daily at 2:30 AM
        "options": {"queue": "maintenance"},
    },
    # Notification cleanup
    "cleanup-old-notifications": {
        "task": "app.notifications.tasks.cleanup_old_notifications",
        "schedule": crontab(hour="2", minute="0"),  # Daily at 2 AM
        "options": {"queue": "default"},
    },
    # Media processing tasks
    "cleanup-failed-media": {
        "task": "app.media.tasks.cleanup_failed_media",
        "schedule": crontab(hour="3", minute="0"),  # Daily at 3 AM
        "options": {"queue": "media"},
    },
    "cleanup-soft-deleted-media": {
        "task": "app.media.tasks.cleanup_soft_deleted_media",
        "schedule": crontab(hour="4", minute="0"),  # Daily at 4 AM
        "options": {"queue": "media"},
    },
    "update-media-analytics": {
        "task": "app.media.tasks.update_media_analytics",
        "schedule": crontab(hour="*/4"),  # Every 4 hours
        "options": {"queue": "analytics"},
    },
    "expire-unpaid-orders": {
        "task": "app.orders.tasks.expire_unpaid_orders",
        "schedule": crontab(hour="*/1"),  # Hourly
        "options": {"queue": "default"},
    },
    "expire-stale-inventory-reservations": {
        "task": "app.inventory.tasks.expire_stale_reservations",
        "schedule": crontab(minute="*/2"),  # Every 2 minutes (10-min reservation TTL)
        "options": {"queue": "default"},
    },
    "expire-abandoned-checkout-payments": {
        "task": "app.payments.tasks.expire_abandoned_checkout_payments",
        "schedule": crontab(minute="*/5"),  # Every 5 min -- 15-min abandonment window
        "options": {"queue": "default"},
    },
    "recompute-inventory-confidence-scores": {
        "task": "app.inventory.tasks.recompute_confidence_scores",
        "schedule": crontab(hour="*/6"),  # Every 6 hours -- recency decays over days
        "options": {"queue": "default"},
    },
    "settle-eligible-order-items": {
        "task": "app.wallet.tasks.settle_eligible_order_items",
        "schedule": crontab(hour="*/1"),  # Hourly -- settlement hold is 12h
        "options": {"queue": "default"},
    },
    "expire-stale-fulfilment-allocations": {
        "task": "app.fulfilment.tasks.expire_stale_allocations",
        "schedule": crontab(minute="*/1"),  # Every minute -- 3-min response window
        "options": {"queue": "default"},
    },
    "expire-stale-buyer-approvals": {
        "task": "app.fulfilment.tasks.expire_stale_buyer_approvals",
        "schedule": crontab(minute="*/1"),  # Every minute -- 5-min 9.1 window
        "options": {"queue": "default"},
    },
    "recompute-seller-reliability-scores": {
        "task": "app.fulfilment.tasks.recompute_seller_reliability_scores",
        "schedule": crontab(hour="*/6"),  # Every 6 hours, same cadence as confidence
        "options": {"queue": "default"},
    },
    "recover-stuck-fulfilment-allocations": {
        "task": "app.fulfilment.tasks.recover_stuck_fulfilment_allocations",
        "schedule": crontab(minute="*/3"),  # Backstop sweep, 10-min deadline (14.3)
        "options": {"queue": "default"},
    },
}
