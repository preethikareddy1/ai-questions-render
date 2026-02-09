import uuid
import json
import subprocess
import sys
import re
from docx import Document
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from typing import List
import pdfplumber
from question_gen import generate_questions

# --------------------------------------------------
# File to store interview links
# --------------------------------------------------
INTERVIEW_LINKS_FILE = Path("interview_links.json")

def load_interview_links():
    if not INTERVIEW_LINKS_FILE.exists():
        return {}

    with open(INTERVIEW_LINKS_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)

def save_interview_links(data):
    with open(INTERVIEW_LINKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# --------------------------------------------------
# FastAPI app
# --------------------------------------------------
app = FastAPI(title="Interview Question Generator API")

@app.get("/")
def root():
    return RedirectResponse(url="/docs")

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def extract_text_from_file(file: UploadFile) -> str:
    filename = file.filename.lower()
    file.file.seek(0)

    # PDF
    if filename.endswith(".pdf"):
        text = ""
        with pdfplumber.open(file.file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text

    # DOCX
    elif filename.endswith(".docx"):
        doc = Document(file.file)
        return "\n".join(p.text for p in doc.paragraphs)

    # TXT
    elif filename.endswith(".txt"):
        return file.file.read().decode("utf-8", errors="ignore")

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.filename}"
        )

    text = ""
    file.file.seek(0)
    with pdfplumber.open(file.file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def extract_email_from_text(text: str):
    match = re.search(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        text
    )
    return match.group(0) if match else None

# --------------------------------------------------
# Generate interview links (NO EMAIL SENDING)
# --------------------------------------------------
@app.post("/generate")
async def generate(
    job_description: str = Form(...),
    resumes: List[UploadFile] = File(...),
    manual_email: str = Form(None),
    num_questions: int = Form(10)
):
    interview_links = load_interview_links()
    generated_links = []
    missing_email_candidates = []

    for resume_file in resumes:
        resume_text = extract_text_from_file(resume_file)

        email = extract_email_from_text(resume_text)
        # If email not in resume, check manual input
        if not email:
            if not manual_email:
                missing_email_candidates.append({
                    "resume_name": resume_file.filename,
                    "message": "Email not found in resume. Please enter email manually and re-submit."
                })
                continue
            else:
                email = manual_email


        # ✅ Generate questions ONLY if email exists
        questions = generate_questions(
            job_description=job_description,
            resume_text=resume_text,
            num_questions=num_questions
        )

        interview_id = str(uuid.uuid4())[:8]
        interview_link = f"http://127.0.0.1:8001/interview/{interview_id}"

        interview_links[interview_id] = {
            "questions": questions,
            "candidate_email": email,
            "completed": False
        }

        generated_links.append({
            "interview_id": interview_id,
            "candidate_email": email,
            "interview_link": interview_link
        })

    save_interview_links(interview_links)

    return {
        "generated_interviews": generated_links,
        "manual_email_required": missing_email_candidates
    }


# --------------------------------------------------
# Start interview
# --------------------------------------------------
@app.get("/interview/{interview_id}")
def start_interview(interview_id: str):
    interview_links = load_interview_links()

    if interview_id not in interview_links:
        raise HTTPException(status_code=404, detail="Invalid interview link")

    subprocess.Popen(
        [sys.executable, "final_code.py", interview_id]
    )

    return {
        "message": "Interview started",
        "interview_id": interview_id
    }
