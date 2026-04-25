"""
Tests for the resume-based (fresher / entry-level) interview flow.

Covers:
  - PDF parsing (happy path + corrupt)
  - Upload validation helpers
  - extract_domain_from_resume (Gemini mocked)
  - generate_technical_questions prompt shaping for target_field
  - create-from-resume endpoint (success, non-PDF, Other-field validation,
    soft-failure parse fallback)
  - /api/v1/resumes/{id} ownership enforcement
  - list/get interview endpoints surface interview_type / target_field / resume_id

All Gemini + Hedra calls are mocked — no API keys required.
"""
from __future__ import annotations

import io
import json
import sys
import uuid
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Stub heavy third-party imports (mirrors test_database.py).
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

from db.models import Base, Interview, Resume, User  # noqa: E402


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _build_pdf(text: str = "Hello World — sample resume content for unit tests.") -> bytes:
    """Produce a tiny in-memory PDF with the given body text. Uses reportlab,
    which is already a project dependency."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 750
    for line in text.split("\n"):
        c.drawString(72, y, line)
        y -= 14
    c.showPage()
    c.save()
    return buf.getvalue()


def _make_gemini_response(text: str) -> MagicMock:
    part = MagicMock(); part.text = text
    content = MagicMock(); content.parts = [part]
    candidate = MagicMock(); candidate.content = content; candidate.finish_reason = 1
    resp = MagicMock()
    resp.text = text
    resp.candidates = [candidate]
    return resp


SAMPLE_DOMAIN_JSON = json.dumps({
    "required_skills": [{"skill": "Python", "level": "beginner", "importance": "high"}],
    "domain_areas": ["Web Development"],
    "technologies": ["Python", "Flask"],
    "problem_domains": ["Simple CRUD applications"],
    "soft_skills": ["Communication", "Willingness to learn"],
    "job_title": "Entry-level Web Developer",
    "experience_level": "junior",
    "key_responsibilities": ["Build UI components", "Fix small bugs"],
    "resume_helpful": True,
    "resume_summary": "Recent CS graduate with Flask side-project experience.",
    "candidate_highlights": ["Flask to-do app", "HTML/CSS coursework"],
})


SAMPLE_QUESTIONS_JSON = json.dumps([
    {
        "question": "Explain what a REST API is.",
        "competency": "Web fundamentals",
        "expected_competencies": ["HTTP", "REST"],
        "scoring_rubric": {
            "9-10": "deep", "7-8": "good", "5-6": "ok", "3-4": "poor", "0-2": "none"
        },
        "good_answer_example": "REST is ...",
        "red_flags": ["confuses with SOAP"],
        "question_type": "expertise",
    },
    {
        "question": "Write a function to reverse a string.",
        "competency": "Basic coding",
        "expected_competencies": ["strings", "loops"],
        "scoring_rubric": {
            "9-10": "deep", "7-8": "good", "5-6": "ok", "3-4": "poor", "0-2": "none"
        },
        "good_answer_example": "def reverse(s): ...",
        "red_flags": ["infinite loop"],
        "question_type": "implementation",
    },
])


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


@pytest.fixture
def mock_settings(monkeypatch):
    import config
    monkeypatch.setattr(config.settings, "GEMINI_API_KEY", "test-key-fake")


@pytest_asyncio.fixture
async def test_app(engine):
    """App with DB + auth overridden."""
    from app.server import app, get_current_user
    from db.session import get_db

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_auth():
        return {"email": "student@example.com", "name": "Student"}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_auth
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(test_app):
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ──────────────────────────────────────────────
# Resume parser unit tests
# ──────────────────────────────────────────────

class TestResumeParser:
    def test_parse_pdf_bytes_happy_path(self):
        from core.resume_parser import parse_pdf_bytes

        pdf = _build_pdf("Python developer with Flask experience.")
        text = parse_pdf_bytes(pdf)
        assert "Python" in text
        assert "Flask" in text

    def test_parse_pdf_bytes_corrupt_raises(self):
        from core.resume_parser import ResumeParseError, parse_pdf_bytes

        with pytest.raises(ResumeParseError):
            parse_pdf_bytes(b"this is definitely not a pdf")

    def test_parse_pdf_bytes_empty_raises(self):
        from core.resume_parser import ResumeParseError, parse_pdf_bytes

        with pytest.raises(ResumeParseError):
            parse_pdf_bytes(b"")

    def test_is_text_useful(self):
        from core.resume_parser import is_text_useful

        assert is_text_useful(None) is False
        assert is_text_useful("") is False
        assert is_text_useful("too short") is False
        assert is_text_useful("x" * 200) is True

    def test_validate_resume_upload(self):
        from core.resume_parser import ResumeParseError, validate_resume_upload

        validate_resume_upload("resume.pdf", "application/pdf", 1024)

        with pytest.raises(ResumeParseError):
            validate_resume_upload("resume.pdf", "application/pdf", 0)

        with pytest.raises(ResumeParseError):
            validate_resume_upload("resume.txt", "text/plain", 1024)

        with pytest.raises(ResumeParseError):
            validate_resume_upload("resume.pdf", "application/pdf", 10 * 1024 * 1024)


# ──────────────────────────────────────────────
# Domain extraction tests (Gemini mocked)
# ──────────────────────────────────────────────

class TestExtractDomainFromResume:
    def test_helpful_resume(self, mock_settings):
        from core import domain_extraction

        with patch.object(domain_extraction, "genai") as mock:
            mock_model = MagicMock()
            mock_model.generate_content.return_value = _make_gemini_response(SAMPLE_DOMAIN_JSON)
            mock.GenerativeModel.return_value = mock_model

            result = domain_extraction.extract_domain_from_resume(
                "Python developer ... Flask ... 3 projects ...",
                target_field="Web Development",
            )

        assert result["resume_helpful"] is True
        assert result["target_field"] == "Web Development"
        assert "Web Development" in result["domain_areas"]
        assert result["candidate_highlights"]

    def test_requires_target_field(self, mock_settings):
        from core.domain_extraction import extract_domain_from_resume

        with pytest.raises(ValueError):
            extract_domain_from_resume("Some resume text.", target_field="")

    def test_sparse_resume_defaults(self, mock_settings):
        """When Gemini returns a minimal payload, defaults are filled in."""
        from core import domain_extraction

        minimal = json.dumps({
            "resume_helpful": False,
            "resume_summary": "Resume did not provide enough detail.",
        })

        with patch.object(domain_extraction, "genai") as mock:
            mock_model = MagicMock()
            mock_model.generate_content.return_value = _make_gemini_response(minimal)
            mock.GenerativeModel.return_value = mock_model

            result = domain_extraction.extract_domain_from_resume(
                "", target_field="Finance",
            )

        assert result["resume_helpful"] is False
        # Defensive defaults populated
        assert result["domain_areas"] == ["Finance"]
        assert result["required_skills"] == []
        assert result["experience_level"] == "junior"
        assert result["target_field"] == "Finance"


# ──────────────────────────────────────────────
# Question generator prompt shaping
# ──────────────────────────────────────────────

class TestQuestionGeneratorResumeFlow:
    def test_prompt_includes_target_field_and_entry_level(self, mock_settings):
        from core import question_generator

        with patch.object(question_generator, "genai") as mock:
            mock_model = MagicMock()
            mock_model.generate_content.return_value = _make_gemini_response(SAMPLE_QUESTIONS_JSON)
            mock.GenerativeModel.return_value = mock_model

            qs = question_generator.generate_technical_questions(
                domain_knowledge={"domain_areas": ["Web Development"], "technologies": ["Python"]},
                difficulty_level="intermediate",  # should be overridden to junior
                target_field="Web Development",
                resume_text="Flask side project with 5 routes.",
                resume_helpful=True,
            )

        assert len(qs) == 2
        # Inspect the prompt actually sent to Gemini
        call_args, call_kwargs = mock_model.generate_content.call_args
        prompt_text = call_args[0]
        assert "ENTRY-LEVEL" in prompt_text
        assert "Web Development" in prompt_text
        # Junior path — should explicitly request a junior-level candidate
        assert "junior-level candidate" in prompt_text
        # Helpful resume path — the resume text should be included
        assert "Flask side project" in prompt_text

    def test_non_helpful_resume_excludes_resume_text(self, mock_settings):
        from core import question_generator

        with patch.object(question_generator, "genai") as mock:
            mock_model = MagicMock()
            mock_model.generate_content.return_value = _make_gemini_response(SAMPLE_QUESTIONS_JSON)
            mock.GenerativeModel.return_value = mock_model

            question_generator.generate_technical_questions(
                domain_knowledge={"domain_areas": ["Finance"]},
                target_field="Finance",
                resume_text="Flask side project with 5 routes.",
                resume_helpful=False,
            )

        prompt_text = mock_model.generate_content.call_args[0][0]
        assert "NOT informative" in prompt_text
        assert "Flask side project" not in prompt_text

    def test_jd_flow_unchanged(self, mock_settings):
        """Without target_field the prompt must not include the entry-level block."""
        from core import question_generator

        with patch.object(question_generator, "genai") as mock:
            mock_model = MagicMock()
            mock_model.generate_content.return_value = _make_gemini_response(SAMPLE_QUESTIONS_JSON)
            mock.GenerativeModel.return_value = mock_model

            question_generator.generate_technical_questions(
                domain_knowledge={"domain_areas": ["Backend"]},
                difficulty_level="intermediate",
            )

        prompt_text = mock_model.generate_content.call_args[0][0]
        assert "ENTRY-LEVEL" not in prompt_text


# ──────────────────────────────────────────────
# API endpoint tests
# ──────────────────────────────────────────────

def _patch_resume_pipeline():
    """Patch the slow external dependencies used by create-from-resume.

    Returns a context-manager-friendly ExitStack-ready list of patches. We
    patch the SYMBOLS inside app.server (where they're imported) rather than
    the source modules, so the endpoint uses our mocks.
    """
    patches = [
        patch(
            "app.server.extract_domain_from_resume",
            return_value=json.loads(SAMPLE_DOMAIN_JSON),
        ),
        patch(
            "app.server.generate_technical_questions",
            return_value=json.loads(SAMPLE_QUESTIONS_JSON),
        ),
        patch("app.server.create_hedra_image_avatar", return_value="avatar_test"),
        patch("app.server.register_interview_session"),
        patch("app.server._persist_interview_for_agent"),
    ]
    return patches


class TestResumeFieldsEndpoint:
    @pytest.mark.asyncio
    async def test_list_fields(self, client):
        resp = await client.get("/api/v1/resume-fields")
        assert resp.status_code == 200
        fields = resp.json()["fields"]
        assert "Software Engineering" in fields
        assert "Other" in fields


class TestCreateFromResumeEndpoint:
    @pytest.mark.asyncio
    async def test_success(self, client, engine, mock_settings):
        pdf = _build_pdf("Python, Flask, SQL, coursework in databases, HTML CSS.")

        patches = _patch_resume_pipeline()
        for p in patches: p.start()
        try:
            resp = await client.post(
                "/api/v1/interviews/create-from-resume",
                files={"file": ("resume.pdf", pdf, "application/pdf")},
                data={
                    "target_field": "Web Development",
                    "candidate_name": "Student",
                    "candidate_email": "student@example.com",
                },
            )
        finally:
            for p in patches: p.stop()

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["interview_type"] == "resume"
        assert body["target_field"] == "Web Development"
        assert body["difficulty_level"] == "junior"
        assert body["resume_id"]
        assert body["total_questions"] == 2

        # DB assertions
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as s:
            result = await s.execute(select(Interview))
            interview = result.scalar_one()
            assert interview.interview_type == "resume"
            assert interview.target_field == "Web Development"
            assert interview.resume_id is not None

            resume = (await s.execute(select(Resume))).scalar_one()
            assert resume.size_bytes == len(pdf)
            assert resume.file_data == pdf
            assert resume.extracted_text  # pdfplumber picked something up

    @pytest.mark.asyncio
    async def test_rejects_non_pdf(self, client, mock_settings):
        resp = await client.post(
            "/api/v1/interviews/create-from-resume",
            files={"file": ("resume.txt", b"hello world", "text/plain")},
            data={
                "target_field": "Software Engineering",
                "candidate_name": "Student",
                "candidate_email": "student@example.com",
            },
        )
        assert resp.status_code == 415

    @pytest.mark.asyncio
    async def test_rejects_invalid_target_field(self, client, mock_settings):
        pdf = _build_pdf()
        resp = await client.post(
            "/api/v1/interviews/create-from-resume",
            files={"file": ("resume.pdf", pdf, "application/pdf")},
            data={
                "target_field": "Underwater Basket Weaving",
                "candidate_name": "Student",
                "candidate_email": "student@example.com",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_other_field_requires_custom(self, client, mock_settings):
        pdf = _build_pdf()
        resp = await client.post(
            "/api/v1/interviews/create-from-resume",
            files={"file": ("resume.pdf", pdf, "application/pdf")},
            data={
                "target_field": "Other",
                "candidate_name": "Student",
                "candidate_email": "student@example.com",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_other_field_with_custom(self, client, engine, mock_settings):
        pdf = _build_pdf("Actuarial models, probability, statistics, R programming.")

        patches = _patch_resume_pipeline()
        for p in patches: p.start()
        try:
            resp = await client.post(
                "/api/v1/interviews/create-from-resume",
                files={"file": ("resume.pdf", pdf, "application/pdf")},
                data={
                    "target_field": "Other",
                    "target_field_custom": "Actuarial Science",
                    "candidate_name": "Student",
                    "candidate_email": "student@example.com",
                },
            )
        finally:
            for p in patches: p.stop()

        assert resp.status_code == 200
        assert resp.json()["target_field"] == "Actuarial Science"

    @pytest.mark.asyncio
    async def test_falls_back_when_parse_fails(self, client, engine, mock_settings):
        """A corrupt PDF must not block the interview — we still create one."""
        junk = b"%PDF-1.4\nnot actually a valid pdf\n%%EOF"

        patches = _patch_resume_pipeline()
        for p in patches: p.start()
        try:
            resp = await client.post(
                "/api/v1/interviews/create-from-resume",
                files={"file": ("bad.pdf", junk, "application/pdf")},
                data={
                    "target_field": "Finance",
                    "candidate_name": "Student",
                    "candidate_email": "student@example.com",
                },
            )
        finally:
            for p in patches: p.stop()

        assert resp.status_code == 200
        body = resp.json()
        assert body["interview_type"] == "resume"
        # Interview exists; resume row also exists but extracted_text may be empty
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as s:
            resume = (await s.execute(select(Resume))).scalar_one()
            assert resume.file_data == junk
            # Parsing failed → extracted_text should be None/empty
            assert not resume.extracted_text


class TestGetResumeEndpoint:
    @pytest.mark.asyncio
    async def test_owner_can_fetch(self, client, engine):
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as s:
            user = User(id=uuid.uuid4(), email="student@example.com", name="Student")
            s.add(user); await s.flush()
            resume = Resume(
                id=uuid.uuid4(), user_id=user.id, filename="me.pdf",
                content_type="application/pdf", size_bytes=4,
                file_data=b"%PDF", extracted_text="Sample",
            )
            s.add(resume); await s.commit()
            rid = str(resume.id)

        resp = await client.get(f"/api/v1/resumes/{rid}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == b"%PDF"

    @pytest.mark.asyncio
    async def test_other_user_gets_404(self, client, engine):
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as s:
            other = User(id=uuid.uuid4(), email="other@example.com", name="Other")
            s.add(other); await s.flush()
            resume = Resume(
                id=uuid.uuid4(), user_id=other.id, filename="theirs.pdf",
                content_type="application/pdf", size_bytes=4, file_data=b"%PDF",
            )
            s.add(resume); await s.commit()
            rid = str(resume.id)

        resp = await client.get(f"/api/v1/resumes/{rid}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_uuid_400(self, client):
        resp = await client.get("/api/v1/resumes/not-a-uuid")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_resume_404(self, client):
        resp = await client.get(f"/api/v1/resumes/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestListSurfacesResumeFields:
    @pytest.mark.asyncio
    async def test_list_and_details_expose_fields(self, client, engine):
        """List + details endpoints must include interview_type / target_field / resume_id."""
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as s:
            user = User(id=uuid.uuid4(), email="student@example.com", name="Student")
            s.add(user); await s.flush()

            resume = Resume(
                id=uuid.uuid4(), user_id=user.id, filename="me.pdf",
                content_type="application/pdf", size_bytes=4, file_data=b"%PDF",
            )
            s.add(resume); await s.flush()

            interview = Interview(
                id="interview_aabbccddee99",
                user_id=user.id,
                job_title="Entry-level — Web Development",
                candidate_name="Student",
                candidate_email="student@example.com",
                domain_knowledge={"domain_areas": ["Web Development"]},
                questions=[{"question": "What is HTTP?", "competency": "Web"}],
                candidate_info={"name": "Student", "email": "student@example.com", "position": "Fresher"},
                status="created",
                interview_type="resume",
                target_field="Web Development",
                resume_id=resume.id,
            )
            s.add(interview); await s.commit()

        list_resp = await client.get("/api/v1/interviews")
        assert list_resp.status_code == 200
        rows = list_resp.json()["interviews"]
        assert len(rows) == 1
        assert rows[0]["interview_type"] == "resume"
        assert rows[0]["target_field"] == "Web Development"
        assert rows[0]["resume_id"] == str(resume.id)

        details = await client.get("/api/v1/interviews/interview_aabbccddee99")
        assert details.status_code == 200
        body = details.json()
        assert body["interview_type"] == "resume"
        assert body["target_field"] == "Web Development"
        assert body["resume_id"] == str(resume.id)
