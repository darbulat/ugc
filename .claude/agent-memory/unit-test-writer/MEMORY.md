# Unit Test Writer Memory

## Project: ugc

### Testing Framework & Conventions
- **Framework**: pytest with `pytest.mark.asyncio` (mode=STRICT)
- **Async tests**: All async tests require `@pytest.mark.asyncio` decorator
- **Timeout**: 5 seconds per test (hard limit)
- **Coverage threshold**: 98% (checked with `make coverage`)
- **Run single file**: `uv run pytest tests/path/to/test_file.py -v`

### Test Organization
- `tests/unit/` — pure unit tests
- `tests/infrastructure/` — infrastructure unit tests (memory repos, caches, db models)
- `tests/integration/` — DB integration tests with `@pytest.mark.integration`
- In-memory fakes for repos: `infrastructure/memory_repositories.py` and `tests/helpers/fakes.py`
- Entity factories: `tests/helpers/factories.py`

### Key Patterns
- **In-memory repos**: Use `InMemory*Repository` from `infrastructure/memory_repositories.py` for testing services without a real DB
- **Domain entities**: All are frozen dataclasses; use `dataclasses.replace()` for mutations
- **Mocking dialects**: Use `MagicMock()` with `dialect.name = "postgresql"` for SQLAlchemy TypeDecorator tests
- **Patching `_evict_expired`**: Use `patch.object(cache, "_evict_expired")` to isolate per-entry expiry checks in `GeocoderCacheMemory`
- **ImportError path in _get_redis**: Patch `builtins.__import__` to raise ImportError for `"redis.asyncio"` to cover the fallback branch in `GeocoderCacheRedis._get_redis()`

### Middleware & API Helper Test Patterns
- **Bot middleware tests**: Place in `tests/unit/bot/middleware/` (no `__init__.py` needed)
- **Miniapp helper tests**: Place in `tests/unit/miniapp/` (no `__init__.py` needed)
- **Mocking FastAPI Request**: Use `MagicMock()` with `request.app.state.config.market.default_locale = "ru"` and `request.app.state.dispatcher = dispatcher_mock`
- **Mocking aiogram middleware data**: Pass plain `dict` with keys like `user_repo`, `country_repo`, `event_from_user` (MagicMock with `.id` attribute)
- **Dispatcher mock pattern**: `dispatcher.get = lambda key: user_repo if key == "user_repo" else country_repo` for conditional returns
- **Pre-existing flaky tests**: `tests/admin/test_dashboard.py` has 3 timeout-flaky tests that fail only under full suite load (not a coverage concern)

### Important Files
- `src/ugc_bot/infrastructure/db/models.py` — `_GeometryOrText` TypeDecorator (tests in `tests/infrastructure/test_db_models.py`)
- `src/ugc_bot/infrastructure/memory_repositories.py` — All in-memory repo implementations
- `src/ugc_bot/infrastructure/geocoder_cache_memory.py` — In-memory TTL cache
- `src/ugc_bot/infrastructure/geocoder_cache_redis.py` — Redis cache with ImportError fallback
- `src/ugc_bot/domain/entities.py` — All domain entity dataclasses
- `src/ugc_bot/domain/enums.py` — All domain enums

### InstagramStatsModel Fields (gotcha)
The ORM model uses: `user_id`, `raw_response` (dict), `fetched_at`, `followers_count`, `follows_count`, `media_count`, `instagram_username`, `biography`, `provider`, `instagram_id`. NOT `followers`, `following`, `posts`, `er`.
