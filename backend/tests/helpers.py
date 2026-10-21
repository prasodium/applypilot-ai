"""Builders for synthetic test files. No real personal data anywhere."""
from __future__ import annotations

import io
import zipfile

import pymupdf
from docx import Document

RESUME_TEXT = """Alex Example
Backend Engineer
Springfield, USA | alex@example.test | +1 555 010 0000
github.com/alex-example

SUMMARY
Backend engineer who enjoys reliable systems.

EXPERIENCE
Software Engineer, Acme Corp          Jan 2021 - Present
• Built REST APIs with Python and FastAPI
• Wrote automated tests with pytest
Junior Developer | Initech | Springfield
Jun 2019 – Dec 2020
- Maintained internal tools in Java and SQL

EDUCATION
State University, Springfield
B.Sc. in Computer Science   2015 - 2019   GPA: 3.6/4.0
• Relevant coursework: Algorithms, Databases

SKILLS
Languages: Python, Java, SQL
Tools: Git, Docker

PROJECTS
Job Tracker | github.com/alex-example/job-tracker
• A command-line tool to track job applications
• Technologies: Python, SQLite
"""


def make_docx(text: str = RESUME_TEXT) -> bytes:
    d = Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_pdf(text: str = RESUME_TEXT, *, password: str | None = None) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 560, 800), text, fontsize=9)
    if password:
        return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    return doc.tobytes()


def blank_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    return doc.tobytes()


def zip_bomb_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("padding.bin", b"\0" * (60 * 1024 * 1024))  # compresses to a few KB, expands to 60 MB
    return buf.getvalue()


DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
