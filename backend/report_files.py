"""Private file storage and immutable screening-PDF generation."""
import hashlib
import json
import os
import uuid
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape


def private_storage_root():
    root = Path(os.getenv("GLUCOVISION_PRIVATE_STORAGE_DIR", "./private_storage")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_private_file(relative_path, content):
    root = private_storage_root()
    destination = (root / relative_path).resolve()
    if root not in destination.parents:
        raise ValueError("Private file path is outside the configured storage directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return relative_path.replace("\\", "/")


def resolve_private_file(relative_path):
    if not relative_path:
        return None
    root = private_storage_root()
    candidate = (root / relative_path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def sha256_bytes(content):
    return hashlib.sha256(content).hexdigest()


def generate_original_screening_pdf(patient, centre, screening, image_path=None, heatmap_path=None):
    """Create the report PDF once, from the saved AI result, before clinical review."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title=f"GlucoVision Screening Report {screening.id}")
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], alignment=TA_CENTER,
        textColor=colors.HexColor("#1d4ed8"), fontSize=17, leading=21)
    heading_style = ParagraphStyle("SectionHeading", parent=styles["Heading2"],
        textColor=colors.HexColor("#1e3a8a"), spaceBefore=8, spaceAfter=6)
    body = styles["BodyText"]
    safe = lambda value: escape(str(value if value is not None else "—"))
    content = [Paragraph("GlucoVision", title_style),
        Paragraph("AI-Assisted Diabetic Retinopathy Screening Report", styles["Heading2"]),
        Paragraph(f"Report #{screening.id} · Screening date: {safe(screening.created_at)}", body),
        Spacer(1, 6 * mm), Paragraph("Patient and referral", heading_style)]
    info = [
        ["Patient name", safe(patient.name)], ["Patient ID", safe(patient.patient_code)],
        ["Age", safe(patient.age)], ["Sex", safe(patient.sex)],
        ["Originating health centre", safe(centre.name if centre else None)],
    ]
    table = Table(info, colWidths=[48 * mm, 120 * mm])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eff6ff")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("PADDING", (0, 0), (-1, -1), 7)]))
    content.extend([table, Paragraph("Original AI screening result", heading_style),
        Paragraph(f"Predicted severity: <b>{safe(screening.prediction)}</b>", body),
        Paragraph(f"Model confidence score: {safe(screening.confidence)}", body),
        Paragraph("Class scores stored by the model (not a doctor's assessment):", body)])
    scores = [["Class", "Stored score"]]
    stored_scores = screening.probabilities or {}
    if isinstance(stored_scores, str):
        try:
            stored_scores = json.loads(stored_scores)
        except (TypeError, ValueError):
            stored_scores = {}
    for name, score in stored_scores.items() if isinstance(stored_scores, dict) else []:
        scores.append([safe(name), safe(score)])
    score_table = Table(scores, colWidths=[84 * mm, 84 * mm], repeatRows=1)
    score_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("PADDING", (0, 0), (-1, -1), 7)]))
    content.extend([score_table, Paragraph("Original retinal image", heading_style)])
    for path, caption in ((image_path, "Retinal image submitted for analysis"),
                          (heatmap_path, "Grad-CAM model explanation")):
        if path and Path(path).is_file():
            content.extend([Paragraph(caption, body), Image(str(path), width=150 * mm, height=82 * mm, kind="proportional"), Spacer(1, 3 * mm)])
    content.extend([Spacer(1, 5 * mm), Paragraph(
        "This AI-assisted screening report supports triage and is not a definitive medical diagnosis. "
        "Clinical decisions should be made by qualified healthcare professionals.", styles["Italic"])])
    document.build(content)
    return output.getvalue()
