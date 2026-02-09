import os   # ✅ REQUIRED
import json
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
import re

# --------------------------------------------------
# Force-load .env from this folder
# --------------------------------------------------
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

raw_key = os.getenv("OPENAI_API_KEY")
if not raw_key:
    raise RuntimeError("OPENAI_API_KEY not found in .env")

client = OpenAI(api_key=raw_key.strip())

# --------------------------------------------------
# Question pool file
# --------------------------------------------------
POOL_FILE = Path("question_pool.json")

def load_pool():
    if not POOL_FILE.exists():
        return {
            "metadata": {
                "job_id": "JD_001",
                "domain": "UNKNOWN"
            },
            "questions": {
                "technical": [],
                "scenario": [],
                "coding": []
            }
        }
    with open(POOL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_pool(pool):
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, indent=2)

# --------------------------------------------------
# AI QUESTION GENERATION (TECH ONLY)
# --------------------------------------------------
def generate_questions(
    job_description: str,
    resume_text: str,
    experience_years: int | None = None,
    num_questions: int = 40,
    language: str | None = None
):
    if experience_years is None:
        experience_level = "mixed"
    elif experience_years <= 1:
        experience_level = "junior"
    elif experience_years <= 4:
        experience_level = "mid"
    else:
        experience_level = "senior"

    prompt = f"""
You are an expert technical interviewer.

Job Description:
{job_description}

Candidate Resumes:
{resume_text}

Candidate Experience Level:
{experience_level}

Difficulty Guidelines:
- junior: focus on fundamentals and basic concepts
- mid: focus on applied concepts and scenario-based questions
- senior: focus on system design, architecture, and advanced topics

STRICT RULES:
- Generate ONLY technical interview questions
- Allowed types:
  - technical
  - scenario
  - coding
- DO NOT generate HR or behavioral questions
- Questions must assess technical skills ONLY
- Generate exactly {num_questions} questions
- Do NOT repeat questions
- Return ONLY valid JSON in the format below:

{{
  "questions": [
    {{
      "type": "technical",
      "text": "...",
      "keywords": ["keyword1", "keyword2"]
    }}
  ]
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )

    content = response.choices[0].message.content

    try:
        start = content.index("{")
        end = content.rindex("}") + 1
        parsed = json.loads(content[start:end])
        questions = parsed.get("questions", [])
    except Exception as e:
        raise ValueError(f"AI response was not valid JSON: {e}")

    questions = [
        q for q in questions
        if q.get("type") in ["technical", "scenario", "coding"]
    ]

    store_questions_in_pool(questions)
    return questions

def store_questions_in_pool(ai_questions):
    pool = load_pool()

    for q in ai_questions:
        q_type = q.get("type")

        entry = {
            "id": f"{q_type.upper()}_{os.urandom(4).hex()}",
            "text": q["text"],
            "type": q_type,
            "keywords": q.get("keywords") if isinstance(q.get("keywords"), list) else [],
            "used": False
        }

        pool["questions"][q_type].append(entry)

    save_pool(pool)
