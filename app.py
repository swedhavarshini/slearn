import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import matplotlib.pyplot as plt
import numpy as np

DB_PATH = "smartlearn.db"

# ========== DB Helpers ==========
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def ensure_tables():
    conn = get_conn()
    cur = conn.cursor()

    # Questions table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT UNIQUE,
        option_a TEXT,
        option_b TEXT,
        option_c TEXT,
        option_d TEXT,
        answer TEXT,
        subject TEXT,
        chapter TEXT,
        topic TEXT,
        difficulty TEXT,
        type TEXT
    );
    """)

    # Scores table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS student_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        question_id INTEGER,
        is_correct INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        role TEXT
    );
    """)

    conn.commit()
    conn.close()

def fetch_df(query, params=()):
    conn = get_conn()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def execute(query, params=()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    conn.close()

# ========== Authentication ==========
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate(username, password):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT password_hash, role FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    if row:
        stored_hash, role = row
        if stored_hash == hash_password(password):
            return True, role
    return False, None

def seed_users():
    conn = get_conn()
    cur = conn.cursor()
    demo_users = [
        ("student1", hash_password("1234"), "student"),
        ("teacher1", hash_password("admin"), "teacher"),
    ]
    for u in demo_users:
        try:
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", u)
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()

# ========== Dashboard ==========
def student_dashboard_ui(student_id):
    st.markdown("<h2 style='color:#4CAF50;'>📊 Dashboard</h2>", unsafe_allow_html=True)

    df_overall = fetch_df(
        "SELECT COUNT(*) AS attempted, SUM(is_correct) AS correct FROM student_scores WHERE student_id=?",
        (student_id,)
    )
    if df_overall.empty or df_overall.at[0, "attempted"] == 0:
        st.info("No attempts yet.")
        return

    attempted = int(df_overall.at[0, "attempted"])
    correct = int(df_overall.at[0, "correct"] or 0)
    accuracy = round(100.0 * correct / attempted, 2)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Attempted", attempted)
    col2.metric("Correct Answers", correct)
    col3.metric("Accuracy (%)", accuracy)

# ========== Take Test (Full Options + Stable Questions) ==========
def take_test_ui(student_id, subject=None, n_questions=5):
    st.markdown("<h2 style='color:#FF5722;'>📝 Take Test</h2>", unsafe_allow_html=True)

    # --- Load questions once ---
    if "test_questions" not in st.session_state or st.button("🔄 Start New Test"):
        conn = get_conn()
        cur = conn.cursor()
        if subject:
            cur.execute("""
                SELECT id, question, option_a, option_b, option_c, option_d, answer 
                FROM questions WHERE subject=? ORDER BY RANDOM() LIMIT ?
            """, (subject, n_questions))
        else:
            cur.execute("""
                SELECT id, question, option_a, option_b, option_c, option_d, answer 
                FROM questions ORDER BY RANDOM() LIMIT ?
            """, (n_questions,))
        st.session_state["test_questions"] = cur.fetchall()
        conn.close()

        # Reset previous answers
        for key in list(st.session_state.keys()):
            if key.startswith("q_"):
                del st.session_state[key]
        st.rerun()

    rows = st.session_state.get("test_questions", [])
    if not rows:
        st.warning("⚠️ No questions available.")
        return

    answers = {}
    total = len(rows)
    progress = st.progress(0)

    # --- Render each question ---
    for i, r in enumerate(rows, start=1):
        qid, qtext, a, b, c, d, ans = r
        st.markdown(f"<b>Q{i}.</b> {qtext}", unsafe_allow_html=True)

        options = [f"A. {a}", f"B. {b}", f"C. {c}", f"D. {d}"]

        if f"q_{qid}" not in st.session_state:
            st.session_state[f"q_{qid}"] = None

        choice = st.radio("Select an option:", options, key=f"q_{qid}")

        # Safe handling if no choice selected yet
        selected_letter = choice.split(".")[0] if choice else None
        answers[qid] = selected_letter
        progress.progress(int(i / total * 100))

    # --- Submit test ---
    if st.button("Submit Test"):
        unanswered = [qid for qid, ans in answers.items() if ans is None or ans == ""]
        if unanswered:
            st.warning("⚠️ Please answer all questions before submitting.")
        else:
            conn = get_conn()
            cur = conn.cursor()
            correct_count = 0
            for qid, user_choice in answers.items():
                cur.execute("SELECT answer FROM questions WHERE id=?", (qid,))
                row = cur.fetchone()
                correct_ans = row[0].strip().upper()[0] if row and row[0] else ""
                is_correct = 1 if user_choice == correct_ans else 0
                if is_correct:
                    correct_count += 1
                cur.execute(
                    "INSERT INTO student_scores (student_id, question_id, is_correct) VALUES (?, ?, ?)",
                    (student_id, qid, is_correct)
                )
            conn.commit()
            conn.close()

            xp = correct_count * 10
            st.success(f"✅ Score: {correct_count}/{total} ({round(100 * correct_count / total, 2)}%) | 🎯 XP Earned: {xp}")

            if correct_count == total:
                st.markdown("🏆 <b>Perfect Score!</b> 🌟", unsafe_allow_html=True)
            elif correct_count >= total - 1:
                st.markdown("🔥 <b>So Close! Excellent Work!</b>", unsafe_allow_html=True)
            elif correct_count >= total / 2:
                st.markdown("💪 <b>Good job, keep practicing!</b>", unsafe_allow_html=True)
            else:
                st.markdown("📈 <b>Don't give up! Focus on weak areas.</b>", unsafe_allow_html=True)

# ========== Leaderboard ==========
def leaderboard_ui():
    st.markdown("<h2 style='color:#9C27B0;'>🏆 Leaderboard</h2>", unsafe_allow_html=True)
    df = fetch_df("""
        SELECT s.student_id AS student,
               COUNT(s.id) AS attempted,
               SUM(s.is_correct) AS correct,
               SUM(s.is_correct)*10 AS xp,
               ROUND(100.0*SUM(s.is_correct)/COUNT(s.id),2) AS accuracy
        FROM student_scores s
        GROUP BY s.student_id
        ORDER BY xp DESC, accuracy DESC
    """)
    if df.empty:
        st.info("No scores yet.")
    else:
        df["Rank"] = range(1, len(df) + 1)
        st.dataframe(df)

# ========== Add Question ==========
def add_question_ui():
    st.markdown("<h2 style='color:#3F51B5;'>➕ Add Question</h2>", unsafe_allow_html=True)
    with st.form("add_q_form"):
        qtext = st.text_area("Question")
        opt_a = st.text_input("Option A")
        opt_b = st.text_input("Option B")
        opt_c = st.text_input("Option C")
        opt_d = st.text_input("Option D")
        answer = st.selectbox("Correct Answer", ("A", "B", "C", "D"))
        subject = st.text_input("Subject")
        chapter = st.text_input("Chapter")
        topic = st.text_input("Topic")
        difficulty = st.selectbox("Difficulty", ("Easy", "Medium", "Hard"))
        qtype = st.text_input("Type")
        submitted = st.form_submit_button("Add")
        if submitted:
            execute("""
                INSERT OR IGNORE INTO questions
                (question, option_a, option_b, option_c, option_d, answer, subject, chapter, topic, difficulty, type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (qtext, opt_a, opt_b, opt_c, opt_d, answer, subject, chapter, topic, difficulty, qtype))
            st.success("✅ Question added.")

# ========== App ==========
st.set_page_config(page_title="SmartLearn AI", layout="wide")
ensure_tables()
seed_users()

# ---- Login / Sign Up ----
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None

if not st.session_state.logged_in:
    st.title("🔑 SmartLearn AI")
    choice = st.radio("Select Option", ["Login", "Sign Up"])

    if choice == "Login":
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            ok, role = authenticate(username, password)
            if ok:
                st.session_state.logged_in = True
                st.session_state.user = username
                st.success(f"Welcome {username}")
                st.rerun()
            else:
                st.error("❌ Invalid credentials")

    elif choice == "Sign Up":
        new_user = st.text_input("Choose a Username")
        new_pass = st.text_input("Choose a Password", type="password")
        role = st.selectbox("Role", ["student", "teacher"])
        if st.button("Create Account"):
            if not new_user or not new_pass:
                st.warning("⚠️ Please fill all fields.")
            else:
                conn = get_conn()
                cur = conn.cursor()
                try:
                    cur.execute(
                        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                        (new_user, hash_password(new_pass), role))
                    conn.commit()
                    st.success("✅ Account created successfully! Please login.")
                except sqlite3.IntegrityError:
                    st.error("⚠️ Username already exists, try another.")
                conn.close()
    st.stop()

# ---- After Login ----
if st.session_state.logged_in:
    student_id = st.session_state.user
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Dashboard", "📝 Take Test", "🏆 Leaderboard", "🔥 Weekly Challenge", "➕ Add Question"
    ])

    with tab1:
        student_dashboard_ui(student_id)
    with tab2:
        subject = st.selectbox("Choose Subject", ["Physics", "Chemistry", "Biology"])
        take_test_ui(student_id, subject)
    with tab3:
        leaderboard_ui()
    with tab4:
        st.info("Weekly Challenge feature under development 🚧")
    with tab5:
        add_question_ui()
