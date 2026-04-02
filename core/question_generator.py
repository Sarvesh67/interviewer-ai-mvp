"""
Technical Question Generation
Uses Gemini to generate contextual technical questions based on domain knowledge
"""
import json
import logging
import re
import google.generativeai as genai
from config import settings
from typing import Dict, List, Optional
from core.domain_extraction import get_technical_expertise_summary

logger = logging.getLogger("question_generator")


def generate_technical_questions(
    domain_knowledge: Dict,
    difficulty_level: str = "intermediate",
    num_questions: Optional[int] = None
) -> List[Dict]:
    """
    Generate domain-specific technical interview questions in a single Gemini call.

    Returns:
        List of question dicts with question, competency, expected_competencies,
        scoring_rubric, good_answer_example, red_flags, question_type fields.
    """
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured. Please set it in .env file")

    if num_questions is None:
        num_questions = {
            "junior": 4,
            "intermediate": 6,
            "senior": 8
        }.get(difficulty_level, 6)

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.GEMINI_MODEL)

    expertise_summary = get_technical_expertise_summary(domain_knowledge)

    question_types = ["Design/Architecture", "Implementation/Code", "Problem-solving scenario", "Domain-specific expertise"]
    type_distribution = [question_types[i % 4] for i in range(num_questions)]

    prompt = f"""Generate exactly {num_questions} technical interview questions for a {difficulty_level}-level candidate.

Domain Knowledge:
{json.dumps(domain_knowledge, indent=2)}

Technical Expertise: {expertise_summary}

Question type distribution (in order): {type_distribution}

Return a JSON array of exactly {num_questions} objects. Each object must have:
{{
    "question": "Clear, specific question text",
    "competency": "Main competency being tested",
    "expected_competencies": ["list", "of", "competencies"],
    "scoring_rubric": {{
        "9-10": "Excellent - deep understanding, perfect execution",
        "7-8": "Good - solid understanding, minor gaps",
        "5-6": "Adequate - basic understanding, some gaps",
        "3-4": "Poor - significant gaps, confused concepts",
        "0-2": "Very Poor - incorrect or no understanding"
    }},
    "good_answer_example": "What a strong answer would include",
    "red_flags": ["common mistake 1", "misconception 2"],
    "question_type": "design|implementation|scenario|expertise"
}}

Return ONLY the JSON array, no markdown, no explanation."""

    generation_config = {
        "temperature": 0.7,
        "max_output_tokens": 8192,
    }

    try:
        response = model.generate_content(prompt, generation_config=generation_config)

        is_complete, reason = is_response_complete(response)
        if not is_complete:
            logger.warning(f"Question generation response incomplete: {reason}")
            if reason != "Response truncated - hit token limit":
                raise RuntimeError(f"Gemini response incomplete: {reason}")

        response_text = robust_parse_json(response.text.strip())
        all_questions = json.loads(response_text)

        if isinstance(all_questions, dict):
            all_questions = [all_questions]

        for idx, q in enumerate(all_questions):
            if "question" not in q:
                raise ValueError(f"Question {idx} missing 'question' field")
            q["question_index"] = idx

        return all_questions

    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse questions JSON: {e}\nResponse: {response_text}")
    except Exception as e:
        raise RuntimeError(f"Error generating questions: {e}")


def validate_questions(all_questions: List[Dict]) -> bool:
    required_fields = ["question", "competency", "expected_competencies", "scoring_rubric"]
    for idx, q in enumerate(all_questions):
        for field in required_fields:
            if field not in q:
                raise ValueError(f"Question {idx} missing required field: {field}")
    return True


def robust_parse_json(response_text):
    """Handles nested code blocks, partial JSON, and markdown"""
    response_text = response_text.strip()

    json_match = re.search(r'```json\s*(\{.*?\}|\[.*?\])\s*```', response_text, re.DOTALL)
    if json_match:
        response_text = json_match.group(1)
    else:
        response_text = re.sub(r'```[^\`]*```', '', response_text)

    json_start = response_text.find('[')
    if json_start == -1:
        json_start = response_text.find('{')

    if json_start != -1:
        brace_count = 0
        bracket_count = 0 if json_start == response_text.find('[') else 1

        for i, char in enumerate(response_text[json_start:], json_start):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
            elif char == '[':
                bracket_count += 1
            elif char == ']':
                bracket_count -= 1

            if brace_count == 0 and bracket_count == 0:
                response_text = response_text[json_start:i+1]
                break

    response_text = re.sub(r'^\s*[\[\{]\s*', '[', response_text)
    response_text = re.sub(r'\s*[\]\}]\s*$', ']', response_text)

    return response_text


def is_response_complete(response) -> tuple[bool, str]:
    if not hasattr(response, 'candidates') or not response.candidates:
        return False, "No candidates in response"

    candidate = response.candidates[0]
    finish_reason = getattr(candidate, 'finish_reason', None)

    if finish_reason is None:
        return False, "No finish_reason in response"

    if finish_reason == 1:
        if hasattr(candidate, 'content') and candidate.content:
            return True, "Response completed normally"
        return False, "Response marked STOP but no content"
    elif finish_reason == 2:
        return False, "Response truncated - hit token limit"
    elif finish_reason == 3:
        return False, "Response blocked by safety filters"
    elif finish_reason == 4:
        return False, "Response blocked - potential recitation detected"
    elif finish_reason == 5:
        return False, "Response stopped for unknown reason"
    else:
        return False, f"Unknown finish_reason: {finish_reason}"
