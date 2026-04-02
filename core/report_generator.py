"""
Interview Report Generation
Creates comprehensive interview reports with ratings and feedback
"""
from datetime import datetime
from typing import Dict, List, Optional
from core.answer_scoring import calculate_overall_metrics


def extract_top_items(scores: List[Dict], field: str, n: int = 3, reverse: bool = True) -> List[str]:
    """
    Extract top N items from scores based on a field
    
    Args:
        scores: List of score dictionaries
        field: Field to extract (e.g., "strengths", "weaknesses")
        n: Number of items to return
        reverse: If True, sort descending (for strengths), else ascending (for weaknesses)
        
    Returns:
        List of top N items
    """
    all_items = []
    for score in scores:
        items = score.get(field, [])
        if isinstance(items, list):
            all_items.extend(items)
        elif isinstance(items, str):
            all_items.append(items)
    
    # Count frequency
    item_counts = {}
    for item in all_items:
        item_counts[item] = item_counts.get(item, 0) + 1
    
    # Sort by frequency
    sorted_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=reverse)
    
    # Return top N
    return [item[0] for item in sorted_items[:n]]


def generate_interview_report(
    candidate_info: Dict,
    answers: List[Dict],
    scores: List[Dict],
    questions: List[Dict],
    domain_knowledge: Optional[Dict] = None,
    interview_duration_minutes: Optional[float] = None
) -> Dict:
    """
    Create comprehensive interview report with overall rating
    
    Args:
        candidate_info: Dictionary with candidate information
        answers: List of answer dictionaries
        scores: List of score dictionaries
        questions: List of question dictionaries
        domain_knowledge: Optional domain knowledge dictionary
        interview_duration_minutes: Optional interview duration
        
    Returns:
        Complete interview report dictionary
    """
    # Calculate overall metrics
    metrics = calculate_overall_metrics(scores)
    
    # Determine recommendation
    overall_score = metrics["overall_score"]
    if overall_score >= 8.0:
        recommendation = "strong_hire"
        recommendation_text = "Strong Hire - Excellent candidate, highly recommended"
    elif overall_score >= 6.0:
        recommendation = "hire"
        recommendation_text = "Hire - Good candidate, recommended"
    elif overall_score >= 4.0:
        recommendation = "review"
        recommendation_text = "Review - Consider with caution, some gaps"
    else:
        recommendation = "no_hire"
        recommendation_text = "No Hire - Significant gaps, not recommended"
    
    # Extract top strengths and weaknesses
    top_strengths = extract_top_items(scores, "strengths", n=3, reverse=True)
    top_weaknesses = extract_top_items(scores, "weaknesses", n=3, reverse=False)
    
    # Category breakdown
    category_scores = {
        "technical_accuracy": metrics["technical_accuracy_pct"],
        "communication_clarity": metrics["communication_clarity_pct"],
        "answer_depth": metrics["depth_pct"]
    }
    
    # Create detailed answer breakdown
    detailed_qa = []
    for idx, answer in enumerate(answers):
        question_idx = answer.get("question_idx", idx)
        if question_idx < len(questions):
            qa_entry = {
                "question": questions[question_idx].get("question", ""),
                "competency": questions[question_idx].get("competency", ""),
                "candidate_answer": answer.get("transcript", ""),
                "follow_up_answer": answer.get("follow_up_transcript"),
                "score": scores[idx].get("score", 0) if idx < len(scores) else 0,
                "reasoning": scores[idx].get("reasoning", "") if idx < len(scores) else "",
                "strengths": scores[idx].get("strengths", []) if idx < len(scores) else [],
                "weaknesses": scores[idx].get("weaknesses", []) if idx < len(scores) else []
            }
            detailed_qa.append(qa_entry)
    
    # Generate interviewer notes
    interviewer_notes = f"""Candidate demonstrated {metrics['technical_accuracy_pct']:.1f}% technical accuracy 
with {metrics['communication_clarity_pct']:.1f}% communication clarity. Overall score: {overall_score}/10.

Key observations:
- Technical knowledge: {'Strong' if metrics['technical_accuracy_pct'] >= 70 else 'Moderate' if metrics['technical_accuracy_pct'] >= 50 else 'Weak'}
- Communication: {'Excellent' if metrics['communication_clarity_pct'] >= 80 else 'Good' if metrics['communication_clarity_pct'] >= 60 else 'Needs improvement'}
- Answer depth: {'Deep' if metrics['depth_pct'] >= 70 else 'Moderate' if metrics['depth_pct'] >= 50 else 'Surface level'}
"""
    
    report = {
        "candidate_name": candidate_info.get("name", "Unknown"),
        "candidate_email": candidate_info.get("email", ""),
        "position": candidate_info.get("position", ""),
        "interview_date": datetime.now().isoformat(),
        "interview_duration_minutes": interview_duration_minutes,
        
        # Overall assessment
        "overall_score": overall_score,
        "recommendation": recommendation,
        "recommendation_text": recommendation_text,
        
        # Category breakdown
        "category_scores": category_scores,
        
        # Detailed feedback
        "top_strengths": top_strengths,
        "top_weaknesses": top_weaknesses,
        "areas_for_improvement": top_weaknesses,  # Alias for consistency
        
        # Interview statistics
        "total_questions": len(questions),
        "questions_answered": len(answers),
        "average_score": overall_score,
        
        # Detailed Q&A
        "detailed_qa": detailed_qa,
        
        # Interviewer notes
        "interviewer_notes": interviewer_notes,
        
        # Domain context (if provided)
        "domain_knowledge": domain_knowledge if domain_knowledge else None,
        
        # Metadata
        "report_generated_at": datetime.now().isoformat(),
        "scoring_model": "gemini-2.5-pro"
    }
    
    return report


def format_report_for_display(report: Dict) -> str:
    """
    Format report as human-readable text
    
    Args:
        report: Interview report dictionary
        
    Returns:
        Formatted text string
    """
    lines = [
        "=" * 80,
        "TECHNICAL INTERVIEW REPORT",
        "=" * 80,
        "",
        f"Candidate: {report['candidate_name']}",
        f"Position: {report['position']}",
        f"Interview Date: {report['interview_date']}",
        f"Duration: {report.get('interview_duration_minutes', 'N/A')} minutes",
        "",
        "=" * 80,
        "OVERALL ASSESSMENT",
        "=" * 80,
        f"Overall Score: {report['overall_score']}/10",
        f"Recommendation: {report['recommendation_text']}",
        "",
        "Category Breakdown:",
        f"  - Technical Accuracy: {report['category_scores']['technical_accuracy']}%",
        f"  - Communication Clarity: {report['category_scores']['communication_clarity']}%",
        f"  - Answer Depth: {report['category_scores']['answer_depth']}%",
        "",
        "=" * 80,
        "TOP STRENGTHS",
        "=" * 80,
    ]
    
    for strength in report['top_strengths']:
        lines.append(f"  • {strength}")
    
    lines.extend([
        "",
        "=" * 80,
        "AREAS FOR IMPROVEMENT",
        "=" * 80,
    ])
    
    for weakness in report['top_weaknesses']:
        lines.append(f"  • {weakness}")
    
    lines.extend([
        "",
        "=" * 80,
        "INTERVIEWER NOTES",
        "=" * 80,
        report['interviewer_notes'],
        ""
    ])
    
    return "\n".join(lines)

