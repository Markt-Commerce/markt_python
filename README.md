# Markt Python Backend


<img
  src="https://avatars.githubusercontent.com/u/188402477?s=200&v=4"
  alt="Markt Logo"
  style="width: 100%; max-width: 800px; height: 150px; object-fit: cover; border-radius: 8px;"
/>

*Empowering Student (but not exclusive) Entrepreneurs with Social Commerce*

## 🚀 Tech Stack

### Core Technologies
- **Framework**: Flask 2.3
- **API**: Flask-Smorest (REST API + OpenAPI/Swagger)
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Auth**: Flask-Login with session management
- **Realtime**: Flask-SocketIO
- **Caching**: Redis

### Key Features
- Social commerce platform for student entrepreneurs (but not exclusive)
- Hybrid e-commerce with social media features
- Real-time chat and notifications
- Comprehensive API documentation

## 🛠️ Development Setup

### Prerequisites
- Python 3.9+
- PostgreSQL 13+
- Redis 6+
- Git

### Installation

```bash
# Clone repository
git clone https://github.com/Markt-Commerce/markt_python.git
cd markt_python

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows

# Copy configuration template
cp settings.ini.example settings.ini

# Install dependencies
pip install -r requirements/dev-requirements.txt

```

### Configuration
Edit `settings.ini` with your local configuration:
```ini
[Database]
DB_HOST=localhost
DB_PORT=5432
DB_USER=markt
DB_PASSWORD=markt123
DB_NAME=markt_db

[Redis]
REDIS_HOST=localhost
REDIS_PORT=6379

[App]
SECRET_KEY=your-secret-key-here
DEBUG=True
```

## 🌟 Redis Management

Start/stop Redis container:
```bash
# Start Redis
cd external
docker-compose -f docker-compose.redis.yml up -d

# Stop Redis
docker-compose -f docker-compose.redis.yml down

# View logs
docker-compose -f docker-compose.redis.yml logs -f
```

## 🏃 Running the Application

```bash
# Start development server
python -m main.run

# Production (using Gunicorn)
gunicorn -w 4 -b 127.0.0.1:8000 "main.setup:create_app()"
```

Access API docs at: `http://localhost:8000/swagger-ui`

## 📦 Database Migrations

```bash
# Set flask app
export FLASK_APP=main.setup:create_flask_app

# Initialize migrations (first time only)
flask db init

# Create new migration
flask db migrate -m "your migration message"

# Apply migrations
flask db upgrade

# Rollback migration
flask db downgrade
```

## ✨ Development Practices

### Code Style

> [!IMPORTANT]
> Use `pre-commit run` command before committing your changes.
> Use `cz commit` command to commit your changes.

### Commit Messages
We use Conventional Commits with Commitizen:
```bash
# Interactive commit
cz commit

# Or follow the pattern:
<type>[optional scope]: <description>

# Example:
feat(auth): add JWT authentication support
```

### Pull Requests
See our [Pull Request Guidelines](PULL_REQUEST_TEMPLATE.md) for details on:
- Required checklist items
- Code review standards
- Testing requirements
- Documentation updates

## 🤝 Contributing

We welcome contributions! Please:
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`cz commit`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.
