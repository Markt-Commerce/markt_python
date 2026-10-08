# Markt prod gunicorn. One gevent worker on purpose: Socket.IO's polling
# transport needs every request of a session to hit the same process, which
# gunicorn cannot guarantee across workers. gevent gives the concurrency.
bind = "127.0.0.1:8000"
workers = 1
worker_class = "geventwebsocket.gunicorn.workers.GeventWebSocketWorker"
worker_connections = 1000
timeout = 60
graceful_timeout = 30
keepalive = 5
accesslog = "/srv/markt/logs/gunicorn_access.log"
errorlog = "/srv/markt/logs/gunicorn_error.log"
loglevel = "info"
proc_name = "markt"
