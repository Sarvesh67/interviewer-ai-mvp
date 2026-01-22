"""
Technical Question Generation
Uses Gemini to generate contextual technical questions based on domain knowledge
"""
import json
import google.generativeai as genai
from config import settings
from typing import Dict, List, Optional
from domain_extraction import get_technical_expertise_summary
import re

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
            "junior": 4,
            "intermediate": 6,
            "senior": 8
        }.get(difficulty_level, 12)
    
    # Configure Gemini
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    
    expertise_summary = get_technical_expertise_summary(domain_knowledge)

    
    try:
        all_questions = []

        for num in range(num_questions):
            question_type = ["Design/Architecture questions", "Implementation/Code questions", "Problem-solving scenario questions", "Domain-specific expertise questions"][num % 4]
            question_num = num + 1

            prompt = f"""
                Create 1 technical interview questions for a {difficulty_level} level candidate.
                
                Domain Knowledge:
                {json.dumps(domain_knowledge, indent=2)}
                
                Type of question: {question_type}[{question_num}]

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
                
                Return as a JSON array of question objects. Be specific and relevant to the domain.
                """

            # Add generation config with proper token limit
            generation_config = {
                "temperature": 0.7,
                "max_output_tokens": 8192,  # Enough for 1 detailed question
            }    
            response = model.generate_content(prompt, generation_config=generation_config)
            response.candidates[0].finish_reason
            # Check if response is complete
            is_complete, reason = is_response_complete(response)

            if not is_complete:
                print(f"⚠️ Warning: Question {question_num} response incomplete: {reason}")
                
                if reason == "Response truncated - hit token limit":
                    # Try to fix incomplete JSON
                    response_text = response.text.strip()
                    # ... your JSON fixing logic ...
                elif reason == "Response blocked by safety filters":
                    # Skip this question
                    continue
                else:
                    # Retry or skip
                    print(f"Skipping question {question_num}")
                    continue

            # Extract JSON from response
            response_text = response.text.strip()

            print(f"Response text for question {question_num}: {response_text}")
                        
            # # Try to parse JSON (might be wrapped in markdown code blocks)
            response_text = robust_parse_json(response_text)
            # if "```json" in response_text:
            #     response_text = response_text.split("```json")[1].split("```")[0].strip()
            # elif "```" in response_text:
            #     response_text = response_text.split("```")[1].split("```")[0].strip()

            print(f"After parsing JSON: Response text for question {question_num}: {response_text}")  
            
            questions = json.loads(response_text)
            all_questions.extend(questions)
        
        # Ensure it's a list
        if isinstance(all_questions, dict):
            all_questions = [all_questions]
        
        # Validate and add question index
        for idx, q in enumerate(all_questions):
            if "question" not in q:
                raise ValueError(f"Question {idx} missing 'question' field")
            q["question_index"] = idx
        
    
    except Exception as e:
        raise RuntimeError(f"Error generating questions: {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse questions JSON: {e}\nResponse: {response_text}")    
    return all_questions    


def validate_questions(all_questions: List[Dict]) -> bool:
    """
    Validate that questions have all required fields
    
    Args:
        questions: List of question dictionaries
        
    Returns:
        True if valid, raises ValueError if invalid
    """
    required_fields = ["question", "competency", "expected_competencies", "scoring_rubric"]
    
    for idx, q in enumerate(all_questions):
        for field in required_fields:
            if field not in q:
                raise ValueError(f"Question {idx} missing required field: {field}")
    
    return True

import re
import json

def robust_parse_json(response_text):
    """Handles nested code blocks, partial JSON, and markdown"""
    response_text = response_text.strip()
    
    # Method 1: Regex extract largest JSON block
    json_match = re.search(r'```json\s*(\{.*?\}|\[.*?\])\s*```', response_text, re.DOTALL)
    if json_match:
        response_text = json_match.group(1)
    else:
        # Method 2: Remove ALL markdown code blocks first
        response_text = re.sub(r'```[^\`]*```', '', response_text)
    
    # Method 3: Extract JSON-like content between outermost [ ] or { }
    json_start = response_text.find('[')
    if json_start == -1:
        json_start = response_text.find('{')
    
    if json_start != -1:
        # Find matching closing bracket
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
    
    # Final cleanup
    response_text = re.sub(r'^\s*[\[\{]\s*', '[', response_text)  # Ensure starts with array/object
    response_text = re.sub(r'\s*[\]\}]\s*$', ']', response_text)  # Ensure ends with array/object
    
    return response_text

# Comprehensive check to confirm response is complete
def is_response_complete(response) -> tuple[bool, str]:
    """
    Check if Gemini response is complete
    
    Returns:
        (is_complete: bool, reason: str)
    """
    if not hasattr(response, 'candidates') or not response.candidates:
        return False, "No candidates in response"
    
    candidate = response.candidates[0]
    
    # Check finish_reason
    finish_reason = getattr(candidate, 'finish_reason', None)
    
    if finish_reason is None:
        return False, "No finish_reason in response"
    
    # Check all possible finish reasons
    if finish_reason == 1:
        # Normal completion - check if content exists
        if hasattr(candidate, 'content') and candidate.content:
            return True, "Response completed normally"
        else:
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

