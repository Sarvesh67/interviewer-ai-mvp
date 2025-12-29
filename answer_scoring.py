"""
Answer Scoring and Evaluation
Uses Claude to evaluate candidate answers with detailed reasoning
"""
import json
from anthropic import Anthropic
from config import settings
from typing import Dict, List, Optional


def score_candidate_answer(
    question: Dict,
    candidate_answer: str,
    follow_up_answer: Optional[str] = None
) -> Dict:
    """
    Score a single candidate answer using Claude
    
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
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not configured. Please set it in .env file")
    
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    
    # Combine main answer and follow-up if available
    full_answer = candidate_answer
    if follow_up_answer:
        full_answer = f"{candidate_answer}\n\nFollow-up: {follow_up_answer}"
    
    scoring_prompt = f"""Evaluate this candidate's answer to a technical interview question.

QUESTION:
{question.get('question', 'N/A')}

CANDIDATE ANSWER:
{full_answer}

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
"""
    
    try:
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": scoring_prompt
            }]
        )
        
        # Extract JSON from response
        response_text = response.content[0].text.strip()
        
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
        
        score = score_candidate_answer(
            question=question,
            candidate_answer=candidate_answer,
            follow_up_answer=follow_up
        )
        
        # Add metadata
        score["question_idx"] = question_idx
        score["question"] = question.get("question", "")
        
        scores.append(score)
    
    return scores


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

