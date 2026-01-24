"""
Real-time Interview Agent using LiveKit + Hedra
Handles live conversations with candidates through Hedra avatars
"""
import asyncio
import logging
import os
from typing import Optional
from datetime import datetime

from livekit import agents
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.plugins import (
    google,
    deepgram,
    elevenlabs
)
from pathlib import Path
import json
import re

from config import settings
from interview_session import TechnicalInterviewSession
from hedra_avatar import create_interviewer_persona
from answer_scoring import score_candidate_answer
from utils.string_utils import StringUtils

logger = logging.getLogger("realtime_interview_agent")


class RealtimeInterviewAgent:
    """
    LiveKit agent that conducts real-time interviews using Hedra avatar
    """
    
    def __init__(
        self,
        interview_session: TechnicalInterviewSession,
        ctx: JobContext
    ):
        self.session = interview_session
        self.ctx = ctx
        self.agent_session: Optional[agents.AgentSession] = None
        self.agent: Optional[agents.Agent] = None
        self.hedra_avatar = None
        self.current_answer_transcript = ""
        self.follow_up_count = 0
        self.max_follow_ups_per_question = 2
        
    async def setup(self):
        """Setup the interview agent with Hedra avatar"""
        try:
            # Initialize STT (Speech-to-Text)
            # Using Deepgram for better accuracy, fallback to OpenAI Whisper
            if settings.DEEPGRAM_API_KEY:
                stt = deepgram.STT(
                    language="en-US",
                    model="nova-2",
                    smart_format=True,
                    api_key=settings.DEEPGRAM_API_KEY
                )
            else:
                raise ValueError("DEEPGRAM_API_KEY must be configured")
            
            # Initialize LLM for conversation
            # Using Gemini Flash for fast, cost-efficient conversations
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY must be configured for LLM")
            
            # Use Google Gemini LLM via livekit-plugins-google
            llm_model = google.LLM(
                model=settings.GEMINI_MODEL,  # e.g., "gemini-2.0-flash-exp"
                api_key=settings.GEMINI_API_KEY,
                temperature=0.7
            )
            
            # Initialize TTS (Text-to-Speech)
            # Using ElevenLabs for better quality, fallback to Silero
            if settings.ELEVENLABS_API_KEY:
                tts = elevenlabs.TTS(
                    voice_id="SAz9YHcvj6GT2YYXdXww",  # Professional female voice
                    api_key=settings.ELEVENLABS_API_KEY
                )
            else:
                raise ValueError("ElevenLabs API key is required for TTS")
            
            # Create system prompt for interviewer persona
            persona = create_interviewer_persona(
                job_title=self.session.job_description.get("title", ""),
                technical_expertise=self.session.job_description.get("domain_knowledge", {}).get("domain_areas", [""])[0] if self.session.job_description.get("domain_knowledge") else "",
                questions=self.session.questions
            )
            
            # Add interview context to persona
            interview_context = f"""
            INTERVIEW CONTEXT:
            - Candidate: {self.session.candidate_info.get('name', 'Candidate')}
            - Position: {self.session.job_description.get('title', 'Technical Role')}
            - Total Questions: {len(self.session.questions)}
            - Current Question Index: {self.session.current_question_idx}
            
            QUESTIONS TO ASK (in order):
            {chr(10).join([f"{i+1}. {q.get('question', '')}" for i, q in enumerate(self.session.questions)])}
            
            IMPORTANT:
            - Ask questions ONE AT A TIME
            - Wait for complete answer before moving to next question
            - Ask follow-ups if answer is unclear or too short
            - After all questions are answered, thank the candidate and end the interview
            """
            
            full_persona = f"{persona}\n\n{interview_context}"
            
            # Create AgentSession with STT, VAD, LLM, TTS
            self.agent_session = agents.AgentSession(
                stt=stt,
                turn_detection="stt",  # Voice Activity Detection
                llm=llm_model,
                tts=tts,
            )
            
            # Create Agent with instructions (system prompt)
            self.agent = agents.Agent(
                instructions=full_persona,
            )
            
            # Setup Hedra avatar integration
            # Note: This requires Hedra LiveKit plugin
            # If plugin is not available, agent will work without avatar video
            try:
                from livekit.plugins import hedra

                avatar_kwargs = {
                    "avatar_participant_name": "technical-interviewer",
                    "api_key": settings.HEDRA_API_KEY,
                    "api_url": "https://api.hedra.com/public/livekit/v1/session",
                }

                # Prefer avatar_id if provided; otherwise fall back to avatar_image (PIL Image).
                #
                # NOTE: The Hedra LiveKit plugin accepts any string avatar_id; it is not
                # required to be UUID-shaped. We should not block valid Hedra IDs.
                if StringUtils.looks_like_uuid(self.session.avatar_id) and self.session.avatar_id.strip():
                    avatar_kwargs["avatar_id"] = self.session.avatar_id.strip()
                else:
                    avatar_image_path = getattr(self.session, "avatar_image_path", None)
                    if not avatar_image_path:
                        # default local image if not provided
                        avatar_image_path = str(Path("frontend") / "assets" / "avatar.png")

                    try:
                        from PIL import Image
                        if Path(avatar_image_path).exists():
                            avatar_kwargs["avatar_image"] = Image.open(avatar_image_path)
                        else:
                            logger.warning(f"Avatar image not found at {avatar_image_path}; Hedra will be skipped")
                    except Exception as e:
                        logger.warning(f"Could not load avatar image for Hedra: {e}")

                # Only create Hedra session if we have either avatar_id or avatar_image
                if "avatar_id" in avatar_kwargs or "avatar_image" in avatar_kwargs:
                    self.hedra_avatar = hedra.AvatarSession(**avatar_kwargs)
                    logger.info("Hedra avatar configured")
                else:
                    logger.error("No valid avatar_id or avatar_image available; skipping Hedra avatar")
                    raise ValueError(f"No valid avatar_id or avatar_image available. Error: {e}")
                
                # Start Hedra avatar (after session is started)
                # We'll do this after session.start()
                logger.info(f"Hedra avatar metadata {self.session.avatar_id} configured")
            except ImportError:
                logger.warning("Hedra plugin not available, running without avatar video")
            except Exception as e:
                logger.warning(f"Could not configure Hedra avatar: {e}, continuing without avatar")
            
            # Start the agent session with the agent
            await self.agent_session.start(
                agent=self.agent,
                room=self.ctx.room
            )
            
            # Start Hedra avatar after session is started
            if self.hedra_avatar:
                try:
                    await self.hedra_avatar.start(
                        self.agent_session,
                        room=self.ctx.room
                    )
                    logger.info(f"Hedra avatar {self.session.avatar_id} started")
                except Exception as e:
                    logger.warning(f"Could not start Hedra avatar: {e}, continuing without avatar")
            
            # Start interview
            self.session.start_interview()
            
            # Send opening message
            opening = self.session.get_opening_message()
            await self.agent_session.say(opening, allow_interruptions=False)
            
            # Ask first question
            await self._ask_current_question()
            
        except Exception as e:
            logger.error(f"Error setting up interview agent: {e}")
            raise
    
    async def _ask_current_question(self):
        """Ask the current question"""
        if self.session.is_complete():
            await self._end_interview()
            return
        
        question_obj = self.session.get_current_question()
        if not question_obj:
            await self._end_interview()
            return
        
        question_text = question_obj.get("question", "")
        
        # Add context if helpful
        context = f"Question {self.session.current_question_idx + 1} of {len(self.session.questions)}: "
        
        await self.agent_session.say(f"{context}{question_text}", allow_interruptions=True)
        self.follow_up_count = 0
        self.current_answer_transcript = ""
    
    async def _handle_answer(self, transcript: str):
        """Handle candidate's answer"""
        self.current_answer_transcript += " " + transcript
        
        # Check if we need follow-up
        if self.session.needs_follow_up(transcript) and self.follow_up_count < self.max_follow_ups_per_question:
            self.follow_up_count += 1
            follow_up = self.session.get_follow_up_question(transcript)
            await self.agent_session.say(follow_up, allow_interruptions=True)
        else:
            # Answer is complete, save it
            self.session.submit_answer(self.current_answer_transcript.strip())
            
            # Move to next question
            if not self.session.is_complete():
                # Brief transition
                await asyncio.sleep(1)
                await self._ask_current_question()
            else:
                await self._end_interview()
    
    async def _end_interview(self):
        """End the interview"""
        closing = self.session.get_closing_message()
        await self.agent_session.say(closing, allow_interruptions=False)
        
        self.session.end_interview()
        
        # Disconnect agent session
        await asyncio.sleep(2)
        if self.agent_session:
            await self.agent_session.aclose()
        
        logger.info("Interview completed")
    
    async def run(self):
        """Run the interview agent"""
        try:
            await self.setup()
            
            # Listen for user input transcribed events
            def on_user_input_transcribed(event: agents.UserInputTranscribedEvent):
                transcript = event.transcript
                logger.info(f"Candidate said: {transcript}")
                asyncio.create_task(self._handle_answer(transcript))

            self.agent_session.on("user_input_transcribed", on_user_input_transcribed)
            
            # Keep agent session running until closed
            # The session will stay alive until explicitly closed or room disconnects
            # We'll wait for the session to close naturally
            try:
                # Wait for close event
                close_event = asyncio.Event()
                
                def on_close(event: agents.CloseEvent):
                    close_event.set()

                self.agent_session.on("close", on_close)
                
                await close_event.wait()
            except asyncio.CancelledError:
                pass
            
        except Exception as e:
            logger.error(f"Error running interview agent: {e}")
            raise
        finally:
            if self.agent_session:
                await self.agent_session.aclose()


async def entrypoint(ctx: JobContext):
    """
    LiveKit agent entrypoint
    This is called when a participant joins the room
    """
    logger.info("Interview agent entrypoint called")

    # Connect agent to room
    await ctx.connect()
    await ctx.wait_for_participant()
    
    # Get interview_id from room name
    interview_id = ctx.room.name
    
    # Fetch interview session
    from realtime_interview_manager import get_interview_session
    
    interview_session = get_interview_session(interview_id)
    
    if not interview_session:
        logger.error(f"Could not load interview session for: {interview_id}")
        raise ValueError(f"Interview session not found for: {interview_id}")
    
    logger.info(f"Starting interview agent for interview: {interview_id}")
    
    # Create and run the interview agent
    agent = RealtimeInterviewAgent(interview_session, ctx)
    await agent.run()


if __name__ == "__main__":
    # Validate and set LiveKit configuration from settings
    # The LiveKit agents framework expects these as environment variables
    if not settings.LIVEKIT_URL:
        raise ValueError(
            "LIVEKIT_URL is required. Please set it in your .env file.\n"
            "Get your LiveKit URL from: https://cloud.livekit.io"
        )
    
    if not settings.LIVEKIT_API_KEY:
        raise ValueError(
            "LIVEKIT_API_KEY is required. Please set it in your .env file.\n"
            "Get your LiveKit API key from: https://cloud.livekit.io"
        )
    
    if not settings.LIVEKIT_API_SECRET:
        raise ValueError(
            "LIVEKIT_API_SECRET is required. Please set it in your .env file.\n"
            "Get your LiveKit API secret from: https://cloud.livekit.io"
        )
    
    # Set environment variables for LiveKit agents framework
    # (only if not already set, to allow override via environment)
    if not os.getenv("LIVEKIT_URL"):
        os.environ["LIVEKIT_URL"] = settings.LIVEKIT_URL
    
    if not os.getenv("LIVEKIT_API_KEY"):
        os.environ["LIVEKIT_API_KEY"] = settings.LIVEKIT_API_KEY
    
    if not os.getenv("LIVEKIT_API_SECRET"):
        os.environ["LIVEKIT_API_SECRET"] = settings.LIVEKIT_API_SECRET
    
    logger.info("LiveKit configuration loaded from settings")
    
    # Run the agent worker
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            ws_url=settings.LIVEKIT_URL,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
        )
    )

