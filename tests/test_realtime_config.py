import importlib


def _reload_config_with_env(monkeypatch, env: dict):
    """
    Reload `config` module after setting environment variables so pydantic-settings
    re-reads values.
    """
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import config  # noqa: WPS433

    return importlib.reload(config)


def test_get_missing_realtime_keys_all_missing(monkeypatch):
    config = _reload_config_with_env(
        monkeypatch,
        {
            # Use empty strings to override any values coming from a local `.env`
            "LIVEKIT_URL": "",
            "LIVEKIT_API_KEY": "",
            "LIVEKIT_API_SECRET": "",
            "GEMINI_API_KEY": "",
            "DEEPGRAM_API_KEY": "",
        },
    )
    missing = config.get_missing_realtime_keys()
    # LIVEKIT is grouped as one
    assert set(missing) == {"LIVEKIT", "GEMINI", "DEEPGRAM"}


def test_get_missing_realtime_keys_all_present(monkeypatch):
    config = _reload_config_with_env(
        monkeypatch,
        {
            "LIVEKIT_URL": "wss://example.livekit.cloud",
            "LIVEKIT_API_KEY": "k",
            "LIVEKIT_API_SECRET": "s",
            "GEMINI_API_KEY": "g",
            "DEEPGRAM_API_KEY": "d",
        },
    )
    assert config.get_missing_realtime_keys() == []
