# 🚀 Markt Backend - EC2 Ubuntu Deployment Guide

## 📋 Overview

This guide provides step-by-step instructions for deploying the Markt Python backend on an EC2 Ubuntu instance with production-ready configuration including Nginx, Gunicorn, Redis, PostgreSQL, and Celery.

## 🎯 Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Nginx (80/443)│    │  Gunicorn (8000)│    │   PostgreSQL    │
│   (Load Balancer)│◄──►│   (WSGI Server) │◄──►│   (Database)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌─────────────────┐
                       │   Redis (6379)  │
                       │   (Cache/Queue) │
                       └─────────────────┘
                              │
                              ▼
                       ┌─────────────────┐
                       │   Celery        │
                       │   (Background)  │
                       └─────────────────┘
```

## 🛠️ Prerequisites

### EC2 Instance Requirements
- **OS**: Ubuntu 22.04 LTS
- **Type**: t3.micro (free tier) or t3.small for better performance
- **Storage**: 20GB minimum
- **Security Groups**: 
  - SSH (22)
  - HTTP (80)
  - HTTPS (443)
  - Custom (8000) - for direct app access if needed

## 📦 Step 1: Initial Server Setup

### 1.1 Connect to EC2 Instance
```bash
ssh -i your-key.pem ubuntu@your-ec2-ip
```

### 1.2 Update System
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl wget git unzip software-properties-common
```

### 1.3 Create Application User
```bash
# Create markt user
sudo adduser markt
sudo usermod -aG sudo markt

# Switch to markt user
sudo su - markt
```

## 🐍 Step 2: Install Python & Dependencies

### 2.1 Install Python 3.10
```bash
# Add deadsnakes PPA
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update

# Install Python 3.10
sudo apt install -y python3.10 python3.10-venv python3.10-dev

# Set Python 3.10 as default
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1
sudo update-alternatives --config python3

# Install pip
curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10
```

### 2.2 Install System Dependencies
```bash
sudo apt install -y \
    build-essential \
    libpq-dev \
    libssl-dev \
    libffi-dev \
    pkg-config \
    libjpeg-dev \
    libpng-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libwebp-dev \
    libtiff5-dev \
    libopenjp2-7-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libxcb1-dev
```

## 🗄️ Step 3: Install & Configure PostgreSQL

### 3.1 Install PostgreSQL
```bash
# Add PostgreSQL repository
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
sudo apt update

# Install PostgreSQL 15
sudo apt install -y postgresql-15 postgresql-contrib-15
```

### 3.2 Configure PostgreSQL
```bash
# Start PostgreSQL service
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Switch to postgres user
sudo -u postgres psql

# Create database and user
CREATE DATABASE markt_db;
CREATE USER markt WITH PASSWORD 'markt123';
GRANT ALL PRIVILEGES ON DATABASE markt_db TO markt;
ALTER USER markt CREATEDB;
\q

# Configure PostgreSQL for remote connections (if needed)
sudo nano /etc/postgresql/15/main/postgresql.conf
# Uncomment and modify: listen_addresses = '*'

sudo nano /etc/postgresql/15/main/pg_hba.conf
# Add: host    all             all             0.0.0.0/0               md5

# Restart PostgreSQL
sudo systemctl restart postgresql
```

## 🔴 Step 4: Install & Configure Redis

### 4.1 Install Redis
```bash
# Install Redis
sudo apt install -y redis-server

# Configure Redis
sudo nano /etc/redis/redis.conf

# Modify these settings:
# bind 127.0.0.1
# maxmemory 256mb
# maxmemory-policy allkeys-lru
# save 900 1
# save 300 10
# save 60 10000

# Start Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Test Redis
redis-cli ping
# Should return: PONG
```

## 📁 Step 5: Deploy Application

### 5.1 Clone Repository
```bash
# Switch to markt user
sudo su - markt

# Create app directory
mkdir -p /home/markt/apps
cd /home/markt/apps

# Clone repository
git clone https://github.com/Markt-Commerce/markt_python.git
cd markt_python
```

### 5.2 Setup Python Environment
```bash
# Create virtual environment
python3.10 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements/requirements.txt
```

### 5.3 Configure Application
```bash
# Create settings file
cp settings.ini.example settings.ini

# Edit settings
nano settings.ini
```

**Production settings.ini:**
```ini
[settings]
ENV=production
DEBUG=False

# Database
DB_HOST=localhost
DB_PORT=5432
DB_USER=markt
DB_PASSWORD=markt123
DB_NAME=markt_db

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Auth
SECRET_KEY=your-super-secret-production-key-here
SESSION_COOKIE_NAME=markt_session

# App
BIND=127.0.0.1:8000

# Logging
LOG_DIR=/home/markt/apps/markt_python/logs
LOG_LEVEL=INFO

# API Docs
API_TITLE=Markt API
API_VERSION=v1
OPENAPI_VERSION=3.0.3
OPENAPI_URL_PREFIX=/api/v1
OPENAPI_SWAGGER_UI_PATH=/swagger-ui
OPENAPI_SWAGGER_UI_URL=https://cdn.jsdelivr.net/npm/swagger-ui-dist/

# Paystack Configuration
PAYSTACK_SECRET_KEY=sk_test_your_secret_key_here
PAYSTACK_PUBLIC_KEY=pk_test_your_public_key_here
PAYMENT_CURRENCY=NGN
PAYMENT_GATEWAY=paystack
```

### 5.4 Create Log Directory
```bash
mkdir -p /home/markt/apps/markt_python/logs
```

### 5.5 Run Database Migrations
```bash
# Set environment variables
export FLASK_APP=main.setup:create_flask_app
export PYTHONPATH=/home/markt/apps/markt_python

# Run migrations
flask db upgrade
```

## 🔧 Step 6: Install & Configure Gunicorn

### 6.1 Install Gunicorn
```bash
# Activate virtual environment
source /home/markt/apps/markt_python/venv/bin/activate

# Install Gunicorn
pip install gunicorn
```

### 6.2 Create Gunicorn Configuration
```bash
# Create gunicorn config
nano /home/markt/apps/markt_python/gunicorn.conf.py
```

**gunicorn.conf.py:**
```python
import multiprocessing
import os

# Server socket
bind = "127.0.0.1:8000"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "gevent"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "/home/markt/apps/markt_python/logs/gunicorn_access.log"
errorlog = "/home/markt/apps/markt_python/logs/gunicorn_error.log"
loglevel = "info"

# Process naming
proc_name = "markt_gunicorn"

# User/Group
user = "markt"
group = "markt"

# Timeout
timeout = 30
keepalive = 2

# Preload app
preload_app = True

def when_ready(server):
    server.log.info("Server is ready. Spawning workers")

def worker_int(worker):
    worker.log.info("worker received INT or QUIT signal")

def pre_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def post_worker_init(worker):
    worker.log.info("Worker initialized (pid: %s)", worker.pid)
```

### 6.3 Create Systemd Service for Gunicorn
```bash
sudo nano /etc/systemd/system/markt.service
```

**markt.service:**
```ini
[Unit]
Description=Markt Gunicorn daemon
After=network.target postgresql.service redis-server.service

[Service]
Type=notify
User=markt
Group=markt
WorkingDirectory=/home/markt/apps/markt_python
Environment="PATH=/home/markt/apps/markt_python/venv/bin"
Environment="PYTHONPATH=/home/markt/apps/markt_python"
ExecStart=/home/markt/apps/markt_python/venv/bin/gunicorn --config gunicorn.conf.py main.setup:create_app
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

## 🔄 Step 7: Setup Celery

### 7.1 Create Celery Configuration
```bash
# Create celery config
nano /home/markt/apps/markt_python/celery.conf.py
```

**celery.conf.py:**
```python
import os

# Celery Configuration
broker_url = 'redis://localhost:6379/0'
result_backend = 'redis://localhost:6379/0'

# Task settings
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True

# Worker settings
worker_prefetch_multiplier = 1
worker_max_tasks_per_child = 1000
worker_disable_rate_limits = False

# Task routing
task_routes = {
    'app.socials.tasks.*': {'queue': 'social'},
    'app.notifications.tasks.*': {'queue': 'notifications'},
}

# Beat schedule
beat_schedule = {
    'cleanup-expired-requests': {
        'task': 'app.requests.tasks.cleanup_expired_requests',
        'schedule': 3600.0,  # Every hour
    },
    'update-trending-products': {
        'task': 'app.socials.tasks.update_trending_products',
        'schedule': 1800.0,  # Every 30 minutes
    },
}
```

### 7.2 Create Systemd Services for Celery
```bash
# Create Celery Worker service
sudo nano /etc/systemd/system/markt-celery.service
```

**markt-celery.service:**
```ini
[Unit]
Description=Markt Celery Worker
After=network.target postgresql.service redis-server.service

[Service]
Type=forking
User=markt
Group=markt
WorkingDirectory=/home/markt/apps/markt_python
Environment="PATH=/home/markt/apps/markt_python/venv/bin"
Environment="PYTHONPATH=/home/markt/apps/markt_python"
ExecStart=/home/markt/apps/markt_python/venv/bin/celery -A main.workers worker -l INFO -Q social,notifications
ExecStop=/home/markt/apps/markt_python/venv/bin/celery control shutdown
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# Create Celery Beat service
sudo nano /etc/systemd/system/markt-celerybeat.service
```

**markt-celerybeat.service:**
```ini
[Unit]
Description=Markt Celery Beat
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=markt
Group=markt
WorkingDirectory=/home/markt/apps/markt_python
Environment="PATH=/home/markt/apps/markt_python/venv/bin"
Environment="PYTHONPATH=/home/markt/apps/markt_python"
ExecStart=/home/markt/apps/markt_python/venv/bin/celery -A main.workers beat -l INFO
Restart=always

[Install]
WantedBy=multi-user.target
```

## 🌐 Step 8: Install & Configure Nginx

### 8.1 Install Nginx
```bash
sudo apt install -y nginx
```

### 8.2 Create Nginx Configuration
```bash
sudo nano /etc/nginx/sites-available/markt
```

**markt nginx config:**
```nginx
upstream markt_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    add_header Content-Security-Policy "default-src 'self' http: https: data: blob: 'unsafe-inline'" always;

    # Logs
    access_log /var/log/nginx/markt_access.log;
    error_log /var/log/nginx/markt_error.log;

    # Client max body size
    client_max_body_size 10M;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/xml+rss
        application/atom+xml
        image/svg+xml;

    # Main application
    location / {
        proxy_pass http://markt_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    # Static files (if any)
    location /static/ {
        alias /home/markt/apps/markt_python/main/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Health check
    location /health {
        proxy_pass http://markt_backend;
        access_log off;
    }
}
```

### 8.3 Enable Site
```bash
# Enable the site
sudo ln -s /etc/nginx/sites-available/markt /etc/nginx/sites-enabled/

# Remove default site
sudo rm /etc/nginx/sites-enabled/default

# Test nginx configuration
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

## 🚀 Step 9: Start Services

### 9.1 Reload Systemd
```bash
sudo systemctl daemon-reload
```

### 9.2 Start All Services
```bash
# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Start Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Start Markt application
sudo systemctl start markt
sudo systemctl enable markt

# Start Celery worker
sudo systemctl start markt-celery
sudo systemctl enable markt-celery

# Start Celery beat
sudo systemctl start markt-celerybeat
sudo systemctl enable markt-celerybeat

# Restart Nginx
sudo systemctl restart nginx
```

### 9.3 Check Service Status
```bash
# Check all services
sudo systemctl status markt
sudo systemctl status markt-celery
sudo systemctl status markt-celerybeat
sudo systemctl status postgresql
sudo systemctl status redis-server
sudo systemctl status nginx
```

## 🔍 Step 10: Monitoring & Logs

### 10.1 View Logs
```bash
# Application logs
sudo journalctl -u markt -f

# Celery logs
sudo journalctl -u markt-celery -f
sudo journalctl -u markt-celerybeat -f

# Nginx logs
sudo tail -f /var/log/nginx/markt_access.log
sudo tail -f /var/log/nginx/markt_error.log

# Application logs
tail -f /home/markt/apps/markt_python/logs/app.log
```

### 10.2 Health Check
```bash
# Test application
curl http://localhost:8000/health

# Test through nginx
curl http://your-domain.com/health
```

## 🔧 Step 11: SSL Certificate (Optional)

### 11.1 Install Certbot
```bash
sudo apt install -y certbot python3-certbot-nginx
```

### 11.2 Get SSL Certificate
```bash
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

## 📊 Step 12: Performance Optimization

### 12.1 PostgreSQL Optimization
```bash
sudo nano /etc/postgresql/15/main/postgresql.conf
```

Add these settings:
```ini
# Memory settings
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
maintenance_work_mem = 64MB

# Connection settings
max_connections = 100

# Logging
log_statement = 'none'
log_duration = off
log_lock_waits = on
log_temp_files = 0
```

### 12.2 Redis Optimization
```bash
sudo nano /etc/redis/redis.conf
```

Add these settings:
```ini
# Memory management
maxmemory 512mb
maxmemory-policy allkeys-lru

# Persistence
save 900 1
save 300 10
save 60 10000

# Performance
tcp-keepalive 300
```

## 🛡️ Step 13: Security Hardening

### 13.1 Firewall Configuration
```bash
# Install UFW
sudo apt install -y ufw

# Configure firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

### 13.2 Fail2ban Installation
```bash
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

## 🔄 Step 14: Deployment Scripts

### 14.1 Create Deployment Script
```bash
nano /home/markt/apps/markt_python/deploy.sh
```

**deploy.sh:**
```bash
#!/bin/bash

# Deployment script for Markt backend

set -e

echo "🚀 Starting Markt deployment..."

# Navigate to app directory
cd /home/markt/apps/markt_python

# Activate virtual environment
source venv/bin/activate

# Pull latest changes
git pull origin main

# Install/update dependencies
pip install -r requirements/requirements.txt

# Run database migrations
export FLASK_APP=main.setup:create_flask_app
export PYTHONPATH=/home/markt/apps/markt_python
flask db upgrade

# Restart services
sudo systemctl restart markt
sudo systemctl restart markt-celery
sudo systemctl restart markt-celerybeat

echo "✅ Deployment completed successfully!"
```

### 14.2 Make Script Executable
```bash
chmod +x /home/markt/apps/markt_python/deploy.sh
```

## 📋 Step 15: Verification

### 15.1 Test All Components
```bash
# Test database connection
sudo -u markt psql -h localhost -U markt -d markt_db -c "SELECT 1;"

# Test Redis connection
redis-cli ping

# Test application
curl http://localhost:8000/health

# Test through nginx
curl http://your-domain.com/health

# Check Celery
sudo -u markt /home/markt/apps/markt_python/venv/bin/celery -A main.workers inspect active
```

### 15.2 Monitor Resources
```bash
# Check system resources
htop
df -h
free -h

# Check service status
sudo systemctl status markt
sudo systemctl status markt-celery
sudo systemctl status markt-celerybeat
```

## 🚨 Troubleshooting

### Common Issues

1. **Permission Denied**
```bash
sudo chown -R markt:markt /home/markt/apps/markt_python
```

2. **Database Connection Issues**
```bash
sudo -u postgres psql -c "SELECT * FROM pg_user;"
```

3. **Redis Connection Issues**
```bash
redis-cli ping
sudo systemctl status redis-server
```

4. **Gunicorn Issues**
```bash
sudo journalctl -u markt -f
```

5. **Celery Issues**
```bash
sudo journalctl -u markt-celery -f
sudo journalctl -u markt-celerybeat -f
```

## 📈 Monitoring Commands

```bash
# View real-time logs
sudo journalctl -u markt -f

# Check application status
curl http://localhost:8000/health

# Monitor system resources
htop
df -h
free -h

# Check service status
sudo systemctl status markt
sudo systemctl status markt-celery
sudo systemctl status markt-celerybeat
```

## 🎯 Next Steps

1. **Set up monitoring** (Prometheus, Grafana)
2. **Configure backups** (database, logs)
3. **Set up CI/CD** pipeline
4. **Configure SSL** certificates
5. **Set up load balancing** (if needed)
6. **Configure log aggregation** (ELK stack)

---

**🎉 Congratulations! Your Markt backend is now deployed and running on EC2!**

**Access your API at:** `http://your-domain.com/api/v1`
**API Documentation:** `http://your-domain.com/swagger-ui` 