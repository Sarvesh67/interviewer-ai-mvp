"""
Real-time Interview Session Management
Handles LiveKit + Hedra integration for conducting interviews
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from config import settings

logger = logging.getLogger("interview_session")


class TechnicalInterviewSession:
    """
    Manages a technical interview session with Hedra avatar.

    Answer data model uses a structured conversation thread per question:
    {
        "question_idx": 0,
        "question": "How would you design a rate limiter?",
        "conversation": [
            {"role": "interviewer", "type": "main_question", "text": "...", "timestamp": "..."},
            {"role": "candidate",  "type": "answer",         "text": "...", "timestamp": "..."},
            {"role": "interviewer", "type": "follow_up",      "text": "...", "timestamp": "..."},
            {"role": "candidate",  "type": "answer",         "text": "...", "timestamp": "..."},
        ],
        "transcript": "flat candidate text for backward compat",
        "skipped": false,
        "timestamp": "..."
    }
    """

    def __init__(
        self,
        avatar_id: Optional[str],
        avatar_image_path: Optional[str],
        job_description: Dict,
        questions: List[Dict],
        candidate_info: Dict
    ):
        self.avatar_id = avatar_id
        self.avatar_image_path = avatar_image_path
        self.job_description = job_description
        self.questions = questions
        self.candidate_info = candidate_info
        self.current_question_idx = 0
        self.answers: List[Dict] = []
        self.scores: List[Dict] = []
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.interview_active = False

    def start_interview(self):
        """Mark interview as started"""
        self.start_time = datetime.now()
        self.interview_active = True

    def end_interview(self):
        """Mark interview as ended"""
        self.end_time = datetime.now()
        self.interview_active = False

    def get_duration_minutes(self) -> Optional[float]:
        """Get interview duration in minutes"""
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            return delta.total_seconds() / 60.0
        return None

    def get_opening_message(self) -> str:
        """Generate opening message for interview"""
        job_title = self.job_description.get("title", "this position")
        candidate_name = self.candidate_info.get("name", "there")

        return (
            f"Hello {candidate_name}! I'm your technical interviewer for the {job_title} position. "
            f"Today we'll have a structured technical conversation covering various aspects of the role. "
            f"We'll start with some foundational questions and progress to more challenging ones. "
            f"Feel free to ask for clarification if needed, and take your time with your answers. "
            f"Let's get started!"
        )

    def get_current_question(self) -> Optional[Dict]:
        """Get current question"""
        if self.current_question_idx < len(self.questions):
            return self.questions[self.current_question_idx]
        return None

    def submit_answer(self, conversation: list = None, transcript: str = None, **kwargs):
        """
        Submit candidate answer for current question with full conversation thread.

        Args:
            conversation: Structured conversation thread (list of {role, type, text, timestamp})
            transcript: Optional flat transcript override. Auto-generated from conversation if omitted.
        """
        if not self.interview_active:
            raise ValueError("Interview is not active")

        if self.current_question_idx >= len(self.questions):
            raise ValueError("All questions have been answered")

        # Build flat transcript from conversation if not provided
        if transcript is None and conversation:
            transcript = " ".join(
                turn["text"] for turn in conversation if turn["role"] == "candidate"
            )

        answer_obj = {
            "question_idx": self.current_question_idx,
            "question": self.questions[self.current_question_idx].get("question", ""),
            "conversation": conversation or [],
            "transcript": transcript or "",
            "skipped": False,
            "timestamp": datetime.now().isoformat()
        }

        self.answers.append(answer_obj)
        self.current_question_idx += 1

    def submit_skip(self, conversation: list = None):
        """Record a skipped question"""
        if not self.interview_active:
            raise ValueError("Interview is not active")

        answer_obj = {
            "question_idx": self.current_question_idx,
            "question": self.questions[self.current_question_idx].get("question", ""),
            "conversation": conversation or [],
            "transcript": "",
            "skipped": True,
            "timestamp": datetime.now().isoformat()
        }
        self.answers.append(answer_obj)
        self.current_question_idx += 1

    def save_partial(self, conversation: list):
        """Save partial conversation for a question (used when navigating away mid-answer)"""
        # Find existing answer for current question, or create one
        for answer in self.answers:
            if answer["question_idx"] == self.current_question_idx:
                answer["conversation"] = conversation
                answer["transcript"] = " ".join(
                    turn["text"] for turn in conversation if turn["role"] == "candidate"
                )
                return
        # No existing answer — save as partial
        self.submit_answer(conversation=conversation)

    def persist_answers(self, interview_id: str):
        """Save current answers to disk for cross-process access (agent → API)"""
        path = Path("interview_store") / f"{interview_id}_answers.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({
            "answers": self.answers,
            "current_question_idx": self.current_question_idx,
            "interview_active": self.interview_active,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
        }, ensure_ascii=False))

    def needs_follow_up(self, transcript: str) -> bool:
        """Determine if answer needs follow-up based on heuristics"""
        word_count = len(transcript.split())

        if word_count < 30:
            return True

        vague_phrases = ["i guess", "maybe", "i think", "probably", "not sure"]
        if any(phrase in transcript.lower() for phrase in vague_phrases):
            return True

        return False

    async def evaluate_answer(self, answer_text: str, question_text: str, follow_up_count: int, max_follow_ups: int) -> str:
        """
        Evaluate answer quality using LLM.
        Returns: "follow_up", "unanswered", or "answered"
        """
        if not answer_text.strip():
            return "unanswered"

        if follow_up_count >= max_follow_ups:
            return "answered"

        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_FOLLOW_UP_MODEL)

        prompt = f"""Evaluate a candidate's interview answer. Classify as exactly ONE of:
- "answered" — substantive attempt that addresses the question
- "follow_up" — vague or partial, a follow-up would help draw out detail
- "unanswered" — deflected, said "I don't know", or didn't attempt to answer

QUESTION: {question_text}
ANSWER: {answer_text}
FOLLOW-UPS ALREADY ASKED: {follow_up_count}

If follow-ups were already asked and the candidate hasn't improved much, lean toward "answered" to move on.

Reply with ONLY one word: answered, follow_up, or unanswered"""

        try:
            response = await model.generate_content_async(prompt)
            verdict = response.text.strip().lower().replace('"', '').replace("'", "")
            if verdict in ("answered", "follow_up", "unanswered"):
                return verdict
            logger.warning(f"Unexpected evaluation result: {verdict}")
            return "answered"
        except Exception as e:
            logger.warning(f"Answer evaluation failed: {e}")
            return "answered" if len(answer_text.split()) >= 15 else "unanswered"

    def get_follow_up_question(self, transcript: str) -> str:
        """Generate follow-up question based on answer"""
        word_count = len(transcript.split())

        if word_count < 30:
            return "Can you elaborate on that? Could you provide more detail about your approach?"

        return "That's helpful. Can you walk me through a specific example or implementation detail?"

    def is_complete(self) -> bool:
        """Check if interview is complete"""
        return self.current_question_idx >= len(self.questions)

    def get_closing_message(self) -> str:
        """Generate closing message"""
        return (
            "That concludes our technical interview. Thank you for your thoughtful answers "
            "and your time today. We'll review your responses and get back to you soon. "
            "Have a great day!"
        )

    def get_interview_state(self) -> Dict:
        """Get current interview state"""
        return {
            "active": self.interview_active,
            "current_question_idx": self.current_question_idx,
            "total_questions": len(self.questions),
            "questions_answered": len(self.answers),
            "is_complete": self.is_complete(),
            "duration_minutes": self.get_duration_minutes()
        }
