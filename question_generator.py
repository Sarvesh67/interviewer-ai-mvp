"""
Technical Question Generation
Uses Gemini to generate contextual technical questions based on domain knowledge
"""
import json
import google.generativeai as genai
from config import settings
from typing import Dict, List, Optional
from domain_extraction import get_technical_expertise_summary


def generate_technical_questions(
    domain_knowledge: Dict,
    difficulty_level: str = "intermediate",
    num_questions: Optional[int] = None
) -> List[Dict]:
    """
    Generate domain-specific technical interview questions
    
    Args:
        domain_knowledge: Extracted domain knowledge from job description
        difficulty_level: "junior", "intermediate", or "senior"
        num_questions: Number of questions to generate (default based on difficulty)
        
    Returns:
        List of question dictionaries with:
        - question: Question text
        - competency: What is being tested
        - expected_competencies: List of competencies
        - scoring_rubric: 0-10 scale criteria
        - good_answer_example: Sample good answer
        - red_flags: Wrong approaches/misconceptions
        - question_type: "design", "implementation", "scenario", "expertise"
    """
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured. Please set it in .env file")
    
    # Determine number of questions based on difficulty
    if num_questions is None:
        num_questions = {
            "junior": 10,
            "intermediate": 12,
            "senior": 15
        }.get(difficulty_level, 12)
    
    # Configure Gemini
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    
    expertise_summary = get_technical_expertise_summary(domain_knowledge)
    
    prompt = f"""
    Create {num_questions} technical interview questions for a {difficulty_level} level candidate.
    
    Domain Knowledge:
    {json.dumps(domain_knowledge, indent=2)}
    
    Technical Expertise: {expertise_summary}
    
    For EACH question, provide a JSON object with:
    {{
        "question": "Clear, specific question text",
        "competency": "Main competency being tested (e.g., 'System Design', 'API Architecture')",
        "expected_competencies": ["List", "of", "competencies"],
        "scoring_rubric": {{
            "9-10": "Excellent - deep understanding, perfect execution",
            "7-8": "Good - solid understanding, minor gaps",
            "5-6": "Adequate - basic understanding, some gaps",
            "3-4": "Poor - significant gaps, confused concepts",
            "0-2": "Very Poor - incorrect or no understanding"
        }},
        "good_answer_example": "What a strong answer would include",
        "red_flags": ["Common mistakes", "Misconceptions to watch for"],
        "question_type": "design|implementation|scenario|expertise"
    }}
    
    Question Distribution:
    - {num_questions // 3} Design/Architecture questions
    - {num_questions // 3} Implementation/Code questions
    - {num_questions // 4} Problem-solving scenario questions
    - {num_questions // 4} Domain-specific expertise questions
    
    Return as a JSON array of question objects. Be specific and relevant to the domain.
    """
    
    try:
        response = model.generate_content(prompt)
        
        # Extract JSON from response
        response_text = response.text.strip()
        
        # Try to parse JSON (might be wrapped in markdown code blocks)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        questions = json.loads(response_text)
        
        # Ensure it's a list
        if isinstance(questions, dict):
            questions = [questions]
        
        # Validate and add question index
        for idx, q in enumerate(questions):
            if "question" not in q:
                raise ValueError(f"Question {idx} missing 'question' field")
            q["question_index"] = idx
        
        return questions
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse questions JSON: {e}\nResponse: {response_text}")
    except Exception as e:
        raise RuntimeError(f"Error generating questions: {e}")


def validate_questions(questions: List[Dict]) -> bool:
    """
    Validate that questions have all required fields
    
    Args:
        questions: List of question dictionaries
        
    Returns:
        True if valid, raises ValueError if invalid
    """
    required_fields = ["question", "competency", "expected_competencies", "scoring_rubric"]
    
    for idx, q in enumerate(questions):
        for field in required_fields:
            if field not in q:
                raise ValueError(f"Question {idx} missing required field: {field}")
    
    return True

