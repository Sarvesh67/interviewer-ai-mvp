"""
Real-time Interview Manager
Creates LiveKit rooms and starts interview agents for live conversations
"""
import asyncio
import logging
import re
from typing import Dict, Optional
from datetime import datetime, timedelta

from livekit import api, rtc
from livekit.agents import JobContext
from livekit.protocol.room import CreateRoomRequest
from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest

import json
from pathlib import Path
from config import settings
from core.session import TechnicalInterviewSession
from agent.worker import RealtimeInterviewAgent

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
                CreateRoomRequest(
                    name=interview_id,
                    empty_timeout=300,  # 5 minutes
                    max_participants=4  # Candidate + Agent + Hedra avatar + buffer
    )
)

            # Explicitly dispatch agent to the room — matches agent_name="interviewer"
            try:
                await self.livekit_api.agent_dispatch.create_dispatch(
                    CreateAgentDispatchRequest(room=interview_id, agent_name="interviewer")
                )
                logger.info(f"Agent dispatched to room {interview_id}")
            except Exception as e:
                logger.error(f"Failed to dispatch agent to room {interview_id}: {e}")
                raise

            # Create access token for candidate (expires in 1 hour)
            candidate_token = api.AccessToken(
                api_key=settings.LIVEKIT_API_KEY,
                api_secret=settings.LIVEKIT_API_SECRET
            ) \
                .with_identity(candidate_name) \
                .with_name(candidate_name) \
                .with_ttl(timedelta(hours=1)) \
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=interview_id,
                        can_publish=True,
                        can_subscribe=True,
                    )
                )

            candidate_token_str = candidate_token.to_jwt()

            # Create access token for interviewer agent (expires in 1 hour)
            agent_token = api.AccessToken(
                api_key=settings.LIVEKIT_API_KEY,
                api_secret=settings.LIVEKIT_API_SECRET
            ) \
                .with_identity("interviewer-agent") \
                .with_name("Technical Interviewer") \
                .with_ttl(timedelta(hours=1)) \
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=interview_id,
                        can_publish=True,
                        can_subscribe=True,
                    )
                )

            agent_token_str = agent_token.to_jwt()
            
            await self.livekit_api.aclose()

            return {
                "room_name": interview_id,
                "room_url": settings.LIVEKIT_URL,
                "candidate_token": candidate_token_str,
                "agent_token": agent_token_str,
                "candidate_join_url": f"{settings.LIVEKIT_URL}?token={candidate_token_str}",
            }

        except Exception as e:
            logger.error(f"Error creating interview room: {e}")
            await self.livekit_api.aclose()
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


INTERVIEW_ID_PATTERN = re.compile(r"^interview_[a-f0-9]{12}$")


def register_interview_session(interview_id: str, session: TechnicalInterviewSession):
    """Register interview session for agent access"""
    if not INTERVIEW_ID_PATTERN.match(interview_id):
        raise ValueError(f"Invalid interview_id format: {interview_id}")

    PERSIST_DIR = Path("interview_store")
    PERSIST_DIR.mkdir(exist_ok=True)

    payload = {
        "avatar_id": session.avatar_id,
        "avatar_image_path": getattr(session, "avatar_image_path", None),
        "job_description": session.job_description,
        "questions": session.questions,
        "candidate_info": session.candidate_info,
    }
    (PERSIST_DIR / f"{interview_id}.json").write_text(json.dumps(payload))


def get_interview_session(interview_id: str) -> Optional[TechnicalInterviewSession]:
    """Get interview session by ID"""
    if not INTERVIEW_ID_PATTERN.match(interview_id):
        logger.error(f"Invalid interview_id format: {interview_id}")
        return None

    store_file = Path("interview_store") / f"{interview_id}.json"
    if store_file.exists():
        try:
            payload = json.loads(store_file.read_text())
        except json.JSONDecodeError as e:
            logger.error(f"Corrupted session file for {interview_id}: {e}")
            return None
        return TechnicalInterviewSession(
            avatar_id=payload.get("avatar_id"),
            avatar_image_path=payload.get("avatar_image_path"),
            job_description=payload["job_description"],
            questions=payload["questions"],
            candidate_info=payload["candidate_info"],
        )
    else:
        logger.error(f"Interview session file not found: {interview_id}")
        return None

