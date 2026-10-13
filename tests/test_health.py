"""Health-probe tests.

These deliberately run WITHOUT TEST_DATABASE_URL. Every other suite in this repo
skips without it, which is exactly how a dead DATABASE_URL stayed invisible: the
tests that touch the database were the only ones that would have caught it, and
they never ran. `get_db` is overridden here so the probe's own logic is covered
on every machine.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.database import get_db


def _override_db(behaviour):
    """Mimic app.database.get_db.

    The real dependency hands back a lazy SQLAlchemy Session; the connection is
    only attempted on first query. So the failure has to surface at .execute(),
    not when the dependency is constructed — otherwise the route's own
    try/except never runs and FastAPI turns it into an opaque 500.
    """

    def override():
        class _Session:
            def execute(self, *_args, **_kwargs):
                if isinstance(behaviour, Exception):
                    raise behaviour
                return behaviour

            def close(self):
                pass

        return _Session()

    return override


@pytest.fixture
def client_factory():
    def build(behaviour, generator_ready=True):
        main.app.dependency_overrides[get_db] = _override_db(behaviour)
        original_generator, original_pull = main.gemini_client, main.ENABLE_OLLAMA_PULL
        main.gemini_client = SimpleNamespace() if generator_ready else None
        main.ENABLE_OLLAMA_PULL = bool(generator_ready)
        with TestClient(main.app) as client:
            yield client
        main.gemini_client, main.ENABLE_OLLAMA_PULL = original_generator, original_pull
        main.app.dependency_overrides.pop(get_db, None)

    return build


def test_health_reports_ok_when_database_answers(client_factory):
    for client in client_factory(behaviour=object()):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"]["status"] == "ok"
        assert body["generator"]["status"] == "ok"


def test_health_reports_503_when_database_is_unreachable(client_factory):
    """The regression this endpoint exists for: a dead DATABASE_URL must be loud.

    Previously the UI probed /docs, which answers whenever uvicorn is alive, so a
    service with no working database rendered as fully operational.
    """
    for client in client_factory(behaviour=RuntimeError("tenant not found")):
        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["database"]["status"] == "error"
        assert body["database"]["detail"] == "RuntimeError"
        assert body["generator"]["status"] == "ok"


def test_health_reports_503_when_no_generator_is_configured(client_factory):
    for client in client_factory(behaviour=object(), generator_ready=False):
        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["database"]["status"] == "ok"
        assert body["generator"]["status"] == "error"


def test_docs_still_answers_when_database_is_dead(client_factory):
    """Pin the gap that motivated /health, so the contrast stays documented."""
    for client in client_factory(behaviour=RuntimeError("tenant not found")):
        assert client.get("/docs").status_code == 200
        assert client.get("/health").status_code == 503