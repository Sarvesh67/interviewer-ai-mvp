import importlib
import types

import pytest


class _DummyRoomService:
    async def create_room(self, *_args, **_kwargs):
        return types.SimpleNamespace(name="dummy-room")


class _DummyLiveKitAPI:
    def __init__(self, *args, **kwargs):
        self.room = _DummyRoomService()


class _DummyAccessToken:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.identity = None
        self.name = None
        self.grants = None

    def with_identity(self, identity):
        self.identity = identity
        return self

    def with_name(self, name):
        self.name = name
        return self

    def with_grants(self, grants):
        self.grants = grants
        return self

    def to_jwt(self):
        # Encode minimal signal for assertions
        return f"jwt(identity={self.identity},name={self.name},room={getattr(self.grants,'room',None)})"


class _DummyVideoGrants:
    def __init__(self, room_join, room, can_publish, can_subscribe):
        self.room_join = room_join
        self.room = room
        self.can_publish = can_publish
        self.can_subscribe = can_subscribe


@pytest.mark.asyncio
async def test_create_interview_room_builds_candidate_join_url(monkeypatch):
    # Reload config with required env
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret")
    import config  # noqa: WPS433

    importlib.reload(config)

    import realtime_interview_manager as rim  # noqa: WPS433

    # Patch livekit api classes used inside manager
    monkeypatch.setattr(rim.api, "LiveKitAPI", _DummyLiveKitAPI)
    monkeypatch.setattr(rim.api, "AccessToken", _DummyAccessToken)
    monkeypatch.setattr(rim.api, "VideoGrants", _DummyVideoGrants)

    manager = rim.RealtimeInterviewManager()

    room_info = await manager.create_interview_room(
        interview_id="interview_123",
        interview_session=types.SimpleNamespace(),
        candidate_name="Alice",
    )

    assert room_info["room_name"] == "interview_123"
    assert room_info["room_url"] == "wss://example.livekit.cloud"
    assert room_info["candidate_join_url"].startswith("wss://example.livekit.cloud?token=")
    assert "jwt(identity=Alice" in room_info["candidate_token"]
    assert "jwt(identity=interviewer-agent" in room_info["agent_token"]


