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
from datetime import datetime
from typing import Optional, Dict, List

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings, validate_api_keys, get_missing_required_keys, get_missing_realtime_keys
from core.domain_extraction import extract_domain_knowledge
from core.question_generator import generate_technical_questions, validate_questions
from integrations.hedra import create_hedra_image_avatar, create_interviewer_persona
from core.session import TechnicalInterviewSession
from core.answer_scoring import score_all_answers, calculate_overall_metrics
from core.report_generator import generate_interview_report, format_report_for_display
from agent.manager import RealtimeInterviewManager, register_interview_session

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
# In-Memory Cache + File Persistence
# WARNING: Single-worker only. Deploy with --workers 1 or replace with database.
# ==================================================

INTERVIEW_STORE_DIR = os.path.join(settings.UPLOAD_DIR, "..", "interview_store")
os.makedirs(INTERVIEW_STORE_DIR, exist_ok=True)

interviews: Dict[str, Dict] = {}


def _persist_interview(interview_id: str, data: Dict):
    """Save interview API state to disk so it survives container restarts."""
    payload = {
        "domain_knowledge": data["domain_knowledge"],
        "questions": data["questions"],
        "candidate_info": data["candidate_info"],
        "avatar_id": data.get("avatar_id"),
        "user_email": data.get("user_email"),
        "created_at": data.get("created_at"),
        "status": data.get("status", "created"),
        "job_title": data.get("candidate_info", {}).get("position", ""),
    }
    path = os.path.join(INTERVIEW_STORE_DIR, f"{interview_id}_api.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _update_interview_status(interview_id: str, status: str):
    """Update the status field in the persisted interview file."""
    path = os.path.join(INTERVIEW_STORE_DIR, f"{interview_id}_api.json")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["status"] = status
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to update status for {interview_id}: {e}")


def _load_interview(interview_id: str) -> Optional[Dict]:
    """Load interview from disk into the in-memory cache."""
    path = os.path.join(INTERVIEW_STORE_DIR, f"{interview_id}_api.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load interview {interview_id}: {e}")
        return None

    session = TechnicalInterviewSession(
        avatar_id=payload.get("avatar_id"),
        avatar_image_path=None,
        job_description={
            "title": payload["candidate_info"].get("position", ""),
            "description": "",
            "domain_knowledge": payload["domain_knowledge"],
        },
        questions=payload["questions"],
        candidate_info=payload["candidate_info"],
    )
    interviews[interview_id] = {
        "session": session,
        "domain_knowledge": payload["domain_knowledge"],
        "questions": payload["questions"],
        "candidate_info": payload["candidate_info"],
        "avatar_id": payload.get("avatar_id"),
        "user_email": payload.get("user_email"),
        "created_at": payload.get("created_at"),
    }
    return interviews[interview_id]


def get_interview(interview_id: str) -> Optional[Dict]:
    """Get interview from cache, falling back to disk."""
    if interview_id in interviews:
        return interviews[interview_id]
    return _load_interview(interview_id)


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
async def list_interviews(user: dict = Depends(get_current_user)):
    """List all interviews for the authenticated user, newest first."""
    user_email = user["email"]
    result = []

    for filename in os.listdir(INTERVIEW_STORE_DIR):
        if not filename.endswith("_api.json"):
            continue
        filepath = os.path.join(INTERVIEW_STORE_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if data.get("user_email") != user_email:
            continue

        interview_id = filename.replace("_api.json", "")
        report_path = os.path.join(UPLOAD_DIR, f"{interview_id}_report.json")

        result.append({
            "interview_id": interview_id,
            "job_title": data.get("job_title", data.get("candidate_info", {}).get("position", "")),
            "candidate_name": data.get("candidate_info", {}).get("name", ""),
            "created_at": data.get("created_at", ""),
            "status": data.get("status", "created"),
            "has_report": os.path.exists(report_path),
        })

    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"interviews": result}


@app.post("/api/v1/interviews/create")
@limiter.limit("10/minute")
async def create_interview(request: Request, interview_request: InterviewRequest, user: dict = Depends(get_current_user)):
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
        # Avatar is independent — no need to wait for it sequentially.
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
        
        # Step 4: Create interview session
        job_desc_dict = {
            "title": interview_request.job_title,
            "description": interview_request.job_description,
            "domain_knowledge": domain_knowledge
        }
        
        candidate_info = {
            "name": interview_request.candidate_name,
            "email": interview_request.candidate_email,
            "position": interview_request.job_title
        }
        
        session = TechnicalInterviewSession(
            avatar_id=avatar_id,
            avatar_image_path=interview_request.avatar_image_path,
            job_description=job_desc_dict,
            questions=questions,
            candidate_info=candidate_info
        )
        
        # Store interview data
        interviews[interview_id] = {
            "session": session,
            "domain_knowledge": domain_knowledge,
            "questions": questions,
            "candidate_info": candidate_info,
            "avatar_id": avatar_id,
            "user_email": user["email"],
            "created_at": datetime.now().isoformat(),
            "status": "created"
        }
        
        # Persist to disk (survives container restarts)
        _persist_interview(interview_id, interviews[interview_id])

        # Register session for real-time agent access
        register_interview_session(interview_id, session)
        
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


@app.post("/api/v1/interviews/{interview_id}/start")
async def start_interview(interview_id: str, user: dict = Depends(get_current_user)):
    validate_interview_id(interview_id)
    """Start an interview session"""
    interview = get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    session = interview["session"]
    
    session.start_interview()
    
    return {
        "interview_id": interview_id,
        "status": "started",
        "opening_message": session.get_opening_message(),
        "first_question": interview["questions"][0] if interview["questions"] else None
    }


@app.get("/api/v1/interviews/{interview_id}/state")
async def get_interview_state(interview_id: str, user: dict = Depends(get_current_user)):
    validate_interview_id(interview_id)
    """Get current interview state"""
    interview = get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    session = interview["session"]
    
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
async def submit_answer(interview_id: str, answer: AnswerSubmission, user: dict = Depends(get_current_user)):
    validate_interview_id(interview_id)
    """Submit candidate answer for current question"""
    interview = get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    session = interview["session"]
    
    if not session.interview_active:
        raise HTTPException(status_code=400, detail="Interview is not active")
    
    if session.is_complete():
        raise HTTPException(status_code=400, detail="Interview is already complete")
    
    # Submit answer
    session.submit_answer(
        transcript=answer.transcript,
        follow_up_transcript=answer.follow_up_transcript
    )
    
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


@app.post("/api/v1/interviews/{interview_id}/complete")
async def complete_interview(interview_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    validate_interview_id(interview_id)
    """Complete interview and generate report"""
    interview = get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    session = interview["session"]
    
    if not session.interview_active:
        raise HTTPException(status_code=400, detail="Interview is not active")
    
    # End interview
    session.end_interview()
    _update_interview_status(interview_id, "completed")
    
    # Score all answers
    try:
        scores = score_all_answers(
            answers=session.answers,
            questions=interview["questions"]
        )
        interview["scores"] = scores
    except Exception as e:
        logger.error(f"Answer scoring failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Answer scoring failed. Check server logs.")
    
    # Generate report
    try:
        report = generate_interview_report(
            candidate_info=interview["candidate_info"],
            answers=session.answers,
            scores=scores,
            questions=interview["questions"],
            domain_knowledge=interview["domain_knowledge"],
            interview_duration_minutes=session.get_duration_minutes()
        )
        interview["report"] = report
        
        # Save report to file
        report_path = os.path.join(UPLOAD_DIR, f"{interview_id}_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        # Also save formatted text version
        text_report = format_report_for_display(report)
        text_report_path = os.path.join(UPLOAD_DIR, f"{interview_id}_report.txt")
        with open(text_report_path, "w", encoding="utf-8") as f:
            f.write(text_report)
        
    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Report generation failed. Check server logs.")
    
    return {
        "interview_id": interview_id,
        "status": "completed",
        "report": report,
        "report_path": report_path
    }


@app.get("/api/v1/interviews/{interview_id}/report")
async def get_interview_report(interview_id: str, user: dict = Depends(get_current_user)):
    validate_interview_id(interview_id)
    """Get interview report"""
    interview = get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    if "report" not in interview:
        raise HTTPException(status_code=404, detail="Report not yet generated")
    
    return interview["report"]


@app.get("/api/v1/interviews/{interview_id}")
async def get_interview_details(interview_id: str, user: dict = Depends(get_current_user)):
    validate_interview_id(interview_id)
    """Get full interview details"""
    interview = get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    session = interview["session"]
    
    return {
        "interview_id": interview_id,
        "candidate_info": interview["candidate_info"],
        "job_title": interview["candidate_info"]["position"],
        "domain_knowledge": interview["domain_knowledge"],
        "total_questions": len(interview["questions"]),
        "state": session.get_interview_state(),
        "has_report": "report" in interview,
        "created_at": interview["created_at"]
    }


@app.post("/api/v1/interviews/{interview_id}/start-realtime")
@limiter.limit("10/minute")
async def start_realtime_interview(request: Request, interview_id: str, user: dict = Depends(get_current_user)):
    validate_interview_id(interview_id)
    """
    Start a real-time interview session with LiveKit + Hedra
    
    Creates a LiveKit room and returns connection details for the candidate
    The interview agent will automatically join and conduct the interview
    """
    interview = get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    session = interview["session"]
    candidate_info = interview["candidate_info"]
    
    try:
        # Fail fast if real-time prerequisites are missing, otherwise the worker can join but never speak
        missing_realtime = get_missing_realtime_keys()
        if missing_realtime:
            raise HTTPException(
                status_code=400,
                detail=f"Real-time interview is not configured. Missing: {', '.join(missing_realtime)}. See /api/config/status for details."
            )

        # Create LiveKit room manager
        manager = RealtimeInterviewManager()
        
        # Create interview room
        room_info = await manager.create_interview_room(
            interview_id=interview_id,
            interview_session=session,
            candidate_name=candidate_info.get("name", "Candidate")
        )
        
        # Start interview session
        session.start_interview()
        _update_interview_status(interview_id, "in_progress")

        return {
            "interview_id": interview_id,
            "status": "realtime_started",
            "room_name": room_info["room_name"],
            "candidate_token": room_info["candidate_token"],
            "candidate_join_url": room_info["candidate_join_url"],
            "livekit_url": room_info["room_url"],
            "instructions": "Use the candidate_join_url to connect to the interview. The interviewer agent will join automatically."
        }
        
    except Exception as e:
        logger.error(f"Real-time interview start failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start real-time interview. Check server logs.")


@app.get("/api/v1/interviews/{interview_id}/realtime/participants")
async def realtime_participants(interview_id: str, user: dict = Depends(get_current_user)):
    validate_interview_id(interview_id)
    """
    Debug endpoint: list current LiveKit participants for the interview room.
    Useful to confirm whether the agent/hedra participant actually joined.
    """
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")

    missing_realtime = get_missing_realtime_keys()
    if missing_realtime:
        raise HTTPException(
            status_code=400,
            detail=f"Real-time interview is not configured. Missing: {', '.join(missing_realtime)}."
        )

    manager = RealtimeInterviewManager()
    try:
        participants = await manager.livekit_api.room.list_participants(room=interview_id)
        # livekit api returns protobuf-ish objects; normalize into JSON-friendly dicts
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

