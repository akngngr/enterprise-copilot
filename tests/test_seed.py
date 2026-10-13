"""Seed-document behaviour.

The seed exists so a first-time visitor gets a real answer instead of "I
couldn't find any relevant documents". The risk it introduces is the obvious
one: a default document that is visible to everyone, or that survives after the
visitor uploads their own. These tests pin both.

Runs without a database: the seed module's decisions are driven by injected
callables, so the policy is testable without Postgres.
"""

from types import SimpleNamespace

import pytest

from app import seed


class FakeDocument:
    def __init__(self, id="d1", owner_id="u1", is_seed=False):
        self.id = id
        self.owner_id = owner_id
        self.is_seed = is_seed


class FakeColumn:
    """Stands in for a SQLAlchemy InstrumentedAttribute.

    `Document.is_seed.is_(True)` has to yield something the fake can match on,
    and `Document.owner_id` has to compare equal to a string. Both go through
    the same predicate form so FakeDB can filter on either.
    """

    def __init__(self, name, value=None):
        self.name = name
        self.value = value

    def is_(self, value):
        return FakeColumn(self.name, value)

    def __eq__(self, other):
        return FakeColumn(self.name, other)

    def __hash__(self):
        return id(self)

    def matches(self, row):
        actual = getattr(row, self.name)
        return actual == self.value if self.value is not None else actual == self


class FakeDocModel:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def __getattr__(self, name):
        return FakeColumn(name)


class FakeDB:
    """Minimal stand-in for a Session, recording what the seed code did."""

    def __init__(self, documents=()):
        self.documents = list(documents)
        self.committed = 0
        self.rolled_back = 0
        self.deleted = []

    def execute(self, statement):
        conditions = getattr(statement, "_conditions", None) or []
        rows = self.documents
        for predicate in conditions:
            if isinstance(predicate, FakeColumn):
                rows = [row for row in rows if predicate.matches(row)]
        return SimpleNamespace(first=lambda: rows[0] if rows else None)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def delete(self, statement):
        self.deleted.append(statement)
        return SimpleNamespace(rowcount=len(self.deleted))


@pytest.fixture
def patched(monkeypatch):
    """Route the seed module's queries at the in-memory fakes above."""
    rows = {"documents": []}

    class FakeSelect:
        def __init__(self, model):
            self._conditions = []

        def where(self, *conditions):
            self._conditions.extend(conditions)
            return self

    monkeypatch.setattr(seed, "select", FakeSelect)
    monkeypatch.setattr(seed, "Document", FakeDocModel(rows["documents"]))

    class FakeDelete:
        def __init__(self, model):
            self._conditions = []

        def where(self, *conditions):
            self._conditions.extend(conditions)
            return self

    monkeypatch.setattr(seed, "delete", FakeDelete)
    return seed


def test_seed_is_created_for_a_brand_new_user(patched, monkeypatch):
    db = FakeDB()
    calls = []

    monkeypatch.setattr(patched, "seed_bytes", lambda: b"%PDF-1.4 fake")
    monkeypatch.setattr(
        patched,
        "process_pdf",
        lambda **kw: calls.append(kw) or SimpleNamespace(id="seed-1"),
    )

    assert patched.ensure_seed_document(db, "u1") is True
    assert len(calls) == 1
    assert calls[0]["owner_id"] == "u1"
    assert calls[0]["original_filename"] == patched.SEED_FILENAME
    assert db.committed == 1


def test_seed_is_not_duplicated_on_a_second_call(patched, monkeypatch):
    db = FakeDB([FakeDocument(owner_id="u1", is_seed=True)])
    calls = []
    monkeypatch.setattr(patched, "process_pdf", lambda **kw: calls.append(kw))

    assert patched.ensure_seed_document(db, "u1") is False
    assert calls == []
    assert db.committed == 0


def test_user_upload_suppresses_reseeding(patched, monkeypatch):
    """A visitor who uploaded their own PDF must never get the seed back."""
    db = FakeDB([FakeDocument(owner_id="u1", is_seed=False)])
    calls = []
    monkeypatch.setattr(patched, "process_pdf", lambda **kw: calls.append(kw))

    assert patched.has_user_document(db, "u1") is True
    assert patched.ensure_seed_document(db, "u1") is False
    assert calls == []


def test_seed_is_scoped_per_user(patched, monkeypatch):
    """One user's seed must not satisfy another user's check.

    The FakeDB filter must consider owner_id, not just is_seed, or this test
    passes for the wrong reason.
    """
    db = FakeDB([FakeDocument(owner_id="user-a", is_seed=True)])
    calls = []
    monkeypatch.setattr(patched, "seed_bytes", lambda: b"%PDF-1.4 fake")
    monkeypatch.setattr(patched, "process_pdf", lambda **kw: calls.append(kw))

    assert patched.ensure_seed_document(db, "user-b") is True
    assert calls[0]["owner_id"] == "user-b"
    # And user-a still sees their existing seed, not a second one.
    calls.clear()
    assert patched.ensure_seed_document(db, "user-a") is False
    assert calls == []


def test_a_missing_seed_file_is_a_no_op_not_an_error(patched, monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(patched, "seed_bytes", lambda: None)

    assert patched.ensure_seed_document(db, "u1") is False
    assert db.rolled_back == 0
    assert db.committed == 0


def test_a_failing_seed_never_breaks_the_session(patched, monkeypatch, capsys):
    """A convenience must not become a dependency."""

    def explode(**kwargs):
        raise RuntimeError("embedding provider unreachable")

    db = FakeDB()
    monkeypatch.setattr(patched, "seed_bytes", lambda: b"%PDF-1.4 fake")
    monkeypatch.setattr(patched, "process_pdf", explode)

    assert patched.ensure_seed_document(db, "u1") is False
    assert db.rolled_back == 1
    assert db.committed == 0
    assert "[seed] skipped" in capsys.readouterr().out


def test_drop_seed_deletes_within_a_transaction(patched, monkeypatch):
    """A deletion that is never committed would leave the seed in place.

    The statement itself is asserted by inspection rather than by executing it
    against a fake: the WHERE clause is SQLAlchemy's job, and asserting on a
    stub would only assert that the stub was called.
    """
    recorded = {}

    class RecordingDelete:
        def where(self, *conditions):
            recorded["conditions"] = conditions
            return self

    class FakeStatement:
        def where(self, *conditions):
            recorded["conditions"] = conditions
            return self

    monkeypatch.setattr(seed, "delete", lambda model: FakeStatement())

    db = FakeDB()
    monkeypatch.setattr(
        db, "execute", lambda stmt: SimpleNamespace(rowcount=1)
    )

    assert patched.drop_seed(db, "u1") == 1
    assert db.committed == 1
    conditions = recorded.get("conditions", ())
    assert conditions, "delete must be scoped by at least one condition"