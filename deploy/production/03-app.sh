#!/bin/bash
# Markt prod, stage 3: app user, code, venv, settings, migrations. Idempotent.
set -euo pipefail
REF="${1:-develop}"
ROOT=/srv/markt
APP=$ROOT/app

id markt >/dev/null 2>&1 || useradd --system --create-home --home-dir $ROOT --shell /bin/bash markt
install -d -o markt -g markt -m 750 $ROOT $ROOT/logs $ROOT/run $ROOT/backups

as_markt() { sudo -u markt -H bash -c "$1"; }

[ -d $APP/.git ] || as_markt "git clone -q https://github.com/Markt-Commerce/markt_python.git $APP"
as_markt "cd $APP && git fetch -q origin && git checkout -q $REF && git pull -q --ff-only origin $REF"
[ -x $ROOT/venv/bin/python ] || as_markt "python3.11 -m venv $ROOT/venv"
as_markt "$ROOT/venv/bin/pip install -q --upgrade pip wheel && $ROOT/venv/bin/pip install -q -r $APP/requirements/requirements.txt"

# settings.ini: written once; never overwritten (it holds the real secrets).
if [ ! -f $APP/settings.ini ]; then
  DBPW=$(cat /root/markt-secrets/db_password)
  SECRET=$(openssl rand -hex 32)
  cat > $APP/settings.ini <<INI
[settings]
ENV=production
DEBUG=False

DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=markt
DB_PASSWORD=${DBPW}
DB_NAME=markt_db

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0

SECRET_KEY=${SECRET}
SESSION_COOKIE_NAME=markt_session
SESSION_COOKIE_SAMESITE=None
SESSION_COOKIE_SECURE=True

BIND=127.0.0.1:8000
LOG_DIR=${ROOT}/logs
LOG_LEVEL=INFO

API_TITLE=Markt API
API_VERSION=v1
OPENAPI_VERSION=3.0.3
OPENAPI_URL_PREFIX=/
OPENAPI_SWAGGER_UI_PATH=/swagger-ui
OPENAPI_SWAGGER_UI_URL=https://cdn.jsdelivr.net/npm/swagger-ui-dist/

# Browser origins only; the native apps do not send Origin. Add the admin
# console's origin here once it has a production URL.
ALLOWED_ORIGINS=https://marktcommerce.com,https://www.marktcommerce.com

API_BASE_URL=https://api.marktcommerce.com
WEB_APP_BASE_URL=https://marktcommerce.com/app
MOBILE_APP_SCHEME=markt://

# ---- FILL IN ON THE BOX (left empty so nothing half-configured runs) ----
# Paystack LIVE keys (sk_live_/pk_live_). Webhook URL to set in the Paystack
# dashboard: https://api.marktcommerce.com/api/v1/payments/webhook/paystack
PAYSTACK_SECRET_KEY=
PAYSTACK_PUBLIC_KEY=
PAYMENT_CURRENCY=NGN
PAYMENT_GATEWAY=paystack

# IAM user markt-prod-s3, scoped to the bucket below
AWS_ACCESS_KEY=
AWS_SECRET_KEY=
AWS_REGION=eu-west-2
AWS_S3_BUCKET=markt-media-prod
CDN_DOMAIN=

RESEND_API_KEY=
RESEND_FROM_EMAIL=noreply@marktcommerce.com
RESEND_FROM_NAME=Markt
EMAIL_REPLY_TO=support@marktcommerce.com
EMAIL_UNSUBSCRIBE_URL=https://marktcommerce.com/settings/notifications

GOOGLE_WEB_CLIENT_ID=
GOOGLE_IOS_CLIENT_ID=
GOOGLE_ANDROID_CLIENT_ID=
APPLE_BUNDLE_ID=
APPLE_SERVICES_ID=
GOOGLE_MAPS_SERVER_KEY=

LOGISTICS_ADAPTER=internal
LOGISTICS_WEBHOOK_SECRET=
DELIVERY_BATCH_ENABLED=false

# Private bucket for nightly DB dumps (NOT the media bucket)
BACKUP_S3_BUCKET=
INI
  chown markt:markt $APP/settings.ini
  chmod 600 $APP/settings.ini
fi

as_markt "cd $APP && FLASK_APP=main.setup:create_flask_app $ROOT/venv/bin/flask db upgrade 2>&1 | grep -E 'Running upgrade|ERROR|Error' | tail -3; FLASK_APP=main.setup:create_flask_app $ROOT/venv/bin/flask db current 2>/dev/null | tail -1"
as_markt "cd $APP && git log -1 --format='code at %h %s'"
echo "STAGE 3 DONE"
