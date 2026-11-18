"""Dependency failures must fail readiness without changing liveness."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot import readiness
from ugc_bot.admin.app import _add_health_route
from ugc_bot.instagram_webhook_app import app as instagram_app
from ugc_bot.max_webhook_app import app as max_app
from ugc_bot.telegram_webhook_app import app as telegram_app


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield async_sessionmaker(engine)
    await engine.dispose()


def failed_factory():
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(
        side_effect=ConnectionError("private-database-credentials")
    )
    return factory


@pytest.mark.asyncio
async def test_readiness_checks_real_database_and_redis(session_factory):
    redis = SimpleNamespace(ping=AsyncMock(return_value=True))
    response = await readiness.readiness_response(session_factory, redis)
    assert response.status_code == 200
    assert response.body == b'{"status":"ok"}'
    redis.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_readiness_checks_database_without_redis(session_factory):
    response = await readiness.readiness_response(session_factory)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_readiness_fails_before_initialization():
    response = await readiness.readiness_response(None)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_readiness_hides_database_connection_errors():
    response = await readiness.readiness_response(failed_factory())
    assert response.status_code == 503
    assert response.body == b'{"status":"unavailable"}'


@pytest.mark.asyncio
async def test_readiness_fails_for_redis_outage(session_factory):
    redis = SimpleNamespace(ping=AsyncMock(side_effect=ConnectionError()))
    response = await readiness.readiness_response(session_factory, redis)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_readiness_fails_for_unsuccessful_redis_ping(session_factory):
    redis = SimpleNamespace(ping=AsyncMock(return_value=False))
    response = await readiness.readiness_response(session_factory, redis)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_readiness_deadline_cancels_and_closes_database(monkeypatch):
    monkeypatch.setattr(readiness, "READINESS_TIMEOUT", 0.01)
    session = MagicMock()

    async def slow_execute(_):
        await asyncio.sleep(5)

    session.execute = AsyncMock(side_effect=slow_execute)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    async with asyncio.timeout(1):
        response = await readiness.readiness_response(factory)
    assert response.status_code == 503
    factory.return_value.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_readiness_deadline_includes_redis(monkeypatch, session_factory):
    monkeypatch.setattr(readiness, "READINESS_TIMEOUT", 0.02)

    async def slow_ping():
        await asyncio.sleep(5)

    redis = SimpleNamespace(ping=slow_ping)
    async with asyncio.timeout(1):
        response = await readiness.readiness_response(session_factory, redis)
    assert response.status_code == 503


@pytest.mark.parametrize("application", [telegram_app, max_app, instagram_app])
def test_ready_route_uses_initialized_database(application, monkeypatch):
    factory = failed_factory()
    container = SimpleNamespace(session_factory=factory)
    monkeypatch.setattr(
        application.state, "container", container, raising=False
    )
    monkeypatch.setattr(
        application.state, "dispatcher", {"container": container}, raising=False
    )
    client = TestClient(application)
    assert client.get("/ready").status_code == 503
    assert client.get("/health").status_code == 200
    factory.assert_called_once()


@pytest.mark.parametrize("application", [telegram_app, max_app, instagram_app])
def test_ready_route_fails_without_container(application, monkeypatch):
    monkeypatch.setattr(application.state, "container", None, raising=False)
    monkeypatch.setattr(application.state, "dispatcher", {}, raising=False)
    assert TestClient(application).get("/ready").status_code == 503


@pytest.mark.parametrize("application", [telegram_app, max_app])
@pytest.mark.asyncio
async def test_ready_route_checks_real_storage(
    application, monkeypatch, session_factory
):
    container = SimpleNamespace(session_factory=session_factory)
    redis = SimpleNamespace(ping=AsyncMock(side_effect=ConnectionError()))
    monkeypatch.setattr(
        application.state, "container", container, raising=False
    )
    monkeypatch.setattr(
        application.state, "dispatcher", {"container": container}, raising=False
    )
    monkeypatch.setattr(application.state, "redis", redis, raising=False)
    monkeypatch.setattr(
        application.state,
        "storage",
        SimpleNamespace(redis=redis),
        raising=False,
    )
    assert TestClient(application).get("/ready").status_code == 503
    redis.ping.assert_awaited_once()


def test_admin_readiness_fails_database_outage():
    app = FastAPI()
    engine = create_engine("sqlite:///:memory:")
    _add_health_route(app, engine, failed_factory())
    assert TestClient(app).get("/ready").status_code == 503
    assert TestClient(app).get("/health").status_code == 200
    engine.dispose()


@pytest.mark.asyncio
async def test_admin_readiness_uses_database(session_factory):
    app = FastAPI()
    engine = create_engine("sqlite:///:memory:")
    _add_health_route(app, engine, session_factory)
    assert TestClient(app).get("/ready").status_code == 200
    engine.dispose()
