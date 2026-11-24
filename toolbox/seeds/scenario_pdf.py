"""Produce a readable PDF with no live customer data."""

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas


def scenario_pdf(title: str, *, copies: int = 1) -> bytes:
    output = BytesIO()
    document = Canvas(output, pagesize=A4, invariant=True)
    document.setTitle(title)
    document.setAuthor("Rubrica staging")
    for page in range(1, copies + 1):
        document.setFont("Helvetica-Bold", 18)
        document.drawString(44, 785, title)
        document.setFont("Helvetica", 11)
        document.drawString(44, 754, "Documento fictício para validação em staging.")
        document.drawString(44, 731, f"Página {page} de {copies}")
        document.showPage()
    document.save()
    return output.getvalue()
