"""
Tests for the PostgreSQL database layer: models, CRUD, and API endpoints.

Uses async SQLite in-memory to avoid requiring a running PostgreSQL instance.
"""
import json
import sys
import uuid
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base, User, Interview, Report

# ──────────────────────────────────────────────
# Stub out heavy third-party imports that aren't
# available outside Docker (livekit plugins, hedra, etc.)
# so we can import app.server in tests.
# ──────────────────────────────────────────────

_STUBS = [
    "livekit.plugins",
    "livekit.plugins.google",
    "livekit.plugins.deepgram",
    "livekit.plugins.hedra",
    "livekit.plugins.turn_detector",
]

for _mod_name in _STUBS:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = ModuleType(_mod_name)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


def _make_user(email: str = "test@example.com", name: str = "Test User") -> User:
    return User(id=uuid.uuid4(), email=email, name=name)


def _make_interview(user_id, interview_id: str = "interview_aabbccddee01") -> Interview:
    return Interview(
        id=interview_id,
        user_id=user_id,
        job_title="Senior Python Engineer",
        candidate_name="Alice",
        candidate_email="alice@example.com",
        domain_knowledge={"required_skills": [{"skill": "Python"}], "domain_areas": ["Backend"]},
        questions=[{"question": "What is a decorator?", "competency": "Python"}],
        candidate_info={"name": "Alice", "email": "alice@example.com", "position": "Senior Python Engineer"},
        avatar_id=None,
        status="created",
    )


# ──────────────────────────────────────────────
# Model CRUD Tests
# ──────────────────────────────────────────────

class TestUserModel:
    @pytest.mark.asyncio
    async def test_create_user(self, db: AsyncSession):
        user = _make_user()
        db.add(user)
        await db.commit()

        result = await db.execute(select(User).where(User.email == "test@example.com"))
        fetched = result.scalar_one()
        assert fetched.email == "test@example.com"
        assert fetched.name == "Test User"
        assert fetched.created_at is not None

    @pytest.mark.asyncio
    async def test_user_unique_email(self, db: AsyncSession):
        u1 = _make_user(email="dup@example.com")
        u2 = User(id=uuid.uuid4(), email="dup@example.com", name="Other")
        db.add(u1)
        await db.commit()

        db.add(u2)
        with pytest.raises(Exception):  # IntegrityError
            await db.commit()
        await db.rollback()

    @pytest.mark.asyncio
    async def test_user_defaults(self, db: AsyncSession):
        user = User(id=uuid.uuid4(), email="defaults@example.com")
        db.add(user)
        await db.commit()
        assert user.name == ""
        assert user.created_at is not None
        assert user.updated_at is not None


class TestInterviewModel:
    @pytest.mark.asyncio
    async def test_create_interview(self, db: AsyncSession):
        user = _make_user()
        db.add(user)
        await db.flush()

        interview = _make_interview(user.id)
        db.add(interview)
        await db.commit()

        result = await db.execute(select(Interview).where(Interview.id == "interview_aabbccddee01"))
        fetched = result.scalar_one()
        assert fetched.job_title == "Senior Python Engineer"
        assert fetched.candidate_name == "Alice"
        assert fetched.status == "created"
        assert fetched.answers is None

    @pytest.mark.asyncio
    async def test_interview_user_relationship(self, db: AsyncSession):
        user = _make_user()
        db.add(user)
        await db.flush()

        interview = _make_interview(user.id)
        db.add(interview)
        await db.commit()

        result = await db.execute(select(User).where(User.email == "test@example.com"))
        fetched_user = result.scalar_one()
        assert len(fetched_user.interviews) == 1
        assert fetched_user.interviews[0].id == "interview_aabbccddee01"

    @pytest.mark.asyncio
    async def test_interview_status_update(self, db: AsyncSession):
        user = _make_user()
        db.add(user)
        await db.flush()

        interview = _make_interview(user.id)
        db.add(interview)
        await db.commit()

        interview.status = "in_progress"
        await db.commit()

        result = await db.execute(select(Interview).where(Interview.id == interview.id))
        assert result.scalar_one().status == "in_progress"

    @pytest.mark.asyncio
    async def test_interview_jsonb_answers(self, db: AsyncSession):
        user = _make_user()
        db.add(user)
        await db.flush()

        interview = _make_interview(user.id)
        db.add(interview)
        await db.commit()

        answers_data = [
            {
                "question_idx": 0,
                "question": "What is a decorator?",
                "conversation": [
                    {"role": "interviewer", "type": "main_question", "text": "What is a decorator?"},
                    {"role": "candidate", "type": "answer", "text": "A decorator wraps a function."},
                ],
                "transcript": "A decorator wraps a function.",
                "skipped": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
        interview.answers = answers_data
        await db.commit()

        result = await db.execute(select(Interview).where(Interview.id == interview.id))
        fetched = result.scalar_one()
        assert len(fetched.answers) == 1
        assert fetched.answers[0]["transcript"] == "A decorator wraps a function."
        assert fetched.answers[0]["conversation"][1]["role"] == "candidate"

    @pytest.mark.asyncio
    async def test_interview_jsonb_domain_knowledge(self, db: AsyncSession):
        user = _make_user()
        db.add(user)
        await db.flush()

        interview = _make_interview(user.id)
        db.add(interview)
        await db.commit()

        result = await db.execute(select(Interview).where(Interview.id == interview.id))
        fetched = result.scalar_one()
        assert fetched.domain_knowledge["domain_areas"] == ["Backend"]
        assert fetched.domain_knowledge["required_skills"][0]["skill"] == "Python"


class TestReportModel:
    @pytest.mark.asyncio
    async def test_create_report(self, db: AsyncSession):
        user = _make_user()
        db.add(user)
        await db.flush()

        interview = _make_interview(user.id)
        db.add(interview)
        await db.flush()

        report = Report(
            interview_id=interview.id,
            report_data={
                "overall_score": 7.5,
                "recommendation": "hire",
                "candidate_name": "Alice",
            },
            report_text="Formatted report text here",
            overall_score=7.5,
            recommendation="hire",
        )
        db.add(report)
        await db.commit()

        result = await db.execute(select(Report).where(Report.interview_id == interview.id))
        fetched = result.scalar_one()
        assert float(fetched.overall_score) == 7.5
        assert fetched.recommendation == "hire"
        assert fetched.report_data["candidate_name"] == "Alice"
        assert fetched.report_text == "Formatted report text here"

    @pytest.mark.asyncio
    async def test_report_unique_per_interview(self, db: AsyncSession):
        user = _make_user()
        db.add(user)
        await db.flush()

        interview = _make_interview(user.id)
        db.add(interview)
        await db.flush()

        r1 = Report(interview_id=interview.id, report_data={"score": 5}, overall_score=5, recommendation="review")
        db.add(r1)
        await db.commit()

        r2 = Report(id=uuid.uuid4(), interview_id=interview.id, report_data={"score": 8}, overall_score=8, recommendation="hire")
        db.add(r2)
        with pytest.raises(Exception):  # IntegrityError — unique constraint
            await db.commit()
        await db.rollback()

    @pytest.mark.asyncio
    async def test_interview_report_relationship(self, db: AsyncSession):
        user = _make_user()
        db.add(user)
        await db.flush()

        interview = _make_interview(user.id)
        db.add(interview)
        await db.flush()

        report = Report(interview_id=interview.id, report_data={"score": 8}, overall_score=8, recommendation="strong_hire")
        db.add(report)
        await db.commit()

        # Refresh interview to load relationship
        await db.refresh(interview)
        assert interview.report is not None
        assert interview.report.recommendation == "strong_hire"


# ──────────────────────────────────────────────
# Helper Function Tests
# ──────────────────────────────────────────────

class TestGetOrCreateUser:
    @pytest.mark.asyncio
    async def test_creates_new_user(self, db: AsyncSession):
        from app.server import get_or_create_user

        user = await get_or_create_user(db, "new@example.com", "New User")
        await db.commit()
        assert user.email == "new@example.com"
        assert user.name == "New User"

    @pytest.mark.asyncio
    async def test_returns_existing_user(self, db: AsyncSession):
        from app.server import get_or_create_user

        existing = _make_user(email="existing@example.com", name="Old Name")
        db.add(existing)
        await db.commit()
        original_id = existing.id

        user = await get_or_create_user(db, "existing@example.com", "Updated Name")
        await db.commit()
        assert user.id == original_id
        assert user.name == "Updated Name"


class TestSessionFromInterview:
    def test_reconstruct_session(self):
        from app.server import _session_from_interview

        row = Interview(
            id="interview_test12345678",
            user_id=uuid.uuid4(),
            job_title="Backend Dev",
            candidate_name="Bob",
            candidate_email="bob@test.com",
            domain_knowledge={"domain_areas": ["API"]},
            questions=[{"question": "Design an API", "competency": "System Design"}],
            candidate_info={"name": "Bob", "email": "bob@test.com", "position": "Backend Dev"},
            avatar_id="avatar_123",
            status="created",
            answers=None,
        )

        session = _session_from_interview(row)
        assert session.avatar_id == "avatar_123"
        assert session.candidate_info["name"] == "Bob"
        assert len(session.questions) == 1
        assert session.current_question_idx == 0
        assert session.answers == []

    def test_reconstruct_session_with_answers(self):
        from app.server import _session_from_interview

        answers = [
            {"question_idx": 0, "transcript": "My answer", "skipped": False},
            {"question_idx": 1, "transcript": "Second answer", "skipped": False},
        ]
        row = Interview(
            id="interview_test12345678",
            user_id=uuid.uuid4(),
            job_title="Backend Dev",
            candidate_name="Bob",
            candidate_email="bob@test.com",
            domain_knowledge={},
            questions=[{"question": "Q1"}, {"question": "Q2"}, {"question": "Q3"}],
            candidate_info={"name": "Bob", "email": "bob@test.com", "position": "Backend Dev"},
            avatar_id=None,
            status="in_progress",
            answers=answers,
        )

        session = _session_from_interview(row)
        assert session.current_question_idx == 2
        assert len(session.answers) == 2


# ──────────────────────────────────────────────
# API Endpoint Tests (with test DB + mock auth)
# ──────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_app(engine):
    """Create a test FastAPI app with overridden DB and auth dependencies."""
    from app.server import app
    from db.session import get_db
    from app.server import get_current_user

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_auth():
        return {"email": "testuser@example.com", "name": "Test User"}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_auth

    yield app

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(test_app):
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestListInterviewsEndpoint:
    @pytest.mark.asyncio
    async def test_empty_list(self, client):
        resp = await client.get("/api/v1/interviews")
        assert resp.status_code == 200
        data = resp.json()
        assert data["interviews"] == []

    @pytest.mark.asyncio
    async def test_list_returns_user_interviews(self, client, engine):
        # Seed an interview for the test user
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            user = User(id=uuid.uuid4(), email="testuser@example.com", name="Test User")
            db.add(user)
            await db.flush()
            interview = _make_interview(user.id, "interview_aabbcc000001")
            db.add(interview)
            await db.commit()

        resp = await client.get("/api/v1/interviews")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["interviews"]) == 1
        assert data["interviews"][0]["interview_id"] == "interview_aabbcc000001"
        assert data["interviews"][0]["job_title"] == "Senior Python Engineer"
        assert data["interviews"][0]["has_report"] is False

    @pytest.mark.asyncio
    async def test_list_excludes_other_users(self, client, engine):
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            other_user = User(id=uuid.uuid4(), email="other@example.com", name="Other")
            db.add(other_user)
            await db.flush()
            interview = _make_interview(other_user.id, "interview_aabbcc000002")
            db.add(interview)
            await db.commit()

        resp = await client.get("/api/v1/interviews")
        assert resp.status_code == 200
        assert len(resp.json()["interviews"]) == 0


class TestGetInterviewEndpoint:
    @pytest.mark.asyncio
    async def test_not_found(self, client):
        resp = await client.get("/api/v1/interviews/interview_000000000000")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_id_format(self, client):
        resp = await client.get("/api/v1/interviews/bad_id")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_get_details(self, client, engine):
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            user = User(id=uuid.uuid4(), email="testuser@example.com", name="Test User")
            db.add(user)
            await db.flush()
            interview = _make_interview(user.id, "interview_aabbcc000003")
            db.add(interview)
            await db.commit()

        resp = await client.get("/api/v1/interviews/interview_aabbcc000003")
        assert resp.status_code == 200
        data = resp.json()
        assert data["interview_id"] == "interview_aabbcc000003"
        assert data["job_title"] == "Senior Python Engineer"
        assert data["total_questions"] == 1
        assert data["has_report"] is False


class TestGetReportEndpoint:
    @pytest.mark.asyncio
    async def test_report_not_found(self, client, engine):
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            user = User(id=uuid.uuid4(), email="testuser@example.com", name="Test User")
            db.add(user)
            await db.flush()
            interview = _make_interview(user.id, "interview_aabbcc000004")
            db.add(interview)
            await db.commit()

        resp = await client.get("/api/v1/interviews/interview_aabbcc000004/report")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_report_found(self, client, engine):
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            user = User(id=uuid.uuid4(), email="testuser@example.com", name="Test User")
            db.add(user)
            await db.flush()
            interview = _make_interview(user.id, "interview_aabbcc000005")
            db.add(interview)
            await db.flush()
            report = Report(
                interview_id=interview.id,
                report_data={"overall_score": 8.0, "recommendation": "strong_hire", "candidate_name": "Alice"},
                overall_score=8.0,
                recommendation="strong_hire",
            )
            db.add(report)
            await db.commit()

        resp = await client.get("/api/v1/interviews/interview_aabbcc000005/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_score"] == 8.0
        assert data["recommendation"] == "strong_hire"


class TestCompleteInterviewEndpoint:
    @pytest.mark.asyncio
    async def test_complete_updates_status(self, client, engine):
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            user = User(id=uuid.uuid4(), email="testuser@example.com", name="Test User")
            db.add(user)
            await db.flush()
            interview = _make_interview(user.id, "interview_aabbcc000006")
            interview.status = "in_progress"
            db.add(interview)
            await db.commit()

        # Mock the background task so it doesn't actually run scoring
        with patch("app.server._generate_report_background", new_callable=AsyncMock):
            resp = await client.post("/api/v1/interviews/interview_aabbcc000006/complete")

        assert resp.status_code == 200
        assert resp.json()["status"] == "generating_report"

        # Verify status persisted in DB
        async with session_factory() as db:
            result = await db.execute(select(Interview).where(Interview.id == "interview_aabbcc000006"))
            row = result.scalar_one()
            assert row.status == "generating_report"


class TestStatusTransitions:
    @pytest.mark.asyncio
    async def test_full_lifecycle(self, db: AsyncSession):
        """Test the full status lifecycle: created -> in_progress -> generating_report -> completed."""
        user = _make_user()
        db.add(user)
        await db.flush()

        interview = _make_interview(user.id)
        db.add(interview)
        await db.commit()
        assert interview.status == "created"

        interview.status = "in_progress"
        await db.commit()
        assert interview.status == "in_progress"

        interview.status = "generating_report"
        await db.commit()
        assert interview.status == "generating_report"

        interview.status = "completed"
        await db.commit()
        assert interview.status == "completed"


# ──────────────────────────────────────────────
# Migration Script Tests
# ──────────────────────────────────────────────

class TestMigrationScript:
    @pytest.mark.asyncio
    async def test_parse_old_format(self, tmp_path):
        """Test parsing the old interview JSON format (job_description.domain_knowledge)."""
        from db.migrate_from_files import _parse_interview_file

        data = {
            "avatar_id": "abc-123",
            "job_description": {
                "title": "Backend Engineer",
                "description": "Some desc",
                "domain_knowledge": {"domain_areas": ["Backend"], "required_skills": []},
            },
            "questions": [{"question": "Q1"}],
            "candidate_info": {"name": "Alice", "email": "alice@test.com", "position": "Backend Engineer"},
        }
        path = tmp_path / "interview_aabbccddee01.json"
        path.write_text(json.dumps(data))

        parsed = _parse_interview_file(path)
        assert parsed["job_title"] == "Backend Engineer"
        assert parsed["domain_knowledge"]["domain_areas"] == ["Backend"]
        assert parsed["candidate_name"] == "Alice"
        assert parsed["avatar_id"] == "abc-123"
        assert parsed["user_email"] is None  # old format has no user_email

    @pytest.mark.asyncio
    async def test_parse_new_api_format(self, tmp_path):
        """Test parsing the newer _api.json format (flat top-level keys)."""
        from db.migrate_from_files import _parse_interview_file

        data = {
            "domain_knowledge": {"domain_areas": ["Frontend"]},
            "questions": [{"question": "Q1"}],
            "candidate_info": {"name": "Bob", "email": "bob@test.com", "position": "Frontend Dev"},
            "avatar_id": None,
            "user_email": "owner@company.com",
            "created_at": "2026-02-01T10:00:00",
            "status": "completed",
            "job_title": "Frontend Dev",
        }
        path = tmp_path / "interview_aabbccddee02_api.json"
        path.write_text(json.dumps(data))

        parsed = _parse_interview_file(path)
        assert parsed["job_title"] == "Frontend Dev"
        assert parsed["user_email"] == "owner@company.com"
        assert parsed["status"] == "completed"

    @pytest.mark.asyncio
    async def test_discover_interviews(self, tmp_path, monkeypatch):
        """Test that _discover_interviews finds all file types."""
        import db.migrate_from_files as mig

        interview_store = tmp_path / "interview_store"
        interview_store.mkdir()
        uploads = tmp_path / "uploads"
        uploads.mkdir()

        # Create test files
        (interview_store / "interview_aabbccddee01.json").write_text("{}")
        (interview_store / "interview_aabbccddee01_answers.json").write_text("{}")
        (uploads / "interview_aabbccddee01_report.json").write_text("{}")
        (uploads / "interview_aabbccddee01_report.txt").write_text("")

        monkeypatch.setattr(mig, "INTERVIEW_STORE", interview_store)
        monkeypatch.setattr(mig, "UPLOADS", uploads)

        discovered = mig._discover_interviews()
        assert "interview_aabbccddee01" in discovered
        entry = discovered["interview_aabbccddee01"]
        assert "interview_path" in entry
        assert "answers_path" in entry
        assert "report_json_path" in entry
        assert "report_txt_path" in entry

    @pytest.mark.asyncio
    async def test_migrate_end_to_end(self, tmp_path, monkeypatch, engine):
        """Full migration: write JSON files → run migrate → verify DB rows."""
        import db.migrate_from_files as mig

        interview_store = tmp_path / "interview_store"
        interview_store.mkdir()
        uploads = tmp_path / "uploads"
        uploads.mkdir()

        # Write a sample interview file (old format)
        interview_data = {
            "avatar_id": "av-1",
            "job_description": {
                "title": "Data Engineer",
                "description": "Build pipelines",
                "domain_knowledge": {"domain_areas": ["Data"], "required_skills": []},
            },
            "questions": [{"question": "What is ETL?", "competency": "Data"}],
            "candidate_info": {"name": "Carol", "email": "carol@test.com", "position": "Data Engineer"},
        }
        (interview_store / "interview_aabbcc112233.json").write_text(json.dumps(interview_data))

        # Write a report
        report_data = {"overall_score": 7.0, "recommendation": "hire", "candidate_name": "Carol"}
        (uploads / "interview_aabbcc112233_report.json").write_text(json.dumps(report_data))
        (uploads / "interview_aabbcc112233_report.txt").write_text("Report text here")

        monkeypatch.setattr(mig, "INTERVIEW_STORE", interview_store)
        monkeypatch.setattr(mig, "UPLOADS", uploads)

        # Patch the engine creation in the migrate function to use our test engine
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def patched_migrate():
            """Run migration logic against the test database."""
            discovered = mig._discover_interviews()
            async with session_factory() as db:
                for iid, paths in discovered.items():
                    data = mig._parse_interview_file(paths["interview_path"])
                    email = "migrator@test.com"

                    result = await db.execute(select(User).where(User.email == email))
                    user = result.scalar_one_or_none()
                    if user is None:
                        user = User(email=email, name="Migrator")
                        db.add(user)
                        await db.flush()

                    interview = Interview(
                        id=iid,
                        user_id=user.id,
                        job_title=data["job_title"],
                        candidate_name=data["candidate_name"],
                        candidate_email=data["candidate_email"],
                        domain_knowledge=data["domain_knowledge"],
                        questions=data["questions"],
                        candidate_info=data["candidate_info"],
                        avatar_id=data["avatar_id"],
                        status="completed",
                    )
                    db.add(interview)
                    await db.flush()

                    report_json_path = paths.get("report_json_path")
                    if report_json_path:
                        rd = json.loads(report_json_path.read_text())
                        rt = paths.get("report_txt_path")
                        report = Report(
                            interview_id=iid,
                            report_data=rd,
                            report_text=rt.read_text() if rt else None,
                            overall_score=rd.get("overall_score"),
                            recommendation=rd.get("recommendation"),
                        )
                        db.add(report)

                await db.commit()

        await patched_migrate()

        # Verify data landed in DB
        async with session_factory() as db:
            result = await db.execute(select(Interview).where(Interview.id == "interview_aabbcc112233"))
            interview = result.scalar_one()
            assert interview.job_title == "Data Engineer"
            assert interview.candidate_name == "Carol"
            assert interview.domain_knowledge["domain_areas"] == ["Data"]

            result = await db.execute(select(Report).where(Report.interview_id == "interview_aabbcc112233"))
            report = result.scalar_one()
            assert float(report.overall_score) == 7.0
            assert report.recommendation == "hire"
            assert report.report_text == "Report text here"

            result = await db.execute(select(User).where(User.email == "migrator@test.com"))
            user = result.scalar_one()
            assert user.name == "Migrator"
