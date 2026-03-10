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

### Important Files
- `src/ugc_bot/infrastructure/db/models.py` — `_GeometryOrText` TypeDecorator (tests in `tests/infrastructure/test_db_models.py`)
- `src/ugc_bot/infrastructure/memory_repositories.py` — All in-memory repo implementations
- `src/ugc_bot/infrastructure/geocoder_cache_memory.py` — In-memory TTL cache
- `src/ugc_bot/infrastructure/geocoder_cache_redis.py` — Redis cache with ImportError fallback
- `src/ugc_bot/domain/entities.py` — All domain entity dataclasses
- `src/ugc_bot/domain/enums.py` — All domain enums
