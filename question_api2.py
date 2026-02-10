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
from pymongo.errors import DuplicateKeyError
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

BASE_URL = "https://ai-questions-render1.onrender.com"

# -----------------------------
# MongoDB Connection
# -----------------------------
MONGO_URL ="mongodb+srv://dasariharikrishna01_db_user:NPysZDsuMJtAEnwn@cluster0.pcjtqzs.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URL)
db = client["smart-engine"]
interview_collection = db["interview_schedule"]
ai_interview_collection = db["ai_interview"]
ai_result_collection = db["ai_result"]


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


def generate_qa_pdf(interview_id, candidate_name, job_role, qa_text):
    base_dir = Path(f"interviews/{interview_id}")
    base_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = base_dir / "qa.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)

    text = c.beginText(40, 800)
    text.setFont("Helvetica", 11)

    text.textLine(f"Candidate Name: {candidate_name}")
    text.textLine(f"Job Role: {job_role}")
    text.textLine("-" * 80)

    for line in qa_text.split("\n"):
        text.textLine(line)

    c.drawText(text)
    c.save()

    return str(pdf_path)
def compress_video(input_path):
    output_path = input_path.replace(".mp4", "_compressed.mp4")

    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-vcodec", "libx264",
        "-preset", "slow",
        "-crf", "22",
        "-movflags", "+faststart",
        output_path
    ]

    subprocess.run(cmd, check=True)
    return output_path


def get_file_size_mb(path):
    return round(Path(path).stat().st_size / (1024 * 1024), 2)

def parse_qa_text(qa_text: str):
    qa_pairs = []
    blocks = re.split(r"\n\s*\n", qa_text.strip())

    for block in blocks:
        q_match = re.search(r"Q\d*[:\-]?\s*(.+)", block, re.I)
        a_match = re.search(r"A\d*[:\-]?\s*(.*)", block, re.I | re.S)

        if q_match:
            question = q_match.group(1).strip()
            answer = a_match.group(1).strip() if a_match else ""
            qa_pairs.append({
                "question": question,
                "answer": answer
            })

    return qa_pairs


def validate_answers(expected_questions, qa_pairs):
    results = []
    answered = []
    skipped = []

    for q in expected_questions:
        matched = next(
            (x for x in qa_pairs if q.lower() in x["question"].lower()),
            None
        )

        if not matched:
            results.append({
                "question": q,
                "answer": "",
                "status": "skipped",
                "score": 0
            })
            skipped.append(q)
            continue

        answer = matched["answer"].strip()

        if not answer:
            status = "skipped"
            score = 0
            skipped.append(q)

        elif len(answer) < 15:
            status = "partial"
            score = 0.5
            answered.append(q)

        else:
            q_keywords = set(q.lower().split())
            a_keywords = set(answer.lower().split())
            overlap = q_keywords & a_keywords

            if not overlap:
                status = "irrelevant"
                score = 0
                skipped.append(q)
            else:
                status = "answered"
                score = 1
                answered.append(q)

        results.append({
            "question": q,
            "answer": answer,
            "status": status,
            "score": score
        })

    return results, answered, skipped
def send_interview_email(
    to_email: str,
    candidate_name: str,
    job_role: str,
    interview_date: str,
    slot_time: str,
    interview_link: str
):
    message = Mail(
        from_email=os.getenv("FROM_EMAIL"),
        to_emails=to_email,
        subject=f"Interview Scheduled – {job_role}",
        html_content=f"""
        <p>Hello <b>{candidate_name}</b>,</p>

        <p>Your interview has been scheduled.</p>

        <ul>
          <li><b>Role:</b> {job_role}</li>
          <li><b>Date:</b> {interview_date}</li>
          <li><b>Time:</b> {slot_time}</li>
        </ul>

        <p>
          👉 <a href="{interview_link}">
          Click here to start your interview
          </a>
        </p>

        <p>Best regards,<br>HR Team</p>
        """
    )

    sg = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))
    sg.send(message)




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
    interview_link = f"{BASE_URL}/interview/{interview_id}"
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
    interview_link=db_record["interview_link"]
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
        interview_link = f"{BASE_URL}/interview/{interview_id}"

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

    return RedirectResponse(
    url=f"{BASE_URL}/docs"
    )

    return {
        "message": "Interview started",
        "interview_id": interview_id
    }
@app.post("/start-interview")
def start_interview_backend(interview_id: str = Form(...)):
    start_time = dt.datetime.utcnow()

    ai_interview_collection.update_one(
        {"interview_id": interview_id},
        {
            "$set": {
                "interview_id": interview_id,
                "interview_start_time": start_time,
                "completed": False
            }
        },
        upsert=True
    )

    return {
        "message": "Interview started",
        "start_time": start_time.isoformat()
    }
@app.post("/end-interview")
def end_interview_backend(interview_id: str = Form(...)):
    end_time = dt.datetime.utcnow()

    record = ai_interview_collection.find_one(
        {"interview_id": interview_id}
    )

    if not record or "interview_start_time" not in record:
        raise HTTPException(400, "Interview start time not found")

    start_time = record["interview_start_time"]
    duration_minutes = int((end_time - start_time).total_seconds() / 60)

    ai_interview_collection.update_one(
        {"interview_id": interview_id},
        {
            "$set": {
                "interview_end_time": end_time,
                "interview_duration_minutes": duration_minutes,
                "completed": True
            }
        }
    )

    return {
        "message": "Interview ended",
        "duration_minutes": duration_minutes
    }
@app.post("/save-qa")
def save_qa_backend(
    interview_id: str = Form(...),
    qa_text: str = Form(...)
):
    interview_links = load_interview_links()

    if interview_id not in interview_links:
        raise HTTPException(404, "Invalid interview ID")

    candidate = interview_links[interview_id]

    pdf_path = generate_qa_pdf(
        interview_id=interview_id,
        candidate_name=candidate.get("candidate_name", "Unknown"),
        job_role=candidate.get("job_role", "Unknown"),
        qa_text=qa_text
    )

    ai_interview_collection.update_one(
        {"interview_id": interview_id},
        {
            "$set": {
                "qa_pdf_path": pdf_path
            }
        }
    )

    return {
        "message": "Q/A PDF generated and stored",
        "qa_pdf_path": pdf_path
    }
@app.post("/save-video")
def save_video_backend(
    interview_id: str = Form(...),
    video: UploadFile = File(...)
):
    base_dir = Path(f"interviews/{interview_id}")
    base_dir.mkdir(parents=True, exist_ok=True)

    raw_video_path = base_dir / "raw_interview.mp4"

    with open(raw_video_path, "wb") as f:
        f.write(video.file.read())

    compressed_video_path = compress_video(str(raw_video_path))
    video_size_mb = get_file_size_mb(compressed_video_path)

    if video_size_mb > 150:
        raise HTTPException(
            status_code=400,
            detail="Compressed video exceeds 150 MB"
        )

    ai_interview_collection.update_one(
        {"interview_id": interview_id},
        {
            "$set": {
                "video_path": compressed_video_path,
                "video_size_mb": video_size_mb
            }
        }
    )

    return {
        "message": "Video saved and compressed successfully",
        "video_path": compressed_video_path,
        "video_size_mb": video_size_mb
    }
@app.post("/save-ai-result")
def save_ai_result(
    interview_id: str = Form(...),
    qa_text: str = Form(...)
):
    interview_links = load_interview_links()

    if interview_id not in interview_links:
        raise HTTPException(404, "Invalid interview ID")

    interview = interview_links[interview_id]
    expected_questions = interview["questions"]

    qa_pairs = parse_qa_text(qa_text)

    validation_results, answered_q, skipped_q = validate_answers(
        expected_questions, qa_pairs
    )

    total_questions = len(expected_questions)
    answered_count = len(answered_q)
    skipped_count = len(skipped_q)

    grand_total_score = round(
        (sum(r["score"] for r in validation_results) / total_questions) * 100
        if total_questions > 0 else 0,
        2
    )

    ai_result_collection.update_one(
        {"interview_id": interview_id},
        {
            "$set": {
                "interview_id": interview_id,
                "candidate_name": interview["candidate_name"],
                "candidate_email": interview["candidate_email"],
                "role": interview["job_role"],

                "total_questions": total_questions,
                "answered_count": answered_count,
                "skipped_count": skipped_count,
                "grand_total_score": grand_total_score,

                "results": validation_results,
                "evaluated_at": dt.datetime.utcnow()
            }
        },
        upsert=True
    )

    return {
        "message": "Validation completed and stored",
        "answered": answered_count,
        "skipped": skipped_count,
        "score": grand_total_score
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
@app.post("/finalize-interview")
def finalize_interview_backend(interview_id: str = Form(...)):
    record = ai_interview_collection.find_one(
        {"interview_id": interview_id}
    )

    if not record:
        raise HTTPException(404, "Interview record not found")

    missing = []
    for field in [
        "interview_start_time",
        "interview_end_time",
        "interview_duration_minutes",
        "qa_pdf_path",
        "video_path"
    ]:
        if field not in record:
            missing.append(field)

    if missing:
        raise HTTPException(
            400,
            f"Cannot finalize. Missing fields: {', '.join(missing)}"
        )

    ai_interview_collection.update_one(
        {"interview_id": interview_id},
        {
            "$set": {
                "completed": True,
                "finalized_at": dt.datetime.utcnow()
            }
        }
    )

    return {
        "message": "Interview finalized successfully",
        "finalized_at": dt.datetime.utcnow().isoformat()
    }
@app.get("/interview-ui/{interview_id}", response_class=HTMLResponse)
def interview_ui(interview_id: str):
    interview_links = load_interview_links()

    if interview_id not in interview_links:
        return "<h2>Invalid Interview Link</h2>"

    return f"""
    <html>
    <head>
        <title>Interview</title>
    </head>
    <body>
        <h2>Welcome {interview_links[interview_id]['candidate_name']}</h2>
        <p>Role: {interview_links[interview_id]['job_role']}</p>

        <p>Interview ID: {interview_id}</p>

        <p><b>Interview will start here.</b></p>
    </body>
    </html>
    """


