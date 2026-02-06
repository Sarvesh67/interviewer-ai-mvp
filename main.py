"""
Main FastAPI Application for Technical Interviewer
Integrates all components: domain extraction, question generation, 
Hedra avatar, interview session, scoring, and reporting
"""
import os
import uuid
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import settings, validate_api_keys, get_missing_required_keys, get_missing_realtime_keys
from domain_extraction import extract_domain_knowledge
from question_generator import generate_technical_questions, validate_questions
from hedra_avatar import create_hedra_image_avatar, create_interviewer_persona
from interview_session import TechnicalInterviewSession
from answer_scoring import score_all_answers, calculate_overall_metrics
from report_generator import generate_interview_report, format_report_for_display
from realtime_interview_manager import RealtimeInterviewManager, register_interview_session

logger = logging.getLogger("main")

# ==================================================
# App Setup
# ==================================================

app = FastAPI(
    title="AI Technical Interviewer with Hedra",
    description="Technical interviewer using Hedra avatars, domain expertise, and AI scoring",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = settings.UPLOAD_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ==================================================
# Data Models
# ==================================================

class InterviewRequest(BaseModel):
    job_description: str = Field(..., description="Full job description text")
    job_title: str = Field(..., description="Job title")
    candidate_name: str = Field(..., description="Candidate name")
    candidate_email: str = Field(..., description="Candidate email")
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
# In-Memory Storage (Replace with DB in production)
# ==================================================

interviews: Dict[str, Dict] = {}


# ==================================================
# Health & Configuration Endpoints
# ==================================================

@app.get("/")
def health():
    """Health check endpoint"""
    return {
        "status": "AI Technical Interviewer API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


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
            "note": "Real-time mode requires LiveKit + Gemini + Deepgram (STT) + ElevenLabs (TTS) with the current agent implementation."
        }
    }


# ==================================================
# Interview Creation Endpoints
# ==================================================

@app.post("/api/v1/interviews/create")
async def create_interview(request: InterviewRequest):
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
        
        # Step 1: Extract domain knowledge
        domain_knowledge = extract_domain_knowledge(request.job_description)
        
        # Step 2: Generate technical questions
        questions = generate_technical_questions(
            domain_knowledge=domain_knowledge,
            difficulty_level=request.difficulty_level
        )
        validate_questions(questions)
        
        try:
            avatar_id = create_hedra_image_avatar(
                avatar_image_path=request.avatar_image_path
            )
        except Exception as e:
            # If avatar creation fails, continue without it (for testing)
            raise ValueError(f"Avatar creation failed: {e}")
        
        # Step 4: Create interview session
        job_desc_dict = {
            "title": request.job_title,
            "description": request.job_description,
            "domain_knowledge": domain_knowledge
        }
        
        candidate_info = {
            "name": request.candidate_name,
            "email": request.candidate_email,
            "position": request.job_title
        }
        
        session = TechnicalInterviewSession(
            avatar_id=avatar_id,
            avatar_image_path=request.avatar_image_path,
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
            "created_at": datetime.now().isoformat()
        }
        
        # Register session for real-time agent access
        register_interview_session(interview_id, session)

        # Note: session persistence for the agent process is handled by register_interview_session()
        
        return {
            "interview_id": interview_id,
            "avatar_id": avatar_id,
            "total_questions": len(questions),
            "difficulty_level": request.difficulty_level,
            "domain_areas": domain_knowledge.get("domain_areas", []),
            "opening_message": session.get_opening_message(),
            "first_question": questions[0] if questions else None
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating interview: {str(e)}")


@app.post("/api/v1/interviews/{interview_id}/start")
async def start_interview(interview_id: str):
    """Start an interview session"""
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview = interviews[interview_id]
    session = interview["session"]
    
    session.start_interview()
    
    return {
        "interview_id": interview_id,
        "status": "started",
        "opening_message": session.get_opening_message(),
        "first_question": interview["questions"][0] if interview["questions"] else None
    }


@app.get("/api/v1/interviews/{interview_id}/state")
async def get_interview_state(interview_id: str):
    """Get current interview state"""
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview = interviews[interview_id]
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
async def submit_answer(interview_id: str, answer: AnswerSubmission):
    """Submit candidate answer for current question"""
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview = interviews[interview_id]
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
async def complete_interview(interview_id: str, background_tasks: BackgroundTasks):
    """Complete interview and generate report"""
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview = interviews[interview_id]
    session = interview["session"]
    
    if not session.interview_active:
        raise HTTPException(status_code=400, detail="Interview is not active")
    
    # End interview
    session.end_interview()
    
    # Score all answers
    try:
        scores = score_all_answers(
            answers=session.answers,
            questions=interview["questions"]
        )
        interview["scores"] = scores
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scoring answers: {str(e)}")
    
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
        raise HTTPException(status_code=500, detail=f"Error generating report: {str(e)}")
    
    return {
        "interview_id": interview_id,
        "status": "completed",
        "report": report,
        "report_path": report_path
    }


@app.get("/api/v1/interviews/{interview_id}/report")
async def get_interview_report(interview_id: str):
    """Get interview report"""
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview = interviews[interview_id]
    
    if "report" not in interview:
        raise HTTPException(status_code=404, detail="Report not yet generated")
    
    return interview["report"]


@app.get("/api/v1/interviews/{interview_id}")
async def get_interview_details(interview_id: str):
    """Get full interview details"""
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview = interviews[interview_id]
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
async def start_realtime_interview(interview_id: str):
    """
    Start a real-time interview session with LiveKit + Hedra
    
    Creates a LiveKit room and returns connection details for the candidate
    The interview agent will automatically join and conduct the interview
    """
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview = interviews[interview_id]
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
        raise HTTPException(status_code=500, detail=f"Error starting real-time interview: {str(e)}")


@app.get("/api/v1/interviews/{interview_id}/realtime/participants")
async def realtime_participants(interview_id: str):
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
        raise HTTPException(status_code=500, detail=f"Error listing participants: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

