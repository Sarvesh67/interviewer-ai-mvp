import pdfplumber
from docx import Document
import re

COMMON_SKILLS = [
    "python", "sql", "machine learning", "data science",
    "product management", "analytics", "ai", "deep learning",
    "react", "node", "fastapi", "aws"
]

def parse_pdf(path: str) -> str:
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text


def parse_docx(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


def extract_skills(text: str):
    text_lower = text.lower()
    found = []
    for skill in COMMON_SKILLS:
        if skill in text_lower:
            found.append(skill)
    return list(set(found))


def ats_score(text: str):
    skills = extract_skills(text)
    score = min(100, len(skills) * 10)
    return score, skills
