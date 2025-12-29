"""
Real-time Interview Manager
Creates LiveKit rooms and starts interview agents for live conversations
"""
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime

from livekit import api, rtc
from livekit.agents import JobContext

from config import settings
from interview_session import TechnicalInterviewSession
from realtime_interview_agent import RealtimeInterviewAgent

logger = logging.getLogger("realtime_interview_manager")


class RealtimeInterviewManager:
    """
    Manages real-time interview sessions with LiveKit
    """
    
    def __init__(self):
        if not all([settings.LIVEKIT_URL, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET]):
            raise ValueError("LiveKit credentials not configured")
        
        self.livekit_api = api.LiveKitAPI(
            url=settings.LIVEKIT_URL,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET
        )
    
    async def create_interview_room(
        self,
        interview_id: str,
        interview_session: TechnicalInterviewSession,
        candidate_name: str
    ) -> Dict:
        """
        Create a LiveKit room for the interview
        
        Args:
            interview_id: Unique interview identifier
            interview_session: Interview session object
            candidate_name: Candidate's name
            
        Returns:
            Dictionary with room info and access token
        """
        try:
            # Create room
            room = await self.livekit_api.room.create_room(
                name=interview_id,
                empty_timeout=300,  # 5 minutes
                max_participants=2,  # Candidate + Interviewer
            )
            
            # Create access token for candidate
            candidate_token = api.AccessToken(
                api_key=settings.LIVEKIT_API_KEY,
                api_secret=settings.LIVEKIT_API_SECRET
            ) \
                .with_identity(candidate_name) \
                .with_name(candidate_name) \
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=interview_id,
                        can_publish=True,
                        can_subscribe=True,
                    )
                )
            
            candidate_token_str = candidate_token.to_jwt()
            
            # Create access token for interviewer agent
            agent_token = api.AccessToken(
                api_key=settings.LIVEKIT_API_KEY,
                api_secret=settings.LIVEKIT_API_SECRET
            ) \
                .with_identity("interviewer-agent") \
                .with_name("Technical Interviewer") \
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=interview_id,
                        can_publish=True,
                        can_subscribe=True,
                    )
                )
            
            agent_token_str = agent_token.to_jwt()
            
            return {
                "room_name": interview_id,
                "room_url": settings.LIVEKIT_URL,
                "candidate_token": candidate_token_str,
                "agent_token": agent_token_str,
                "candidate_join_url": f"{settings.LIVEKIT_URL}?token={candidate_token_str}",
            }
            
        except Exception as e:
            logger.error(f"Error creating interview room: {e}")
            raise
    
    async def start_interview_agent(
        self,
        interview_id: str,
        interview_session: TechnicalInterviewSession
    ):
        """
        Start the interview agent in the room
        
        This would typically be handled by the LiveKit agent worker
        The agent worker should be running separately and will pick up jobs
        """
        # In production, the agent worker runs as a separate process
        # and picks up jobs from LiveKit
        # This is just a placeholder showing the structure
        
        logger.info(f"Interview agent should be started for interview: {interview_id}")
        logger.info("Make sure the LiveKit agent worker is running:")
        logger.info("  python realtime_interview_agent.py dev")


def get_interview_session_for_agent(interview_id: str) -> Optional[TechnicalInterviewSession]:
    """
    Retrieve interview session for agent
    In production, this would fetch from database
    For now, we'll use the in-memory storage from main.py
    """
    # Import here to avoid circular imports
    from main import interviews
    
    if interview_id not in interviews:
        return None
    
    interview_data = interviews[interview_id]
    return interview_data.get("session")


# Global storage for active interviews (in production, use database)
active_interviews: Dict[str, TechnicalInterviewSession] = {}


def register_interview_session(interview_id: str, session: TechnicalInterviewSession):
    """Register interview session for agent access"""
    active_interviews[interview_id] = session


def get_interview_session(interview_id: str) -> Optional[TechnicalInterviewSession]:
    """Get interview session by ID"""
    return active_interviews.get(interview_id)

