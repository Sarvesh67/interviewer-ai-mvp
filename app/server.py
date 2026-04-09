"""
Main FastAPI Application for Technical Interviewer
Integrates all components: domain extraction, question generation,
Hedra avatar, interview session, scoring, and reporting
"""
import asyncio
import os
import re
import uuid
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings, validate_api_keys, get_missing_required_keys, get_missing_realtime_keys
from core.domain_extraction import extract_domain_knowledge
from core.question_generator import generate_technical_questions, validate_questions
from integrations.hedra import create_hedra_image_avatar, create_interviewer_persona
from core.session import TechnicalInterviewSession
from core.answer_scoring import score_all_answers, score_all_answers_batch, calculate_overall_metrics
from core.report_generator import generate_interview_report, format_report_for_display
from agent.manager import RealtimeInterviewManager, register_interview_session
from db.session import get_db, AsyncSessionLocal
from db.models import User, Interview, Report

logger = logging.getLogger("main")

# ==================================================
# Validation & Security Helpers
# ==================================================

INTERVIEW_ID_PATTERN = re.compile(r"^interview_[a-f0-9]{12}$")


def validate_interview_id(interview_id: str):
    """Validate interview_id format to prevent path traversal"""
    if not INTERVIEW_ID_PATTERN.match(interview_id):
        raise HTTPException(status_code=400, detail="Invalid interview ID format")


# Google OAuth token verification
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_OAUTH_PLAYGROUND_CLIENT_ID = "407408718192.apps.googleusercontent.com"
ALLOWED_AUDIENCES = {aud for aud in [GOOGLE_CLIENT_ID, GOOGLE_OAUTH_PLAYGROUND_CLIENT_ID] if aud}


async def get_current_user(authorization: str = Header(...)):
    """Verify Google OAuth ID token and extract user info"""
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

        token = authorization.replace("Bearer ", "")
        # Skip audience check during verification, then validate manually
        # This allows tokens from both the app and Google OAuth Playground
        idinfo = id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=None
        )
        token_audience = idinfo.get("aud")
        if token_audience not in ALLOWED_AUDIENCES:
            raise ValueError(
                f"Token audience '{token_audience}' is not allowed. "
                f"Expected one of: {ALLOWED_AUDIENCES}"
            )
        return {"email": idinfo["email"], "name": idinfo.get("name", "")}
    except ValueError as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail=f"Token verification failed: {e}")
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail=f"Authentication error: {e}")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


# ==================================================
# App Setup
# ==================================================

app = FastAPI(
    title="AI Technical Interviewer with Hedra",
    description="Technical interviewer using Hedra avatars, domain expertise, and AI scoring",
    version="1.0.0"
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

UPLOAD_DIR = settings.UPLOAD_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Interview store dir is still needed for agent-to-API file communication
INTERVIEW_STORE_DIR = os.path.join(settings.UPLOAD_DIR, "..", "interview_store")
os.makedirs(INTERVIEW_STORE_DIR, exist_ok=True)

# ==================================================
# Data Models
# ==================================================

class InterviewRequest(BaseModel):
    job_description: str = Field(..., description="Full job description text", max_length=50000)
    job_title: str = Field(..., description="Job title", max_length=200)
    candidate_name: str = Field(..., description="Candidate name", max_length=200)
    candidate_email: str = Field(..., description="Candidate email", max_length=320)
    difficulty_level: Optional[str] = Field("intermediate", description="junior, intermediate, or senior")
    avatar_image_path: Optional[str] = Field(None, description="Optional path to avatar image")


class AnswerSubmission(BaseModel):
    interview_id: str
    question_idx: int
    transcript: str
    follow_up_transcript: Optional[str] = None


class InterviewStateResponse(BaseModel):
    interview_id: str
    active: bool
    current_question_idx: int
    total_questions: int
    questions_answered: int
    is_complete: bool
    current_question: Optional[Dict] = None


# ==================================================
# Database Helpers
# ==================================================


async def get_or_create_user(db: AsyncSession, email: str, name: str) -> User:
    """Get existing user by email or create a new one. Updates name on each login."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email, name=name)
        db.add(user)
        await db.flush()
    else:
        user.name = name
        user.updated_at = datetime.now(timezone.utc)
    return user


def _session_from_interview(row: Interview) -> TechnicalInterviewSession:
    """Reconstruct a runtime TechnicalInterviewSession from a DB row."""
    session = TechnicalInterviewSession(
        avatar_id=row.avatar_id,
        avatar_image_path=None,
        job_description={
            "title": row.job_title,
            "description": "",
            "domain_knowledge": row.domain_knowledge,
        },
        questions=row.questions,
        candidate_info=row.candidate_info,
    )
    if row.answers:
        session.answers = row.answers
        session.current_question_idx = len(row.answers)
    return session


async def _get_interview_or_404(db: AsyncSession, interview_id: str) -> Interview:
    """Load an interview from the database or raise 404."""
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Interview not found")
    return row


# ==================================================
# Health & Configuration Endpoints
# ==================================================

@app.get("/api/health")
def health():
    """Health check endpoint"""
    return {
        "status": "AI Technical Interviewer API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/config/client-id")
def get_client_id():
    """Return Google OAuth Client ID for frontend sign-in initialization"""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured")
    return {"client_id": GOOGLE_CLIENT_ID}


@app.get("/api/config/status")
def config_status():
    """Check API key configuration status"""
    status = validate_api_keys()
    missing = get_missing_required_keys()
    missing_realtime = get_missing_realtime_keys()

    return {
        "api_keys_status": status,
        "missing_required_keys": missing,
        "all_configured": len(missing) == 0,
        "realtime": {
            "ready": len(missing_realtime) == 0,
            "missing_keys": missing_realtime,
            "note": "Real-time mode requires LiveKit + Gemini + Deepgram (STT + TTS) with the current agent implementation."
        }
    }


# ==================================================
# Interview List & Creation Endpoints
# ==================================================

@app.get("/api/v1/interviews")
async def list_interviews(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all interviews for the authenticated user, newest first."""
    user_obj = await get_or_create_user(db, user["email"], user["name"])

    result = await db.execute(
        select(Interview)
        .where(Interview.user_id == user_obj.id)
        .order_by(Interview.created_at.desc())
    )
    rows = result.scalars().all()

    interviews_list = []
    for row in rows:
        interviews_list.append({
            "interview_id": row.id,
            "job_title": row.job_title,
            "candidate_name": row.candidate_name,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "status": row.status,
            "has_report": row.report is not None,
        })

    await db.commit()
    return {"interviews": interviews_list}


@app.post("/api/v1/interviews/create")
@limiter.limit("10/minute")
async def create_interview(
    request: Request,
    interview_request: InterviewRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new technical interview session

    Steps:
    1. Extract domain knowledge from job description
    2. Generate technical questions
    3. Create Hedra avatar
    4. Initialize interview session
    """
    # Validate API keys
    missing_keys = get_missing_required_keys()
    if missing_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required API keys: {', '.join(missing_keys)}"
        )

    try:
        interview_id = f"interview_{uuid.uuid4().hex[:12]}"

        # Run avatar creation concurrently with domain extraction + question generation.
        async def create_avatar():
            try:
                return await asyncio.to_thread(
                    create_hedra_image_avatar,
                    avatar_image_path=interview_request.avatar_image_path
                )
            except Exception as e:
                logger.warning(f"Avatar creation failed, continuing without avatar: {e}")
                return None

        async def extract_and_generate():
            domain = await asyncio.to_thread(
                extract_domain_knowledge, interview_request.job_description
            )
            qs = await asyncio.to_thread(
                generate_technical_questions,
                domain_knowledge=domain,
                difficulty_level=interview_request.difficulty_level
            )
            validate_questions(qs)
            return domain, qs

        (domain_knowledge, questions), avatar_id = await asyncio.gather(
            extract_and_generate(),
            create_avatar()
        )

        candidate_info = {
            "name": interview_request.candidate_name,
            "email": interview_request.candidate_email,
            "position": interview_request.job_title
        }

        # Upsert user
        user_obj = await get_or_create_user(db, user["email"], user["name"])

        # Create interview row
        interview_row = Interview(
            id=interview_id,
            user_id=user_obj.id,
            job_title=interview_request.job_title,
            candidate_name=interview_request.candidate_name,
            candidate_email=interview_request.candidate_email,
            domain_knowledge=domain_knowledge,
            questions=questions,
            candidate_info=candidate_info,
            avatar_id=avatar_id,
            status="created",
        )
        db.add(interview_row)
        await db.commit()

        # Build a runtime session for the agent and register it
        session = TechnicalInterviewSession(
            avatar_id=avatar_id,
            avatar_image_path=interview_request.avatar_image_path,
            job_description={
                "title": interview_request.job_title,
                "description": interview_request.job_description,
                "domain_knowledge": domain_knowledge,
            },
            questions=questions,
            candidate_info=candidate_info,
        )
        register_interview_session(interview_id, session)

        # Persist interview metadata to disk for agent cross-container access
        _persist_interview_for_agent(interview_id, interview_row)

        return {
            "interview_id": interview_id,
            "avatar_id": avatar_id,
            "total_questions": len(questions),
            "difficulty_level": interview_request.difficulty_level,
            "domain_areas": domain_knowledge.get("domain_areas", []),
            "opening_message": session.get_opening_message(),
            "first_question": questions[0] if questions else None
        }

    except Exception as e:
        logger.error(f"Interview creation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Interview creation failed. Check server logs.")


def _persist_interview_for_agent(interview_id: str, row: Interview):
    """Write interview metadata to disk so the agent container can read it."""
    payload = {
        "domain_knowledge": row.domain_knowledge,
        "questions": row.questions,
        "candidate_info": row.candidate_info,
        "avatar_id": row.avatar_id,
        "status": row.status,
        "job_title": row.job_title,
    }
    path = os.path.join(INTERVIEW_STORE_DIR, f"{interview_id}_api.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


@app.post("/api/v1/interviews/{interview_id}/start")
async def start_interview(interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    validate_interview_id(interview_id)
    """Start an interview session"""
    row = await _get_interview_or_404(db, interview_id)

    row.status = "in_progress"
    await db.commit()

    session = _session_from_interview(row)
    session.start_interview()

    return {
        "interview_id": interview_id,
        "status": "started",
        "opening_message": session.get_opening_message(),
        "first_question": row.questions[0] if row.questions else None
    }


@app.get("/api/v1/interviews/{interview_id}/state")
async def get_interview_state(interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    validate_interview_id(interview_id)
    """Get current interview state"""
    row = await _get_interview_or_404(db, interview_id)
    session = _session_from_interview(row)

    state = session.get_interview_state()
    current_question = session.get_current_question()

    return InterviewStateResponse(
        interview_id=interview_id,
        active=state["active"],
        current_question_idx=state["current_question_idx"],
        total_questions=state["total_questions"],
        questions_answered=state["questions_answered"],
        is_complete=state["is_complete"],
        current_question=current_question
    )


@app.post("/api/v1/interviews/{interview_id}/answer")
async def submit_answer(interview_id: str, answer: AnswerSubmission, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    validate_interview_id(interview_id)
    """Submit candidate answer for current question"""
    row = await _get_interview_or_404(db, interview_id)
    session = _session_from_interview(row)

    if not session.interview_active and row.status != "in_progress":
        raise HTTPException(status_code=400, detail="Interview is not active")

    # Force the session active for non-realtime mode
    session.interview_active = True

    if session.is_complete():
        raise HTTPException(status_code=400, detail="Interview is already complete")

    # Submit answer
    session.submit_answer(
        transcript=answer.transcript,
        follow_up_transcript=answer.follow_up_transcript
    )

    # Persist answers back to DB
    row.answers = session.answers
    await db.commit()

    # Check if follow-up is needed
    needs_followup = session.needs_follow_up(answer.transcript)
    follow_up_question = None
    if needs_followup and not session.is_complete():
        follow_up_question = session.get_follow_up_question(answer.transcript)

    # Get next question or closing
    if session.is_complete():
        next_message = session.get_closing_message()
        next_question = None
    else:
        next_question = session.get_current_question()
        next_message = None

    return {
        "interview_id": interview_id,
        "question_answered": answer.question_idx,
        "needs_followup": needs_followup,
        "follow_up_question": follow_up_question,
        "next_question": next_question,
        "is_complete": session.is_complete(),
        "closing_message": next_message if session.is_complete() else None
    }


async def _generate_report_background(interview_id: str):
    """Background task: score answers and generate report, then save to DB."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Interview).where(Interview.id == interview_id))
            row = result.scalar_one_or_none()
            if row is None:
                logger.error(f"Background report: interview {interview_id} not found")
                return

            session = _session_from_interview(row)

            # Score all answers (blocking Gemini calls — run in thread)
            scores = await asyncio.to_thread(
                score_all_answers_batch,
                answers=session.answers,
                questions=row.questions,
            )

            # Generate report (CPU-bound, fast)
            report = generate_interview_report(
                candidate_info=row.candidate_info,
                answers=session.answers,
                scores=scores,
                questions=row.questions,
                domain_knowledge=row.domain_knowledge,
                interview_duration_minutes=None,
            )

            text_report = format_report_for_display(report)

            # Save report to DB
            report_row = Report(
                interview_id=interview_id,
                report_data=report,
                report_text=text_report,
                overall_score=report.get("overall_score"),
                recommendation=report.get("recommendation"),
            )
            db.add(report_row)
            row.status = "completed"
            await db.commit()
            logger.info(f"Report generated for {interview_id}")

    except Exception as e:
        logger.error(f"Background report generation failed for {interview_id}: {e}", exc_info=True)
        # Still mark as completed so the UI doesn't hang
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Interview).where(Interview.id == interview_id))
                row = result.scalar_one_or_none()
                if row:
                    row.status = "completed"
                    await db.commit()
        except Exception:
            pass


@app.post("/api/v1/interviews/{interview_id}/complete")
async def complete_interview(interview_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    validate_interview_id(interview_id)
    """Complete interview and kick off report generation in background"""
    row = await _get_interview_or_404(db, interview_id)

    # Load agent-persisted answers (agent runs in separate container — answers are on disk)
    answers_file = Path(INTERVIEW_STORE_DIR) / f"{interview_id}_answers.json"
    if answers_file.exists():
        try:
            agent_data = json.loads(answers_file.read_text())
            row.answers = agent_data.get("answers", [])
            logger.info(f"Loaded {len(row.answers)} answers from agent for {interview_id}")
        except Exception as e:
            logger.warning(f"Failed to load agent answers for {interview_id}: {e}")

    row.status = "generating_report"
    await db.commit()

    # Kick off scoring + report generation in background
    background_tasks.add_task(_generate_report_background, interview_id)

    return {
        "interview_id": interview_id,
        "status": "generating_report",
    }


@app.get("/api/v1/interviews/{interview_id}/report")
async def get_interview_report(interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    validate_interview_id(interview_id)
    """Get interview report"""
    result = await db.execute(select(Report).where(Report.interview_id == interview_id))
    report_row = result.scalar_one_or_none()
    if report_row is None:
        raise HTTPException(status_code=404, detail="Report not yet generated")

    return report_row.report_data


@app.get("/api/v1/interviews/{interview_id}")
async def get_interview_details(interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    validate_interview_id(interview_id)
    """Get full interview details"""
    row = await _get_interview_or_404(db, interview_id)
    session = _session_from_interview(row)

    return {
        "interview_id": interview_id,
        "candidate_info": row.candidate_info,
        "job_title": row.job_title,
        "domain_knowledge": row.domain_knowledge,
        "total_questions": len(row.questions),
        "state": session.get_interview_state(),
        "has_report": row.report is not None,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


@app.post("/api/v1/interviews/{interview_id}/start-realtime")
@limiter.limit("10/minute")
async def start_realtime_interview(request: Request, interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    validate_interview_id(interview_id)
    """
    Start a real-time interview session with LiveKit + Hedra

    Creates a LiveKit room and returns connection details for the candidate
    The interview agent will automatically join and conduct the interview
    """
    row = await _get_interview_or_404(db, interview_id)
    session = _session_from_interview(row)

    try:
        # Fail fast if real-time prerequisites are missing
        missing_realtime = get_missing_realtime_keys()
        if missing_realtime:
            raise HTTPException(
                status_code=400,
                detail=f"Real-time interview is not configured. Missing: {', '.join(missing_realtime)}. See /api/config/status for details."
            )

        manager = RealtimeInterviewManager()

        room_info = await manager.create_interview_room(
            interview_id=interview_id,
            interview_session=session,
            candidate_name=row.candidate_info.get("name", "Candidate")
        )

        session.start_interview()
        row.status = "in_progress"
        await db.commit()

        return {
            "interview_id": interview_id,
            "status": "realtime_started",
            "room_name": room_info["room_name"],
            "candidate_token": room_info["candidate_token"],
            "candidate_join_url": room_info["candidate_join_url"],
            "livekit_url": room_info["room_url"],
            "instructions": "Use the candidate_join_url to connect to the interview. The interviewer agent will join automatically."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Real-time interview start failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start real-time interview. Check server logs.")


@app.get("/api/v1/interviews/{interview_id}/realtime/participants")
async def realtime_participants(interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    validate_interview_id(interview_id)
    """
    Debug endpoint: list current LiveKit participants for the interview room.
    Useful to confirm whether the agent/hedra participant actually joined.
    """
    await _get_interview_or_404(db, interview_id)

    missing_realtime = get_missing_realtime_keys()
    if missing_realtime:
        raise HTTPException(
            status_code=400,
            detail=f"Real-time interview is not configured. Missing: {', '.join(missing_realtime)}."
        )

    manager = RealtimeInterviewManager()
    try:
        participants = await manager.livekit_api.room.list_participants(room=interview_id)
        normalized = []
        for p in participants.participants:
            normalized.append(
                {
                    "identity": getattr(p, "identity", None),
                    "name": getattr(p, "name", None),
                    "state": getattr(p, "state", None),
                    "joined_at": getattr(p, "joined_at", None),
                    "metadata": getattr(p, "metadata", None),
                }
            )
        return {"room": interview_id, "participants": normalized}
    except Exception as e:
        logger.error(f"Participant listing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list participants. Check server logs.")


# ==================================================
# Static File Serving (Frontend)
# Must be AFTER all /api/... routes — StaticFiles is a catch-all
# ==================================================
if os.path.isdir("frontend"):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
