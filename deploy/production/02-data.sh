#!/bin/bash
# Markt prod, stage 2: Postgres + Redis. Idempotent.
set -euo pipefail

# --- Postgres ----------------------------------------------------------------
install -d -m 700 /root/markt-secrets
PWFILE=/root/markt-secrets/db_password
[ -s "$PWFILE" ] || (openssl rand -base64 36 | tr -d '/+=\n' | head -c 40 > "$PWFILE"; chmod 600 "$PWFILE")
DBPW=$(cat "$PWFILE")

sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'markt') THEN
    CREATE ROLE markt LOGIN PASSWORD '${DBPW}';
  ELSE
    ALTER ROLE markt PASSWORD '${DBPW}';
  END IF;
END \$\$;
SQL
sudo -u postgres psql -Atc "SELECT 1 FROM pg_database WHERE datname='markt_db'" | grep -q 1 \
  || sudo -u postgres createdb -O markt -E UTF8 markt_db

# Sized for a 2 GB box shared with the app.
cat > /etc/postgresql/16/main/conf.d/markt.conf <<'PG'
listen_addresses = 'localhost'
max_connections = 50
shared_buffers = 256MB
effective_cache_size = 768MB
work_mem = 4MB
maintenance_work_mem = 64MB
wal_compression = on
checkpoint_completion_target = 0.9
random_page_cost = 1.1
log_min_duration_statement = 500ms
timezone = 'UTC'
PG

# If memory runs out, the kernel should kill a celery child, not the database.
mkdir -p /etc/systemd/system/postgresql@16-main.service.d
cat > /etc/systemd/system/postgresql@16-main.service.d/oom.conf <<'OOM'
[Service]
OOMScoreAdjust=-900
OOM
systemctl daemon-reload
systemctl restart postgresql@16-main
systemctl enable postgresql -q

# --- Redis -------------------------------------------------------------------
# Localhost only. volatile-lru: under pressure evict only keys that have a TTL
# (caches), never Celery's queue, which has none.
REDIS_CONF=/etc/redis/redis.conf
set_redis() { grep -qE "^$1 " $REDIS_CONF && sed -i -E "s|^$1 .*|$1 $2|" $REDIS_CONF || echo "$1 $2" >> $REDIS_CONF; }
set_redis bind "127.0.0.1 -::1"
set_redis protected-mode yes
set_redis maxmemory 200mb
set_redis maxmemory-policy volatile-lru
set_redis appendonly yes
set_redis appendfsync everysec
systemctl enable redis-server -q
systemctl restart redis-server

# --- checks ------------------------------------------------------------------
PGPASSWORD="$DBPW" psql -h 127.0.0.1 -U markt -d markt_db -Atc "select 'pg ok as '||current_user||', shared_buffers='||current_setting('shared_buffers')"
redis-cli ping
redis-cli config get maxmemory-policy | tail -1
ss -lntp | grep -E ':(5432|6379) ' | awk '{print $4}'
echo "STAGE 2 DONE"
