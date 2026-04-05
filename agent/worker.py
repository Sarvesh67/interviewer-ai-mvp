"""
Real-time Interview Agent using LiveKit + Hedra
Handles live conversations with candidates through Hedra avatars.

Pipeline: Deepgram STT → Gemini LLM → Deepgram TTS → Hedra Avatar
Data channel: sends question/transcript events to frontend in real-time.
Answer persistence: writes structured conversation to disk after each question
so the API server (separate container) can read them for report generation.
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

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
)

from config import settings
from core.session import TechnicalInterviewSession
from integrations.hedra import create_interviewer_persona, _default_avatar_image_path
from utils.string_utils import StringUtils

logger = logging.getLogger("realtime_interview_agent")


class RealtimeInterviewAgent:
    """LiveKit agent that conducts real-time interviews using Hedra avatar"""

    def __init__(self, interview_session: TechnicalInterviewSession, ctx: JobContext):
        self.session = interview_session
        self.ctx = ctx
        self.agent_session: Optional[agents.AgentSession] = None
        self.agent: Optional[agents.Agent] = None
        self.hedra_avatar = None

        # Conversation state per question
        self.current_conversation: list = []
        self.current_answer_text = ""  # accumulated candidate text for current question
        self.follow_up_count = 0
        self.max_follow_ups_per_question = 2
        self._awaiting_answer = False
        self._expecting_follow_up = False  # flag for conversation_item_added handler
        self._answer_timer: Optional[asyncio.Task] = None  # silence timeout task
        self._answer_silence_seconds = 6.0  # seconds of silence before answer is considered complete
        self._nudge_given = False  # whether we've already nudged for unanswered on current question

        # Interview time limit
        self._interview_timer: Optional[asyncio.Task] = None
        self._max_interview_minutes = settings.MAX_INTERVIEW_DURATION_MINUTES  # 45 min default
        self._interview_start_time: Optional[datetime] = None
        self._done_event = asyncio.Event()

    # ──────────────────────────────────────────────
    # Data channel helpers
    # ──────────────────────────────────────────────

    async def _publish_data(self, payload: dict, reliable: bool = True):
        """Send JSON data to frontend via LiveKit data channel"""
        try:
            await self.ctx.room.local_participant.publish_data(
                json.dumps(payload).encode(),
                reliable=reliable,
            )
        except Exception as e:
            logger.warning(f"Failed to publish data: {e}")

    async def _send_question(self, question_idx: int, text: str, status: str = "active"):
        """Broadcast current question to frontend"""
        await self._publish_data({
            "type": "question",
            "question_idx": question_idx,
            "total": len(self.session.questions),
            "text": text,
            "status": status,
        })

    async def _send_transcript(self, speaker: str, text: str, is_final: bool = True):
        """Broadcast transcript entry to frontend"""
        await self._publish_data({
            "type": "transcript",
            "speaker": speaker,
            "text": text,
            "is_final": is_final,
            "timestamp": datetime.now().isoformat(),
        }, reliable=is_final)

    async def _say_with_live_transcript(self, text: str, allow_interruptions: bool = False):
        """
        Speak text via TTS while streaming word-by-word transcript to frontend.
        Transcript words appear progressively in sync with speech.
        If interrupted, only the words "spoken" so far appear in the final transcript.
        """
        words = text.split()
        if not words:
            return

        spoken_words = []
        speech_rate = 2.8  # words per second (~168 WPM, natural speech)
        delay = 1.0 / speech_rate

        async def stream_words():
            """Stream words one-by-one as interim transcripts"""
            try:
                for i, word in enumerate(words):
                    spoken_words.append(word)
                    await self._send_transcript(
                        "interviewer",
                        " ".join(spoken_words),
                        is_final=False,
                    )
                    if i < len(words) - 1:
                        await asyncio.sleep(delay)
            except asyncio.CancelledError:
                pass  # speech ended (completed or interrupted) — stop streaming

        # Start word streaming and TTS concurrently
        stream_task = asyncio.ensure_future(stream_words())
        await self.agent_session.say(text, allow_interruptions=allow_interruptions)

        # Speech finished — cancel streaming
        stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            pass

        # Send final transcript with what was actually "spoken"
        final_text = " ".join(spoken_words) if spoken_words else text
        await self._send_transcript("interviewer", final_text, is_final=True)

    async def _generate_follow_up(self, question_text: str) -> str:
        """Generate a follow-up question using Gemini directly (bypasses agent pipeline)."""
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_FOLLOW_UP_MODEL)

        prompt = (
            f"You are an interviewer. The candidate gave a vague or incomplete answer.\n"
            f"QUESTION: {question_text}\n"
            f"ANSWER: {self.current_answer_text}\n\n"
            f"Ask ONE brief follow-up question to get more detail. Keep it short and to the point. "
            f"Reply with ONLY the follow-up question, nothing else."
        )

        try:
            response = await model.generate_content_async(prompt)
            return response.text.strip()
        except Exception as e:
            logger.warning(f"Follow-up generation failed: {e}")
            return self.session.get_follow_up_question(self.current_answer_text)

    # ──────────────────────────────────────────────
    # Navigation intent detection
    # ──────────────────────────────────────────────

    def _detect_navigation_intent(self, transcript: str) -> Optional[str]:
        """Detect skip/goto intents from candidate speech"""
        t = transcript.lower().strip()

        skip_phrases = [
            "skip", "next question", "move on", "let's move on",
            "pass", "i don't know", "don't have an answer",
            "move to the next", "go to the next", "let's go to next",
            "can we skip", "i'll skip", "skip this",
        ]
        if any(phrase in t for phrase in skip_phrases):
            return "skip"

        back_match = re.search(r"(?:go back|return|revisit).*question\s*(\d+)", t)
        if back_match:
            target = int(back_match.group(1)) - 1
            if 0 <= target < len(self.session.questions):
                return f"goto:{target}"

        return None

    # ──────────────────────────────────────────────
    # Setup
    # ──────────────────────────────────────────────

    async def setup(self):
        """Setup the interview agent with STT/LLM/TTS/Hedra"""
        try:
            if not settings.DEEPGRAM_API_KEY:
                raise ValueError("DEEPGRAM_API_KEY must be configured")
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY must be configured for LLM")

            # STT — Deepgram Nova-2
            stt = deepgram.STT(
                language="en-US",
                model="nova-2",
                smart_format=True,
                api_key=settings.DEEPGRAM_API_KEY,
            )

            # TTS — Deepgram Aura-2
            tts = deepgram.TTS(
                model="aura-2-orpheus-en",
                api_key=settings.DEEPGRAM_API_KEY,
            )

            # Turn detection — prefer EOUModel, fall back to STT-based
            turn_det = "stt"
            try:
                from livekit.plugins.turn_detector import EOUModel
                turn_det = EOUModel()
                logger.info("Using EOUModel for turn detection")
            except (ImportError, Exception) as e:
                logger.info(f"EOUModel not available ({e}), using STT-based turn detection")

            # System prompt
            persona = create_interviewer_persona(
                job_title=self.session.job_description.get("title", ""),
                technical_expertise=(
                    self.session.job_description.get("domain_knowledge", {}).get("domain_areas", [""])[0]
                    if self.session.job_description.get("domain_knowledge") else ""
                ),
                questions=self.session.questions,
            )

            interview_context = f"""
            INTERVIEW CONTEXT:
            - Candidate: {self.session.candidate_info.get('name', 'Candidate')}
            - Position: {self.session.job_description.get('title', 'Technical Role')}
            - Total Questions: {len(self.session.questions)}

            QUESTIONS TO ASK (in order):
            {chr(10).join([f"{i+1}. {q.get('question', '')}" for i, q in enumerate(self.session.questions)])}

            IMPORTANT:
            - Ask questions ONE AT A TIME
            - Wait for complete answer before moving to next question
            - Ask follow-ups if answer is unclear or too short
            - After all questions are answered, thank the candidate and end the interview

            NAVIGATION RULES:
            - If the candidate asks to skip a question, acknowledge briefly and move to the next question
            - If the candidate asks to go back to a previous question, acknowledge and revisit it
            - Always confirm navigation: "Sure, let's move to the next question" or "Let's revisit question 1."
            """

            full_persona = f"{persona}\n\n{interview_context}"

            # Create agent session
            self.agent_session = agents.AgentSession(
                stt=stt,
                turn_detection=turn_det,
                tts=tts,
            )

            self.agent = agents.Agent(instructions=full_persona)

            # Capture LLM-generated follow-up question text and stream it live
            def on_conversation_item_added(event):
                try:
                    if not self._expecting_follow_up:
                        return
                    item = getattr(event, "item", None)
                    if not item or getattr(item, "role", None) != "assistant":
                        return

                    # Try multiple attribute paths for the text
                    text = getattr(item, "text_content", None)
                    if not text:
                        content = getattr(item, "content", [])
                        for part in (content or []):
                            if hasattr(part, "text"):
                                text = part.text
                                break
                    if not text:
                        logger.warning(f"Follow-up item had no text. Attrs: {dir(item)}")
                        return

                    self._expecting_follow_up = False
                    self.current_conversation.append({
                        "role": "interviewer",
                        "type": "follow_up",
                        "text": text,
                        "timestamp": datetime.now().isoformat(),
                    })
                    asyncio.create_task(self._send_transcript("interviewer", text))
                    logger.info(f"Follow-up transcript sent: {text[:80]}")
                except Exception as e:
                    logger.warning(f"conversation_item_added handler error: {e}")

            self.agent_session.on("conversation_item_added", on_conversation_item_added)

            # Setup Hedra avatar
            try:
                from livekit.plugins import hedra

                avatar_kwargs = {
                    "avatar_participant_name": "technical-interviewer",
                    "api_key": settings.HEDRA_API_KEY,
                    "api_url": "https://api.hedra.com/public/livekit/v1/session",
                }

                if StringUtils.looks_like_uuid(self.session.avatar_id) and self.session.avatar_id.strip():
                    avatar_kwargs["avatar_id"] = self.session.avatar_id.strip()
                else:
                    avatar_image_path = getattr(self.session, "avatar_image_path", None)
                    if not avatar_image_path:
                        avatar_image_path = _default_avatar_image_path()
                    try:
                        from PIL import Image
                        if Path(avatar_image_path).exists():
                            avatar_kwargs["avatar_image"] = Image.open(avatar_image_path)
                        else:
                            logger.warning(f"Avatar image not found at {avatar_image_path}")
                    except Exception as e:
                        logger.warning(f"Could not load avatar image: {e}")

                if "avatar_id" in avatar_kwargs or "avatar_image" in avatar_kwargs:
                    self.hedra_avatar = hedra.AvatarSession(**avatar_kwargs)
                    logger.info("Hedra avatar configured")
                else:
                    logger.warning("No valid avatar; skipping Hedra")

            except ImportError:
                logger.warning("Hedra plugin not available, running without avatar video")
            except Exception as e:
                logger.warning(f"Could not configure Hedra avatar: {e}")

            # Start agent session
            logger.info(f"[{self.ctx.room.name}] Starting agent session...")
            await self.agent_session.start(agent=self.agent, room=self.ctx.room)
            logger.info(f"[{self.ctx.room.name}] Agent session started successfully")

            # Start Hedra avatar
            if self.hedra_avatar:
                try:
                    await self.hedra_avatar.start(self.agent_session, room=self.ctx.room)
                    logger.info("Hedra avatar started")
                except Exception as e:
                    logger.warning(f"Could not start Hedra avatar: {e}")

            # Start interview + time limit
            self.session.start_interview()
            self.session.persist_answers(self.ctx.room.name)
            self._interview_start_time = datetime.now()
            self._interview_timer = asyncio.ensure_future(self._interview_time_limit())

            # Opening message — live transcript streams word-by-word with speech
            opening = self.session.get_opening_message()
            await self._say_with_live_transcript(opening, allow_interruptions=False)

            # First question
            await self._ask_current_question()

        except Exception as e:
            logger.error(f"Error setting up interview agent: {e}")
            raise

    # ──────────────────────────────────────────────
    # Question flow
    # ──────────────────────────────────────────────

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
        idx = self.session.current_question_idx

        # Reset per-question state
        self._cancel_answer_timer()
        self.current_conversation = [{
            "role": "interviewer",
            "type": "main_question",
            "text": question_text,
            "timestamp": datetime.now().isoformat(),
        }]
        self.current_answer_text = ""
        self.follow_up_count = 0
        self._expecting_follow_up = False
        self._nudge_given = False

        # Question panel updates at start of speech (non-interruptible, safe to show immediately).
        # Transcript streams word-by-word in sync with TTS.
        spoken_text = f"Question {idx + 1} of {len(self.session.questions)}: {question_text}"
        await self._send_question(idx, question_text, "active")
        await self._say_with_live_transcript(spoken_text, allow_interruptions=False)
        self._awaiting_answer = True

    async def _handle_answer(self, transcript: str):
        """
        Accumulate candidate speech fragments and reset the silence timer.
        Navigation intents (skip, go back) are always processed regardless of state.
        """
        transcript = (transcript or "").strip()
        if not transcript:
            return

        # Check for navigation intents FIRST — always process these,
        # even if _awaiting_answer is False (timer may have already fired)
        nav = self._detect_navigation_intent(transcript)

        if nav == "skip":
            self._cancel_answer_timer()
            self._awaiting_answer = False

            # If the user already gave a partial answer (e.g. skipping during follow-up),
            # submit what they said as a real answer — don't lose their work.
            # Only mark as "skipped" if they said nothing at all.
            if self.current_answer_text.strip():
                self.session.submit_answer(conversation=self.current_conversation)
                question_status = "answered"
            else:
                self.session.submit_skip(self.current_conversation)
                question_status = "skipped"

            self.session.persist_answers(self.ctx.room.name)
            msg = "Sure, let's move on to the next question."
            await self._send_question(self.session.current_question_idx - 1, "", question_status)
            await self._say_with_live_transcript(msg, allow_interruptions=False)
            await self._ask_current_question()
            return

        if nav and nav.startswith("goto:"):
            self._cancel_answer_timer()
            target_idx = int(nav.split(":")[1])
            self._awaiting_answer = False
            if self.current_conversation:
                self.session.save_partial(self.current_conversation)
                self.session.persist_answers(self.ctx.room.name)
            self.session.current_question_idx = target_idx
            msg = f"Sure, let's revisit question {target_idx + 1}."
            await self._say_with_live_transcript(msg, allow_interruptions=False)
            await self._ask_current_question()
            return

        # Normal answer accumulation — only when awaiting
        if not self._awaiting_answer:
            return

        # Record candidate speech fragment in conversation thread
        self.current_conversation.append({
            "role": "candidate",
            "type": "answer",
            "text": transcript,
            "timestamp": datetime.now().isoformat(),
        })

        # Accumulate full candidate text for this question
        self.current_answer_text = (self.current_answer_text + " " + transcript).strip()

        # Reset silence timer — wait for user to finish speaking
        self._reset_answer_timer()

    def _cancel_answer_timer(self):
        """Cancel the pending answer timer"""
        if self._answer_timer and not self._answer_timer.done():
            self._answer_timer.cancel()
        self._answer_timer = None

    def _reset_answer_timer(self):
        """Reset the silence timer. When it fires, the accumulated answer is processed."""
        self._cancel_answer_timer()
        self._answer_timer = asyncio.ensure_future(self._answer_silence_timeout())

    async def _answer_silence_timeout(self):
        """
        Wait for 6 seconds of silence after the last speech fragment.
        If no new speech arrives, process the accumulated answer.
        If user speaks during the wait, this task is cancelled and a new one starts.
        """
        try:
            await asyncio.sleep(self._answer_silence_seconds)
            if self._awaiting_answer:
                await self._process_complete_answer()
        except asyncio.CancelledError:
            pass  # timer was reset by new speech — expected
        except Exception as e:
            logger.error(f"Answer processing failed: {e}")
            # Don't leave the interview stuck — submit what we have and move on
            if self._awaiting_answer:
                self._awaiting_answer = False
                self.session.submit_answer(conversation=self.current_conversation)
                self.session.persist_answers(self.ctx.room.name)
                await self._ask_current_question()

    async def _process_complete_answer(self):
        """Called after silence timeout. Evaluate answer and decide next action."""
        if not self._awaiting_answer:
            return

        question_text = self.session.get_current_question().get("question", "")
        verdict = await self.session.evaluate_answer(
            self.current_answer_text,
            question_text,
            self.follow_up_count,
            self.max_follow_ups_per_question,
        )
        logger.info(f"Answer eval: {verdict} (words={len(self.current_answer_text.split())}, follow_ups={self.follow_up_count})")

        if verdict == "follow_up":
            self.follow_up_count += 1
            follow_up_text = await self._generate_follow_up(question_text)
            self.current_conversation.append({
                "role": "interviewer",
                "type": "follow_up",
                "text": follow_up_text,
                "timestamp": datetime.now().isoformat(),
            })
            await self._say_with_live_transcript(follow_up_text, allow_interruptions=True)
            self._reset_answer_timer()
            return

        if verdict == "unanswered" and not self._nudge_given:
            self._nudge_given = True
            nudge = "No worries if you'd like to skip this one. Would you like me to move on to the next question?"
            self.current_conversation.append({
                "role": "interviewer", "type": "nudge",
                "text": nudge, "timestamp": datetime.now().isoformat(),
            })
            await self._send_transcript("interviewer", nudge)
            await self.agent_session.say(nudge, allow_interruptions=True)
            # _awaiting_answer stays True — restart silence timer so we don't get stuck
            self._reset_answer_timer()
            return

        # "answered" OR "unanswered" after nudge → submit and move on
        self._awaiting_answer = False
        if verdict == "unanswered" and not self.current_answer_text.strip():
            self.session.submit_skip(self.current_conversation)
            status = "skipped"
        else:
            self.session.submit_answer(conversation=self.current_conversation)
            status = "answered"
        self.session.persist_answers(self.ctx.room.name)
        logger.info(f"Answer submitted as {status} ({len(self.current_answer_text.split())} words, {self.follow_up_count} follow-ups)")

        answered_idx = self.session.current_question_idx - 1
        await self._send_question(answered_idx, "", status)

        if not self.session.is_complete():
            await asyncio.sleep(1)
            await self._ask_current_question()
        else:
            await self._end_interview()

    async def _interview_time_limit(self):
        """
        Manages the 45-minute interview hard limit.
        Broadcasts remaining time to frontend every 30 seconds.
        Auto-ends interview when time expires.
        """
        try:
            total_seconds = self._max_interview_minutes * 60
            elapsed = 0

            while elapsed < total_seconds:
                remaining = total_seconds - elapsed
                remaining_minutes = remaining // 60
                remaining_secs = remaining % 60

                # Broadcast timer to frontend
                await self._publish_data({
                    "type": "timer",
                    "remaining_seconds": remaining,
                    "total_seconds": total_seconds,
                    "remaining_display": f"{int(remaining_minutes):02d}:{int(remaining_secs):02d}",
                })

                # Warn at 5 minutes remaining
                if remaining == 300:
                    warn_msg = "Just a heads up — we have about 5 minutes remaining."
                    await self._say_with_live_transcript(warn_msg, allow_interruptions=True)

                # Warn at 1 minute remaining
                if remaining == 60:
                    warn_msg = "We have about 1 minute left. Let's wrap up."
                    await self._say_with_live_transcript(warn_msg, allow_interruptions=True)

                # Update every 30 seconds
                await asyncio.sleep(30)
                elapsed += 30

            # Time's up — force end
            logger.info("Interview time limit reached, ending interview")
            timeout_msg = "We've reached the end of our allotted time. Thank you for your answers."
            await self._say_with_live_transcript(timeout_msg, allow_interruptions=False)
            await self._end_interview()

        except asyncio.CancelledError:
            pass  # interview ended normally before time limit

    def _cancel_interview_timer(self):
        """Cancel the interview time limit"""
        if self._interview_timer and not self._interview_timer.done():
            self._interview_timer.cancel()
        self._interview_timer = None

    async def _end_interview(self):
        """End the interview"""
        self._cancel_answer_timer()
        self._cancel_interview_timer()
        closing = self.session.get_closing_message()
        await self._say_with_live_transcript(closing, allow_interruptions=False)

        self.session.end_interview()
        self.session.persist_answers(self.ctx.room.name)

        # Tell frontend to generate report before we disconnect
        await self._publish_data({"type": "interview_end"})

        await asyncio.sleep(2)

        if self.agent_session:
            await self.agent_session.aclose()
            self.agent_session = None
            self.hedra_avatar = None

        self._done_event.set()

        logger.info("Interview completed")

    # ──────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────

    async def run(self):
        """Run the interview agent"""
        try:
            await self.setup()

            # Listen for STT events
            def on_user_input_transcribed(event: agents.UserInputTranscribedEvent):
                transcript = (event.transcript or "").strip()
                if not transcript:
                    return

                is_final = getattr(event, "is_final", False)

                # Send all transcripts (interim + final) to frontend for live display
                asyncio.create_task(self._send_transcript("candidate", transcript, is_final=is_final))

                # Only process final transcripts for answer logic
                if is_final:
                    asyncio.create_task(self._handle_answer(transcript))

            self.agent_session.on("user_input_transcribed", on_user_input_transcribed)

            # Also unblock if agent session closes externally (e.g. participant disconnect)
            def on_close(event: agents.CloseEvent):
                self._done_event.set()

            self.agent_session.on("close", on_close)

            # Wait until interview ends or session closes
            await self._done_event.wait()

        except Exception as e:
            logger.error(f"Error running interview agent: {e}")
            raise
        finally:
            if self.hedra_avatar:
                try:
                    await self.hedra_avatar.aclose()
                except Exception:
                    pass
                self.hedra_avatar = None
            if self.agent_session:
                await self.agent_session.aclose()


async def entrypoint(ctx: JobContext):
    """LiveKit agent entrypoint — called when a participant joins the room"""
    logger.info(f"Interview agent entrypoint called for room: {ctx.room.name}")

    try:
        logger.info(f"[{ctx.room.name}] Connecting to room...")
        await ctx.connect()
        logger.info(f"[{ctx.room.name}] Connected to room successfully")
    except Exception as e:
        logger.error(f"[{ctx.room.name}] Failed to connect to room: {e}")
        raise

    try:
        logger.info(f"[{ctx.room.name}] Waiting for participant...")
        await ctx.wait_for_participant()
        logger.info(f"[{ctx.room.name}] Participant joined")
    except Exception as e:
        logger.error(f"[{ctx.room.name}] Error waiting for participant: {e}")
        raise

    interview_id = ctx.room.name

    from agent.manager import get_interview_session

    interview_session = get_interview_session(interview_id)
    if not interview_session:
        logger.error(f"Could not load interview session for: {interview_id}")
        raise ValueError(f"Interview session not found for: {interview_id}")

    logger.info(f"Starting interview agent for: {interview_id}")

    agent = RealtimeInterviewAgent(interview_session, ctx)
    await agent.run()


if __name__ == "__main__":
    if not settings.LIVEKIT_URL:
        raise ValueError("LIVEKIT_URL is required. Set it in your .env file.")
    if not settings.LIVEKIT_API_KEY:
        raise ValueError("LIVEKIT_API_KEY is required. Set it in your .env file.")
    if not settings.LIVEKIT_API_SECRET:
        raise ValueError("LIVEKIT_API_SECRET is required. Set it in your .env file.")

    if not os.getenv("LIVEKIT_URL"):
        os.environ["LIVEKIT_URL"] = settings.LIVEKIT_URL
    if not os.getenv("LIVEKIT_API_KEY"):
        os.environ["LIVEKIT_API_KEY"] = settings.LIVEKIT_API_KEY
    if not os.getenv("LIVEKIT_API_SECRET"):
        os.environ["LIVEKIT_API_SECRET"] = settings.LIVEKIT_API_SECRET

    logger.info("LiveKit configuration loaded from settings")

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="interviewer",
            ws_url=settings.LIVEKIT_URL,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
        )
    )
