# Production server

One EC2 instance runs the whole stack: nginx → gunicorn (1 gevent worker) →
Flask-SocketIO, a Celery worker with embedded beat, Postgres 16 and Redis, all
on localhost. This directory is everything installed on that box, so it can be
rebuilt from scratch rather than from memory.

| Path on the box | What |
|---|---|
| `/srv/markt/app` | the repo, detached at the deployed commit of `main` |
| `/srv/markt/app/settings.ini` | config + secrets (`600`, owner `markt`; never in git) |
| `/srv/markt/venv` | Python 3.11 venv (`requirements/requirements.txt` only) |
| `/srv/markt/logs` | app + gunicorn logs (logrotate: daily, 14 kept) |
| `/srv/markt/backups` | nightly `pg_dump`s, 14 days |
| `/etc/markt/gunicorn.conf.py` | gunicorn config |

Services: `markt` (API), `markt-celery` (worker + beat), `markt-backup.timer`
(02:30 UTC), `nginx`, `postgresql@16-main`, `redis-server`.

## Rebuild a server

Ubuntu 24.04, security group open on 22/80/443 only. As `ubuntu`:

```bash
git clone https://github.com/Markt-Commerce/markt_python.git /tmp/markt && cd /tmp/markt/deploy/production
sudo bash 01-base.sh            # packages, swap, ufw, fail2ban, python3.11(+gdbm)
sudo bash 02-data.sh            # postgres (random pw in /root/markt-secrets) + redis
sudo bash 03-app.sh main        # markt user, clone, venv, settings.ini, migrations
sudo bash 04-services.sh deploy_key.pub   # units, nginx, logrotate, backups, deploy user
sudo certbot --nginx -d api.marktcommerce.com --redirect --hsts --register-unsafely-without-email --agree-tos   # once DNS points here
```

Then fill in the empty secrets in `settings.ini` and
`sudo systemctl restart markt markt-celery`.

## Deploying

Merging to `main` runs CI, then **Deploy to Production** waits for approval on
the `production` environment. It SSHes in as `deploy`, whose key can only run
`markt-deploy <sha>`: refuse anything not on `origin/main` → `pg_dump` →
checkout → install → migrate → restart → health check.

Rollback: `sudo markt-deploy <previous sha>` as `ubuntu` (the previous sha is
printed by every deploy). Code rolls back; migrations do not, so restore the
pre-deploy dump in `/srv/markt/backups` if a migration was the problem.

## Restore a backup

```bash
sudo systemctl stop markt markt-celery
sudo -u postgres dropdb markt_db && sudo -u postgres createdb -O markt markt_db
sudo -u postgres pg_restore -d markt_db --no-owner --role=markt /srv/markt/backups/<file>.dump
sudo systemctl start markt markt-celery
```
