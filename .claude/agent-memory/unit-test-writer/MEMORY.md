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

### Max Handler Test Patterns
- **_deps() mock config**: Must include `mock_config.docs.get_urls_for_country = MagicMock(return_value=(...))` when testing handlers that call `format_agreements_message` (advertiser/blogger registration, my_orders agreement prompt)
- **keyboard text keys**: `role_inline_keyboard` needs `btn_creator`, `btn_advertiser`, `btn_support` in `get_many` return; `confirm_agreement_inline_keyboard` needs `btn_confirm_agreement`
- **RejectionReason values**: Only `LOW_PRICE`, `WRONG_FORMAT`, `UNINTERESTING_PRODUCT`, `NO_TIME`, `ALREADY_WORKING_WITH_BRAND` — no `TOO_EXPENSIVE`
- **TransactionManager mock**: Use `@asynccontextmanager` on a nested function for `tm.transaction` when the handler uses `async with transaction_manager.transaction() as session`
- **FakeMessengerClient for /referral**: Use `from tests.helpers.fakes import FakeMessengerClient` when testing handlers that append `sent_text` (use `.sent_text[0]["text"]` to inspect)
- **Defensive `else` branches**: Cannot be reached through router routing (state predicates block them); test them by importing and calling handler functions directly
- **Pre-existing failure**: `tests/unit/bot/max/handlers/test_feedback.py::test_handle_no_deal_other_text_user_not_found` fails — not related to blogger/advertiser handler tests
- **instagram_stats_collector_service**: Pure functions `_safe_float`, `_safe_bool`, `_extract_post_metrics`, `_extract_posting_frequency`, `_extract_profile_fields`, `_get_posts_from_raw`, `_get_user_dict`, `_extract_analytics_fields` are testable without mocking; extra tests in `tests/application/services/test_instagram_stats_collector_service_extra.py`
- **Max handler `if not incoming.data:` guards**: Test by importing handler functions directly and calling with `data=None` IncomingCallback; don't rely on router routing
- **Unreachable defensive branches**: Lines guarded by `if not isinstance(data, dict): return []` in `_get_posts_from_raw` (line 395) and similar are truly unreachable when args are correctly typed; don't waste time trying to cover them
