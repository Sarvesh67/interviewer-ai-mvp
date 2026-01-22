"""
Real-time Interview Session Management
Handles LiveKit + Hedra integration for conducting interviews
"""
import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from config import settings
from hedra_avatar import create_interviewer_persona


class TechnicalInterviewSession:
    """
    Manages a technical interview session with Hedra avatar
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
        
        opening = f"""Hello {candidate_name}! I'm your technical interviewer for the {job_title} position.

Today we'll have a structured technical conversation covering various aspects of the role.
We'll start with some foundational questions and progress to more challenging ones.

Feel free to ask for clarification if needed, and take your time with your answers.
Let's get started!"""
        
        return opening
    
    def get_current_question(self) -> Optional[Dict]:
        """Get current question"""
        if self.current_question_idx < len(self.questions):
            return self.questions[self.current_question_idx]
        return None
    
    def submit_answer(self, transcript: str, follow_up_transcript: Optional[str] = None):
        """
        Submit candidate answer for current question
        
        Args:
            transcript: Main answer transcript
            follow_up_transcript: Optional follow-up answer
        """
        if not self.interview_active:
            raise ValueError("Interview is not active")
        
        if self.current_question_idx >= len(self.questions):
            raise ValueError("All questions have been answered")
        
        answer_obj = {
            "question_idx": self.current_question_idx,
            "question": self.questions[self.current_question_idx].get("question", ""),
            "transcript": transcript,
            "follow_up_transcript": follow_up_transcript,
            "timestamp": datetime.now().isoformat()
        }
        
        self.answers.append(answer_obj)
        self.current_question_idx += 1
    
    def needs_follow_up(self, transcript: str) -> bool:
        """
        Determine if answer needs follow-up
        
        Args:
            transcript: Answer transcript
            
        Returns:
            True if follow-up is recommended
        """
        # Simple heuristics - can be enhanced with LLM
        word_count = len(transcript.split())
        
        # Too short
        if word_count < 30:
            return True
        
        # Check for vague indicators
        vague_phrases = ["i guess", "maybe", "i think", "probably", "not sure"]
        if any(phrase in transcript.lower() for phrase in vague_phrases):
            return True
        
        return False
    
    def get_follow_up_question(self, transcript: str) -> str:
        """
        Generate follow-up question based on answer
        
        Args:
            transcript: Original answer transcript
            
        Returns:
            Follow-up question text
        """
        word_count = len(transcript.split())
        
        if word_count < 30:
            return "Can you elaborate on that? Could you provide more detail about your approach?"
        
        # Generic follow-up
        return "That's helpful. Can you walk me through a specific example or implementation detail?"
    
    def is_complete(self) -> bool:
        """Check if interview is complete"""
        return self.current_question_idx >= len(self.questions)
    
    def get_closing_message(self) -> str:
        """Generate closing message"""
        return """That concludes our technical interview. Thank you for your thoughtful answers and your time today.

We'll review your responses and get back to you soon. Have a great day!"""
    
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


# Note: Full LiveKit + Hedra integration would require:
# - livekit SDK installation
# - Hedra plugin for LiveKit
# - WebRTC setup
# - Real-time audio/video streaming
#
# For now, this provides the session management structure.
# The actual real-time integration would be implemented as:
#
# async def setup_hedra_agent(ctx):
#     from livekit import agents
#     from livekit.plugins import hedra
#     from livekit.plugins import openai
#     
#     # Create AgentSession with STT, VAD, LLM, TTS
#     agent_session = agents.AgentSession(
#         stt=openai.STT(model="whisper-1"),
#         vad=agents.vad.VAD.load(),
#         llm=openai.LLM(model="gpt-4o-mini"),
#         tts=openai.TTS(),
#     )
#     
#     # Create Agent with instructions
#     agent = agents.Agent(
#         instructions="You are a technical interviewer..."
#     )
#     
#     # Start the agent session
#     await agent_session.start(agent=agent, room=ctx.room)
#     
#     # Setup Hedra avatar
#     avatar = hedra.AvatarSession(
#         avatar_id=avatar_id,
#         avatar_participant_name="technical-interviewer"
#     )
#     
#     # Start Hedra avatar with the agent session
#     await avatar.start(agent_session, room=ctx.room)
#     
#     return agent_session, avatar

