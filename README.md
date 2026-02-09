# AI-Based Interview Question Generator & Proctored Interview System

## Project Overview
This project is an end-to-end AI-powered interview system where recruiters upload resumes and job descriptions, generate unique interview links, and candidates attend a fully proctored interview.

---

## Folder Structure

ai-questions/
├── question_api.py        # FastAPI backend
├── gen.py                 # AI question generator
├── selector.py            # Question selector (optional)
├── final_code.py          # Candidate interview & proctoring
├── interview_links.json   # Stores interview IDs + questions
├── question_pool.json     # Global question pool
├── candidate_answers.json # Final answers & scores
├── audio/                 # Generated audio questions
├── .env                   # OpenAI API key
└── README.md              # Project documentation

---

## How the System Works

### Recruiter Side
1. Recruiter starts FastAPI server
2. Uploads job description + resumes
3. System:
   - Extracts email from resume
   - Generates candidate-specific questions
   - Generates unique interview ID & link
4. Data is stored in `interview_links.json`

---

### Candidate Side
1. Candidate opens interview link
2. Interview starts automatically
3. AI asks questions via voice
4. Candidate answers via speech / code editor
5. Proctoring monitors:
   - Camera
   - Multiple faces
   - Blur
   - Voice fraud
   - Unauthorized apps

---

## Stored Files Explanation

### interview_links.json
Stores per-candidate interview data:
- Interview ID
- Candidate email
- Generated questions

### question_pool.json
Stores all generated questions globally.

### candidate_answers.json
Stores:
- Candidate answers
- Final score
- Overall feedback

---

## How to Run

### 1. Start API
```bash
uvicorn question_api:app --port 8001
Open:

http://127.0.0.1:8001/docs

2. Generate Interview

Upload resumes

Enter job description

Click Execute

Copy interview link

3. Start Interview

Candidate opens:

http://127.0.0.1:8001/interview/{interview_id}


This runs:

python final_code.py interview_id

Important Notes

Each candidate gets a UNIQUE interview ID

Questions are UNIQUE per resume

Interviews auto-submit on rule violations

No automatic email sending (manual sharing)

Platform

Windows OS only

Uses camera, mic, and system process monitoring

Project Status

✔ Working end-to-end
✔ Proctoring enabled
✔ Evaluation stored


---
