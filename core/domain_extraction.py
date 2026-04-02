"""
Domain Knowledge Extraction from Job Descriptions
Uses Gemini to extract technical requirements and domain expertise
"""
import json
import google.generativeai as genai
from config import settings
from typing import Dict, List, Optional


def extract_domain_knowledge(job_description: str) -> Dict:
    """
    Extract technical requirements and domain knowledge from job description
    
    Args:
        job_description: Full job description text
        
    Returns:
        Dictionary with extracted domain knowledge including:
        - required_skills: List of skills with proficiency levels
        - domain_areas: Core competency areas
        - technologies: Specific tools/frameworks
        - problem_domains: Areas where candidate will solve problems
        - soft_skills: Communication, teamwork, etc.
    """
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured. Please set it in .env file")
    
    # Configure Gemini
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    
    prompt = f"""
    Analyze this job description and extract technical requirements and domain knowledge.
    
    Job Description:
    {job_description}
    
    Extract and format as JSON with the following structure:
    {{
        "required_skills": [
            {{"skill": "Python", "level": "expert", "importance": "high"}},
            {{"skill": "FastAPI", "level": "intermediate", "importance": "high"}}
        ],
        "domain_areas": [
            "Backend Engineering",
            "API Design",
            "System Architecture"
        ],
        "technologies": [
            "Python",
            "FastAPI",
            "PostgreSQL",
            "Redis",
            "Docker"
        ],
        "problem_domains": [
            "Scalable API design",
            "Database optimization",
            "Microservices architecture"
        ],
        "soft_skills": [
            "Communication",
            "Team collaboration",
            "Problem-solving"
        ],
        "job_title": "Extracted job title",
        "experience_level": "junior|intermediate|senior",
        "key_responsibilities": [
            "List of main responsibilities"
        ]
    }}
    
    Be specific and comprehensive. Focus on technical competencies that would be tested in an interview.
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
        
        domain_knowledge = json.loads(response_text)
        
        return domain_knowledge
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse domain knowledge JSON: {e}\nResponse: {response_text}")
    except Exception as e:
        raise RuntimeError(f"Error extracting domain knowledge: {e}")


def get_technical_expertise_summary(domain_knowledge: Dict) -> str:
    """
    Create a summary string of technical expertise for persona creation
    
    Args:
        domain_knowledge: Extracted domain knowledge dictionary
        
    Returns:
        Formatted string describing technical expertise
    """
    expertise_parts = []
    
    if domain_knowledge.get("domain_areas"):
        expertise_parts.append(f"Domain expertise in: {', '.join(domain_knowledge['domain_areas'][:3])}")
    
    if domain_knowledge.get("technologies"):
        tech_list = domain_knowledge["technologies"][:5]
        expertise_parts.append(f"Technologies: {', '.join(tech_list)}")
    
    if domain_knowledge.get("required_skills"):
        top_skills = [s["skill"] for s in domain_knowledge["required_skills"][:3]]
        expertise_parts.append(f"Key skills: {', '.join(top_skills)}")
    
    return ". ".join(expertise_parts) if expertise_parts else "Technical expert"

