from ugc_bot.domain.enums import UserStatus


def test_bot_blocked_status_exists() -> None:
    assert UserStatus.BOT_BLOCKED == "bot_blocked"
