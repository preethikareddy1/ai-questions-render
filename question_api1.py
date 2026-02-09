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
from fastapi.responses import HTMLResponse
import datetime as dt
from booking import make_ics
from pymongo import MongoClient
import smtplib
from email.message import EmailMessage
from pymongo.errors import DuplicateKeyError


# -----------------------------
# MongoDB Connection
# -----------------------------
MONGO_URL ="mongodb+srv://dasariharikrishna01_db_user:NPysZDsuMJtAEnwn@cluster0.pcjtqzs.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URL)
db = client["smart-engine"]
interview_collection = db["interview_schedule"]

TIME_SLOTS = {
    1: ("00:00", "04:00"),
    2: ("04:00", "08:00"),
    3: ("08:00", "12:00"),
    4: ("12:00", "16:00"),
    5: ("16:00", "20:00"),
    6: ("20:00", "23:59")
}



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
def extract_candidate_name(text: str):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return "Unknown Candidate"

    name = lines[0]
    name = re.sub(r"[^a-zA-Z\s]", "", name)

    return name[:50]
def clean_role_title(role: str) -> str:
    """
    Extract only role title (remove location/exp/etc.)
    Example:
    '1 role: sr. core java developer location: alpharetta...'
    → 'Sr. Core Java Developer'
    """

    if not role:
        return "Unknown Role"

    role = role.lower()

    # remove leading numbering + 'role:'
    role = re.sub(r"^\d+\s*(role|title)\s*:\s*", "", role)

    # stop keywords where JD usually continues
    stop_words = [
        "location",
        "exp",
        "experience",
        "duration",
        "jd",
        "skills",
        "responsibilities",
        "|",
        "-"
    ]

    for word in stop_words:
        if word in role:
            role = role.split(word)[0]

    # remove extra symbols
    role = re.sub(r"[^a-zA-Z\s]", "", role)

    return role.strip().title()




def send_interview_email(to_email, candidate_name, job_role,
                          interview_date, slot_time,
                          interview_link, ics_file):

    msg = EmailMessage()
    msg["Subject"] = job_role
    msg["From"] = "dasariharikrishna01@gmail.com"
    msg["To"] = to_email

    msg.set_content(f"""
Hello {candidate_name},

Your interview has been scheduled.

Role: {job_role}
Date: {interview_date}
Time: {slot_time}

Interview Link:
{interview_link}

Please find the calendar invite attached.

Best regards,
HR Team
""")

    # attach calendar invite
    with open(ics_file, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="text",
            subtype="calendar",
            filename="interview.ics"
        )

    # Gmail SMTP (use App Password)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login("preethikareddy68@gmail.com", "xkpfrsbsyxxfeyjb")
        server.send_message(msg)



# --------------------------------------------------
# Generate interview links (NO EMAIL SENDING)
# --------------------------------------------------

@app.post("/schedule-meeting")
def schedule_meeting(
    interview_id: str = Form(...),
    interview_date: str = Form(...),
    slot_number: int = Form(...)
):
    interview_links = load_interview_links()

    # 1. Validate interview ID
    if interview_id not in interview_links:
        raise HTTPException(status_code=404, detail="Invalid interview ID")

    if slot_number not in TIME_SLOTS:
        raise HTTPException(status_code=400, detail="Invalid slot selected")

    # 2. Build start & end time (Zoom logic)
    start_str, end_str = TIME_SLOTS[slot_number]

    start_dt = dt.datetime.strptime(
        f"{interview_date} {start_str}", "%Y-%m-%d %H:%M"
    )
    end_dt = dt.datetime.strptime(
        f"{interview_date} {end_str}", "%Y-%m-%d %H:%M"
    )

    # 3. Interview link (already generated earlier)
    interview_link = f"http://127.0.0.1:8001/interview/{interview_id}"

    # 4. Create calendar invite (USING YOUR booking.py)
    ics_path = make_ics(
        invite_dir="invites",
        candidate_name=interview_links[interview_id]["candidate_email"],
        start_dt=start_dt,
        duration_min=int((end_dt - start_dt).total_seconds() / 60),
        meeting_link=interview_link,
        title="Interview Meeting"
    )

    # 5. Save meeting (Zoom DB style)
    interview_links[interview_id]["meeting"] = {
        "date": interview_date,
        "slot": slot_number,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "ics_file": ics_path
    }

    save_interview_links(interview_links)
    slot_time = f"{start_str} - {end_str}"

    db_record = {
        "interview_id": interview_id,
        "candidate_name": interview_links[interview_id].get(
        "candidate_name", "Unknown Candidate"
        ),
        "candidate_email": interview_links[interview_id]["candidate_email"],
        "job_role": interview_links[interview_id].get(
        "job_role", "Unknown Role"
        ),
        "interview_link": interview_link,
        "interview_date": interview_date,
        "slot_number": slot_number,
        "slot_time": slot_time,
        "start_time": start_dt,
        "end_time": end_dt,
        "ics_file": ics_path,
        "completed": False
    }
    
    interview_collection.update_one(
    {"interview_id": interview_id},   # condition
    {"$set": db_record},              # data
    upsert=True                       # insert if not exists
    )

    send_interview_email(
        to_email=db_record["candidate_email"],
        candidate_name=db_record["candidate_name"],
        job_role=db_record["job_role"],
        interview_date=db_record["interview_date"],
        slot_time=db_record["slot_time"],
        interview_link=db_record["interview_link"],
        ics_file=db_record["ics_file"]
    )

    return {
        "message": "Meeting scheduled successfully",
        "interview_id": interview_id,
        "date": interview_date,
        "slot": slot_number,
        "ics_file": ics_path
    }

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
        candidate_name = extract_candidate_name(resume_text)

        # ✅ CLEAN ROLE HERE (ONLY ONCE)
        first_line = job_description.split("\n")[0]
        first_line = re.sub(r"(?i)^title\s*:\s*", "", first_line)
        job_role = clean_role_title(first_line)


        interview_id = str(uuid.uuid4())[:8]
        interview_link = f"http://127.0.0.1:8001/interview/{interview_id}"

        interview_links[interview_id] = {
            "questions": questions,
            "candidate_email": email,
            "candidate_name": candidate_name,
            "job_role": job_role,
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
@app.get("/admin-schedule", response_class=HTMLResponse)
def admin_schedule_page():
    return """
    <html>
    <head>
        <title>Schedule Interview</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background-color: #f4f6f8;
            }
            .container {
                width: 400px;
                margin: 80px auto;
                padding: 25px;
                background: white;
                border-radius: 8px;
                box-shadow: 0 0 10px rgba(0,0,0,0.1);
            }
            h2 {
                text-align: center;
                margin-bottom: 20px;
            }
            label {
                font-weight: bold;
            }
            input, select, button {
                width: 100%;
                padding: 8px;
                margin-top: 5px;
                margin-bottom: 15px;
            }
            button {
                background-color: #0b5ed7;
                color: white;
                border: none;
                cursor: pointer;
                border-radius: 4px;
            }
            button:hover {
                background-color: #084298;
            }
        </style>
    </head>

    <body>
        <div class="container">
            <h2>Schedule Interview</h2>

            <form method="post" action="/schedule-meeting">
                <label>Interview ID</label>
                <input type="text" name="interview_id" required>

                <label>Select Date</label>
                <input type="date" name="interview_date" required>

                <label>Select Slot</label>
                <select name="slot_number" required>
                    <option value="1">00:00 - 04:00</option>
                    <option value="2">04:00 - 08:00</option>
                    <option value="3">08:00 - 12:00</option>
                    <option value="4">12:00 - 16:00</option>
                    <option value="5">16:00 - 20:00</option>
                    <option value="6">20:00 - 23:59</option>
                </select>

                <button type="submit">Schedule Meeting</button>
            </form>
        </div>
    </body>
    </html>
    """


