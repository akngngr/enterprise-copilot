"""Resilience tests for the Gemini generation path.

Background: Gemini returns 503 UNAVAILABLE ("high demand") under load. Without a
retry and a fallback model, a busy upstream takes the whole RAG pipeline down —
which is how a demo fails in front of a customer.

These run without a database and without network access: the Gemini client is
replaced with a stub that raises whatever the test needs.
"""

from types import SimpleNamespace

import pytest

from app import main


class FakeServerError(Exception):
    """Stands in for google.genai.errors.ServerError (503)."""

    code = 503


class FakeBadRequest(Exception):
    """Stands in for a 400 — prompt or auth failure, never worth retrying."""

    code = 400


class _Missing:
    """Distinguishes "nothing scripted" from a scripted empty response."""


_MISSING = _Missing()


class StubModels:
    def __init__(self, script, default=None):
        # script: one value or exception per attempt. Once exhausted, `default`
        # is used when given; otherwise the last scripted item repeats, so an
        # "always failing" model keeps failing however many attempts run.
        # None is a valid scripted value: it means an empty response body.
        self.script = list(script)
        self.calls = []
        self.default = default
        self.last: object = _MISSING

    def generate_content(self, model, contents, config=None):
        self.calls.append(model)
        if self.script:
            nxt: object = self.script.pop(0)
            self.last = nxt
        elif self.default is not None:
            nxt = self.default
        else:
            nxt = self.last
        if nxt is _MISSING:
            raise AssertionError(f"stub exhausted on attempt for {model} (calls: {self.calls})")
        if isinstance(nxt, Exception):
            raise nxt
        return SimpleNamespace(text=nxt)


@pytest.fixture
def stub_client(monkeypatch):
    def install(script, default=None):
        stub = StubModels(script, default=default)
        monkeypatch.setattr(main, "gemini_client", SimpleNamespace(models=stub))
        monkeypatch.setattr(main, "GEMINI_MAX_ATTEMPTS", 3)
        monkeypatch.setattr(main, "GEMINI_BACKOFF_SECONDS", 0)
        monkeypatch.setattr(main, "GEMINI_CHAT_MODEL", "primary-model")
        monkeypatch.setattr(
            main, "GEMINI_CHAT_MODEL_FALLBACKS", ("fallback-a", "fallback-b")
        )
        return stub

    return install


def test_success_on_first_attempt(stub_client):
    stub = stub_client(["hello"])
    assert main.query_gemini("q") == "hello"
    assert stub.calls == ["primary-model"]


def test_retries_then_succeeds_on_the_same_model(stub_client):
    stub = stub_client([FakeServerError("busy"), FakeServerError("busy"), "recovered"])
    assert main.query_gemini("q") == "recovered"
    assert stub.calls == ["primary-model"] * 3


def test_falls_back_through_the_chain_when_primary_is_exhausted(stub_client):
    """A whole model family can be down at once, so the chain must be walked."""
    stub = stub_client(
        [FakeServerError("busy")] * 3
        + [FakeServerError("busy")] * 3
        + ["answered by the second fallback"]
    )
    assert main.query_gemini("q") == "answered by the second fallback"
    assert stub.calls == ["primary-model"] * 3 + ["fallback-a"] * 3 + ["fallback-b"]


def test_chain_ends_at_the_last_fallback(stub_client):
    # primary(3) + fallback-a(3) all fail; fallback-b answers on its first try.
    stub = stub_client([FakeServerError("busy")] * 6 + ["last one standing"])
    assert main.query_gemini("q") == "last one standing"
    assert stub.calls[-1] == "fallback-b"
    assert stub.calls == ["primary-model"] * 3 + ["fallback-a"] * 3 + ["fallback-b"]


def test_non_transient_error_stops_the_chain_immediately(stub_client):
    """A 400 on the primary must not burn six more upstream calls."""
    stub = stub_client([FakeBadRequest("bad prompt"), "never reached"])
    with pytest.raises(FakeBadRequest):
        main.query_gemini("q")
    assert stub.calls == ["primary-model"]


def test_final_failure_raises_the_underlying_error(stub_client):
    """3 models x 3 attempts must all be spent before the error surfaces."""
    stub = stub_client([FakeServerError("busy")])
    with pytest.raises(FakeServerError):
        main.query_gemini("q")
    assert stub.calls == ["primary-model"] * 3 + ["fallback-a"] * 3 + ["fallback-b"] * 3


def test_non_transient_errors_are_not_retried(stub_client):
    """A 400 must fail immediately — retrying it just wastes the user's time."""
    stub = stub_client([FakeBadRequest("bad prompt"), "never reached"])
    with pytest.raises(FakeBadRequest):
        main.query_gemini("q")
    assert stub.calls == ["primary-model"]


def test_duplicate_and_self_referencing_fallbacks_are_skipped(stub_client):
    """A fallback naming the primary would otherwise double its attempt budget."""
    stub = stub_client(["ok from primary"])
    main.GEMINI_CHAT_MODEL = "primary-model"
    monkey = main.GEMINI_CHAT_MODEL_FALLBACKS
    try:
        main.GEMINI_CHAT_MODEL_FALLBACKS = ("primary-model", "", "primary-model")
        assert main.query_gemini("q") == "ok from primary"
        assert stub.calls == ["primary-model"]
    finally:
        main.GEMINI_CHAT_MODEL_FALLBACKS = monkey


def test_empty_response_is_treated_as_a_failure(stub_client):
    stub = stub_client([None, "second attempt"])
    assert main.query_gemini("q") == "second attempt"
    assert stub.calls == ["primary-model", "primary-model"]


def test_missing_api_key_fails_before_any_call(monkeypatch):
    monkeypatch.setattr(main, "gemini_client", None)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        main.query_gemini("q")


def test_transient_classifier():
    assert main._is_transient(FakeServerError("x"))
    assert not main._is_transient(FakeBadRequest("x"))
    assert main._is_transient(Exception("boom").__class__("boom")) is False