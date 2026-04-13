"""
Tests for PDF report generation (core/pdf_report.py) and the PDF download endpoint.
"""
import sys
import uuid
import pytest
import pytest_asyncio
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from core.pdf_report import generate_pdf_report

# ──────────────────────────────────────────────
# Sample report data fixtures
# ──────────────────────────────────────────────

def _full_report_data():
    """A realistic, fully-populated report dict."""
    return {
        "candidate_name": "Alice Johnson",
        "candidate_email": "alice@example.com",
        "position": "Senior Backend Engineer",
        "interview_date": "2026-04-10T14:30:00.000000",
        "interview_duration_minutes": 32.5,
        "overall_score": 7.2,
        "recommendation": "hire",
        "recommendation_text": "Hire - Good candidate, recommended",
        "category_scores": {
            "technical_accuracy": 75.0,
            "communication_clarity": 80.0,
            "answer_depth": 65.0,
        },
        "top_strengths": [
            "Strong Python knowledge",
            "Good communication",
            "Solid database skills",
        ],
        "top_weaknesses": [
            "Limited distributed systems experience",
            "Could improve caching knowledge",
        ],
        "total_questions": 3,
        "questions_answered": 3,
        "average_score": 7.2,
        "detailed_qa": [
            {
                "question": "Explain asyncio event loop.",
                "competency": "Async Programming",
                "candidate_answer": "The event loop manages coroutines using cooperative multitasking.",
                "follow_up_answer": "I've used uvloop in production for better performance.",
                "score": 8.5,
                "reasoning": "Strong understanding with practical experience.",
                "strengths": ["Clear explanation"],
                "weaknesses": ["Could mention TaskGroups"],
            },
            {
                "question": "Design a rate limiter.",
                "competency": "System Design",
                "candidate_answer": "Token bucket with Redis for distributed rate limiting.",
                "follow_up_answer": None,
                "score": 7.0,
                "reasoning": "Good approach, mentioned multiple algorithms.",
                "strengths": ["Practical solution"],
                "weaknesses": ["No race condition discussion"],
            },
            {
                "question": "How do you test FastAPI apps?",
                "competency": "Testing",
                "candidate_answer": "Pytest with TestClient and async fixtures.",
                "follow_up_answer": None,
                "score": 3.5,
                "reasoning": "Surface-level answer lacking depth.",
                "strengths": ["Knows pytest"],
                "weaknesses": ["No fixture discussion", "No mocking strategy"],
            },
        ],
        "interviewer_notes": "Strong candidate overall.\nGood communication skills.",
        "domain_knowledge": {
            "job_title": "Senior Backend Engineer",
            "experience_level": "senior",
            "technologies": ["Python", "FastAPI"],
        },
        "report_generated_at": "2026-04-10T15:05:00.000000",
        "scoring_model": "gemini-2.5-pro",
    }


def _minimal_report_data():
    """Minimal report with empty/None optional fields."""
    return {
        "candidate_name": "Bob",
        "candidate_email": "bob@example.com",
        "position": "Junior Developer",
        "interview_date": "2026-04-10T10:00:00.000000",
        "interview_duration_minutes": None,
        "overall_score": 0.0,
        "recommendation": "no_hire",
        "recommendation_text": "No Hire - Significant gaps, not recommended",
        "category_scores": {
            "technical_accuracy": 0.0,
            "communication_clarity": 0.0,
            "answer_depth": 0.0,
        },
        "top_strengths": [],
        "top_weaknesses": [],
        "total_questions": 5,
        "questions_answered": 0,
        "average_score": 0.0,
        "detailed_qa": [],
        "interviewer_notes": "",
        "domain_knowledge": None,
        "report_generated_at": "2026-04-10T10:05:00.000000",
        "scoring_model": "gemini-2.5-pro",
    }


# ──────────────────────────────────────────────
# PDF Generation Unit Tests
# ──────────────────────────────────────────────

class TestGeneratePdfReport:
    def test_returns_valid_pdf_bytes(self):
        """PDF output starts with %PDF- header."""
        pdf = generate_pdf_report(_full_report_data())
        assert isinstance(pdf, bytes)
        assert len(pdf) > 0
        assert pdf[:5] == b"%PDF-"

    def test_minimal_report_no_crash(self):
        """Handles empty QA, None duration, None domain_knowledge."""
        pdf = generate_pdf_report(_minimal_report_data())
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 0

    def test_handles_missing_fields_gracefully(self):
        """Works with a nearly-empty dict — all fields use .get() defaults."""
        pdf = generate_pdf_report({})
        assert pdf[:5] == b"%PDF-"

    def test_html_special_chars_in_answers(self):
        """Candidate answers with <script> tags and & don't break PDF generation."""
        data = _full_report_data()
        data["detailed_qa"][0]["candidate_answer"] = (
            '<script>alert("xss")</script> & "quoted" <b>bold</b>'
        )
        data["candidate_name"] = 'O\'Brien & Sons <Corp>'
        pdf = generate_pdf_report(data)
        assert pdf[:5] == b"%PDF-"

    def test_all_recommendation_types(self):
        """Each recommendation type produces a valid PDF."""
        for rec in ["strong_hire", "hire", "review", "no_hire"]:
            data = _full_report_data()
            data["recommendation"] = rec
            pdf = generate_pdf_report(data)
            assert pdf[:5] == b"%PDF-", f"Failed for recommendation={rec}"

    def test_score_edge_values(self):
        """Scores at boundary values (0, 4, 7, 10) produce valid PDFs."""
        for score in [0.0, 3.9, 4.0, 6.9, 7.0, 10.0]:
            data = _full_report_data()
            data["overall_score"] = score
            data["detailed_qa"][0]["score"] = score
            pdf = generate_pdf_report(data)
            assert pdf[:5] == b"%PDF-", f"Failed for score={score}"

    def test_category_scores_none_values(self):
        """None values in category_scores default to 0."""
        data = _full_report_data()
        data["category_scores"] = {
            "technical_accuracy": None,
            "communication_clarity": None,
            "answer_depth": None,
        }
        pdf = generate_pdf_report(data)
        assert pdf[:5] == b"%PDF-"

    def test_malformed_dates_dont_crash(self):
        """Invalid ISO dates are displayed as-is without raising."""
        data = _full_report_data()
        data["interview_date"] = "not-a-date"
        data["report_generated_at"] = ""
        pdf = generate_pdf_report(data)
        assert pdf[:5] == b"%PDF-"

    def test_unicode_in_answers(self):
        """Unicode characters in answers are handled correctly."""
        data = _full_report_data()
        data["detailed_qa"][0]["candidate_answer"] = (
            "I used the strategy pattern \u2014 it worked well. \u00e9\u00e8\u00ea \u4f60\u597d"
        )
        pdf = generate_pdf_report(data)
        assert pdf[:5] == b"%PDF-"

    def test_very_long_answer_text(self):
        """Long answer text doesn't crash the PDF builder."""
        data = _full_report_data()
        data["detailed_qa"][0]["candidate_answer"] = "A" * 5000
        pdf = generate_pdf_report(data)
        assert pdf[:5] == b"%PDF-"


# ──────────────────────────────────────────────
# Stub heavy imports for app.server
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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from db.models import Base, User, Interview, Report


# ──────────────────────────────────────────────
# API Endpoint Tests
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
def test_client(db):
    """Create a FastAPI TestClient with DB dependency overridden."""
    from app.server import app, get_current_user
    from fastapi.testclient import TestClient

    async def override_db():
        yield db

    def override_user():
        return {"email": "test@example.com", "name": "Test User"}

    app.dependency_overrides[get_current_user] = override_user
    # Patch get_db to use our test session
    from db.session import get_db as real_get_db
    app.dependency_overrides[real_get_db] = override_db

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


class TestPdfEndpoint:
    @pytest.mark.asyncio
    async def test_pdf_endpoint_returns_pdf(self, db: AsyncSession, test_client):
        """GET /report/pdf returns valid PDF with correct headers."""
        user = User(id=uuid.uuid4(), email="test@example.com", name="Test User")
        db.add(user)
        await db.flush()

        interview = Interview(
            id="interview_aabbccddee01",
            user_id=user.id,
            job_title="Backend Engineer",
            candidate_name="Alice",
            candidate_email="alice@example.com",
            domain_knowledge={},
            questions=[],
            candidate_info={"name": "Alice", "email": "alice@example.com", "position": "Backend Engineer"},
            avatar_id=None,
            status="completed",
        )
        db.add(interview)
        await db.flush()

        report = Report(
            id=uuid.uuid4(),
            interview_id="interview_aabbccddee01",
            report_data=_full_report_data(),
            report_text="test",
            overall_score=7.2,
            recommendation="hire",
        )
        db.add(report)
        await db.commit()

        resp = test_client.get("/api/v1/interviews/interview_aabbccddee01/report/pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert "content-disposition" in resp.headers
        assert resp.headers["content-disposition"].startswith("attachment")
        assert resp.content[:5] == b"%PDF-"

    @pytest.mark.asyncio
    async def test_pdf_endpoint_404_no_report(self, db: AsyncSession, test_client):
        """GET /report/pdf returns 404 when no report exists."""
        user = User(id=uuid.uuid4(), email="test@example.com", name="Test User")
        db.add(user)
        await db.flush()

        interview = Interview(
            id="interview_ccddee112233",
            user_id=user.id,
            job_title="Backend Engineer",
            candidate_name="Bob",
            candidate_email="bob@example.com",
            domain_knowledge={},
            questions=[],
            candidate_info={"name": "Bob", "email": "bob@example.com", "position": "Backend Engineer"},
            avatar_id=None,
            status="completed",
        )
        db.add(interview)
        await db.commit()

        resp = test_client.get("/api/v1/interviews/interview_ccddee112233/report/pdf")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_json_endpoint_still_works(self, db: AsyncSession, test_client):
        """Existing GET /report JSON endpoint is unaffected."""
        user = User(id=uuid.uuid4(), email="test@example.com", name="Test User")
        db.add(user)
        await db.flush()

        interview = Interview(
            id="interview_ddeeff445566",
            user_id=user.id,
            job_title="Backend Engineer",
            candidate_name="Carol",
            candidate_email="carol@example.com",
            domain_knowledge={},
            questions=[],
            candidate_info={"name": "Carol", "email": "carol@example.com", "position": "Backend Engineer"},
            avatar_id=None,
            status="completed",
        )
        db.add(interview)
        await db.flush()

        report = Report(
            id=uuid.uuid4(),
            interview_id="interview_ddeeff445566",
            report_data=_full_report_data(),
            report_text="test",
            overall_score=7.2,
            recommendation="hire",
        )
        db.add(report)
        await db.commit()

        resp = test_client.get("/api/v1/interviews/interview_ddeeff445566/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["candidate_name"] == "Alice Johnson"
        assert "overall_score" in data

    @pytest.mark.asyncio
    async def test_pdf_filename_sanitized(self, db: AsyncSession, test_client):
        """Candidate names with special chars produce safe filenames."""
        user = User(id=uuid.uuid4(), email="test@example.com", name="Test User")
        db.add(user)
        await db.flush()

        interview = Interview(
            id="interview_aabb11223344",
            user_id=user.id,
            job_title="Engineer",
            candidate_name="Test",
            candidate_email="test@example.com",
            domain_knowledge={},
            questions=[],
            candidate_info={"name": "Test", "email": "test@example.com", "position": "Engineer"},
            avatar_id=None,
            status="completed",
        )
        db.add(interview)
        await db.flush()

        report_data = _minimal_report_data()
        report_data["candidate_name"] = "O'Brien & Sons <Corp>"
        report = Report(
            id=uuid.uuid4(),
            interview_id="interview_aabb11223344",
            report_data=report_data,
            report_text="test",
            overall_score=0.0,
            recommendation="no_hire",
        )
        db.add(report)
        await db.commit()

        resp = test_client.get("/api/v1/interviews/interview_aabb11223344/report/pdf")
        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"]
        # Filename should not contain quotes, angle brackets, ampersands
        assert "<" not in disposition
        assert ">" not in disposition
        assert "&" not in disposition
