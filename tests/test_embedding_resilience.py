"""Embedding-path resilience.

Ingest embeds one call per chunk in a tight loop, so a 12-chunk document makes
12 sequential upstream calls. Any one of them hitting a rate limit failed the
whole upload and discarded every chunk already embedded. Generation was made
retry-tolerant earlier; these pin the same behaviour for embeddings.

No network and no database: the Gemini client is replaced with a stub.
"""

from types import SimpleNamespace

import pytest

from app import ingest


class FakeServerError(Exception):
    code = 503


class FakeRateLimitError(Exception):
    code = 429


class FakeBadRequest(Exception):
    code = 400


class StubModels:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.last = None

    def embed_content(self, model, contents, config=None):
        self.calls += 1
        nxt = self.script.pop(0) if self.script else self.last
        if nxt is None:
            raise AssertionError("stub exhausted")
        self.last = nxt
        if isinstance(nxt, Exception):
            raise nxt
        return SimpleNamespace(embedding=SimpleNamespace(values=nxt))


def stub(script, monkeypatch):
    stub_models = StubModels(script)
    monkeypatch.setattr(ingest, "gemini_client", SimpleNamespace(models=stub_models))
    monkeypatch.setattr(ingest, "EMBED_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(ingest, "EMBED_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(ingest, "ENABLE_OLLAMA_PULL", False)
    return stub_models


def vector(n=768):
    return [0.01] * n


def test_success_on_first_attempt(monkeypatch):
    models = stub([vector()], monkeypatch)
    assert ingest.get_gemini_embedding("text") == vector()
    assert models.calls == 1


def test_retries_a_rate_limit_then_succeeds(monkeypatch):
    """A 429 on chunk 1 must not discard the document."""
    models = stub([FakeRateLimitError("slow down"), FakeRateLimitError("slow down"), vector()], monkeypatch)
    assert ingest.get_gemini_embedding("text") == vector()
    assert models.calls == 3


def test_retries_a_503_then_succeeds(monkeypatch):
    models = stub([FakeServerError("busy"), vector()], monkeypatch)
    assert ingest.get_gemini_embedding("text") == vector()
    assert models.calls == 2


def test_gives_up_after_the_attempt_budget(monkeypatch):
    models = stub([FakeServerError("busy")], monkeypatch)
    with pytest.raises(FakeServerError):
        ingest.get_gemini_embedding("text")
    assert models.calls == 3


def test_bad_request_is_not_retried(monkeypatch):
    """A 400 will never succeed on a second try."""
    models = stub([FakeBadRequest("bad"), vector()], monkeypatch)
    with pytest.raises(FakeBadRequest):
        ingest.get_gemini_embedding("text")
    assert models.calls == 1


def test_missing_api_key_fails_before_any_call(monkeypatch):
    monkeypatch.setattr(ingest, "gemini_client", None)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        ingest.get_gemini_embedding("text")


def test_wrong_dimension_is_rejected(monkeypatch):
    stub([vector(512)], monkeypatch)
    with pytest.raises(ValueError, match="768"):
        ingest.get_gemini_embedding("text")


def test_transient_classifier():
    assert ingest.is_transient(FakeServerError("x"))
    assert ingest.is_transient(FakeRateLimitError("x"))
    assert not ingest.is_transient(FakeBadRequest("x"))
    assert not ingest.is_transient(ValueError("bad dimension"))


def test_a_twelve_chunk_document_survives_a_rate_limit_on_the_last_chunk(monkeypatch):
    """The real failure mode: one transient error at chunk 12 of 12."""
    calls = {"n": 0}

    class FlakyModels:
        def embed_content(self, model, contents, config=None):
            calls["n"] += 1
            if calls["n"] == 12:
                raise FakeRateLimitError("rate limited on the final chunk")
            return SimpleNamespace(embedding=SimpleNamespace(values=vector()))

    monkeypatch.setattr(ingest, "gemini_client", SimpleNamespace(models=FlakyModels()))
    monkeypatch.setattr(ingest, "EMBED_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(ingest, "EMBED_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(ingest, "ENABLE_OLLAMA_PULL", False)

    results = [ingest.get_gemini_embedding(f"chunk {i}") for i in range(12)]
    assert len(results) == 12
    assert calls["n"] == 13  # 12 chunks plus one retry