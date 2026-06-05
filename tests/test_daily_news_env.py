"""Environment checks for daily_news (KAZ-214)."""

import daily_news


def test_required_env_vars_exclude_youtube() -> None:
    assert "YOUTUBE_API_KEY" not in daily_news.REQUIRED_ENV_VARS
