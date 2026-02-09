# =========================================================
# FINAL INTERVIEW + PROCTORING SYSTEM
# UNIFIED AUTO-SUBMIT (VIDEO OR SPEECH = 3/3)
# =========================================================

# =============================
# ENV + IMPORTS
# =============================
import os
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import cv2
import time
import winsound
import mediapipe as mp
import threading
import asyncio
import edge_tts
import speech_recognition as sr
import win32gui
import win32process
import psutil
import audioop
import tkinter as tk
import sys
from pydub import AudioSegment
from pydub.playback import play



import json


answers_collected = []

# =============================
# INTERVIEW CONFIRMATION WORDS
# =============================
POSITIVE_RESPONSES = [
    "yes",
    "yeah",
    "yep",
    "ok",
    "okay",
    "sure",
    "ready",
    "proceed",
    "go ahead",
    "let's start",
    "start",
    "fine"
]

INTERVIEW_LINKS_FILE = "interview_links.json"

def load_questions_by_interview_id(interview_id):
    with open(INTERVIEW_LINKS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if interview_id not in data:
        raise ValueError("Invalid interview ID")

    return data[interview_id]["questions"]


def is_positive_response(text):
    if not text:
        return False

    text = text.lower().strip()
    return any(word in text for word in POSITIVE_RESPONSES)



# =============================
# GLOBAL SETTINGS
# =============================
MAX_WARNINGS = 3
STOP_INTERVIEW = False   # 🔥 unified stop flag

FACE_MISSING_TIME = 5
BLUR_TIME = 5
MULTI_FACE_TIME = 5
BLUR_THRESHOLD = 120
CAMERA_INDEX = 0


VOICE = "en-GB-RyanNeural"
ALLOWED_APPS = [
    "python",      # interview script
    "opencv",      # camera window
    "interview",   # interview-related window name
    "code",        # ✅ Allow VS Code window 
]


# =============================
# MEDIAPIPE FACEMESH
# =============================
mp_face = mp.solutions.face_mesh
face_detector = mp_face.FaceMesh(
    static_image_mode=False,
    max_num_faces=3,
    refine_landmarks=False,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.6
)

# =============================
# BLUR CHECK
# =============================
def blur_score(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()

# =============================
# VIDEO PROCTORING THREAD
# =============================
def run_video_proctoring():
    global STOP_INTERVIEW

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("❌ Camera not accessible")
        STOP_INTERVIEW = True
        return

    warnings = 0
    countdown_start = None
    countdown_duration = 0
    last_violation = None

    warning_text = ""
    warning_show_until = 0

    print("✅ Video proctoring started")
    # ✅ FIX: Create stable window (only once)
    cv2.namedWindow("Interview Monitoring", cv2.WINDOW_NORMAL)

    # ✅ FIX: Set fixed window size
    cv2.resizeWindow("Interview Monitoring", 750, 500)

    # ✅ FIX: Keep window always visible
    cv2.moveWindow("Interview Monitoring", 50, 50)


    while not STOP_INTERVIEW:
        ret, frame = cap.read()
        if not ret:
            continue

        now = time.time()

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_detector.process(rgb)
        faces = results.multi_face_landmarks if results.multi_face_landmarks else []

        sharpness = blur_score(frame)

        violation = None
        duration = 0

        if len(faces) > 1:
            violation = "Multiple people detected"
            duration = MULTI_FACE_TIME
        elif len(faces) == 0:
            violation = "Face not visible"
            duration = FACE_MISSING_TIME
        elif sharpness < BLUR_THRESHOLD:
            violation = "Camera is blurry"
            duration = BLUR_TIME

        if violation:
            if violation != last_violation:
                countdown_start = now
                countdown_duration = duration
                last_violation = violation

            remaining = int(countdown_duration - (now - countdown_start))

            if remaining > 0:
                cv2.putText(
                    frame,
                    f"{violation} - Check your webcam ({remaining}s)",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.75,
                    (0, 255, 255),
                    2
                )
            else:
                warnings += 1
                winsound.Beep(1000, 500)

                warning_text = f"WARNING {warnings}/{MAX_WARNINGS} : {violation}"
                warning_show_until = now + 3

                print(f"⚠️ VIDEO WARNING {warnings}/{MAX_WARNINGS}: {violation}")

                last_violation = None
                countdown_start = None

                if warnings >= MAX_WARNINGS:
                    print("⛔ Interview auto-submitted due to VIDEO violations")
                    STOP_INTERVIEW = True
                    break
        else:
            last_violation = None
            countdown_start = None

        if time.time() < warning_show_until:
            cv2.putText(
                frame,
                warning_text,
                (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (0, 0, 255),
                2
            )
        frame = cv2.resize(frame, (750, 500))
        cv2.imshow("Interview Monitoring", frame)
        key = cv2.waitKey(20)
        if key == ord('q'):
            STOP_INTERVIEW = True
            break

    cap.release()
    cv2.destroyAllWindows()
    print("✅ Video proctoring stopped")

# =============================
# EDGE TTS
# =============================
async def speak_async(text, index):
    os.makedirs("audio", exist_ok=True)
    path = f"audio/question_{index}.mp3"
    communicate = edge_tts.Communicate(text=text, voice=VOICE)
    await communicate.save(path)
    play(AudioSegment.from_mp3(path))

def speak(text, index):
    asyncio.run(speak_async(text, index))

# =============================
# SPEECH LISTENER
# =============================
def listen_user_answer():
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.2

    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.8)
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=60)
        except sr.WaitTimeoutError:
            return "(No response)", None

    try:
        return recognizer.recognize_google(audio, language="en-IN"), audio
    except:
        return "(Speech not clear)", audio
    

    
def handle_introduction():
    print("\n🟢 Introduction Phase Started")

    # Ask introduction
    intro_question = "Please introduce yourself."
    speak(intro_question, 0)

    print("🎙️ Listening for introduction...")
    intro_answer, _ = listen_user_answer()
    
    print("Candidate Introduction:", intro_answer)

    if is_no_answer(intro_answer):
        print("❌ No introduction provided. Interview stopped.")
        return False

    answers_collected.append({
        "question": "Please introduce yourself.",
        "answer": intro_answer
    })


    # Ask confirmation
    confirm_question = "Shall we proceed with the interview?"
    speak(confirm_question, 0)

    print("🎙️ Waiting for confirmation...")
    confirm_answer, _ = listen_user_answer()

    print("Candidate Confirmation:", confirm_answer)

    if is_positive_response(confirm_answer):
        print("✅ Candidate confirmed. Starting interview.")
        return True
    else:
        print("❌ Candidate did not confirm. Interview stopped.")
        return False


# =============================
# SPEECH FRAUD DETECTION
# =============================
previous_voice_features = None

def detect_voice_change(audio):
    global previous_voice_features

    if audio is None:
        return None

    raw = audio.get_raw_data()
    width = audio.sample_width

    rms = audioop.rms(raw, width)
    zc = audioop.cross(raw, width)

    if previous_voice_features is None:
        previous_voice_features = (rms, zc)
        return None

    prev_rms, _ = previous_voice_features
    previous_voice_features = (rms, zc)

    if abs(rms - prev_rms) / (prev_rms + 1) > 0.6:
        return "Possible different speaker detected"

    return None


def is_no_answer(answer):
    invalid_responses = [
        "(no response)",
        "(speech not clear)",
        "(no speech detected)",
        ""
    ]
    return answer.strip().lower() in invalid_responses



def get_active_app_name():
    try:
        hwnd = win32gui.GetForegroundWindow()  # get active window
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        return process.name().lower()
    except:
        return None

def run_app_monitoring():
    global STOP_INTERVIEW

    app_warnings = 0
    last_app = None

    print("✅ Application monitoring started")

    while not STOP_INTERVIEW:
        active_app = get_active_app_name()

        if active_app:
            allowed = any(app in active_app for app in ALLOWED_APPS)

            if not allowed and active_app != last_app:
                app_warnings += 1

                print(
                    f"⚠️ APP WARNING {app_warnings}/{MAX_WARNINGS}: "
                    f"Unauthorized application detected -> {active_app}"
                )

                last_app = active_app

                if app_warnings >= MAX_WARNINGS:
                    print("⛔ Interview auto-submitted due to APP violations")
                    STOP_INTERVIEW = True
                    break

        time.sleep(1)

    print("✅ Application monitoring stopped")

# =============================
# CODING POPUP WINDOW
# =============================
def open_coding_popup(question, q_index):
    result = {"code": None}

    def save_code():
        code = editor.get("1.0", tk.END)

        with open(f"code_q{q_index}_draft.txt", "w", encoding="utf-8") as f:
            f.write(code)

        print(f"✅ Draft code saved for Question {q_index}")

    def submit_code():
        result["code"] = editor.get("1.0", tk.END)

        with open(f"code_q{q_index}_final.txt", "w", encoding="utf-8") as f:
            f.write(result["code"])

        print(f"✅ Code submitted for Question {q_index}")
        root.destroy()

    root = tk.Tk()
    root.title("Coding Question")
    root.attributes("-topmost", True)
    root.after(500, lambda: root.attributes("-topmost", False))


    # Window size
    root.geometry("600x420")

    tk.Label(
        root,
        text=f"Question {q_index}: {question}",
        font=("Segoe UI", 11, "bold"),
        wraplength=760
    ).pack(pady=10)

    editor = tk.Text(root, font=("Consolas", 11))
    editor.config(height=15)
    editor.pack(expand=True, fill="both", padx=10, pady=(0, 5))


    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=10)

    tk.Button(btn_frame, text="Save", width=15, command=save_code)\
        .pack(side="left", padx=20)

    tk.Button(btn_frame, text="Submit", width=15, command=submit_code)\
        .pack(side="right", padx=20)

    root.mainloop()
    return result["code"]



def evaluate_answers(answers):
    results = []
    total_score = 0

    for item in answers:
        question = item["question"]
        answer = item["answer"]

        # INTRODUCTION QUESTION
        if question.lower().startswith("please introduce"):
            score = 5.0
            feedback = "Introduction recorded."

        # NO ANSWER
        elif is_no_answer(answer):
            score = 0.0
            feedback = "No answer provided."

        # CODING QUESTION
        elif is_coding_question(question):
            if answer != "(Not submitted)":
                score = 8.0
                feedback = "Code submitted successfully."
            else:
                score = 2.0
                feedback = "Coding question not answered."

        # SPOKEN TECHNICAL ANSWER
        else:
            word_count = len(answer.split())

            if word_count >= 30:
                score = 8.0
                feedback = "Clear and detailed explanation."
            elif word_count >= 15:
                score = 6.0
                feedback = "Adequate explanation."
            elif word_count >= 7:
                score = 4.0
                feedback = "Short explanation."
            else:
                score = 2.0
                feedback = "Very minimal explanation."

        results.append({
            "question": question,
            "score": score,
            "feedback": feedback
        })

        total_score += score

    final_score = round(total_score / len(results), 1) if results else 0

    if final_score >= 8:
        overall_feedback = "Strong overall performance."
    elif final_score >= 5:
        overall_feedback = "Average performance."
    else:
        overall_feedback = "Needs significant improvement."

    return results, final_score, overall_feedback


# =============================
# CODING QUESTION DETECTION
# =============================

# Words that indicate it is a coding-type question
CODING_KEYWORDS = [
    "code",
    "program",
    "write",
    "implement",
    "function",
    "algorithm"
]

# This function checks whether a question is a coding question
def is_coding_question(question):
    question = question.lower()

    for keyword in CODING_KEYWORDS:
        if keyword in question:
            return True

    return False


def save_candidate_answers(interview_id, answers, final_score, overall_feedback):
    file = "candidate_answers.json"

    if os.path.exists(file):
            with open(file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                else:
                    data = {}
    else:
        data={}
    data[interview_id] = {
        "answers": answers,
        "final_score": final_score,
        "overall_feedback": overall_feedback
    }

    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# =============================
# INTERVIEW LOGIC
# =============================

def run_interview(interview_id):
    global STOP_INTERVIEW, answers_collected

    STOP_INTERVIEW = False
    answers_collected = []


    speech_warnings = 0

    # INTRODUCTION FIRST
    proceed = handle_introduction()
    if not proceed:
        return

    questions_data = load_questions_by_interview_id(interview_id)
    questions = [q["text"] for q in questions_data]

    print("\n=== 🎤 TECHNICAL INTERVIEW STARTED ===\n")



    for i, q in enumerate(questions, 1):
        if STOP_INTERVIEW:
            print("⛔ Interview auto-submitted")
            break

        print(f"\nQuestion {i}: {q}")
        speak(q, i)

        # ✅ CODING QUESTION → OPEN POPUP
        if is_coding_question(q):

            print("🧑‍💻 Coding Question Detected → Opening Popup Editor")

            code_answer = open_coding_popup(q, i)

            answers_collected.append({
                "question": q,
                "answer": code_answer if code_answer else "(Not submitted)"
            })

            continue


        # ✅ NORMAL SPEECH QUESTION
        print("🎙️ Listening for answer...")
        answer, audio = listen_user_answer()

        print("Candidate Answer:", answer)

        answers_collected.append({
            "question": q,
            "answer": answer
        })



        fraud = detect_voice_change(audio)
        if fraud:
            speech_warnings += 1
            print(f"⚠️ SPEECH WARNING {speech_warnings}/{MAX_WARNINGS}: {fraud}")

            if speech_warnings >= MAX_WARNINGS:
                print("⛔ Interview auto-submitted due to SPEECH fraud")
                STOP_INTERVIEW = True
                break

    print("\n✅ Interview ended")
    
    print("\n--- 📊 EVALUATION REPORT ---")
    

    results, final_score, overall_feedback = evaluate_answers(answers_collected)
    for i, r in enumerate(results, 1):
        print(f"\nQuestion {i}: {r['question']}")
        print(f"Score: {r['score']}/10")
        print(f"Feedback: {r['feedback']}")

    print(f"\nFinal Interview Score: {final_score}/10")
    print(f"Overall Feedback: {overall_feedback}")
    
    save_candidate_answers(
    interview_id,
    answers_collected,
    final_score,
    overall_feedback
)

# ============================= 
# MAIN
# =============================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Interview ID not provided")
        sys.exit(1)

    interview_id = sys.argv[1]

    threading.Thread(target=run_video_proctoring, daemon=True).start()
    threading.Thread(target=run_app_monitoring, daemon=True).start()

    try:
        run_interview(interview_id)
    except Exception as e:
        print("❌ Error:", e)



