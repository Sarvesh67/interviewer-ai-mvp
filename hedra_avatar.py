"""
Hedra Avatar Creation and Management
Handles avatar creation, persona setup, and session management
"""
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

import requests
from config import settings
from requests import Response
from utils.constants import HEDRA_RESPONSE_ID_KEY

logger = logging.getLogger("hedra_avatar")


def _default_avatar_image_path() -> str:
    """
    Default avatar image bundled with the repo.

    We keep this in code (instead of relying on cwd) so it works regardless of where the
    process is launched from.
    """
    repo_root = Path(__file__).resolve().parent
    return str(repo_root / "frontend" / "assets" / "avatar.png")


def _safe_json(response: Response) -> Dict[str, Any]:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def create_hedra_image_avatar(
    job_title: str,
    technical_expertise: str,
    avatar_image_path: Optional[str] = None
) -> Optional[str]:
    """
    Create or select a Hedra avatar.

    NOTE: Hedra's public APIs for avatar creation may vary by account/plan and can change.
    The LiveKit Hedra plugin can work with either:
    - a valid Hedra avatar UUID (avatar_id), OR
    - a local PIL Image passed as avatar_image.

    In this repository we treat avatar creation as best-effort. If we cannot create an
    avatar UUID reliably, we return None and let the agent fall back to avatar_image.
    
    Args:
        job_title: Job title for the position
        technical_expertise: Technical expertise summary
        avatar_image_path: Optional path to avatar image (if None, uses default)
        
    Returns:
        avatar_id: Hedra avatar UUID if available, else None.
    """
    if not settings.HEDRA_API_KEY:
        raise ValueError("HEDRA_API_KEY is not configured. Please set it in .env file")
    
    api_key = settings.HEDRA_API_KEY
    base_url = settings.HEDRA_API_URL
    
    # Prefer caller-provided image; otherwise use the bundled default.
    image_path = avatar_image_path or _default_avatar_image_path()
    if not os.path.exists(image_path):
        logger.warning(f"Avatar image not found at {image_path}; cannot create Hedra avatar_id")
        return None

    # Hedra Create Asset requires JSON body with required fields `name` and `type`.
    # Ref: https://www.hedra.com/docs/api-reference/public/create-asset?playground=open
    request_body = {"name": "technical-interviewer", "type": "image"}
    # Step 1: Create asset
    asset_response = requests.post(
        f"{base_url}/assets",
        headers={"X-API-Key": api_key},
        json=request_body,
        timeout=30,
    )
    asset_response.raise_for_status()
    asset_payload = _safe_json(asset_response)
    asset_id = asset_payload.get(HEDRA_RESPONSE_ID_KEY)
    if not asset_id:
        raise ValueError(
            "Hedra asset creation succeeded but response did not include an id field "
            f"({HEDRA_RESPONSE_ID_KEY!r}"
        )

    # Step 2: Upload image into asset
    with open(image_path, "rb") as f:
        upload_response = requests.post(
            f"{base_url}/assets/{asset_id}/upload",
            headers={"X-API-Key": api_key},
            files={"file": f},
            timeout=60,
        )
    upload_response.raise_for_status()

    return str(asset_id)


def create_interviewer_persona(
    job_title: str,
    technical_expertise: str,
    questions: Optional[list] = None
) -> str:
    """
    Create system prompt for Hedra avatar to act as expert interviewer
    
    Args:
        job_title: Job title for the position
        technical_expertise: Technical expertise summary
        questions: Optional list of questions (for context)
        
    Returns:
        Persona prompt string
    """
    expertise_context = ""
    if questions:
        competencies = [q.get("competency", "") for q in questions[:5] if isinstance(q, dict)]
        expertise_context = "\n".join([f"- {c}" for c in competencies if c])
    
    persona = f"""You are an expert technical interviewer for the role of {job_title}.

TECHNICAL EXPERTISE:
{technical_expertise}

{f'KEY COMPETENCIES TO ASSESS:\n{expertise_context}' if expertise_context else ''}

YOUR ROLE:
1. Conduct structured technical interviews
2. Ask clarifying follow-up questions when answers are unclear
3. Evaluate answers based on depth, correctness, and approach
4. Be encouraging but fair and objective
5. Assess both technical knowledge and communication ability

INTERVIEW STYLE:
- Start with easier questions, progress to harder ones
- Give context before each question when helpful
- Listen actively and ask follow-ups on unclear or incomplete answers
- Provide brief positive feedback on strengths
- Suggest areas for improvement if answer is weak (but don't be harsh)

SCORING RUBRIC (0-10 scale):
- 9-10: Excellent - deep understanding, perfect execution, considers edge cases
- 7-8: Good - solid understanding, minor gaps, mostly correct approach
- 5-6: Adequate - basic understanding, some gaps, partially correct
- 3-4: Poor - significant gaps, confused concepts, incorrect approach
- 0-2: Very Poor - incorrect or no understanding, major misconceptions

IMPORTANT GUIDELINES:
- Do NOT reveal all evaluation criteria upfront (keep it natural)
- Make it feel like a natural conversation, not an interrogation
- Be warm and professional
- Encourage detailed explanations ("Can you tell me more about...")
- Ask "why" and "how" questions to understand reasoning
- Listen for how candidate thinks, not just what they know
- If an answer is too short (< 30 words), ask for elaboration
- If an answer shows misunderstanding, gently probe to clarify

CONVERSATION FLOW:
1. Welcome candidate warmly
2. Explain the interview format briefly
3. Ask questions one at a time
4. Listen to full answer before responding
5. Ask follow-ups if needed (max 2 per question)
6. Move to next question after adequate response
7. Thank candidate at the end
"""
    
    return persona


def get_avatar_info(avatar_id: str) -> Dict:
    """
    Get information about an existing avatar
    
    Args:
        avatar_id: Hedra avatar identifier
        
    Returns:
        Avatar information dictionary
    """
    if not settings.HEDRA_API_KEY:
        raise ValueError("HEDRA_API_KEY is not configured")
    
    try:
        response = requests.get(
            f"{settings.HEDRA_API_URL}/avatars/{avatar_id}",
            headers={"X-API-Key": settings.HEDRA_API_KEY}
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise RuntimeError(f"Error fetching avatar info: {e}")

