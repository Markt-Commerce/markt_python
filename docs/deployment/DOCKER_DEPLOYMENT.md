# 🐳 Markt Docker Deployment Guide

## 📋 Overview

This guide provides Docker-based deployment options for the Markt backend, offering both development and production configurations with Redis, PostgreSQL, and all application components.

## 🎯 Docker Approach Benefits

### ✅ **Advantages:**
- **Consistency** across environments
- **Easy setup** and teardown
- **Isolation** from system dependencies
- **Version control** of all components
- **Easy backup** and restore
- **No system conflicts**
- **Reproducible environments**

### 🚀 **What's Included:**
- **Redis** for caching and queues
- **PostgreSQL** for data persistence
- **Flask Application** with Gunicorn
- **Celery** for background tasks
- **Nginx** for reverse proxy (production)
- **Health checks** for all services
- **Volume persistence** for data

## 📁 File Structure

```
markt_python/
├── docker-compose.production.yml    # Production setup
├── docker-compose.dev.yml           # Development setup
├── Dockerfile.production            # Production Dockerfile
├── Dockerfile.dev                   # Development Dockerfile
├── docker/
│   ├── deploy.sh                    # Deployment script
│   ├── env.example                  # Environment template
│   ├── redis/
│   │   └── redis.conf              # Redis configuration
│   └── nginx/
│       └── nginx.conf              # Nginx configuration
└── external/
    └── docker-compose.redis.yml    # Your existing Redis setup
```

## 🚀 Quick Start

### **Option 1: Development Setup (Recommended for Testing)**

```bash
# 1. Start development environment
docker-compose -f docker-compose.dev.yml up -d

# 2. Run database migrations
docker-compose -f docker-compose.dev.yml exec markt-app-dev flask db upgrade

# 3. Check services
docker-compose -f docker-compose.dev.yml ps

# 4. View logs
docker-compose -f docker-compose.dev.yml logs -f
```

### **Option 2: Production Setup**

```bash
# 1. Copy environment template
cp docker/env.example .env

# 2. Edit environment variables
nano .env

# 3. Run deployment script
./docker/deploy.sh

# 4. Check services
docker-compose -f docker-compose.production.yml ps
```

## 🔧 Configuration Options

### **Development Environment**
- **Hot reload** enabled
- **Volume mounting** for code changes
- **Debug mode** enabled
- **Local development** friendly

### **Production Environment**
- **Gunicorn** with multiple workers
- **Nginx** reverse proxy
- **Health checks** for all services
- **Rate limiting** and security headers
- **Optimized** for performance

## 📊 Service Architecture

### **Development Setup:**
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Your Host     │    │  Flask App      │    │   PostgreSQL    │
│   (Port 8000)   │◄──►│   (Development) │◄──►│   (Container)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌─────────────────┐
                       │   Redis         │
                       │   (Container)   │
                       └─────────────────┘
```

### **Production Setup:**
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Nginx (80)    │    │  Gunicorn       │    │   PostgreSQL    │
│   (Reverse Proxy)│◄──►│   (WSGI Server) │◄──►│   (Container)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌─────────────────┐
                       │   Redis         │
                       │   (Container)   │
                       └─────────────────┘
```

## 🛠️ Manual Commands

### **Development Commands:**

```bash
# Start all services
docker-compose -f docker-compose.dev.yml up -d

# Start specific service
docker-compose -f docker-compose.dev.yml up -d redis

# View logs
docker-compose -f docker-compose.dev.yml logs -f markt-app-dev

# Execute commands in container
docker-compose -f docker-compose.dev.yml exec markt-app-dev bash

# Run migrations
docker-compose -f docker-compose.dev.yml exec markt-app-dev flask db upgrade

# Stop all services
docker-compose -f docker-compose.dev.yml down

# Rebuild and restart
docker-compose -f docker-compose.dev.yml up -d --build
```

### **Production Commands:**

```bash
# Start all services
docker-compose -f docker-compose.production.yml up -d

# View service status
docker-compose -f docker-compose.production.yml ps

# View logs
docker-compose -f docker-compose.production.yml logs -f

# Restart specific service
docker-compose -f docker-compose.production.yml restart markt-app

# Scale services
docker-compose -f docker-compose.production.yml up -d --scale markt-celery=3

# Stop all services
docker-compose -f docker-compose.production.yml down

# Remove volumes (careful!)
docker-compose -f docker-compose.production.yml down -v
```

## 🔍 Monitoring & Debugging

### **Health Checks:**

```bash
# Check application health
curl http://localhost:8000/health

# Check Redis
docker-compose -f docker-compose.dev.yml exec redis redis-cli ping

# Check PostgreSQL
docker-compose -f docker-compose.dev.yml exec postgres pg_isready -U markt -d markt_db

# Check Celery
docker-compose -f docker-compose.dev.yml exec markt-celery-dev celery -A main.workers inspect active
```

### **Logs:**

```bash
# View all logs
docker-compose -f docker-compose.dev.yml logs -f

# View specific service logs
docker-compose -f docker-compose.dev.yml logs -f markt-app-dev

# View Redis logs
docker-compose -f docker-compose.dev.yml logs -f redis

# View PostgreSQL logs
docker-compose -f docker-compose.dev.yml logs -f postgres
```

## 🔧 Customization

### **Environment Variables:**

Create `.env` file:
```bash
# Copy template
cp docker/env.example .env

# Edit variables
nano .env
```

Key variables:
```bash
# Application
ENV=production
DEBUG=False
SECRET_KEY=your-secret-key

# Database
DB_HOST=postgres
DB_PORT=5432
DB_USER=markt
DB_PASSWORD=markt123

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# Paystack
PAYSTACK_SECRET_KEY=sk_test_...
PAYSTACK_PUBLIC_KEY=pk_test_...
```

### **Redis Configuration:**

Edit `docker/redis/redis.conf`:
```bash
# Memory management
maxmemory 512mb
maxmemory-policy allkeys-lru

# Persistence
save 900 1
save 300 10
save 60 10000
```

### **Nginx Configuration:**

Edit `docker/nginx/nginx.conf`:
```bash
# Rate limiting
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

# Security headers
add_header X-Frame-Options "SAMEORIGIN" always;
```

## 🚨 Troubleshooting

### **Common Issues:**

1. **Port Conflicts:**
```bash
# Check what's using port 8000
sudo lsof -i :8000

# Change port in docker-compose.yml
ports:
  - "8001:8000"  # Use port 8001 instead
```

2. **Permission Issues:**
```bash
# Fix file permissions
sudo chown -R $USER:$USER .

# Fix Docker permissions
sudo usermod -aG docker $USER
```

3. **Database Connection Issues:**
```bash
# Check if PostgreSQL is running
docker-compose -f docker-compose.dev.yml ps postgres

# Check database logs
docker-compose -f docker-compose.dev.yml logs postgres
```

4. **Redis Connection Issues:**
```bash
# Check Redis status
docker-compose -f docker-compose.dev.yml exec redis redis-cli ping

# Check Redis logs
docker-compose -f docker-compose.dev.yml logs redis
```

5. **Application Issues:**
```bash
# Check application logs
docker-compose -f docker-compose.dev.yml logs markt-app-dev

# Execute commands in container
docker-compose -f docker-compose.dev.yml exec markt-app-dev bash
```

## 📈 Performance Optimization

### **Development:**
- **Volume mounting** for fast development
- **Hot reload** enabled
- **Debug mode** for detailed logs

### **Production:**
- **Gunicorn** with multiple workers
- **Nginx** for load balancing
- **Redis** for caching
- **Health checks** for reliability

## 🔄 Deployment Workflow

### **Development:**
```bash
# 1. Start services
docker-compose -f docker-compose.dev.yml up -d

# 2. Run migrations
docker-compose -f docker-compose.dev.yml exec markt-app-dev flask db upgrade

# 3. Test application
curl http://localhost:8000/health

# 4. Make changes and restart
docker-compose -f docker-compose.dev.yml restart markt-app-dev
```

### **Production:**
```bash
# 1. Update code
git pull origin main

# 2. Update environment
nano .env

# 3. Deploy
./docker/deploy.sh

# 4. Verify deployment
curl http://your-domain.com/health
```

## 🎯 Recommendations

### **For Development:**
- Use `docker-compose.dev.yml`
- Enable volume mounting for code changes
- Use debug mode for detailed logs
- Keep Redis and PostgreSQL in containers

### **For Production:**
- Use `docker-compose.production.yml`
- Set up proper environment variables
- Configure SSL certificates
- Set up monitoring and backups
- Use external database if needed

### **For Testing:**
- Use development setup for local testing
- Use production setup for staging
- Test all components before deployment

---

**🎉 Your Markt backend is now containerized and ready for deployment!**

**Access your application:**
- **Development:** `http://localhost:8000`
- **Production:** `http://your-domain.com`
- **Health Check:** `http://localhost:8000/health`
- **API Docs:** `http://localhost:8000/swagger-ui` 