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


def extract_domain_from_resume(
    resume_text: str,
    target_field: str,
) -> Dict:
    """
    Build a domain_knowledge dict for a fresher/entry-level candidate by
    combining their resume text with a chosen career field.

    The output shape matches ``extract_domain_knowledge`` so downstream code
    (question generation, scoring) doesn't have to branch. An extra key
    ``resume_helpful`` is included so callers know whether the resume had
    enough signal to influence the questions. When the resume is sparse or
    missing, the LLM is instructed to fall back to generic entry-level
    expectations for ``target_field``.

    Args:
        resume_text: Extracted PDF text (may be empty).
        target_field: User-selected career field (e.g. "Web Development").
                      Must be non-empty — this is always used as the anchor.
    """
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured. Please set it in .env file")
    if not target_field or not target_field.strip():
        raise ValueError("target_field is required for resume-based extraction.")

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.GEMINI_MODEL)

    # Hard cap resume context to keep the prompt reasonable.
    trimmed_resume = (resume_text or "").strip()[:12000]
    resume_block = trimmed_resume if trimmed_resume else "(no resume text extracted)"

    prompt = f"""
    You are profiling a college student / recent graduate for an ENTRY-LEVEL
    interview. They have little to no professional experience.

    Target career field (ALWAYS the primary anchor): {target_field}

    Resume text (may be short, sparse, or empty):
    ---
    {resume_block}
    ---

    Produce a JSON object describing the candidate profile for the interviewer.
    Prioritize fundamentals of the target field. If the resume is informative,
    lean on its concrete skills/projects. If the resume is missing or sparse,
    generate a reasonable generic entry-level profile for the target field.

    Schema:
    {{
        "required_skills": [
            {{"skill": "<skill>", "level": "beginner|intermediate", "importance": "high|medium"}}
        ],
        "domain_areas": ["<area 1>", "<area 2>"],
        "technologies": ["<tech 1>", "<tech 2>"],
        "problem_domains": ["<entry-level problem type>"],
        "soft_skills": ["Communication", "Willingness to learn"],
        "job_title": "Entry-level <role> in {target_field}",
        "experience_level": "junior",
        "key_responsibilities": ["<what a junior in this field does>"],
        "resume_helpful": true | false,
        "resume_summary": "<one-sentence summary of the candidate, or 'Resume did not provide enough detail.'>",
        "candidate_highlights": ["<concrete skill, project, or course from resume if any>"]
    }}

    Set "resume_helpful" to false if the resume text is missing, unreadable,
    or contains fewer than two concrete technical skills or projects. When
    false, "candidate_highlights" may be an empty array. Return ONLY the JSON
    object — no markdown, no prose.
    """

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()

        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        domain_knowledge = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse resume domain JSON: {e}\nResponse: {response_text}")
    except Exception as e:
        raise RuntimeError(f"Error extracting domain from resume: {e}")

    # Defensive defaults — downstream code expects these keys.
    domain_knowledge.setdefault("required_skills", [])
    domain_knowledge.setdefault("domain_areas", [target_field])
    domain_knowledge.setdefault("technologies", [])
    domain_knowledge.setdefault("problem_domains", [])
    domain_knowledge.setdefault("soft_skills", ["Communication", "Willingness to learn"])
    domain_knowledge.setdefault("experience_level", "junior")
    domain_knowledge.setdefault("resume_helpful", False)
    domain_knowledge.setdefault("resume_summary", "")
    domain_knowledge.setdefault("candidate_highlights", [])
    domain_knowledge["target_field"] = target_field
    return domain_knowledge


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

