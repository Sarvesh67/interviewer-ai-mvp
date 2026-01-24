import types

import pytest


def test_create_hedra_image_avatar_returns_created_avatar_id(monkeypatch, tmp_path):
    import hedra_avatar
    from config import settings

    avatar_id = hedra_avatar.create_hedra_image_avatar(
        job_title="Backend Engineer",
        technical_expertise="Python"
    )
    
    from utils.string_utils import StringUtils
    assert StringUtils.looks_like_uuid(avatar_id)