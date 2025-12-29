"""
Hedra Avatar Creation and Management
Handles avatar creation, persona setup, and session management
"""
import requests
import os
from typing import Optional, Dict
from config import settings
from domain_extraction import get_technical_expertise_summary


def create_hedra_avatar(
    job_title: str,
    technical_expertise: str,
    avatar_image_path: Optional[str] = None
) -> str:
    """
    Create a Hedra avatar with technical expert persona
    
    Args:
        job_title: Job title for the position
        technical_expertise: Technical expertise summary
        avatar_image_path: Optional path to avatar image (if None, uses default)
        
    Returns:
        avatar_id: Hedra avatar identifier
    """
    if not settings.HEDRA_API_KEY:
        raise ValueError("HEDRA_API_KEY is not configured. Please set it in .env file")
    
    api_key = settings.HEDRA_API_KEY
    base_url = settings.HEDRA_API_URL
    
    # Step 1: Create asset (if image provided)
    asset_id = None
    if avatar_image_path and os.path.exists(avatar_image_path):
        try:
            # Create asset
            asset_response = requests.post(
                f"{base_url}/assets",
                headers={"X-API-Key": api_key}
            )
            asset_response.raise_for_status()
            asset_id = asset_response.json().get("asset_id")
            
            # Upload image
            with open(avatar_image_path, "rb") as f:
                upload_response = requests.post(
                    f"{base_url}/assets/{asset_id}/upload",
                    headers={"X-API-Key": api_key},
                    files={"file": f}
                )
                upload_response.raise_for_status()
        except Exception as e:
            print(f"Warning: Could not upload avatar image: {e}")
            asset_id = None
    
    # Step 2: Create avatar with persona
    # Note: Actual Hedra API endpoints may vary - adjust based on Hedra documentation
    try:
        avatar_data = {
            "name": f"Technical Interviewer - {job_title}",
            "persona": create_interviewer_persona(job_title, technical_expertise),
            "asset_id": asset_id  # If image was uploaded
        }
        
        avatar_response = requests.post(
            f"{base_url}/avatars",
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json"
            },
            json=avatar_data
        )
        avatar_response.raise_for_status()
        
        avatar_id = avatar_response.json().get("avatar_id")
        
        if not avatar_id:
            raise ValueError("Failed to get avatar_id from Hedra API response")
        
        return avatar_id
        
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error creating Hedra avatar: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error creating avatar: {e}")


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

