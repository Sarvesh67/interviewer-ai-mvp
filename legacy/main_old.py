import os
import uuid
import torch
torch.set_num_threads(1)

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from PyPDF2 import PdfReader
import docx
import whisper

# ==================================================
# App Setup
# ==================================================

app = FastAPI(title="AI Interviewer – Stable Core")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ==================================================
# Whisper (Lazy load – Windows safe)
# ==================================================

_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = whisper.load_model("base")
    return _whisper_model

# ==================================================
# Resume Parsing
# ==================================================

def parse_pdf(path):
    reader = PdfReader(path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

def parse_docx(path):
    doc = docx.Document(path)
    return "\n".join(p.text for p in doc.paragraphs)

# ==================================================
# ATS Scoring
# ==================================================

SKILLS = [
    "python", "sql", "product", "analytics", "ai",
    "machine learning", "data", "fastapi", "react"
]

def compute_ats(text):
    found = [s for s in SKILLS if s in text.lower()]
    score = min(100, len(found) * 10)
    return score, found

# ==================================================
# Answer Analysis & Follow-ups
# ==================================================

def analyze_answer(answer):
    words = answer.lower().split()

    if len(words) < 15:
        return "too_short"

    if any(k in answer.lower() for k in ["sql", "python", "api", "database", "system"]):
        return "technical"

    if any(k in answer.lower() for k in ["led", "managed", "impact", "stakeholder"]):
        return "leadership"

    if len(words) < 40:
        return "generic"

    return "specific"

FOLLOW_UPS = {
    "too_short": "Can you expand on that with a concrete example?",
    "generic": "Can you walk me through a specific situation?",
    "technical": "Can you explain how you implemented this technically?",
    "leadership": "What was your personal impact in that situation?"
}

MAX_FOLLOWUPS = 2

# ==================================================
# Final Feedback
# ==================================================

def generate_feedback(session):
    total_words = sum(len(a.split()) for a in session["answers"])
    avg_words = total_words // max(1, len(session["answers"]))

    clarity = min(10, avg_words // 8)
    depth = min(10, avg_words // 12)

    recommendation = "Strong Hire" if clarity >= 6 and depth >= 6 else "Consider"

    return {
        "communication_score": clarity,
        "depth_score": depth,
        "ats_score": session["ats_score"],
        "answers_count": len(session["answers"]),
        "recommendation": recommendation
    }

# ==================================================
# Session (single-user prototype)
# ==================================================

session = {
    "resume_text": "",
    "ats_score": 0,
    "skills": [],
    "questions": [],
    "current_index": 0,
    "followup_count": 0,
    "answers": []
}

BASE_QUESTIONS = [
    "Tell me about yourself.",
    "Tell me about a project related to {skill}.",
    "What was the most challenging problem you faced?",
    "How do you usually improve your skills?",
    "Where do you see yourself in the next 2–3 years?"
]

# ==================================================
# Routes
# ==================================================

@app.get("/")
def health():
    return {"status": "Backend running"}

@app.post("/start_interview")
async def start_interview(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as f:
        f.write(await file.read())

    if file.filename.endswith(".pdf"):
        resume_text = parse_pdf(file_path)
    elif file.filename.endswith(".docx"):
        resume_text = parse_docx(file_path)
    else:
        return {"error": "Unsupported file type"}

    ats, skills = compute_ats(resume_text)
    skill = skills[0] if skills else "your experience"

    questions = [q.format(skill=skill) for q in BASE_QUESTIONS]

    session.update({
        "resume_text": resume_text,
        "ats_score": ats,
        "skills": skills,
        "questions": questions,
        "current_index": 0,
        "followup_count": 0,
        "answers": []
    })

    return {
        "ats_score": ats,
        "skills": skills,
        "question": questions[0]
    }

@app.post("/answer_audio")
async def answer_audio(audio: UploadFile = File(...)):
    audio_id = str(uuid.uuid4())
    audio_path = os.path.join(UPLOAD_DIR, f"{audio_id}.wav")
    transcript_path = os.path.join(UPLOAD_DIR, f"{audio_id}.txt")

    with open(audio_path, "wb") as f:
        f.write(await audio.read())

    transcript = get_whisper_model().transcribe(audio_path)["text"].strip()

    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(transcript)

    session["answers"].append(transcript)

    analysis = analyze_answer(transcript)

    # Follow-up logic
    if analysis in FOLLOW_UPS and session["followup_count"] < MAX_FOLLOWUPS:
        session["followup_count"] += 1
        return {
            "transcript": transcript,
            "analysis": analysis,
            "next_question": FOLLOW_UPS[analysis]
        }

    # Move to next base question
    session["followup_count"] = 0
    session["current_index"] += 1

    # End interview
    if session["current_index"] >= len(session["questions"]):
        return {
            "transcript": transcript,
            "analysis": analysis,
            "done": True,
            "message": "Thank you for completing the interview.",
            "final_report": generate_feedback(session)
        }

    return {
        "transcript": transcript,
        "analysis": analysis,
        "next_question": session["questions"][session["current_index"]]
    }
