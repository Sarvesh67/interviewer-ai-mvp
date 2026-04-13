"""
PDF Report Generation
Converts interview report JSON data into a professionally formatted PDF.
"""
from io import BytesIO
from datetime import datetime
from typing import Dict
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable,
)
from reportlab.lib.enums import TA_CENTER


def _esc(text) -> str:
    """Escape text for reportlab's mini-HTML parser."""
    if text is None:
        return ""
    return xml_escape(str(text))


def _score_color(score) -> HexColor:
    """Return color based on score value: green >= 7, amber >= 4, red < 4."""
    if score >= 7:
        return HexColor("#2E7D32")
    elif score >= 4:
        return HexColor("#F57F17")
    else:
        return HexColor("#C62828")


def _rec_color(rec: str) -> HexColor:
    """Return color for recommendation badge."""
    colors = {
        "strong_hire": HexColor("#2E7D32"),
        "hire": HexColor("#558B2F"),
        "review": HexColor("#F57F17"),
        "no_hire": HexColor("#C62828"),
    }
    return colors.get(rec, HexColor("#666666"))


def generate_pdf_report(report_data: Dict) -> bytes:
    """
    Generate a professionally formatted PDF from interview report data.

    Args:
        report_data: The report dictionary as produced by generate_interview_report()

    Returns:
        Raw PDF bytes
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=22, spaceAfter=4,
        textColor=HexColor("#1a1a2e"),
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"], fontSize=10,
        textColor=HexColor("#666666"), alignment=TA_CENTER, spaceAfter=16,
    )
    section_style = ParagraphStyle(
        "SectionHeader", parent=styles["Heading2"], fontSize=13,
        textColor=HexColor("#1a1a2e"), spaceBefore=16, spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=9.5, leading=13, spaceAfter=4,
    )
    small_style = ParagraphStyle(
        "Small", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=HexColor("#555555"),
    )
    bullet_style = ParagraphStyle(
        "Bullet", parent=body_style, leftIndent=18, bulletIndent=6,
        spaceBefore=2, spaceAfter=2,
    )
    qa_question_style = ParagraphStyle(
        "QAQuestion", parent=body_style, fontSize=9.5, leading=13,
        textColor=HexColor("#1a1a2e"),
    )
    qa_answer_style = ParagraphStyle(
        "QAAnswer", parent=body_style, fontSize=9, leading=12,
        textColor=HexColor("#333333"), leftIndent=12,
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=8,
        textColor=HexColor("#999999"), alignment=TA_CENTER,
    )

    elements = []

    # --- Title ---
    elements.append(Paragraph("Interview Report", title_style))
    gen_date = report_data.get("report_generated_at", "")
    try:
        dt = datetime.fromisoformat(gen_date)
        date_str = dt.strftime("%B %d, %Y")
    except (ValueError, TypeError):
        date_str = gen_date
    elements.append(Paragraph(f"Generated on {_esc(date_str)}", subtitle_style))

    # --- Candidate Info ---
    elements.append(Paragraph("Candidate Information", section_style))
    dur = report_data.get("interview_duration_minutes")
    dur_str = f"{dur:.0f} minutes" if dur else "N/A"
    interview_date = report_data.get("interview_date", "")
    try:
        idt = datetime.fromisoformat(interview_date)
        interview_date_str = idt.strftime("%B %d, %Y at %I:%M %p")
    except (ValueError, TypeError):
        interview_date_str = interview_date

    info_data = [
        ["Name", _esc(report_data.get("candidate_name", "Unknown")),
         "Position", _esc(report_data.get("position", "N/A"))],
        ["Email", _esc(report_data.get("candidate_email", "N/A")),
         "Duration", dur_str],
        ["Interview Date", interview_date_str,
         "Questions", f"{report_data.get('questions_answered', 0)} / {report_data.get('total_questions', 0)}"],
    ]
    info_table = Table(info_data, colWidths=[1.1 * inch, 2.3 * inch, 1.1 * inch, 2.3 * inch])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HexColor("#f0f0f5")),
        ("BACKGROUND", (2, 0), (2, -1), HexColor("#f0f0f5")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 12))

    # --- Overall Assessment ---
    elements.append(Paragraph("Overall Assessment", section_style))
    overall = report_data.get("overall_score", 0)
    rec = report_data.get("recommendation", "review")
    rec_text = report_data.get("recommendation_text", rec)
    rec_clr = _rec_color(rec)

    score_para = Paragraph(
        f"<b>{overall:.1f} / 10</b>",
        ParagraphStyle(
            "ScoreDisplay", parent=styles["Normal"], fontSize=20,
            fontName="Helvetica-Bold", alignment=TA_CENTER,
            textColor=HexColor("#1a1a2e"), spaceAfter=0,
        ),
    )

    rec_label = rec.replace("_", " ").upper()
    rec_badge = Paragraph(
        f'<font color="white"><b>{_esc(rec_label)}</b></font>',
        ParagraphStyle(
            "RecBadge", parent=styles["Normal"], fontSize=10,
            alignment=TA_CENTER, textColor=white,
        ),
    )

    rec_desc = Paragraph(
        f"<i>{_esc(rec_text)}</i>",
        ParagraphStyle("RecDesc", parent=small_style, alignment=TA_CENTER, spaceBefore=4),
    )

    assess_data = [[score_para, rec_badge]]
    assess_table = Table(assess_data, colWidths=[2.8 * inch, 2.0 * inch], rowHeights=[0.45 * inch])
    assess_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, 0), HexColor("#f5f5fa")),
        ("BACKGROUND", (1, 0), (1, 0), rec_clr),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#dddddd")),
        ("LINEBEFORE", (1, 0), (1, 0), 0.5, HexColor("#dddddd")),
    ]))

    outer = Table([[assess_table]], colWidths=[doc.width])
    outer.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("PADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(outer)
    elements.append(rec_desc)
    elements.append(Spacer(1, 8))

    # --- Category Scores ---
    elements.append(Paragraph("Category Scores", section_style))
    cats = report_data.get("category_scores", {})
    cat_labels = {
        "technical_accuracy": "Technical Accuracy",
        "communication_clarity": "Communication Clarity",
        "answer_depth": "Answer Depth",
    }
    bar_width = 3.0 * inch
    cat_rows = []
    for key, label in cat_labels.items():
        val = cats.get(key, 0) or 0
        color = (HexColor("#2E7D32") if val >= 70
                 else HexColor("#F57F17") if val >= 40
                 else HexColor("#C62828"))

        filled_w = max(bar_width * val / 100, 0.01 * inch)
        empty_w = bar_width - filled_w
        if val > 0:
            bar = Table([["", ""]], colWidths=[filled_w, empty_w], rowHeights=[14])
            bar.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), color),
                ("BACKGROUND", (1, 0), (1, 0), HexColor("#e8e8e8")),
                ("PADDING", (0, 0), (-1, -1), 0),
            ]))
        else:
            bar = Table([[""]], colWidths=[bar_width], rowHeights=[14])
            bar.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), HexColor("#e8e8e8")),
                ("PADDING", (0, 0), (-1, -1), 0),
            ]))

        cat_rows.append([label, bar, f"{val:.0f}%"])

    cat_table = Table(cat_rows, colWidths=[1.6 * inch, bar_width + 0.1 * inch, 0.6 * inch])
    cat_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [HexColor("#fafafa"), white]),
    ]))
    elements.append(cat_table)
    elements.append(Spacer(1, 8))

    # --- Strengths ---
    strengths = report_data.get("top_strengths", [])
    if strengths:
        elements.append(Paragraph("Top Strengths", section_style))
        for s in strengths:
            elements.append(Paragraph(f"\u2022  {_esc(s)}", bullet_style))
        elements.append(Spacer(1, 4))

    # --- Weaknesses ---
    weaknesses = report_data.get("top_weaknesses", [])
    if weaknesses:
        elements.append(Paragraph("Areas for Improvement", section_style))
        for w in weaknesses:
            elements.append(Paragraph(f"\u2022  {_esc(w)}", bullet_style))
        elements.append(Spacer(1, 4))

    # --- Detailed Q&A ---
    detailed = report_data.get("detailed_qa", [])
    if detailed:
        elements.append(Paragraph("Detailed Question &amp; Answer Breakdown", section_style))
        for i, qa in enumerate(detailed, 1):
            q_score = qa.get("score", 0)
            sc = _score_color(q_score)

            comp = _esc(qa.get("competency", ""))
            header_text = (
                f'<b>Q{i}.</b>  '
                f'<font color="#667eea"><b>[{comp}]</b></font>  '
                f'<font color="{sc.hexval()}">Score: {q_score:.1f}/10</font>'
            )
            elements.append(Paragraph(
                header_text,
                ParagraphStyle(
                    "QAHeader", parent=body_style, fontSize=10,
                    spaceBefore=10, spaceAfter=4,
                ),
            ))

            elements.append(Paragraph(
                f'<b>Question:</b> {_esc(qa.get("question", ""))}',
                qa_question_style,
            ))

            ans = qa.get("candidate_answer", "")
            if ans:
                elements.append(Paragraph(f"<b>Answer:</b> {_esc(ans)}", qa_answer_style))

            fu = qa.get("follow_up_answer")
            if fu:
                elements.append(Paragraph(f"<b>Follow-up:</b> {_esc(fu)}", qa_answer_style))

            reasoning = qa.get("reasoning", "")
            if reasoning:
                elements.append(Paragraph(
                    f"<b>Assessment:</b> <i>{_esc(reasoning)}</i>", small_style,
                ))

            q_strengths = qa.get("strengths", [])
            q_weaknesses = qa.get("weaknesses", [])
            if q_strengths:
                items = ", ".join(_esc(s) for s in q_strengths)
                elements.append(Paragraph(
                    f'<font color="#2E7D32"><b>+</b></font> {items}', small_style,
                ))
            if q_weaknesses:
                items = ", ".join(_esc(w) for w in q_weaknesses)
                elements.append(Paragraph(
                    f'<font color="#C62828"><b>\u2013</b></font> {items}', small_style,
                ))

            if i < len(detailed):
                elements.append(HRFlowable(
                    width="100%", thickness=0.5, color=HexColor("#e0e0e0"),
                    spaceAfter=4, spaceBefore=6,
                ))
    else:
        elements.append(Paragraph("Detailed Q&amp;A", section_style))
        elements.append(Paragraph("<i>No Q&amp;A data available.</i>", small_style))

    # --- Interviewer Notes ---
    notes = report_data.get("interviewer_notes", "")
    if notes:
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("Interviewer Notes", section_style))
        for line in notes.strip().split("\n"):
            elements.append(Paragraph(
                _esc(line) if line.strip() else "&nbsp;", small_style,
            ))

    # --- Footer ---
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="100%", thickness=1, color=HexColor("#cccccc"), spaceAfter=8))
    elements.append(Paragraph("Generated by AI Interviewer", footer_style))

    doc.build(elements)
    return buf.getvalue()
