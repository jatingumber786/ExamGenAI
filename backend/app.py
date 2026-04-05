from __future__ import annotations

import json
import os
import random
import re
from datetime import datetime
from functools import wraps
from pathlib import Path
from tempfile import NamedTemporaryFile

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
SERVERLESS_TEMP_DIR = Path(os.getenv("TMPDIR", os.getenv("TEMP", "/tmp")))
DEFAULT_SQLITE_PATH = (SERVERLESS_TEMP_DIR / "portal.db") if os.getenv("VERCEL") else (PROJECT_ROOT / "portal.db")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}")
IS_SQLITE = DATABASE_URL.startswith("sqlite")
UPLOAD_DIR = SERVERLESS_TEMP_DIR
GENERATED_DIR = SERVERLESS_TEMP_DIR
ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".docx", ".pdf"}
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "").strip().lower()

QUESTION_TYPE_LABELS = {
    "mcq": "MCQ",
    "fill_blanks": "Fill in the blanks",
    "very_short": "Very short answer",
    "short": "Short answer",
    "long": "Long answer",
    "two_mark": "2 marks",
    "five_mark": "5 marks",
    "ten_mark": "10 marks",
}

QUESTION_TYPE_DEFAULTS = [
    "mcq",
    "fill_blanks",
    "very_short",
    "short",
    "long",
    "two_mark",
    "five_mark",
    "ten_mark",
]

SUBJECT_RUBRICS = {
    "science": {
        "focus": "concept accuracy, terminology, and scientific explanation",
        "keywords": ["define", "process", "experiment", "reason", "observation", "result"],
    },
    "mathematics": {
        "focus": "formula usage, method, logical steps, and final answer accuracy",
        "keywords": ["formula", "solve", "step", "calculation", "proof", "result"],
    },
    "english": {
        "focus": "clarity, grammar, interpretation, and expression quality",
        "keywords": ["meaning", "theme", "grammar", "tone", "summary", "expression"],
    },
    "social science": {
        "focus": "facts, chronology, explanation, and cause-effect reasoning",
        "keywords": ["cause", "effect", "event", "reason", "history", "impact"],
    },
    "computer science": {
        "focus": "technical correctness, terminology, syntax awareness, and application",
        "keywords": ["algorithm", "syntax", "logic", "output", "function", "program"],
    },
    "general subject": {
        "focus": "coverage, relevance, and completeness",
        "keywords": ["concept", "example", "point", "reason", "detail", "application"],
    },
}


app = Flask(
    __name__,
    template_folder=str(FRONTEND_DIR / "templates"),
    static_folder=str(FRONTEND_DIR / "static"),
    static_url_path="/static",
)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config["DATABASE_URL"] = DATABASE_URL


def build_engine() -> Engine:
    connect_args = {}
    if IS_SQLITE:
        connect_args["check_same_thread"] = False
    return create_engine(DATABASE_URL, future=True, connect_args=connect_args)


engine = build_engine()


def ensure_directories() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def db_all(query: str, params: dict[str, object] | None = None) -> list[dict[str, object]]:
    with engine.begin() as connection:
        result = connection.execute(text(query), params or {})
        return [dict(row) for row in result.mappings().all()]


def db_one(query: str, params: dict[str, object] | None = None) -> dict[str, object] | None:
    rows = db_all(query, params)
    return rows[0] if rows else None


def db_execute(query: str, params: dict[str, object] | None = None) -> None:
    with engine.begin() as connection:
        connection.execute(text(query), params or {})


def db_insert(query: str, params: dict[str, object] | None = None) -> int | None:
    with engine.begin() as connection:
        result = connection.execute(text(query), params or {})
        inserted = result.scalar_one_or_none() if result.returns_rows else None
        if inserted is not None:
            return int(inserted)
    return None


@app.teardown_appcontext
def close_db(_: object | None) -> None:
    g.pop("db", None)


def init_db() -> None:
    id_column = "INTEGER PRIMARY KEY AUTOINCREMENT" if IS_SQLITE else "INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS teachers (
                    id PLACEHOLDER_ID,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
                .replace("PLACEHOLDER_ID", id_column)
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS evaluations (
                    id PLACEHOLDER_ID,
                    teacher_id INTEGER NOT NULL,
                    student_name TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    total_marks REAL NOT NULL,
                    marks_obtained REAL NOT NULL,
                    percentage REAL NOT NULL,
                    performance_band TEXT NOT NULL,
                    strengths TEXT NOT NULL,
                    improvements TEXT NOT NULL,
                    answer_key TEXT NOT NULL,
                    student_answers TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    rubric_name TEXT NOT NULL DEFAULT 'General Subject',
                    question_breakdown TEXT NOT NULL DEFAULT '[]',
                    class_name TEXT NOT NULL DEFAULT 'Not Set',
                    section_name TEXT NOT NULL DEFAULT 'Not Set'
                )
                """
                .replace("PLACEHOLDER_ID", id_column)
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS generated_papers (
                    id PLACEHOLDER_ID,
                    teacher_id INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    exam_title TEXT NOT NULL DEFAULT 'Generated Question Paper',
                    grade TEXT NOT NULL,
                    duration TEXT NOT NULL,
                    marks TEXT NOT NULL,
                    difficulty_level TEXT NOT NULL DEFAULT 'Medium',
                    question_types TEXT NOT NULL,
                    source_excerpt TEXT NOT NULL,
                    structured_data TEXT NOT NULL DEFAULT '[]',
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
                .replace("PLACEHOLDER_ID", id_column)
            )
        )

    try:
        db_execute("ALTER TABLE teachers ADD COLUMN created_at TEXT")
    except SQLAlchemyError:
        pass
    try:
        db_execute("UPDATE teachers SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at = ''")
    except SQLAlchemyError:
        pass
    try:
        db_execute("ALTER TABLE evaluations ADD COLUMN rubric_name TEXT NOT NULL DEFAULT 'General Subject'")
    except SQLAlchemyError:
        pass
    try:
        db_execute("ALTER TABLE evaluations ADD COLUMN question_breakdown TEXT NOT NULL DEFAULT '[]'")
    except SQLAlchemyError:
        pass
    try:
        db_execute("ALTER TABLE evaluations ADD COLUMN class_name TEXT NOT NULL DEFAULT 'Not Set'")
    except SQLAlchemyError:
        pass
    try:
        db_execute("ALTER TABLE evaluations ADD COLUMN section_name TEXT NOT NULL DEFAULT 'Not Set'")
    except SQLAlchemyError:
        pass
    try:
        db_execute("ALTER TABLE generated_papers ADD COLUMN exam_title TEXT NOT NULL DEFAULT 'Generated Question Paper'")
    except SQLAlchemyError:
        pass
    try:
        db_execute("ALTER TABLE generated_papers ADD COLUMN difficulty_level TEXT NOT NULL DEFAULT 'Medium'")
    except SQLAlchemyError:
        pass
    try:
        db_execute("ALTER TABLE generated_papers ADD COLUMN structured_data TEXT NOT NULL DEFAULT '[]'")
    except SQLAlchemyError:
        pass


ensure_directories()
init_db()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "teacher_id" not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for("auth"))
        return view(*args, **kwargs)

    return wrapped_view


def owner_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "teacher_id" not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for("auth"))
        if not session.get("is_owner"):
            flash("Owner access is required for this page.", "danger")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)

    return wrapped_view


OWNER_CREDENTIALS = {
    "jatingumber": "23bcs10547",
    "kumarishristi": "23bcs10551",
}


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def extract_text_from_upload(uploaded_file) -> str:
    suffix = Path(uploaded_file.filename).suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".py"}:
        return uploaded_file.read().decode("utf-8", errors="ignore")

    temp_file = NamedTemporaryFile(delete=False, suffix=suffix, dir=UPLOAD_DIR)
    temp_path = Path(temp_file.name)
    temp_file.close()
    uploaded_file.save(temp_path)

    try:
        if suffix == ".docx":
            from docx import Document

            document = Document(temp_path)
            return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())

        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(temp_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
    finally:
        temp_path.unlink(missing_ok=True)

    return ""


def clean_lines(raw_text: str) -> list[str]:
    lines = [line.strip(" -*\t") for line in raw_text.splitlines()]
    meaningful = [line for line in lines if len(line) > 2]
    if meaningful:
        return meaningful

    chunks = re.split(r"[.;,\n]", raw_text)
    return [chunk.strip() for chunk in chunks if len(chunk.strip()) > 2]


def extract_topics(raw_text: str) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()

    for line in clean_lines(raw_text):
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized:
            continue
        truncated = " ".join(normalized.split()[:16])
        key = truncated.lower()
        if key not in seen:
            seen.add(key)
            topics.append(truncated)
        if len(topics) >= 20:
            break

    return topics or [
        "Fundamental concepts",
        "Core principles",
        "Applications in daily life",
        "Analytical reasoning",
        "Advanced discussion",
    ]


def safe_fragment(topic: str) -> str:
    topic = re.sub(r"[^A-Za-z0-9\s]", "", topic).strip()
    words = topic.split()
    return " ".join(words[:4]) if words else "the topic"


def make_mcq(topic: str, index: int) -> str:
    clue = safe_fragment(topic)
    return (
        f"{index}. Which option best matches {topic}?\n"
        f"   A. Definition of {clue}\n"
        f"   B. Example of {clue}\n"
        f"   C. Incorrect statement about {clue}\n"
        f"   D. Unrelated concept\n"
    )


def make_fill_blank(topic: str, index: int) -> str:
    clue = safe_fragment(topic)
    return f"{index}. __________ is closely related to {clue}."


def make_very_short(topic: str, index: int) -> str:
    return f"{index}. Write one or two lines on {topic}."


def make_short(topic: str, index: int) -> str:
    return f"{index}. Explain {topic} briefly with an example."


def make_long(topic: str, index: int) -> str:
    return f"{index}. Discuss {topic} in detail with suitable points and examples."


def make_marks_question(topic: str, index: int, mark_value: int) -> str:
    if mark_value == 2:
        return f"{index}. State any two key points about {topic}. (2 marks)"
    if mark_value == 5:
        return f"{index}. Explain {topic} with supporting details. (5 marks)"
    return f"{index}. Write a detailed note on {topic} with classroom relevance and examples. (10 marks)"


def build_section(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return ["", title, *items]


def build_question_paper(
    subject: str,
    grade: str,
    duration: str,
    marks: str,
    raw_text: str,
    selected_types: list[str],
) -> str:
    topics = extract_topics(raw_text)
    pool = topics[:]
    random.shuffle(pool)
    if len(pool) < 12:
        pool.extend(topics[: 12 - len(pool)])

    pointer = 0

    def take_topics(count: int) -> list[str]:
        nonlocal pointer
        chosen: list[str] = []
        for _ in range(count):
            chosen.append(pool[pointer % len(pool)])
            pointer += 1
        return chosen

    lines = [
        "QUESTION PAPER",
        f"Subject: {subject}",
        f"Class/Level: {grade}",
        f"Duration: {duration}",
        f"Maximum Marks: {marks}",
        "",
        "Instructions:",
        "- Read all questions carefully.",
        "- Follow the marks weightage mentioned with each question.",
    ]

    if "mcq" in selected_types:
        mcqs = [make_mcq(topic, i) for i, topic in enumerate(take_topics(4), start=1)]
        lines.extend(build_section("Section A: MCQ", mcqs))

    if "fill_blanks" in selected_types:
        fills = [make_fill_blank(topic, i) for i, topic in enumerate(take_topics(4), start=1)]
        lines.extend(build_section("Section B: Fill in the blanks", fills))

    if "very_short" in selected_types:
        very_short = [make_very_short(topic, i) for i, topic in enumerate(take_topics(4), start=1)]
        lines.extend(build_section("Section C: Very short answer", very_short))

    if "short" in selected_types:
        short_qs = [make_short(topic, i) for i, topic in enumerate(take_topics(4), start=1)]
        lines.extend(build_section("Section D: Short answer", short_qs))

    if "long" in selected_types:
        long_qs = [make_long(topic, i) for i, topic in enumerate(take_topics(3), start=1)]
        lines.extend(build_section("Section E: Long answer", long_qs))

    if "two_mark" in selected_types:
        two_mark_qs = [make_marks_question(topic, i, 2) for i, topic in enumerate(take_topics(4), start=1)]
        lines.extend(build_section("Section F: 2 mark questions", two_mark_qs))

    if "five_mark" in selected_types:
        five_mark_qs = [make_marks_question(topic, i, 5) for i, topic in enumerate(take_topics(4), start=1)]
        lines.extend(build_section("Section G: 5 mark questions", five_mark_qs))

    if "ten_mark" in selected_types:
        ten_mark_qs = [make_marks_question(topic, i, 10) for i, topic in enumerate(take_topics(3), start=1)]
        lines.extend(build_section("Section H: 10 mark questions", ten_mark_qs))

    return "\n".join(lines)


def question_type_title(question_type: str) -> str:
    mapping = {
        "mcq": "MCQ",
        "fill_blanks": "Fill in the Blank",
        "short": "Short Answer",
        "long": "Long Answer",
    }
    return mapping.get(question_type, question_type.replace("_", " ").title())


def expected_answer_for(topic: str, question_type: str, marks: int) -> str:
    if question_type == "mcq":
        return f"B) {topic} is applied correctly in the given context."
    if question_type == "fill_blanks":
        return topic
    if marks >= 10:
        return f"A complete answer should define {topic}, explain the core idea, include examples, and discuss its application."
    if marks >= 5:
        return f"A strong answer should explain {topic} with at least three clear supporting points."
    return f"A short answer should mention the key concept behind {topic} in one or two lines."


def build_structured_question_paper(
    subject: str,
    exam_title: str,
    difficulty_level: str,
    raw_text: str,
    selected_types: list[str],
    marks_plan: dict[int, int],
) -> tuple[list[dict[str, object]], str, int]:
    topics = extract_topics(raw_text)
    pool = topics[:]
    random.shuffle(pool)
    if len(pool) < 20:
        pool.extend(topics[: 20 - len(pool)])

    pointer = 0

    def next_topic() -> str:
        nonlocal pointer
        topic = pool[pointer % len(pool)]
        pointer += 1
        return topic

    def choose_type(mark_value: int, index: int) -> str:
        preferred = {
            2: [item for item in ["mcq", "fill_blanks", "short"] if item in selected_types],
            5: [item for item in ["short", "mcq", "fill_blanks"] if item in selected_types],
            10: [item for item in ["long", "short"] if item in selected_types],
        }
        options = preferred.get(mark_value) or selected_types
        return options[index % len(options)]

    questions: list[dict[str, object]] = []
    question_number = 1

    for mark_value in (2, 5, 10):
        count = marks_plan.get(mark_value, 0)
        for index in range(count):
            topic = next_topic()
            question_type = choose_type(mark_value, index)
            prompt = f"Explain {topic}."
            if question_type == "mcq":
                prompt = f"What is the most accurate statement about {topic}?"
            elif question_type == "fill_blanks":
                prompt = f"{topic} is closely associated with __________."
            elif question_type == "short":
                prompt = f"Write a concise answer on {topic}."
            elif question_type == "long":
                prompt = f"Discuss {topic} in detail with examples and applications."

            options: list[str] = []
            if question_type == "mcq":
                fragment = safe_fragment(topic)
                options = [
                    f"A) The first stage of {fragment}",
                    f"B) {fragment} is applied correctly in context",
                    f"C) An unrelated statement about {fragment}",
                    f"D) A definition from another topic",
                ]

            questions.append(
                {
                    "number": question_number,
                    "type": question_type,
                    "type_label": question_type_title(question_type),
                    "marks": mark_value,
                    "prompt": prompt,
                    "options": options,
                    "expected_answer": expected_answer_for(topic, question_type, mark_value),
                    "topic": topic,
                    "difficulty": difficulty_level,
                }
            )
            question_number += 1

    total_marks = sum(item["marks"] for item in questions)
    lines = [
        exam_title or "Generated Question Paper",
        f"Subject: {subject}",
        f"Difficulty: {difficulty_level}",
        f"Maximum Marks: {total_marks}",
        "",
    ]
    for question in questions:
        lines.append(
            f"{question['number']}. ({question['type_label']} - {question['marks']} marks) {question['prompt']}"
        )
        for option in question["options"]:
            lines.append(option)
        lines.append(f"Expected Answer: {question['expected_answer']}")
        lines.append("")

    return questions, "\n".join(lines).strip(), total_marks


def save_question_paper(
    teacher_id: int,
    subject: str,
    exam_title: str,
    grade: str,
    duration: str,
    marks: str,
    difficulty_level: str,
    selected_types: list[str],
    source_text: str,
    structured_data: list[dict[str, object]],
    content: str,
) -> int | None:
    query = """
        INSERT INTO generated_papers (
            teacher_id, subject, exam_title, grade, duration, marks, difficulty_level, question_types,
            source_excerpt, structured_data, content, created_at
        )
        VALUES (:teacher_id, :subject, :exam_title, :grade, :duration, :marks, :difficulty_level, :question_types,
                :source_excerpt, :structured_data, :content, :created_at)
        RETURNING id
    """
    if IS_SQLITE:
        db_execute(
            """
            INSERT INTO generated_papers (
                teacher_id, subject, exam_title, grade, duration, marks, difficulty_level, question_types,
                source_excerpt, structured_data, content, created_at
            )
            VALUES (:teacher_id, :subject, :exam_title, :grade, :duration, :marks, :difficulty_level, :question_types,
                    :source_excerpt, :structured_data, :content, :created_at)
            """,
            {
                "teacher_id": teacher_id,
                "subject": subject,
                "exam_title": exam_title,
                "grade": grade,
                "duration": duration,
                "marks": marks,
                "difficulty_level": difficulty_level,
                "question_types": json.dumps(selected_types),
                "source_excerpt": source_text[:1500],
                "structured_data": json.dumps(structured_data),
                "content": content,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        row = db_one("SELECT id FROM generated_papers WHERE teacher_id = :teacher_id ORDER BY id DESC LIMIT 1", {"teacher_id": teacher_id})
        return int(row["id"]) if row else None

    return db_insert(
        query,
        {
            "teacher_id": teacher_id,
            "subject": subject,
            "exam_title": exam_title,
            "grade": grade,
            "duration": duration,
            "marks": marks,
            "difficulty_level": difficulty_level,
            "question_types": json.dumps(selected_types),
            "source_excerpt": source_text[:1500],
            "structured_data": json.dumps(structured_data),
            "content": content,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


def latest_generated_paper(teacher_id: int) -> dict[str, object] | None:
    return db_one(
        """
        SELECT id, content, subject, exam_title, grade, duration, marks, difficulty_level, structured_data, created_at
        FROM generated_papers
        WHERE teacher_id = :teacher_id
        ORDER BY id DESC
        LIMIT 1
        """,
        {"teacher_id": teacher_id},
    )


def owner_insights() -> dict[str, object]:
    totals = db_one(
        """
        SELECT
            (SELECT COUNT(*) FROM teachers) AS total_teachers,
            (SELECT COUNT(*) FROM generated_papers) AS total_papers,
            (SELECT COUNT(*) FROM evaluations) AS total_evaluations
        """
    ) or {"total_teachers": 0, "total_papers": 0, "total_evaluations": 0}
    recent_teachers = db_all(
        """
        SELECT full_name, email, created_at
        FROM teachers
        ORDER BY id DESC
        LIMIT 8
        """
    )
    teacher_activity = db_all(
        """
        SELECT t.full_name AS label, COUNT(g.id) AS papers
        FROM teachers t
        LEFT JOIN generated_papers g ON g.teacher_id = t.id
        GROUP BY t.id, t.full_name
        ORDER BY papers DESC, t.full_name ASC
        LIMIT 8
        """
    )
    evaluation_activity = db_all(
        """
        SELECT t.full_name AS label, COUNT(e.id) AS evaluations
        FROM teachers t
        LEFT JOIN evaluations e ON e.teacher_id = t.id
        GROUP BY t.id, t.full_name
        ORDER BY evaluations DESC, t.full_name ASC
        LIMIT 8
        """
    )
    teacher_records = db_all(
        """
        SELECT
            t.id,
            t.full_name,
            t.email,
            t.created_at,
            COUNT(DISTINCT g.id) AS papers,
            COUNT(DISTINCT e.id) AS evaluations
        FROM teachers t
        LEFT JOIN generated_papers g ON g.teacher_id = t.id
        LEFT JOIN evaluations e ON e.teacher_id = t.id
        GROUP BY t.id, t.full_name, t.email, t.created_at
        ORDER BY t.id DESC
        """
    )
    return {
        "totals": totals,
        "recent_teachers": recent_teachers,
        "teacher_records": teacher_records,
        "paper_bars": build_bar_data(teacher_activity, "label", "papers"),
        "evaluation_bars": build_bar_data(evaluation_activity, "label", "evaluations"),
    }


def create_pdf(title: str, lines: list[str], output_name: str) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    temp_file = NamedTemporaryFile(delete=False, suffix=".pdf", dir=GENERATED_DIR)
    temp_path = Path(temp_file.name)
    temp_file.close()

    pdf = canvas.Canvas(str(temp_path), pagesize=A4)
    width, height = A4
    y = height - 50
    pdf.setTitle(title)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, title)
    y -= 28
    pdf.setFont("Helvetica", 11)

    for raw_line in lines:
        wrapped = [raw_line[i:i + 95] for i in range(0, len(raw_line), 95)] or [""]
        for line in wrapped:
            if y < 50:
                pdf.showPage()
                y = height - 50
                pdf.setFont("Helvetica", 11)
            pdf.drawString(40, y, line)
            y -= 16

    pdf.save()
    return temp_path


def parse_answer_lines(raw_text: str) -> list[str]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if lines:
        return lines
    return [part.strip() for part in raw_text.split("||") if part.strip()]


def tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9]+", text.lower()) if len(token) > 2}


def rubric_for_subject(subject: str) -> tuple[str, dict[str, object]]:
    normalized = subject.strip().lower()
    rubric = SUBJECT_RUBRICS.get(normalized, SUBJECT_RUBRICS["general subject"])
    rubric_name = subject.strip().title() if normalized in SUBJECT_RUBRICS else "General Subject"
    return rubric_name, rubric


def evaluate_answers(subject: str, answer_key: str, student_answers: str) -> dict[str, object]:
    key_items = parse_answer_lines(answer_key)
    student_items = parse_answer_lines(student_answers)
    rubric_name, rubric = rubric_for_subject(subject)
    max_len = max(len(key_items), len(student_items), 1)
    while len(key_items) < max_len:
        key_items.append("")
    while len(student_items) < max_len:
        student_items.append("")

    question_results: list[dict[str, object]] = []
    marks_obtained = 0.0
    total_marks = float(max_len * 10)

    for index, (key, answer) in enumerate(zip(key_items, student_items), start=1):
        key_tokens = tokenize(key)
        answer_tokens = tokenize(answer)
        if not key_tokens and not answer_tokens:
            score_ratio = 0.0
        elif not key_tokens:
            score_ratio = 0.35
        else:
            overlap = len(key_tokens & answer_tokens)
            score_ratio = overlap / max(len(key_tokens), 1)
        keyword_hits = sum(1 for keyword in rubric["keywords"] if keyword in answer.lower())
        score_ratio = min(score_ratio + (keyword_hits * 0.03), 1.0)
        question_marks = round(min(score_ratio * 10, 10), 2)
        marks_obtained += question_marks
        feedback = "Needs more accuracy."
        if question_marks >= 8:
            feedback = "Strong answer with good coverage."
        elif question_marks >= 5:
            feedback = "Reasonable answer but more detail would help."
        question_results.append(
            {
                "number": index,
                "marks": question_marks,
                "out_of": 10,
                "feedback": feedback,
            }
        )

    percentage = round((marks_obtained / total_marks) * 100, 2) if total_marks else 0.0

    if percentage >= 85:
        performance_band = "Excellent"
    elif percentage >= 70:
        performance_band = "Very Good"
    elif percentage >= 55:
        performance_band = "Good"
    elif percentage >= 40:
        performance_band = "Average"
    else:
        performance_band = "Needs Improvement"

    strong_items = [item for item in question_results if item["marks"] >= 7]
    weak_items = [item for item in question_results if item["marks"] < 5]

    strengths = (
        f"Strong coverage in {len(strong_items)} answer(s) with attention to {rubric['focus']}."
        if strong_items
        else f"Student needs more complete answers with better focus on {rubric['focus']}."
    )
    improvements = (
        f"Focus on improving question(s): {', '.join(str(item['number']) for item in weak_items[:4])}."
        if weak_items
        else f"Maintain this consistency and add more precise detail based on the {rubric_name} rubric."
    )

    return {
        "question_results": question_results,
        "marks_obtained": round(marks_obtained, 2),
        "total_marks": round(total_marks, 2),
        "percentage": percentage,
        "performance_band": performance_band,
        "strengths": strengths,
        "improvements": improvements,
        "rubric_name": rubric_name,
        "rubric_focus": rubric["focus"],
    }


def evaluation_grade(percentage: float) -> str:
    if percentage >= 90:
        return "A+"
    if percentage >= 80:
        return "A"
    if percentage >= 70:
        return "B+"
    if percentage >= 60:
        return "B"
    if percentage >= 50:
        return "C"
    if percentage >= 40:
        return "D"
    return "F"


def combine_text_and_upload(form_value: str, uploaded_file) -> str:
    text_parts: list[str] = []
    if form_value.strip():
        text_parts.append(form_value.strip())

    if uploaded_file and uploaded_file.filename:
        if not allowed_file(uploaded_file.filename):
            raise ValueError("Unsupported file type.")
        extracted = extract_text_from_upload(uploaded_file).strip()
        if extracted:
            text_parts.append(extracted)

    return "\n".join(part for part in text_parts if part).strip()


def build_evaluation_detail_rows(answer_key: str, student_answers: str, breakdown: list[dict[str, object]]) -> list[dict[str, object]]:
    key_items = parse_answer_lines(answer_key)
    student_items = parse_answer_lines(student_answers)
    detail_rows: list[dict[str, object]] = []

    for index, item in enumerate(breakdown, start=1):
        expected = key_items[index - 1] if index - 1 < len(key_items) else ""
        answer = student_items[index - 1] if index - 1 < len(student_items) else ""
        prompt = expected
        if "answer:" in expected.lower():
            prompt = expected.split("Answer:", 1)[0].strip()
        prompt = prompt or f"Question {index}"

        detail_rows.append(
            {
                "number": index,
                "prompt": prompt,
                "expected_answer": expected,
                "student_answer": answer or "No answer provided.",
                "marks": item.get("marks", 0),
                "out_of": item.get("out_of", 10),
                "feedback": item.get("feedback", ""),
            }
        )

    return detail_rows


def teacher_average(teacher_id: int) -> float:
    row = db_one(
        "SELECT AVG(percentage) AS avg_percentage FROM evaluations WHERE teacher_id = :teacher_id",
        {"teacher_id": teacher_id},
    )
    if row and row["avg_percentage"] is not None:
        return round(float(row["avg_percentage"]), 2)
    return 0.0


def build_bar_data(rows: list[dict[str, object]], label_key: str, value_key: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    max_value = max((float(row[value_key] or 0) for row in rows), default=0.0)
    for row in rows:
        value = round(float(row[value_key] or 0), 2)
        width = round((value / max_value) * 100, 2) if max_value else 0.0
        items.append({"label": row[label_key], "value": value, "width": width})
    return items


def fetch_history_analytics(teacher_id: int) -> dict[str, object]:
    subject_rows = db_all(
        """
        SELECT subject AS label, AVG(percentage) AS value
        FROM evaluations
        WHERE teacher_id = :teacher_id
        GROUP BY subject
        ORDER BY value DESC, subject ASC
        LIMIT 6
        """,
        {"teacher_id": teacher_id},
    )
    class_rows = db_all(
        """
        SELECT (class_name || ' - ' || section_name) AS label, AVG(percentage) AS value
        FROM evaluations
        WHERE teacher_id = :teacher_id
        GROUP BY class_name, section_name
        ORDER BY value DESC, class_name ASC, section_name ASC
        LIMIT 8
        """,
        {"teacher_id": teacher_id},
    )
    band_rows = db_all(
        """
        SELECT performance_band, COUNT(*) AS total
        FROM evaluations
        WHERE teacher_id = :teacher_id
        GROUP BY performance_band
        ORDER BY total DESC
        """,
        {"teacher_id": teacher_id},
    )
    recent_rows = db_all(
        """
        SELECT student_name, subject, class_name, section_name, percentage, created_at
        FROM evaluations
        WHERE teacher_id = :teacher_id
        ORDER BY id DESC
        LIMIT 6
        """,
        {"teacher_id": teacher_id},
    )

    total_bands = sum(int(row["total"]) for row in band_rows) or 1
    band_data = [
        {
            "label": row["performance_band"],
            "value": int(row["total"]),
            "width": round((int(row["total"]) / total_bands) * 100, 2),
        }
        for row in band_rows
    ]

    return {
        "subject_bars": build_bar_data(subject_rows, "label", "value"),
        "class_bars": build_bar_data(class_rows, "label", "value"),
        "band_bars": band_data,
        "recent_rows": recent_rows,
    }


@app.route("/")
def landing():
    signed_in = bool(session.get("teacher_id"))
    return render_template("landing.html", signed_in=signed_in)


@app.route("/auth", methods=["GET", "POST"])
def auth():
    if session.get("teacher_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        mode = request.form.get("mode", "login").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        login_id = request.form.get("login_id", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if mode == "signup":
            if not full_name or not email or not password:
                flash("Enter full name, email, and password to create an account.", "danger")
                return render_template("auth.html", active_mode="signup")
            if "@" not in email or "." not in email:
                flash("Enter a valid email address.", "danger")
                return render_template("auth.html", active_mode="signup")
            if len(password) < 6:
                flash("Password must be at least 6 characters long.", "danger")
                return render_template("auth.html", active_mode="signup")
            if password != confirm_password:
                flash("Password and confirm password do not match.", "danger")
                return render_template("auth.html", active_mode="signup")

            existing = db_one("SELECT id FROM teachers WHERE LOWER(email) = :email", {"email": email})
            if existing:
                flash("An account with this email already exists. Please sign in instead.", "warning")
                return render_template("auth.html", active_mode="login")

            teacher_id = db_insert(
                """
                INSERT INTO teachers (full_name, email, password_hash, created_at)
                VALUES (:full_name, :email, :password_hash, :created_at)
                RETURNING id
                """,
                {
                    "full_name": full_name,
                    "email": email,
                    "password_hash": generate_password_hash(password),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            if teacher_id is None and IS_SQLITE:
                row = db_one(
                    "SELECT id FROM teachers WHERE LOWER(email) = :email ORDER BY id DESC LIMIT 1",
                    {"email": email},
                )
                teacher_id = int(row["id"]) if row else None

            if teacher_id is None:
                flash("We could not create the account right now. Please try again.", "danger")
                return render_template("auth.html", active_mode="signup")

            session.clear()
            session["teacher_id"] = teacher_id
            session["teacher_name"] = full_name
            session["teacher_email"] = email
            session["is_owner"] = False
            flash("Account created successfully. You are now signed in.", "success")
            return redirect(url_for("dashboard"))

        if not email or not password:
            login_id = login_id or email

        if not login_id or not password:
            flash("Enter your email or username and password to sign in.", "danger")
            return render_template("auth.html", active_mode="login")

        if login_id in OWNER_CREDENTIALS and password == OWNER_CREDENTIALS[login_id]:
            session.clear()
            session["teacher_id"] = 0
            session["teacher_name"] = "Jatin Gumber" if login_id == "jatingumber" else "Kumari Shristi"
            session["teacher_email"] = login_id
            session["is_owner"] = True
            flash("Owner signed in successfully.", "success")
            return redirect(url_for("owner"))

        teacher = db_one(
            """
            SELECT id, full_name, email, password_hash
            FROM teachers
            WHERE LOWER(email) = :email
            """,
            {"email": login_id.lower()},
        )

        if teacher and check_password_hash(str(teacher["password_hash"]), password):
            session.clear()
            session["teacher_id"] = int(teacher["id"])
            session["teacher_name"] = str(teacher["full_name"])
            session["teacher_email"] = str(teacher["email"])
            session["is_owner"] = False
            flash("Signed in successfully.", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email/username or password.", "danger")
        return render_template("auth.html", active_mode="login")

    return render_template("auth.html", active_mode="login")


@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    wizard = session.get("paper_wizard", {})

    if request.method == "POST":
        subject = request.form.get("subject", "").strip() or "General Subject"
        exam_title = request.form.get("exam_title", "").strip() or "Generated Question Paper"
        manual_text = request.form.get("content", "").strip()
        uploaded_file = request.files.get("file")
        source_text = manual_text
        uploaded_name = ""

        if uploaded_file and uploaded_file.filename:
            if not allowed_file(uploaded_file.filename):
                flash("Unsupported file type. Upload TXT, MD, CSV, JSON, PY, DOCX, or PDF.", "danger")
                return render_template("dashboard.html", wizard=wizard)
            uploaded_name = uploaded_file.filename
            extracted_text = extract_text_from_upload(uploaded_file)
            source_text = f"{manual_text}\n{extracted_text}".strip()

        if not source_text:
            flash("Upload study material or paste text before continuing.", "danger")
            return render_template("dashboard.html", wizard=wizard)

        session["paper_wizard"] = {
            "subject": subject,
            "exam_title": exam_title,
            "source_text": source_text,
            "uploaded_name": uploaded_name or "Pasted content",
        }
        return redirect(url_for("configure_paper"))

    return render_template("dashboard.html", wizard=wizard)


@app.route("/dashboard/configure", methods=["GET", "POST"])
@login_required
def configure_paper():
    wizard = session.get("paper_wizard")
    if not wizard:
        flash("Start by uploading study material first.", "warning")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        selected_types = request.form.getlist("question_types")
        if not selected_types:
            flash("Select at least one question type.", "danger")
            return render_template("configure.html", wizard=wizard, question_types=QUESTION_TYPE_LABELS)

        difficulty_level = request.form.get("difficulty_level", "").strip() or "Medium - Application-based questions"
        count_2 = max(int(request.form.get("count_2", 5) or 0), 0)
        count_5 = max(int(request.form.get("count_5", 3) or 0), 0)
        count_10 = max(int(request.form.get("count_10", 2) or 0), 0)
        marks_plan = {2: count_2, 5: count_5, 10: count_10}

        questions, paper_text, total_marks = build_structured_question_paper(
            wizard["subject"],
            wizard["exam_title"],
            difficulty_level,
            wizard["source_text"],
            selected_types,
            marks_plan,
        )

        paper_id = save_question_paper(
            session["teacher_id"],
            wizard["subject"],
            wizard["exam_title"],
            wizard["exam_title"],
            "60 Minutes",
            str(total_marks),
            difficulty_level,
            selected_types,
            wizard["source_text"],
            questions,
            paper_text,
        )
        session["latest_generated_paper_id"] = paper_id
        return redirect(url_for("generated_paper"))

    return render_template("configure.html", wizard=wizard, question_types=QUESTION_TYPE_LABELS)


@app.route("/dashboard/generated")
@login_required
def generated_paper():
    paper_id = session.get("latest_generated_paper_id")
    paper = None
    if paper_id:
        paper = db_one(
            """
            SELECT id, subject, exam_title, marks, content, structured_data, created_at
            FROM generated_papers
            WHERE id = :paper_id AND teacher_id = :teacher_id
            """,
            {"paper_id": paper_id, "teacher_id": session["teacher_id"]},
        )
    if paper is None:
        paper = latest_generated_paper(session["teacher_id"])
    if paper is None:
        flash("Generate a question paper first.", "warning")
        return redirect(url_for("dashboard"))

    paper["questions"] = json.loads(paper.get("structured_data") or "[]")
    return render_template("generated.html", paper=paper)


@app.route("/dashboard/start-over")
@login_required
def start_over_paper():
    session.pop("paper_wizard", None)
    session.pop("latest_generated_paper_id", None)
    flash("Question paper flow reset. Start again from upload.", "success")
    return redirect(url_for("dashboard"))


@app.route("/evaluate", methods=["GET", "POST"])
@login_required
def evaluate():
    if request.method == "POST":
        student_name = request.form.get("student_name", "").strip() or "Student"
        subject = request.form.get("subject", "").strip() or "General Subject"
        class_name = request.form.get("class_name", "").strip() or "Not Set"
        section_name = request.form.get("section_name", "").strip() or "Not Set"
        answer_key_file = request.files.get("answer_key_file")
        student_answers_file = request.files.get("student_answers_file")

        try:
            answer_key = combine_text_and_upload(request.form.get("answer_key", ""), answer_key_file)
            student_answers = combine_text_and_upload(
                request.form.get("student_answers", ""),
                student_answers_file,
            )
        except ValueError:
            flash("Please upload only supported files such as PDF, TXT, MD, DOCX, or CSV.", "danger")
            return render_template("evaluate.html")

        if not answer_key or not student_answers:
            flash("Enter or upload both the answer key and the student's answers.", "danger")
        else:
            result = evaluate_answers(subject, answer_key, student_answers)
            inserted_id = db_insert(
                """
                INSERT INTO evaluations (
                    teacher_id,
                    student_name,
                    subject,
                    class_name,
                    section_name,
                    total_marks,
                    marks_obtained,
                    percentage,
                    performance_band,
                    strengths,
                    improvements,
                    answer_key,
                    student_answers,
                    created_at,
                    rubric_name,
                    question_breakdown
                ) VALUES (
                    :teacher_id, :student_name, :subject, :class_name, :section_name,
                    :total_marks, :marks_obtained, :percentage, :performance_band, :strengths,
                    :improvements, :answer_key, :student_answers, :created_at, :rubric_name, :question_breakdown
                )
                RETURNING id
                """,
                {
                    "teacher_id": session["teacher_id"],
                    "student_name": student_name,
                    "subject": subject,
                    "class_name": class_name,
                    "section_name": section_name,
                    "total_marks": result["total_marks"],
                    "marks_obtained": result["marks_obtained"],
                    "percentage": result["percentage"],
                    "performance_band": result["performance_band"],
                    "strengths": result["strengths"],
                    "improvements": result["improvements"],
                    "answer_key": answer_key,
                    "student_answers": student_answers,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "rubric_name": result["rubric_name"],
                    "question_breakdown": json.dumps(result["question_results"]),
                },
            )
            if inserted_id is None and IS_SQLITE:
                row = db_one(
                    "SELECT id FROM evaluations WHERE teacher_id = :teacher_id ORDER BY id DESC LIMIT 1",
                    {"teacher_id": session["teacher_id"]},
                )
                inserted_id = int(row["id"]) if row else None
            flash("Student answers evaluated and saved to history.", "success")
            if inserted_id is not None:
                return redirect(url_for("evaluate_result", evaluation_id=inserted_id))
            return redirect(url_for("history"))

    return render_template("evaluate.html")


@app.route("/evaluate/result/<int:evaluation_id>")
@login_required
def evaluate_result(evaluation_id: int):
    row = db_one(
        """
        SELECT id, student_name, subject, class_name, section_name, total_marks, marks_obtained,
               percentage, performance_band, strengths, improvements, answer_key, student_answers,
               created_at, rubric_name, question_breakdown
        FROM evaluations
        WHERE id = :evaluation_id AND teacher_id = :teacher_id
        """,
        {"evaluation_id": evaluation_id, "teacher_id": session["teacher_id"]},
    )

    if row is None:
        flash("Evaluation result not found.", "danger")
        return redirect(url_for("evaluate"))

    history_count_row = db_one(
        "SELECT COUNT(*) AS total FROM evaluations WHERE teacher_id = :teacher_id",
        {"teacher_id": session["teacher_id"]},
    )
    breakdown = json.loads(row["question_breakdown"] or "[]")
    result = dict(row)
    result["history_count"] = int(history_count_row["total"]) if history_count_row else 0
    result["class_average"] = teacher_average(session["teacher_id"])
    result["grade"] = evaluation_grade(float(row["percentage"] or 0))
    result["question_results"] = breakdown
    detail_rows = build_evaluation_detail_rows(
        str(row["answer_key"] or ""),
        str(row["student_answers"] or ""),
        breakdown,
    )
    return render_template("evaluate_result.html", result=result, detail_rows=detail_rows)


@app.route("/history")
@login_required
def history():
    rows = db_all(
        """
        SELECT id, student_name, subject, class_name, section_name, marks_obtained, total_marks, percentage,
               performance_band, strengths, improvements, created_at, rubric_name
        FROM evaluations
        WHERE teacher_id = :teacher_id
        ORDER BY id DESC
        """,
        {"teacher_id": session["teacher_id"]},
    )

    stats = db_one(
        """
        SELECT
            COUNT(*) AS total_students,
            AVG(percentage) AS average_percentage,
            MAX(percentage) AS best_percentage,
            MIN(percentage) AS lowest_percentage
        FROM evaluations
        WHERE teacher_id = :teacher_id
        """,
        {"teacher_id": session["teacher_id"]},
    ) or {"total_students": 0, "average_percentage": 0, "best_percentage": 0, "lowest_percentage": 0}

    analytics = fetch_history_analytics(session["teacher_id"])
    return render_template("history.html", records=rows, stats=stats, analytics=analytics)


@app.route("/history/delete", methods=["POST"])
@login_required
def delete_history_records():
    selected_ids = [value for value in request.form.getlist("evaluation_ids") if value.isdigit()]
    if not selected_ids:
        flash("Select at least one history record to delete.", "warning")
        return redirect(url_for("history"))

    deleted_count = 0
    for evaluation_id in selected_ids:
        row = db_one(
            "SELECT id FROM evaluations WHERE id = :evaluation_id AND teacher_id = :teacher_id",
            {"evaluation_id": int(evaluation_id), "teacher_id": session["teacher_id"]},
        )
        if row:
            db_execute(
                "DELETE FROM evaluations WHERE id = :evaluation_id AND teacher_id = :teacher_id",
                {"evaluation_id": int(evaluation_id), "teacher_id": session["teacher_id"]},
            )
            deleted_count += 1

    if deleted_count:
        flash(f"Deleted {deleted_count} history record(s). Analytics have been refreshed.", "success")
    else:
        flash("No matching history records were found to delete.", "warning")
    return redirect(url_for("history"))


@app.route("/owner")
@owner_required
def owner():
    insights = owner_insights()
    return render_template("owner.html", insights=insights)


@app.route("/owner/delete-teacher/<int:teacher_id>", methods=["POST"])
@owner_required
def owner_delete_teacher(teacher_id: int):
    row = db_one("SELECT id, full_name, email FROM teachers WHERE id = :teacher_id", {"teacher_id": teacher_id})
    if row is None:
        flash("Teacher account not found.", "warning")
        return redirect(url_for("owner"))

    db_execute("DELETE FROM generated_papers WHERE teacher_id = :teacher_id", {"teacher_id": teacher_id})
    db_execute("DELETE FROM evaluations WHERE teacher_id = :teacher_id", {"teacher_id": teacher_id})
    db_execute("DELETE FROM teachers WHERE id = :teacher_id", {"teacher_id": teacher_id})

    flash(f"Deleted teacher account for {row['full_name']}. That user must create a new account to sign in again.", "success")
    return redirect(url_for("owner"))


@app.route("/download-paper-pdf")
@login_required
def download_paper_pdf():
    latest = latest_generated_paper(session["teacher_id"])
    if latest is None:
        flash("Generate a question paper before downloading a PDF.", "warning")
        return redirect(url_for("dashboard"))

    pdf_path = create_pdf("Question Paper", str(latest["content"]).splitlines(), "question_paper.pdf")
    return send_file(pdf_path, as_attachment=True, download_name="question_paper.pdf")


@app.route("/evaluation-report/<int:evaluation_id>")
@login_required
def evaluation_report(evaluation_id: int):
    row = db_one(
        """
        SELECT id, student_name, subject, total_marks, marks_obtained, percentage,
               performance_band, strengths, improvements, created_at, rubric_name,
               class_name, section_name,
               question_breakdown
        FROM evaluations
        WHERE id = :evaluation_id AND teacher_id = :teacher_id
        """,
        {"evaluation_id": evaluation_id, "teacher_id": session["teacher_id"]},
    )

    if row is None:
        flash("Evaluation report not found.", "danger")
        return redirect(url_for("history"))

    breakdown = json.loads(row["question_breakdown"] or "[]")
    lines = [
        f"Student Name: {row['student_name']}",
        f"Subject: {row['subject']}",
        f"Class: {row['class_name']}",
        f"Section: {row['section_name']}",
        f"Rubric: {row['rubric_name']}",
        f"Marks: {row['marks_obtained']} / {row['total_marks']}",
        f"Percentage: {row['percentage']}%",
        f"Performance Band: {row['performance_band']}",
        f"Created At: {row['created_at']}",
        "",
        f"Strengths: {row['strengths']}",
        f"Areas to Improve: {row['improvements']}",
        "",
        "Question-wise Review:",
    ]
    for item in breakdown:
        lines.append(
            f"Q{item['number']}: {item['marks']} / {item['out_of']} - {item['feedback']}"
        )

    output_name = f"evaluation_report_{row['id']}.pdf"
    pdf_path = create_pdf("Student Evaluation Report", lines, output_name)
    return send_file(pdf_path, as_attachment=True, download_name=output_name)


@app.route("/download")
@login_required
def download():
    latest = latest_generated_paper(session["teacher_id"])
    if latest is None:
        flash("No generated question paper is available yet.", "warning")
        return redirect(url_for("dashboard"))
    temp_file = NamedTemporaryFile(delete=False, suffix=".txt", dir=GENERATED_DIR)
    temp_path = Path(temp_file.name)
    temp_file.write(str(latest["content"]).encode("utf-8"))
    temp_file.close()
    return send_file(temp_path, as_attachment=True, download_name="question_paper.txt")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth"))


if __name__ == "__main__":
    app.run(debug=True)
