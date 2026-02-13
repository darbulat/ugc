"""Root conftest: register plugins that must be at top level (pytest 8+)."""

# Register Telegram E2E fixtures so e2e_telegram tests can use them.
pytest_plugins = ["tests.e2e.telegram_client"]
