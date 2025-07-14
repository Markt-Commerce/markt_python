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
}
