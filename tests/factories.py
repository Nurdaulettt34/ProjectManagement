"""Test documents built in memory (no files on disk)."""
import io
import zipfile

CERT_LINES = [
    "CERTIFICATE OF ENROLLMENT",
    "This is to certify that Aigerim Sadykova is a full-time student of Satbayev University.",
    "Full name: Aigerim Sadykova",
    "Issued by: Registrar's Office, Satbayev University",
    "Date of issue: 15.09.2026",
    "Document number: CERT-2026-0415",
    "Purpose: for submission to the military registration office",
]

APPLICATION_LINES = [
    "APPLICATION FORM",
    "Application for academic leave",
    "Full name: Daniyar Bekov",
    "Student ID: 220103456",
    "Faculty: Information Technology",
    "Subject: academic leave for one semester",
    "Date: 01.10.2026",
    "I hereby apply for academic leave for the spring semester.",
]

RU_CERT_LINES = [
    "СПРАВКА",
    "Дана настоящая справка Иванову Ивану в том, что он является студентом 2 курса.",
    "Справка выдана для предоставления по месту требования.",
]

KZ_CERT_LINES = [
    "АНЫҚТАМА",
    "Осы анықтама Серікова Айгүлге берілді, ол университеттің 1 курс студенті.",
]

UNIDENTIFIABLE_LINES = [
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
]

LOW_CONFIDENCE_LINES = [
    "The grade for this assignment was announced to the group yesterday evening.",
]

REGULATION_LINES = [
    "Rules for transferring to another university.",
    "Students must submit the application no later than 25 August 2026.",
    "The following documents are required: a copy of the passport, an academic transcript and two photos.",
    "The application is reviewed by the Dean's Office within 10 working days.",
    "Applicants with academic debts must close them before the transfer.",
    "The decision is sent to the student by email.",
    "Contact the Registrar's Office for questions.",
]


def blurred_certificate_lines():
    """Certificate with unreadable values and a missing 'Purpose' line."""
    lines = []
    for line in CERT_LINES:
        if line.startswith("Date of issue"):
            lines.append("Date of issue: 1?.0?.20??")
        elif line.startswith("Document number"):
            lines.append("Document number: [illegible]")
        elif line.startswith("Purpose"):
            continue
        else:
            lines.append(line)
    return lines


def make_pdf(lines=("Hello, this is a test PDF document with real text.",)):
    """Real PDF with Unicode text (uses a TTF font when available)."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    font = _unicode_font()
    c.setFont(font, 11)
    y = 780
    for line in lines:
        c.drawString(50, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


def _unicode_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/TTF/DejaVuSans.ttf",
                 "C:/Windows/Fonts/arial.ttf",
                 "/Library/Fonts/Arial Unicode.ttf"):
        try:
            pdfmetrics.registerFont(TTFont("TestUnicode", path))
            return "TestUnicode"
        except Exception:
            continue
    return "Helvetica"


def make_blank_pdf():
    """Valid PDF without any text (like a scan) -> unreadable."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(100, 100, 200, 200, fill=1)
    c.save()
    return buf.getvalue()


def make_docx(lines=("Hello, this is a test DOCX document with real text.",)):
    import docx
    buf = io.BytesIO()
    d = docx.Document()
    for line in lines:
        d.add_paragraph(line)
    d.save(buf)
    return buf.getvalue()


def make_zip_not_docx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "not a word document")
    return buf.getvalue()
