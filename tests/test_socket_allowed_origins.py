"""The API's own origin is always an accepted Socket.IO origin.

React Native's iOS WebSocket sends the URL it is connecting to as its Origin.
With only the web frontends in ALLOWED_ORIGINS, Socket.IO refused the app's
chat and notification sockets ("<api> is not an accepted origin").
"""

from main.config import Config


def _config(monkeypatch, allowed, api_base):
    monkeypatch.setenv("ALLOWED_ORIGINS", allowed)
    monkeypatch.setenv("API_BASE_URL", api_base)
    return Config()


def test_api_origin_is_added_to_socket_origins(monkeypatch):
    c = _config(
        monkeypatch, "https://marktcommerce.com", "https://api.marktcommerce.com/v1"
    )
    assert c.SOCKET_ALLOWED_ORIGINS == [
        "https://marktcommerce.com",
        "https://api.marktcommerce.com",
    ]
    # HTTP CORS is untouched: the API is not a browser frontend.
    assert c.ALLOWED_ORIGINS == ["https://marktcommerce.com"]


def test_not_duplicated_when_already_listed(monkeypatch):
    c = _config(
        monkeypatch,
        "http://localhost:3000,http://localhost:8000",
        "http://localhost:8000",
    )
    assert c.SOCKET_ALLOWED_ORIGINS.count("http://localhost:8000") == 1


def test_empty_api_base_adds_nothing(monkeypatch):
    c = _config(monkeypatch, "https://marktcommerce.com", "")
    assert c.SOCKET_ALLOWED_ORIGINS == ["https://marktcommerce.com"]
