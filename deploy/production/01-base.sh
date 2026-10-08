#!/bin/bash
# Markt prod, stage 1: base system. Idempotent.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

hostnamectl set-hostname markt-prod

apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -q
apt-get install -y -q \
  git curl ufw fail2ban unattended-upgrades logrotate \
  python3.11 python3.11-venv python3.11-dev python3.11-gdbm \
  build-essential libpq-dev libjpeg-dev libpng-dev libwebp-dev libffi-dev libssl-dev \
  postgresql-16 redis-server nginx certbot python3-certbot-nginx

# 2 GB swap: headroom for image-processing spikes on a 2 GB box.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
cat > /etc/sysctl.d/99-markt.conf <<'SYS'
vm.swappiness=10
vm.overcommit_memory=1
SYS
sysctl -q --system

# Firewall: SSH + web only. Postgres/Redis listen on localhost anyway.
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# fail2ban for sshd (port 22 is open to GitHub Actions' changing IPs).
cat > /etc/fail2ban/jail.d/sshd.local <<'F2B'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
F2B
systemctl enable --now fail2ban
systemctl restart fail2ban

# Security updates automatically; never reboot on its own.
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'UU'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
UU

python3.11 -c "import dbm.gnu" && echo "python3.11 + gdbm OK"
echo "STAGE 1 DONE"
