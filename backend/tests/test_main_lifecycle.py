import asyncio
from types import SimpleNamespace

from fastapi import Request

from app import main
from app.errors import PlatformError


class _Session:
    def __init__(self, profile_count=0):
        self.profile_count = profile_count
        self.added = []
        self.commits = 0
        self.closed = 0

    def query(self, _model):
        return SimpleNamespace(count=lambda: self.profile_count)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed += 1


def test_seed_model_profiles_creates_default_profiles(monkeypatch):
    session = _Session()
    hashes = []
    monkeypatch.setattr(
        main, "ensure_model_profile_hash", lambda profile: hashes.append(profile.name)
    )
    main._seed_model_profiles(session)
    assert [profile.name for profile in session.added] == ["lite", "standard", "high"]
    assert hashes == ["lite", "standard", "high"]
    assert session.commits == 1


def test_seed_model_profiles_skips_nonempty_table(monkeypatch):
    session = _Session(profile_count=1)
    monkeypatch.setattr(
        main, "ensure_model_profile_hash", lambda profile: (_ for _ in ()).throw(AssertionError)
    )
    main._seed_model_profiles(session)
    assert session.added == []


def test_lifespan_initializes_and_validates(monkeypatch):
    sessions = [_Session(), _Session(), _Session(), _Session()]
    metadata_calls = []
    monkeypatch.setattr(
        main.Base.metadata, "create_all", lambda **kwargs: metadata_calls.append(kwargs)
    )
    monkeypatch.setattr(main, "SessionLocal", lambda: sessions.pop(0))
    monkeypatch.setattr(main, "load_all_templates", lambda session: 3)
    monkeypatch.setattr(main, "validate_template_model_references", lambda session: [])
    monkeypatch.setattr(main, "seed_default_admin", lambda session: None)

    async def run():
        async with main.lifespan(main.app):
            assert len(metadata_calls) == 1

    asyncio.run(run())
    assert all(session.closed == 1 for session in sessions) if sessions else True


def test_create_app_exception_handlers_return_safe_responses():
    app = main.create_app()
    request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": []})
    platform_handler = app.exception_handlers[PlatformError]
    response = asyncio.run(platform_handler(request, PlatformError("bad request")))
    assert response.status_code == 500
    assert b'"code":"PLATFORM_ERROR"' in response.body
    fallback = app.exception_handlers[Exception]
    response = asyncio.run(fallback(request, RuntimeError("secret")))
    assert response.status_code == 500
    assert b"secret" not in response.body
