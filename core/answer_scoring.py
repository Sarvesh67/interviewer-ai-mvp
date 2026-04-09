"""
Answer Scoring and Evaluation
Uses Gemini to evaluate candidate answers with detailed reasoning
"""
import json
import logging
import re
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from config import settings
from typing import Dict, List, Optional

logger = logging.getLogger("answer_scoring")


def score_candidate_answer(
    question: Dict,
    candidate_answer: str,
    follow_up_answer: Optional[str] = None,
    conversation: Optional[list] = None
) -> Dict:
    """
    Score a single candidate answer using Gemini

    Args:
        question: Question dictionary with rubric and expected competencies
        candidate_answer: Transcript of candidate's answer
        follow_up_answer: Optional follow-up answer if provided

    Returns:
        Score dictionary with:
        - score: 0-10 numeric score
        - reasoning: Why this score was given
        - strengths: List of what candidate got right
        - weaknesses: List of what could be better
        - depth_level: "surface", "intermediate", or "deep"
        - communication_clarity: "poor", "fair", "good", or "excellent"
        - technical_accuracy: "incorrect", "partial", or "correct"
        - follow_up_recommended: Boolean
    """
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured. Please set it in .env file")

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.GEMINI_SCORING_MODEL)

    # Build conversation context if available, otherwise use flat answer
    if conversation and len(conversation) > 0:
        convo_lines = []
        for turn in conversation:
            role_label = "Interviewer" if turn.get("role") == "interviewer" else "Candidate"
            turn_type = turn.get("type", "")
            type_tag = f" ({turn_type})" if turn_type == "follow_up" else ""
            convo_lines.append(f"{role_label}{type_tag}: {turn.get('text', '')}")
        full_answer = "\n".join(convo_lines)
    else:
        full_answer = candidate_answer
        if follow_up_answer:
            full_answer = f"{candidate_answer}\n\nFollow-up: {follow_up_answer}"

    scoring_prompt = f"""Evaluate this candidate's answer to a technical interview question.

QUESTION:
{question.get('question', 'N/A')}

FULL CONVERSATION THREAD:
{full_answer}

Note: If follow-up questions were asked, consider whether the candidate needed prompting to give a complete answer. A candidate who gives a comprehensive first answer should score higher on communication than one who needed multiple follow-ups.

EXPECTED COMPETENCIES:
{', '.join(question.get('expected_competencies', []))}

SCORING RUBRIC:
{json.dumps(question.get('scoring_rubric', {}), indent=2)}

GOOD ANSWER EXAMPLE:
{question.get('good_answer_example', 'N/A')}

RED FLAGS TO WATCH FOR:
{', '.join(question.get('red_flags', []))}

Provide evaluation in JSON format:
{{
    "score": <0-10 integer>,
    "reasoning": "<detailed explanation of why this score was given>",
    "strengths": ["<what they got right>", "<another strength>"],
    "weaknesses": ["<what could be better>", "<another weakness>"],
    "depth_level": "<surface|intermediate|deep>",
    "communication_clarity": "<poor|fair|good|excellent>",
    "technical_accuracy": "<incorrect|partial|correct>",
    "follow_up_recommended": <true|false>,
    "follow_up_question": "<suggested follow-up if recommended, else empty string>"
}}

Be thorough and fair. Consider:
- Technical correctness
- Depth of understanding
- Communication clarity
- Problem-solving approach
- Consideration of edge cases and trade-offs

Return ONLY the JSON object, no other text.
"""

    try:
        generation_config = {
            "temperature": 0.3,  # Lower temp for consistent scoring
            "max_output_tokens": 2048,
        }
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        response = model.generate_content(
            scoring_prompt,
            generation_config=generation_config,
            safety_settings=safety_settings,
        )

        # Handle blocked responses (safety filter)
        if (not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts):
            logger.warning(f"Gemini response blocked (finish_reason: {getattr(response.candidates[0], 'finish_reason', 'unknown') if response.candidates else 'no candidates'})")
            return {
                "score": 0,
                "reasoning": "Unable to score — response was filtered. Default score assigned.",
                "strengths": [],
                "weaknesses": [],
                "depth_level": "intermediate",
                "communication_clarity": "fair",
                "technical_accuracy": "partial",
                "follow_up_recommended": False,
            }

        # Extract JSON from response
        response_text = response.text.strip()

        # Try to parse JSON (might be wrapped in markdown code blocks)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        score_data = json.loads(response_text)

        # Validate score is in range
        score_data["score"] = max(0, min(10, int(score_data.get("score", 5))))

        return score_data

    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse scoring JSON: {e}\nResponse: {response_text}")
    except Exception as e:
        raise RuntimeError(f"Error scoring answer: {e}")


def score_all_answers(
    answers: List[Dict],
    questions: List[Dict]
) -> List[Dict]:
    """
    Score all candidate answers

    Args:
        answers: List of answer dictionaries with question_idx and transcript
        questions: List of question dictionaries

    Returns:
        List of score dictionaries (one per answer)
    """
    scores = []

    for answer_obj in answers:
        question_idx = answer_obj.get("question_idx", 0)

        if question_idx >= len(questions):
            raise ValueError(f"Question index {question_idx} out of range")

        question = questions[question_idx]
        candidate_answer = answer_obj.get("transcript", "")
        follow_up = answer_obj.get("follow_up_transcript")
        conversation = answer_obj.get("conversation", [])

        # Skip scoring for skipped questions
        if answer_obj.get("skipped"):
            scores.append({
                "question_idx": question_idx,
                "question": question.get("question", ""),
                "score": 0,
                "reasoning": "Question was skipped by the candidate.",
                "strengths": [],
                "weaknesses": ["Question not attempted"],
                "depth_level": "surface",
                "communication_clarity": "poor",
                "technical_accuracy": "incorrect",
                "follow_up_recommended": False,
                "skipped": True
            })
            continue

        score = score_candidate_answer(
            question=question,
            candidate_answer=candidate_answer,
            follow_up_answer=follow_up,
            conversation=conversation
        )

        # Add metadata
        score["question_idx"] = question_idx
        score["question"] = question.get("question", "")

        scores.append(score)

    return scores


def score_all_answers_batch(
    answers: List[Dict],
    questions: List[Dict]
) -> List[Dict]:
    """
    Score all candidate answers in a single batched LLM call (or chunked if N > 15).
    Falls back to score_all_answers() per-answer if the batch call fails.

    Reduces N Gemini calls to 1 (or ceil(N/10) for large sets).
    Uses response_mime_type="application/json" + response_schema for strict output.
    """
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured. Please set it in .env file")

    results: List[Optional[Dict]] = [None] * len(answers)

    # Resolve skipped answers locally — no LLM needed
    to_score = []  # list of (result_index, answer_obj, question)
    for i, answer_obj in enumerate(answers):
        question_idx = answer_obj.get("question_idx", 0)
        if question_idx >= len(questions):
            raise ValueError(f"Question index {question_idx} out of range")
        question = questions[question_idx]

        if answer_obj.get("skipped"):
            results[i] = {
                "question_idx": question_idx,
                "question": question.get("question", ""),
                "score": 0,
                "reasoning": "Question was skipped by the candidate.",
                "strengths": [],
                "weaknesses": ["Question not attempted"],
                "depth_level": "surface",
                "communication_clarity": "poor",
                "technical_accuracy": "incorrect",
                "follow_up_recommended": False,
                "skipped": True,
            }
        else:
            to_score.append((i, answer_obj, question))

    if not to_score:
        return [r for r in results if r is not None]

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.GEMINI_SCORING_MODEL)

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    # Schema enforces exact output shape — no regex parsing needed
    response_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "score": {"type": "integer"},
                "reasoning": {"type": "string"},
                "strengths": {"type": "array", "items": {"type": "string"}},
                "weaknesses": {"type": "array", "items": {"type": "string"}},
                "depth_level": {"type": "string", "enum": ["surface", "intermediate", "deep"]},
                "communication_clarity": {"type": "string", "enum": ["poor", "fair", "good", "excellent"]},
                "technical_accuracy": {"type": "string", "enum": ["incorrect", "partial", "correct"]},
                "follow_up_recommended": {"type": "boolean"},
                "follow_up_question": {"type": "string"},
            },
            "required": [
                "score", "reasoning", "strengths", "weaknesses",
                "depth_level", "communication_clarity", "technical_accuracy",
                "follow_up_recommended",
            ],
        },
    }

    CHUNK_SIZE = 10
    for chunk_start in range(0, len(to_score), CHUNK_SIZE):
        chunk = to_score[chunk_start: chunk_start + CHUNK_SIZE]
        n = len(chunk)

        # Build batch prompt
        parts = [
            f"You are scoring {n} candidate answer(s) from a technical interview. "
            f"Return a JSON array with exactly {n} score objects in the same order as presented.\n"
        ]
        for idx, (_, answer_obj, question) in enumerate(chunk, 1):
            conversation = answer_obj.get("conversation", [])
            candidate_answer = answer_obj.get("transcript", "")
            follow_up = answer_obj.get("follow_up_transcript")

            if conversation:
                convo_lines = []
                for turn in conversation:
                    role_label = "Interviewer" if turn.get("role") == "interviewer" else "Candidate"
                    turn_type = turn.get("type", "")
                    type_tag = f" ({turn_type})" if turn_type == "follow_up" else ""
                    convo_lines.append(f"{role_label}{type_tag}: {turn.get('text', '')}")
                full_answer = "\n".join(convo_lines)
            else:
                full_answer = candidate_answer
                if follow_up:
                    full_answer = f"{candidate_answer}\n\nFollow-up: {follow_up}"

            parts.append(f"--- ANSWER {idx} ---")
            parts.append(f"QUESTION:\n{question.get('question', 'N/A')}")
            parts.append(f"FULL CONVERSATION THREAD:\n{full_answer}")
            parts.append(
                "Note: If follow-up questions were asked, consider whether the candidate needed prompting. "
                "A candidate who gives a comprehensive first answer should score higher on communication."
            )
            parts.append(f"EXPECTED COMPETENCIES:\n{', '.join(question.get('expected_competencies', []))}")
            parts.append(f"SCORING RUBRIC:\n{json.dumps(question.get('scoring_rubric', {}), indent=2)}")
            parts.append(f"GOOD ANSWER EXAMPLE:\n{question.get('good_answer_example', 'N/A')}")
            parts.append(f"RED FLAGS TO WATCH FOR:\n{', '.join(question.get('red_flags', []))}")
            parts.append("")

        parts.append(
            f"Evaluate all {n} answers. Be thorough and fair for each: consider technical correctness, "
            "depth of understanding, communication clarity, problem-solving approach, and edge cases."
        )
        batch_prompt = "\n".join(parts)

        generation_config = {
            "temperature": 0.3,
            "max_output_tokens": min(400 * n, 8192),
            "response_mime_type": "application/json",
            "response_schema": response_schema,
        }

        try:
            response = model.generate_content(
                batch_prompt,
                generation_config=generation_config,
                safety_settings=safety_settings,
            )

            if (
                not response.candidates
                or not response.candidates[0].content
                or not response.candidates[0].content.parts
            ):
                raise RuntimeError(
                    f"Batch scoring response blocked (finish_reason: "
                    f"{getattr(response.candidates[0], 'finish_reason', 'unknown') if response.candidates else 'no candidates'})"
                )

            batch_scores = json.loads(response.text)
            if not isinstance(batch_scores, list) or len(batch_scores) != n:
                raise ValueError(f"Expected {n} scores in batch response, got {len(batch_scores) if isinstance(batch_scores, list) else type(batch_scores)}")

            for (orig_idx, answer_obj, question), score_data in zip(chunk, batch_scores):
                score_data["score"] = max(0, min(10, int(score_data.get("score", 5))))
                score_data["question_idx"] = answer_obj.get("question_idx", 0)
                score_data["question"] = question.get("question", "")
                results[orig_idx] = score_data

        except Exception as e:
            logger.warning(f"Batch scoring failed for chunk (answers {chunk_start}–{chunk_start + n - 1}): {e}. Falling back to individual scoring.")
            for orig_idx, answer_obj, question in chunk:
                score = score_candidate_answer(
                    question=question,
                    candidate_answer=answer_obj.get("transcript", ""),
                    follow_up_answer=answer_obj.get("follow_up_transcript"),
                    conversation=answer_obj.get("conversation", []),
                )
                score["question_idx"] = answer_obj.get("question_idx", 0)
                score["question"] = question.get("question", "")
                results[orig_idx] = score

    return [r for r in results if r is not None]


def calculate_overall_metrics(scores: List[Dict]) -> Dict:
    """
    Calculate overall interview metrics from individual scores

    Args:
        scores: List of score dictionaries

    Returns:
        Dictionary with overall metrics
    """
    if not scores:
        return {
            "overall_score": 0.0,
            "technical_accuracy_pct": 0.0,
            "communication_clarity_pct": 0.0,
            "depth_pct": 0.0
        }

    total_score = sum(s.get("score", 0) for s in scores)
    overall_score = total_score / len(scores)

    # Calculate percentages
    technical_correct = sum(
        1 for s in scores
        if s.get("technical_accuracy") == "correct"
    )
    technical_accuracy_pct = (technical_correct / len(scores)) * 100

    communication_good = sum(
        1 for s in scores
        if s.get("communication_clarity") in ["good", "excellent"]
    )
    communication_clarity_pct = (communication_good / len(scores)) * 100

    depth_good = sum(
        1 for s in scores
        if s.get("depth_level") in ["intermediate", "deep"]
    )
    depth_pct = (depth_good / len(scores)) * 100

    return {
        "overall_score": round(overall_score, 2),
        "technical_accuracy_pct": round(technical_accuracy_pct, 1),
        "communication_clarity_pct": round(communication_clarity_pct, 1),
        "depth_pct": round(depth_pct, 1),
        "total_questions": len(scores)
    }
