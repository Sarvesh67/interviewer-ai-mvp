"""
Real-time Interview Agent using LiveKit + Hedra
Handles live conversations with candidates through Hedra avatars
"""
import asyncio
import logging
from typing import Optional
from datetime import datetime

from livekit import agents, rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.plugins import (
    openai,
    deepgram,
    elevenlabs,
    silero,
)

from config import settings
from interview_session import TechnicalInterviewSession
from hedra_avatar import create_interviewer_persona
from answer_scoring import score_candidate_answer

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
        self.agent: Optional[agents.VoiceAssistant] = None
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
                    smart_format=True
                )
            elif settings.OPENAI_API_KEY:
                stt = openai.STT(model="whisper-1")
            else:
                raise ValueError("Either DEEPGRAM_API_KEY or OPENAI_API_KEY must be configured")
            
            # Initialize LLM for conversation
            # Using Gemini for cost efficiency, fallback to OpenAI
            if settings.GEMINI_API_KEY:
                # Note: LiveKit may not have direct Gemini plugin, using OpenAI as fallback
                # You may need to create a custom Gemini LLM plugin
                llm_model = openai.LLM(
                    model="gpt-4o-mini",  # Cost-effective option
                    temperature=0.7
                )
            else:
                llm_model = openai.LLM(
                    model="gpt-4o-mini",
                    temperature=0.7
                )
            
            # Initialize TTS (Text-to-Speech)
            # Using ElevenLabs for better quality, fallback to Silero
            if settings.ELEVENLABS_API_KEY:
                tts = elevenlabs.TTS(
                    voice="Rachel",  # Professional female voice
                    model="eleven_multilingual_v2"
                )
            else:
                tts = silero.TTS(voice="en_1")  # Free alternative
            
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
            
            # Create voice assistant agent
            self.agent = agents.VoiceAssistant(
                vad=agents.vad.VAD.load(),  # Voice Activity Detection
                stt=stt,
                llm=llm_model,
                tts=tts,
                chat_ctx=llm.ChatContext().append(
                    role="system",
                    text=full_persona
                ),
            )
            
            # Setup Hedra avatar integration
            # Note: This requires Hedra LiveKit plugin
            # If plugin is not available, agent will work without avatar video
            try:
                from livekit.plugins import hedra
                
                self.hedra_avatar = hedra.AvatarSession(
                    avatar_id=self.session.avatar_id,
                    avatar_participant_name="technical-interviewer"
                )
                
                # Start Hedra avatar
                await self.hedra_avatar.start(
                    self.agent.session,
                    room=self.ctx.room
                )
                logger.info(f"Hedra avatar {self.session.avatar_id} started")
            except ImportError:
                logger.warning("Hedra plugin not available, running without avatar video")
            except Exception as e:
                logger.warning(f"Could not start Hedra avatar: {e}, continuing without avatar")
            
            # Start the agent
            self.agent.start(ctx=self.ctx.room)
            
            # Start interview
            self.session.start_interview()
            
            # Send opening message
            opening = self.session.get_opening_message()
            await self.agent.say(opening, allow_interruptions=False)
            
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
        
        await self.agent.say(f"{context}{question_text}", allow_interruptions=True)
        self.follow_up_count = 0
        self.current_answer_transcript = ""
    
    async def _handle_answer(self, transcript: str):
        """Handle candidate's answer"""
        self.current_answer_transcript += " " + transcript
        
        # Check if we need follow-up
        if self.session.needs_follow_up(transcript) and self.follow_up_count < self.max_follow_ups_per_question:
            self.follow_up_count += 1
            follow_up = self.session.get_follow_up_question(transcript)
            await self.agent.say(follow_up, allow_interruptions=True)
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
        await self.agent.say(closing, allow_interruptions=False)
        
        self.session.end_interview()
        
        # Disconnect agent
        await asyncio.sleep(2)
        if self.agent:
            await self.agent.aclose()
        
        logger.info("Interview completed")
    
    async def run(self):
        """Run the interview agent"""
        try:
            await self.setup()
            
            # Listen for user speech and handle responses
            @self.agent.on("user_speech_committed")
            async def on_user_speech(msg: agents.VoiceAssistantUserMessage):
                transcript = msg.content
                logger.info(f"Candidate said: {transcript}")
                await self._handle_answer(transcript)
            
            # Keep agent running
            await self.agent.aclose()
            
        except Exception as e:
            logger.error(f"Error running interview agent: {e}")
            raise


async def entrypoint(ctx: JobContext):
    """
    LiveKit agent entrypoint
    This is called when a participant joins the room
    """
    logger.info("Interview agent entrypoint called")
    
    # Get interview_id from room name
    interview_id = ctx.room.name
    
    # Fetch interview session
    from realtime_interview_manager import get_interview_session
    
    interview_session = get_interview_session(interview_id)
    
    if not interview_session:
        logger.error(f"Interview session not found for: {interview_id}")
        # Try to get from main.py's interviews dict as fallback
        try:
            from main import interviews
            if interview_id in interviews:
                interview_session = interviews[interview_id]["session"]
            else:
                raise ValueError(f"Interview {interview_id} not found")
        except Exception as e:
            logger.error(f"Could not load interview session: {e}")
            return
    
    logger.info(f"Starting interview agent for interview: {interview_id}")
    
    # Create and run the interview agent
    agent = RealtimeInterviewAgent(interview_session, ctx)
    await agent.run()


if __name__ == "__main__":
    # Run the agent worker
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )

