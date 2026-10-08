#!/bin/bash
# Markt prod, stage 4: services, nginx, logrotate, backups, deploy user.
# Run from this directory as root:  sudo bash 04-services.sh /path/to/deploy_key.pub
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PUBKEY_FILE="${1:?usage: 04-services.sh <github-actions deploy public key file>}"

install -d -m 755 /etc/markt
install -m 644 $HERE/etc/gunicorn.conf.py /etc/markt/gunicorn.conf.py
install -m 644 $HERE/etc/markt.service $HERE/etc/markt-celery.service \
  $HERE/etc/markt-backup.service $HERE/etc/markt-backup.timer /etc/systemd/system/
install -m 644 $HERE/etc/logrotate-markt /etc/logrotate.d/markt
install -m 644 $HERE/etc/nginx-markt.conf /etc/nginx/sites-available/markt
ln -sf /etc/nginx/sites-available/markt /etc/nginx/sites-enabled/markt
rm -f /etc/nginx/sites-enabled/default
install -m 755 -o root -g root $HERE/bin/markt-backup /usr/local/bin/markt-backup
install -m 755 -o root -g root $HERE/bin/markt-deploy /usr/local/bin/markt-deploy

# Deploy user: its key can only run markt-deploy <sha>.
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
printf '%s %s\n' 'restrict,command="sudo /usr/local/bin/markt-deploy \"$SSH_ORIGINAL_COMMAND\""' \
  "$(cat "$PUBKEY_FILE")" > /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
echo "deploy ALL=(root) NOPASSWD: /usr/local/bin/markt-deploy" > /etc/sudoers.d/markt-deploy
chmod 440 /etc/sudoers.d/markt-deploy
visudo -cf /etc/sudoers.d/markt-deploy

nginx -t
systemctl daemon-reload
systemctl enable -q markt markt-celery markt-backup.timer
systemctl restart markt markt-celery nginx
systemctl start markt-backup.timer
echo "STAGE 4 DONE"
