from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import json
import re
import smtplib
from datetime import date, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from database import engine, get_db
from id_generator import generate_employee_id

app = FastAPI(title="School System API")
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# EMAIL SENDING (Gmail SMTP)
# Requires two environment variables set on Render:
#   EMAIL_ADDRESS       - the Gmail address sending on behalf of the school
#   EMAIL_APP_PASSWORD  - the 16-character Google App Password (NOT the login password)
# If either is missing, emails are skipped (logged, not sent) so the
# rest of the API keeps working even before email is configured.
# ============================================================

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_FROM_NAME = "Tiu Cho Teg - Ana Ros Foundation Integrated Farm School"

def send_email(to_email: Optional[str], subject: str, body: str):
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        print(f"[email skipped - not configured] to={to_email} subject={subject}")
        return
    if not to_email:
        print(f"[email skipped - no recipient] subject={subject}")
        return
    msg = MIMEMultipart()
    msg["From"] = f"{EMAIL_FROM_NAME} <{EMAIL_ADDRESS}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to_email, msg.as_string())
        print(f"[email sent] to={to_email} subject={subject}")
    except Exception as e:
        print(f"[email FAILED] to={to_email} subject={subject} error={e}")


# ============================================================
# Request/response shapes (Pydantic models)
# FastAPI uses these to validate incoming data automatically -
# if a request is missing a required field or has the wrong type,
# it rejects it before your code even runs.
# ============================================================

class DepartmentCreate(BaseModel):
    code: str
    name: str


class StrandCreate(BaseModel):
    name: str


class SubjectCreate(BaseModel):
    name: str
    grade_level: str
    strand_id: Optional[int] = None


class SectionCreate(BaseModel):
    grade_level: str
    strand_id: Optional[int] = None
    section_name: str


class TeacherCreate(BaseModel):
    first_name: str
    last_name: str
    phone_number: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None   # 'male' / 'female' / 'other'
    department_id: int


class AssignmentCreate(BaseModel):
    section_id: int
    subject_id: int
    teacher_id: int
    schedule_day: str
    start_time: str   # e.g. "08:00:00"
    end_time: str      # e.g. "09:00:00"


# ============================================================
# Health check (kept from the first version)
# ============================================================

@app.get("/")
def read_root():
    return {"message": "API is running"}


@app.get("/health/db")
def check_database_connection(db: Session = Depends(get_db)):
    try:
        result = db.execute(text("SHOW TABLES"))
        tables = [row[0] for row in result]
        return {"status": "connected", "table_count": len(tables), "tables": tables}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ============================================================
# DEPARTMENTS
# ============================================================

@app.get("/departments")
def list_departments(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT id, code, name FROM departments ORDER BY name"))
    return [dict(row._mapping) for row in result]


@app.post("/departments")
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db)):
    existing = db.execute(
        text("SELECT id FROM departments WHERE code = :code"),
        {"code": payload.code}
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Department code already exists")

    db.execute(
        text("INSERT INTO departments (code, name) VALUES (:code, :name)"),
        {"code": payload.code, "name": payload.name}
    )
    db.commit()
    return {"message": "Department created", "code": payload.code}


# ============================================================
# STRANDS
# ============================================================

@app.get("/strands")
def list_strands(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT id, name FROM strands ORDER BY name"))
    return [dict(row._mapping) for row in result]


@app.post("/strands")
def create_strand(payload: StrandCreate, db: Session = Depends(get_db)):
    db.execute(text("INSERT INTO strands (name) VALUES (:name)"), {"name": payload.name})
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {"message": "Strand created", "id": new_id, "name": payload.name}


# ============================================================
# SUBJECTS
# ============================================================

@app.get("/subjects")
def list_subjects(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT s.id, s.name, s.grade_level, s.strand_id, st.name AS strand_name
        FROM subjects s
        LEFT JOIN strands st ON s.strand_id = st.id
        ORDER BY s.grade_level, s.name
    """))
    return [dict(row._mapping) for row in result]


@app.post("/subjects")
def create_subject(payload: SubjectCreate, db: Session = Depends(get_db)):
    db.execute(
        text("""
            INSERT INTO subjects (name, grade_level, strand_id)
            VALUES (:name, :grade_level, :strand_id)
        """),
        {"name": payload.name, "grade_level": payload.grade_level, "strand_id": payload.strand_id}
    )
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {"message": "Subject created", "id": new_id}


# ============================================================
# SECTIONS
# ============================================================

@app.get("/sections")
def list_sections(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT sec.id, sec.grade_level, sec.section_name, sec.strand_id,
               st.name AS strand_name, sec.adviser_id
        FROM sections sec
        LEFT JOIN strands st ON sec.strand_id = st.id
        ORDER BY sec.grade_level, sec.section_name
    """))
    return [dict(row._mapping) for row in result]


@app.post("/sections")
def create_section(payload: SectionCreate, db: Session = Depends(get_db)):
    db.execute(
        text("""
            INSERT INTO sections (grade_level, strand_id, section_name)
            VALUES (:grade_level, :strand_id, :section_name)
        """),
        {
            "grade_level": payload.grade_level,
            "strand_id": payload.strand_id,
            "section_name": payload.section_name
        }
    )
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {"message": "Section created", "id": new_id}


# ============================================================
# TEACHERS
# This is the main one: registers a teacher, generates their
# Employee ID, and creates both the users + teachers rows.
# Email sending is intentionally left out for now (no API key yet)
# but the response includes the generated credentials so they can
# be communicated manually in the meantime.
# ============================================================

@app.get("/teachers")
def list_teachers(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT t.id, t.first_name, t.last_name, t.phone_number, t.email,
               t.gender, t.employee_id, d.code AS department_code, d.name AS department_name
        FROM teachers t
        LEFT JOIN departments d ON t.department_id = d.id
        ORDER BY t.last_name, t.first_name
    """))
    return [dict(row._mapping) for row in result]


@app.post("/teachers")
def create_teacher(payload: TeacherCreate, db: Session = Depends(get_db)):
    # Look up the department code, needed to build the employee ID
    dept = db.execute(
        text("SELECT code FROM departments WHERE id = :id"),
        {"id": payload.department_id}
    ).fetchone()
    if not dept:
        raise HTTPException(status_code=400, detail="Department not found")

    department_code = dept._mapping["code"]

    # Generate employee ID, retrying on the rare chance of a collision
    employee_id = generate_employee_id(department_code)
    for _ in range(5):
        exists = db.execute(
            text("SELECT id FROM teachers WHERE employee_id = :eid"),
            {"eid": employee_id}
        ).fetchone()
        if not exists:
            break
        employee_id = generate_employee_id(department_code)

    # Create the login (users table). Employee ID is both username and
    # initial password - must_change_password flags that it should be
    # changed on first login.
    user_result = db.execute(
        text("""
            INSERT INTO users (username, password_hash, role, status)
            VALUES (:username, :password_hash, 'teacher', 'active')
        """),
        {"username": employee_id, "password_hash": employee_id}
        # NOTE: storing the raw employee_id as password_hash is a
        # placeholder. Before this goes live, this needs to be replaced
        # with a real hash (e.g. using passlib/bcrypt) - flagged here
        # so it isn't forgotten.
    )
    new_user_id = user_result.lastrowid
    db.commit()

    # Create the teacher record, linked to that login
    teacher_result = db.execute(
        text("""
            INSERT INTO teachers
                (user_id, first_name, last_name, phone_number, email,
                 gender, employee_id, department_id, must_change_password)
            VALUES
                (:user_id, :first_name, :last_name, :phone_number, :email,
                 :gender, :employee_id, :department_id, TRUE)
        """),
        {
            "user_id": new_user_id,
            "first_name": payload.first_name,
            "last_name": payload.last_name,
            "phone_number": payload.phone_number,
            "email": payload.email,
            "gender": payload.gender,
            "employee_id": employee_id,
            "department_id": payload.department_id
        }
    )
    new_teacher_id = teacher_result.lastrowid
    db.commit()

    return {
        "message": "Teacher registered",
        "teacher_id": new_teacher_id,
        "employee_id": employee_id,
        "username": employee_id,
        "initial_password": employee_id,
        "note": "Email sending is not yet configured. Share these credentials with the teacher manually for now."
    }


# ============================================================
# SECTION_SUBJECT_TEACHER (the actual assignment)
# ============================================================

@app.get("/assignments")
def list_assignments(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT sst.id, sec.grade_level, sec.section_name, sub.name AS subject_name,
               t.first_name, t.last_name, t.employee_id,
               sst.schedule_day, sst.start_time, sst.end_time
        FROM section_subject_teacher sst
        JOIN sections sec ON sst.section_id = sec.id
        JOIN subjects sub ON sst.subject_id = sub.id
        JOIN teachers t ON sst.teacher_id = t.id
        ORDER BY sec.grade_level, sec.section_name, sst.schedule_day, sst.start_time
    """))
    return [dict(row._mapping) for row in result]


@app.post("/assignments")
def create_assignment(payload: AssignmentCreate, db: Session = Depends(get_db)):
    db.execute(
        text("""
            INSERT INTO section_subject_teacher
                (section_id, subject_id, teacher_id, schedule_day, start_time, end_time)
            VALUES
                (:section_id, :subject_id, :teacher_id, :schedule_day, :start_time, :end_time)
        """),
        payload.model_dump()
    )
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {"message": "Assignment created", "id": new_id}


# ============================================================
# LOGIN
# ============================================================
class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    # NOTE: password_hash is currently stored as plaintext (same TODO
    # flagged at account-creation time in create_teacher/complete_application)
    # - this is a direct equality check as a placeholder, not real auth.
    # Replace with a real hash comparison (passlib/bcrypt) before this
    # handles real credentials at scale.
    user = db.execute(text("""
        SELECT id, username, role, status FROM users
        WHERE username = :username AND password_hash = :password
    """), {"username": payload.username, "password": payload.password}).fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user_data = dict(user._mapping)
    if user_data["status"] != "active":
        raise HTTPException(status_code=403, detail="This account is not active")

    if user_data["role"] == "teacher":
        teacher = db.execute(text("""
            SELECT id, first_name, last_name, email, phone_number, employee_id,
                   department_id, must_change_password
            FROM teachers WHERE user_id = :uid
        """), {"uid": user_data["id"]}).fetchone()
        if not teacher:
            raise HTTPException(status_code=404, detail="Teacher record not found for this login")
        teacher_data = dict(teacher._mapping)
        return {
            "user_id": user_data["id"],
            "username": user_data["username"],
            "role": "teacher",
            "teacher_id": teacher_data["id"],
            "first_name": teacher_data["first_name"],
            "last_name": teacher_data["last_name"],
            "email": teacher_data["email"],
            "employee_id": teacher_data["employee_id"],
            "must_change_password": bool(teacher_data["must_change_password"]),
        }

    return {
        "user_id": user_data["id"],
        "username": user_data["username"],
        "role": user_data["role"],
    }


@app.put("/users/{user_id}/change-password")
def change_password(user_id: int, new_password: str, db: Session = Depends(get_db)):
    exists = db.execute(text("SELECT id FROM users WHERE id = :id"), {"id": user_id}).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="User not found")

    db.execute(text(
        "UPDATE users SET password_hash = :pw WHERE id = :id"
    ), {"pw": new_password, "id": user_id})
    db.execute(text(
        "UPDATE teachers SET must_change_password = FALSE WHERE user_id = :id"
    ), {"id": user_id})
    db.commit()
    return {"message": "Password updated"}


# ============================================================
# TEACHER-SCOPED VIEWS
# ============================================================
@app.get("/teachers/{teacher_id}/assignments")
def get_teacher_assignments(teacher_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT sst.id, sst.section_id, sst.subject_id,
               sec.grade_level, sec.section_name, sub.name AS subject_name,
               sst.schedule_day, sst.start_time, sst.end_time
        FROM section_subject_teacher sst
        JOIN sections sec ON sst.section_id = sec.id
        JOIN subjects sub ON sst.subject_id = sub.id
        WHERE sst.teacher_id = :tid
        ORDER BY sec.grade_level, sec.section_name, sst.schedule_day, sst.start_time
    """), {"tid": teacher_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@app.get("/sections/{section_id}/students")
def get_section_students(section_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT id, student_id_number, first_name, last_name, email, phone_number
        FROM students
        WHERE section_id = :sid
        ORDER BY last_name, first_name
    """), {"sid": section_id}).fetchall()
    return [dict(r._mapping) for r in rows]


# ============================================================
# GRADES
# ============================================================
class GradeCreate(BaseModel):
    student_id: int
    section_subject_teacher_id: int
    assessment_type: str      # e.g. 'Quiz', 'Project', 'Activity', 'Exam'
    title: str
    score: Optional[float] = None
    max_score: float
    status: str = "missing"   # 'submitted', 'missing', 'incomplete' - matches the actual DB enum
    due_date: Optional[str] = None
    category: str = "written_work"   # 'written_work', 'performance_task', 'term_exam'
    term: str = "1st Term"           # '1st Term', '2nd Term', '3rd Term'
    school_year_id: Optional[int] = None  # auto-filled from is_current if not given


class GradeUpdate(BaseModel):
    title: Optional[str] = None
    score: Optional[float] = None
    max_score: Optional[float] = None
    status: Optional[str] = None   # 'submitted', 'missing', 'incomplete'
    due_date: Optional[str] = None
    category: Optional[str] = None
    term: Optional[str] = None


@app.get("/grades")
def list_grades(section_subject_teacher_id: int, term: Optional[str] = None, db: Session = Depends(get_db)):
    query = """
        SELECT g.id, g.student_id, s.first_name, s.last_name, s.student_id_number,
               g.assessment_type, g.title, g.score, g.max_score, g.status,
               g.due_date, g.synced, g.category, g.term,
               g.school_year_id, sy.label AS school_year_label
        FROM grades g
        JOIN students s ON g.student_id = s.id
        LEFT JOIN school_years sy ON g.school_year_id = sy.id
        WHERE g.section_subject_teacher_id = :sstid
    """
    params = {"sstid": section_subject_teacher_id}
    if term:
        query += " AND g.term = :term"
        params["term"] = term
    query += " ORDER BY g.due_date DESC, s.last_name, s.first_name"

    rows = db.execute(text(query), params).fetchall()
    result = []
    for r in rows:
        item = dict(r._mapping)
        if item.get("due_date"):
            item["due_date"] = str(item["due_date"])
        result.append(item)
    return result


@app.post("/grades")
def create_grade(payload: GradeCreate, db: Session = Depends(get_db)):
    school_year_id = payload.school_year_id
    if school_year_id is None:
        current_year = db.execute(text(
            "SELECT id FROM school_years WHERE is_current = 1 LIMIT 1"
        )).fetchone()
        school_year_id = current_year[0] if current_year else None

    result = db.execute(text("""
        INSERT INTO grades
            (student_id, section_subject_teacher_id, school_year_id,
             assessment_type, title, score, max_score, status, due_date,
             category, term, synced)
        VALUES
            (:student_id, :sstid, :school_year_id,
             :assessment_type, :title, :score, :max_score, :status, :due_date,
             :category, :term, 1)
    """), {
        "student_id": payload.student_id,
        "sstid": payload.section_subject_teacher_id,
        "school_year_id": school_year_id,
        "assessment_type": payload.assessment_type,
        "title": payload.title,
        "score": payload.score,
        "max_score": payload.max_score,
        "status": payload.status,
        "due_date": payload.due_date,
        "category": payload.category,
        "term": payload.term,
    })
    db.commit()
    return {"message": "Grade created", "id": result.lastrowid}


@app.put("/grades/{grade_id}")
def update_grade(grade_id: int, payload: GradeUpdate, db: Session = Depends(get_db)):
    existing = db.execute(text("SELECT id FROM grades WHERE id = :id"), {"id": grade_id}).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Grade not found")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        return {"message": "Nothing to update"}

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = grade_id
    db.execute(text(f"UPDATE grades SET {set_clause} WHERE id = :id"), updates)
    db.commit()
    return {"message": "Grade updated"}


@app.delete("/grades/{grade_id}")
def delete_grade(grade_id: int, db: Session = Depends(get_db)):
    existing = db.execute(text("SELECT id FROM grades WHERE id = :id"), {"id": grade_id}).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Grade not found")
    db.execute(text("DELETE FROM grades WHERE id = :id"), {"id": grade_id})
    db.commit()
    return {"message": "Grade deleted"}


# ============================================================
# ATTENDANCE
# marked_by distinguishes who logged the record - 'teacher' for
# everything today. The mobile-app self-log feature (older students
# marking their own attendance) will write 'student' here later, so
# the enum already has room for it without a schema change.
# ============================================================
class AttendanceEntry(BaseModel):
    student_id: int
    status: str    # 'present', 'absent', 'late', 'excused' - matches DB enum


class AttendanceBulkSave(BaseModel):
    section_subject_teacher_id: int
    date: str          # "YYYY-MM-DD"
    entries: List[AttendanceEntry]


class AttendanceOverride(BaseModel):
    status: str


@app.get("/assignments/{sstid}/attendance")
def get_attendance_for_date(sstid: int, date: str, db: Session = Depends(get_db)):
    """Roster for this class + whatever attendance is already recorded for
    that date, so the Take Attendance tab can pre-fill from a re-opened day."""
    section_row = db.execute(text(
        "SELECT section_id FROM section_subject_teacher WHERE id = :id"
    ), {"id": sstid}).fetchone()
    if not section_row:
        raise HTTPException(status_code=404, detail="Class assignment not found")
    section_id = section_row[0]

    roster = db.execute(text("""
        SELECT id AS student_id, student_id_number, first_name, last_name
        FROM students WHERE section_id = :sid
        ORDER BY last_name, first_name
    """), {"sid": section_id}).fetchall()

    existing = db.execute(text("""
        SELECT id, student_id, status FROM attendance
        WHERE section_subject_teacher_id = :sstid AND date = :date
    """), {"sstid": sstid, "date": date}).fetchall()
    existing_map = {r[1]: {"attendance_id": r[0], "status": r[2]} for r in existing}

    result = []
    for s in roster:
        srow = dict(s._mapping)
        marked = existing_map.get(srow["student_id"])
        srow["attendance_id"] = marked["attendance_id"] if marked else None
        srow["status"] = marked["status"] if marked else None
        result.append(srow)
    return result


@app.post("/attendance/bulk")
def save_attendance_bulk(payload: AttendanceBulkSave, db: Session = Depends(get_db)):
    saved = 0
    for entry in payload.entries:
        existing = db.execute(text("""
            SELECT id FROM attendance
            WHERE student_id = :sid AND section_subject_teacher_id = :sstid AND date = :date
        """), {"sid": entry.student_id, "sstid": payload.section_subject_teacher_id, "date": payload.date}).fetchone()

        if existing:
            db.execute(text("""
                UPDATE attendance SET status = :status, marked_by = 'teacher', synced = 1
                WHERE id = :id
            """), {"status": entry.status, "id": existing[0]})
        else:
            db.execute(text("""
                INSERT INTO attendance (student_id, section_subject_teacher_id, date, status, marked_by, synced)
                VALUES (:sid, :sstid, :date, :status, 'teacher', 1)
            """), {
                "sid": entry.student_id, "sstid": payload.section_subject_teacher_id,
                "date": payload.date, "status": entry.status
            })
        saved += 1
    db.commit()
    return {"message": f"Saved attendance for {saved} student(s)"}


@app.get("/assignments/{sstid}/attendance/records")
def get_attendance_records(
    sstid: int,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = """
        SELECT a.id, a.student_id, s.first_name, s.last_name, s.student_id_number,
               a.date, a.status, a.marked_by
        FROM attendance a
        JOIN students s ON a.student_id = s.id
        WHERE a.section_subject_teacher_id = :sstid
    """
    params = {"sstid": sstid}
    if date_from:
        query += " AND a.date >= :date_from"
        params["date_from"] = date_from
    if date_to:
        query += " AND a.date <= :date_to"
        params["date_to"] = date_to
    query += " ORDER BY a.date DESC, s.last_name, s.first_name"

    rows = db.execute(text(query), params).fetchall()
    result = []
    for r in rows:
        item = dict(r._mapping)
        if item.get("date"):
            item["date"] = str(item["date"])
        result.append(item)
    return result


@app.put("/attendance/{attendance_id}")
def override_attendance(attendance_id: int, payload: AttendanceOverride, db: Session = Depends(get_db)):
    existing = db.execute(text("SELECT id FROM attendance WHERE id = :id"), {"id": attendance_id}).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    db.execute(text(
        "UPDATE attendance SET status = :status WHERE id = :id"
    ), {"status": payload.status, "id": attendance_id})
    db.commit()
    return {"message": "Attendance record updated"}


# ============================================================
# TEACHER REPORTS / ANALYTICS
# Computes a provisional final grade per student per class:
#   final = written_works% * 0.40 + performance_tasks% * 0.40 + term_exam% * 0.20
# A category's % is the average of (score/max_score*100) across every
# graded item in that category for that student in that class, across
# all terms recorded so far (not just one term) - this is deliberately
# a running/provisional view for early-warning purposes, not an
# official quarterly grade computation.
# If a student has no graded items in a category yet, that category is
# left out and the remaining weights are rescaled so the provisional
# grade is still meaningful with partial data. A student with zero
# graded items in ANY category is excluded entirely (nothing to assess).
# Passing threshold: 75.
# ============================================================
PASSING_GRADE = 75
CATEGORY_WEIGHTS = {"written_work": 0.40, "performance_task": 0.40, "term_exam": 0.20}


def _compute_class_report(db: Session, sstid: int, section_id: int):
    roster = db.execute(text("""
        SELECT id AS student_id, first_name, last_name
        FROM students WHERE section_id = :sid
    """), {"sid": section_id}).fetchall()

    cat_rows = db.execute(text("""
        SELECT student_id, category, AVG(score / max_score * 100) AS pct
        FROM grades
        WHERE section_subject_teacher_id = :sstid AND score IS NOT NULL AND max_score > 0
        GROUP BY student_id, category
    """), {"sstid": sstid}).fetchall()

    by_student: Dict[int, Dict[str, float]] = {}
    for r in cat_rows:
        by_student.setdefault(r[0], {})[r[1]] = float(r[2])

    passing, failing, at_risk = 0, 0, []
    for s in roster:
        srow = dict(s._mapping)
        cats = by_student.get(srow["student_id"])
        if not cats:
            continue   # nothing graded yet - can't assess

        total_weight = sum(CATEGORY_WEIGHTS[c] for c in cats if c in CATEGORY_WEIGHTS)
        if total_weight == 0:
            continue
        final = sum(cats[c] * CATEGORY_WEIGHTS[c] for c in cats if c in CATEGORY_WEIGHTS) / total_weight

        if final >= PASSING_GRADE:
            passing += 1
        else:
            failing += 1
            at_risk.append({
                "student_id": srow["student_id"],
                "first_name": srow["first_name"],
                "last_name": srow["last_name"],
                "final_grade": round(final, 1),
                "section_subject_teacher_id": sstid,
            })

    return passing, failing, at_risk


@app.get("/teachers/{teacher_id}/reports")
def get_teacher_reports(teacher_id: int, db: Session = Depends(get_db)):
    assignments = db.execute(text("""
        SELECT sst.id AS sstid, sst.section_id, sec.grade_level, sec.section_name, sub.name AS subject_name
        FROM section_subject_teacher sst
        JOIN sections sec ON sst.section_id = sec.id
        JOIN subjects sub ON sst.subject_id = sub.id
        WHERE sst.teacher_id = :tid
    """), {"tid": teacher_id}).fetchall()

    by_section = []
    all_at_risk = []
    total_passing, total_failing = 0, 0

    for a in assignments:
        arow = dict(a._mapping)
        passing, failing, at_risk = _compute_class_report(db, arow["sstid"], arow["section_id"])
        total_passing += passing
        total_failing += failing

        for student in at_risk:
            student["grade_level"] = arow["grade_level"]
            student["section_name"] = arow["section_name"]
            student["subject_name"] = arow["subject_name"]
            all_at_risk.append(student)

        by_section.append({
            "section_subject_teacher_id": arow["sstid"],
            "grade_level": arow["grade_level"],
            "section_name": arow["section_name"],
            "subject_name": arow["subject_name"],
            "passing": passing,
            "failing": failing,
            "total_assessed": passing + failing,
        })

    all_at_risk.sort(key=lambda x: x["final_grade"])

    return {
        "summary": {
            "total_assessed": total_passing + total_failing,
            "passing": total_passing,
            "failing": total_failing,
        },
        "by_section": by_section,
        "at_risk_students": all_at_risk,
    }


# ============================================================
# MESSAGES (student <-> teacher)
# ============================================================
# The student mobile app doesn't exist yet, so nothing can send with
# sender_role='student' until that's built - these endpoints are ready
# for that day, and already let a teacher message a student directly.

class MessageCreate(BaseModel):
    student_id: int
    teacher_id: int
    sender_role: str  # 'student' or 'teacher'
    body: str
    section_subject_teacher_id: Optional[int] = None


@app.get("/teachers/{teacher_id}/messages")
def list_teacher_conversations(teacher_id: int, db: Session = Depends(get_db)):
    """One row per student the teacher has an active conversation with,
    most recently active first, with an unread count for each."""
    rows = db.execute(text("""
        SELECT
            s.id AS student_id, s.first_name, s.last_name, s.student_id_number,
            MAX(m.sent_at) AS last_sent_at,
            (SELECT body FROM messages m2
             WHERE m2.student_id = s.id AND m2.teacher_id = :tid
             ORDER BY m2.sent_at DESC LIMIT 1) AS last_message,
            SUM(CASE WHEN m.sender_role = 'student' AND m.read_by_recipient = 0 THEN 1 ELSE 0 END) AS unread_count
        FROM messages m
        JOIN students s ON m.student_id = s.id
        WHERE m.teacher_id = :tid
        GROUP BY s.id, s.first_name, s.last_name, s.student_id_number
        ORDER BY last_sent_at DESC
    """), {"tid": teacher_id}).fetchall()
    result = []
    for r in rows:
        item = dict(r._mapping)
        if item.get("last_sent_at"):
            item["last_sent_at"] = str(item["last_sent_at"])
        result.append(item)
    return result


@app.get("/teachers/{teacher_id}/messages/{student_id}")
def get_conversation_thread(teacher_id: int, student_id: int, db: Session = Depends(get_db)):
    """Full message history between this teacher and this student,
    oldest first. Also marks the student's unread messages as read."""
    db.execute(text("""
        UPDATE messages SET read_by_recipient = 1
        WHERE teacher_id = :tid AND student_id = :sid AND sender_role = 'student'
    """), {"tid": teacher_id, "sid": student_id})
    db.commit()

    rows = db.execute(text("""
        SELECT id, sender_role, body, sent_at, read_by_recipient, section_subject_teacher_id
        FROM messages
        WHERE teacher_id = :tid AND student_id = :sid
        ORDER BY sent_at ASC
    """), {"tid": teacher_id, "sid": student_id}).fetchall()
    result = []
    for r in rows:
        item = dict(r._mapping)
        if item.get("sent_at"):
            item["sent_at"] = str(item["sent_at"])
        result.append(item)
    return result


@app.post("/messages")
def send_message(payload: MessageCreate, db: Session = Depends(get_db)):
    if payload.sender_role not in ("student", "teacher"):
        raise HTTPException(status_code=400, detail="sender_role must be 'student' or 'teacher'")
    result = db.execute(text("""
        INSERT INTO messages (student_id, teacher_id, section_subject_teacher_id, sender_role, body)
        VALUES (:student_id, :teacher_id, :sstid, :sender_role, :body)
    """), {
        "student_id": payload.student_id, "teacher_id": payload.teacher_id,
        "sstid": payload.section_subject_teacher_id,
        "sender_role": payload.sender_role, "body": payload.body,
    })
    db.commit()
    return {"message": "Message sent", "id": result.lastrowid}




class FAQCreate(BaseModel):
    question: str
    answer: str
    sort_order: Optional[int] = 0

@app.get("/website/faqs")
def get_faqs(db: Session = Depends(get_db)):
    result = db.execute(text(
        "SELECT id, question, answer, sort_order, created_at "
        "FROM website_faqs ORDER BY sort_order ASC, created_at ASC"
    ))
    return [dict(row._mapping) for row in result]

@app.post("/website/faqs")
def create_faq(payload: FAQCreate, db: Session = Depends(get_db)):
    db.execute(text(
        "INSERT INTO website_faqs (question, answer, sort_order) "
        "VALUES (:question, :answer, :sort_order)"
    ), {"question": payload.question, "answer": payload.answer, "sort_order": payload.sort_order})
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {"message": "FAQ created", "id": new_id}

@app.delete("/website/faqs/{faq_id}")
def delete_faq(faq_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM website_faqs WHERE id = :id"), {"id": faq_id})
    db.commit()
    return {"message": "FAQ deleted"}

class AnnouncementCreate(BaseModel):
    title: str
    body: str
    badge: Optional[str] = "Anunsyo"
    date: Optional[str] = None

@app.get("/website/announcements")
def get_announcements(db: Session = Depends(get_db)):
    result = db.execute(text(
        "SELECT id, title, body, badge, date, created_at "
        "FROM website_announcements ORDER BY date DESC, created_at DESC"
    ))
    rows = []
    for row in result:
        r = dict(row._mapping)
        if r.get("date"):
            r["date"] = str(r["date"])
        if r.get("created_at"):
            r["created_at"] = str(r["created_at"])
        rows.append(r)
    return rows

@app.post("/website/announcements")
def create_announcement(payload: AnnouncementCreate, db: Session = Depends(get_db)):
    from datetime import date
    ann_date = payload.date if payload.date else str(date.today())
    db.execute(text(
        "INSERT INTO website_announcements (title, body, badge, date) "
        "VALUES (:title, :body, :badge, :date)"
    ), {"title": payload.title, "body": payload.body, "badge": payload.badge, "date": ann_date})
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {"message": "Announcement created", "id": new_id}

@app.delete("/website/announcements/{ann_id}")
def delete_announcement(ann_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM website_announcements WHERE id = :id"), {"id": ann_id})
    db.commit()
    return {"message": "Announcement deleted"}

class VideoUpdate(BaseModel):
    url: Optional[str] = None
    description: Optional[str] = None

@app.get("/website/video")
def get_video(db: Session = Depends(get_db)):
    result = db.execute(text(
        "SELECT id, url, description FROM website_video LIMIT 1"
    )).fetchone()
    if not result:
        return {"url": None, "description": None}
    return dict(result._mapping)

@app.put("/website/video")
def update_video(payload: VideoUpdate, db: Session = Depends(get_db)):
    db.execute(text(
        "UPDATE website_video SET url = :url, description = :description WHERE id = 1"
    ), {"url": payload.url, "description": payload.description})
    db.commit()
    return {"message": "Video updated", "url": payload.url}


class TestimonialCreate(BaseModel):
    name: str
    role: str
    quote: str
    rating: Optional[int] = 5

class TestimonialSubmit(BaseModel):
    name: str
    role: str
    quote: str
    rating: Optional[int] = 5

MAX_TESTIMONIALS = 5

def _clean_rating(rating: Optional[int]) -> int:
    return rating if rating and 1 <= rating <= 5 else 5

# ---- PUBLIC: homepage only ever sees approved testimonials ----
@app.get("/website/testimonials")
def get_testimonials(db: Session = Depends(get_db)):
    result = db.execute(text(
        "SELECT id, name, role, quote, rating, created_at "
        "FROM website_testimonials WHERE status = 'approved' "
        "ORDER BY created_at ASC"
    ))
    rows = []
    for row in result:
        r = dict(row._mapping)
        if r.get("created_at"):
            r["created_at"] = str(r["created_at"])
        rows.append(r)
    return rows

# ---- ADMIN: view the pending queue ----
@app.get("/website/testimonials/pending")
def get_pending_testimonials(db: Session = Depends(get_db)):
    result = db.execute(text(
        "SELECT id, name, role, quote, rating, created_at "
        "FROM website_testimonials WHERE status = 'pending' "
        "ORDER BY created_at ASC"
    ))
    rows = []
    for row in result:
        r = dict(row._mapping)
        if r.get("created_at"):
            r["created_at"] = str(r["created_at"])
        rows.append(r)
    return rows

# ---- PUBLIC: submission form posts here, always lands as pending ----
@app.post("/website/testimonials/submit")
def submit_testimonial(payload: TestimonialSubmit, db: Session = Depends(get_db)):
    rating = _clean_rating(payload.rating)
    db.execute(text(
        "INSERT INTO website_testimonials (name, role, quote, rating, status) "
        "VALUES (:name, :role, :quote, :rating, 'pending')"
    ), {"name": payload.name, "role": payload.role, "quote": payload.quote, "rating": rating})
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {"message": "Testimonial submitted for review", "id": new_id}

# ---- ADMIN: add a testimonial directly, auto-approved (staff-entered) ----
@app.post("/website/testimonials")
def create_testimonial(payload: TestimonialCreate, db: Session = Depends(get_db)):
    count = db.execute(
        text("SELECT COUNT(*) FROM website_testimonials WHERE status = 'approved'")
    ).scalar()
    if count >= MAX_TESTIMONIALS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum of {MAX_TESTIMONIALS} approved testimonials reached. Remove one first."
        )
    rating = _clean_rating(payload.rating)
    db.execute(text(
        "INSERT INTO website_testimonials (name, role, quote, rating, status) "
        "VALUES (:name, :role, :quote, :rating, 'approved')"
    ), {"name": payload.name, "role": payload.role, "quote": payload.quote, "rating": rating})
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {"message": "Testimonial created", "id": new_id}

# ---- ADMIN: approve a pending submission ----
@app.put("/website/testimonials/{testimonial_id}/approve")
def approve_testimonial(testimonial_id: int, db: Session = Depends(get_db)):
    count = db.execute(
        text("SELECT COUNT(*) FROM website_testimonials WHERE status = 'approved'")
    ).scalar()
    if count >= MAX_TESTIMONIALS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum of {MAX_TESTIMONIALS} approved testimonials reached. Remove one first."
        )
    result = db.execute(
        text("UPDATE website_testimonials SET status = 'approved' WHERE id = :id"),
        {"id": testimonial_id}
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Testimonial not found")
    return {"message": "Testimonial approved"}

# ---- ADMIN: delete/reject any testimonial (pending or approved) ----
@app.delete("/website/testimonials/{testimonial_id}")
def delete_testimonial(testimonial_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM website_testimonials WHERE id = :id"), {"id": testimonial_id})
    db.commit()
    return {"message": "Testimonial deleted"}


# ============================================================
# APPLICATIONS (enrollment submissions -> registrar review)
# ============================================================

class ApplicationCreate(BaseModel):
    application_type: str          # 'regular' or 'als'
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone_number: Optional[str] = None
    grade_level: str
    requirement_ids_declared: List[int] = []

    # School year this application is for. If the form doesn't send one,
    # we fall back to whichever school year is marked is_current=1.
    school_year_id: Optional[int] = None

    # ---- Shared identity / demographic fields ----
    lrn: Optional[str] = None
    middle_name: Optional[str] = None
    ext_name: Optional[str] = None
    birthdate: Optional[str] = None
    age: Optional[str] = None
    sex: Optional[str] = None
    religion: Optional[str] = None
    mother_tongue: Optional[str] = None
    ip_group: Optional[str] = None
    signer_name: Optional[str] = None
    sign_date: Optional[str] = None

    # ---- Address ----
    current_street: Optional[str] = None
    current_barangay: Optional[str] = None
    current_municipality: Optional[str] = None
    current_province: Optional[str] = None
    current_zip: Optional[str] = None
    permanent_same_as_current: Optional[bool] = None
    permanent_street: Optional[str] = None
    permanent_barangay: Optional[str] = None
    permanent_municipality: Optional[str] = None
    permanent_province: Optional[str] = None
    permanent_zip: Optional[str] = None

    # ---- Parents / guardian ----
    father_last_name: Optional[str] = None
    father_first_name: Optional[str] = None
    father_contact: Optional[str] = None
    father_occupation: Optional[str] = None
    mother_last_name: Optional[str] = None
    mother_first_name: Optional[str] = None
    mother_contact: Optional[str] = None
    mother_occupation: Optional[str] = None
    guardian_last_name: Optional[str] = None
    guardian_first_name: Optional[str] = None
    guardian_contact: Optional[str] = None

    # ---- Special classifications ----
    ip_member: Optional[str] = None
    four_ps: Optional[str] = None
    four_ps_id: Optional[str] = None
    special_needs: Optional[str] = None
    disability: Optional[str] = None
    pwd_id: Optional[str] = None
    pwd_id_number: Optional[str] = None

    # ---- Regular-form-specific ----
    graded_status: Optional[str] = None
    psa_no: Optional[str] = None
    place_of_birth: Optional[str] = None
    returning_learner: Optional[str] = None
    last_school_year: Optional[str] = None
    last_grade: Optional[str] = None
    last_school: Optional[str] = None
    trimester: Optional[str] = None
    shs_track: Optional[str] = None
    shs_strand: Optional[str] = None
    modality: Optional[str] = None

    # ---- ALS-form-specific ----
    civil_status: Optional[str] = None
    pwd: Optional[str] = None
    dropout_reason: Optional[str] = None
    dropout_other: Optional[str] = None
    als_before: Optional[str] = None
    als_program_name: Optional[str] = None
    als_year_attended: Optional[str] = None
    als_completed: Optional[str] = None
    als_not_completed_reason: Optional[str] = None
    distance_km: Optional[str] = None
    travel_hours: Optional[str] = None
    travel_mins: Optional[str] = None
    travel_mode: Optional[str] = None
    travel_other: Optional[str] = None
    als_availability_schedule: Optional[Dict[str, Any]] = None


# Every application-detail column beyond the original 5 basics, used to
# build the INSERT and the SELECT in one place instead of duplicating the
# list - add a new field here and to ApplicationCreate above, and both the
# save and the read-back pick it up automatically.
APPLICATION_DETAIL_FIELDS = [
    "lrn", "middle_name", "ext_name", "birthdate", "age", "sex", "religion",
    "mother_tongue", "ip_group", "signer_name", "sign_date",
    "current_street", "current_barangay", "current_municipality",
    "current_province", "current_zip", "permanent_same_as_current",
    "permanent_street", "permanent_barangay", "permanent_municipality",
    "permanent_province", "permanent_zip",
    "father_last_name", "father_first_name", "father_contact", "father_occupation",
    "mother_last_name", "mother_first_name", "mother_contact", "mother_occupation",
    "guardian_last_name", "guardian_first_name", "guardian_contact",
    "ip_member", "four_ps", "four_ps_id", "special_needs", "disability",
    "pwd_id", "pwd_id_number",
    "graded_status", "psa_no", "place_of_birth", "returning_learner",
    "last_school_year", "last_grade", "last_school", "trimester",
    "shs_track", "shs_strand", "modality",
    "civil_status", "pwd", "dropout_reason", "dropout_other", "als_before",
    "als_program_name", "als_year_attended", "als_completed",
    "als_not_completed_reason", "distance_km", "travel_hours", "travel_mins",
    "travel_mode", "travel_other",
]


# ---- PUBLIC: enrollment forms submit here ----
@app.post("/applications")
def create_application(payload: ApplicationCreate, db: Session = Depends(get_db)):
    if payload.application_type not in ("regular", "als"):
        raise HTTPException(status_code=400, detail="application_type must be 'regular' or 'als'")

    # 1. Create the student record
    student_result = db.execute(text("""
        INSERT INTO students (first_name, last_name, email, phone_number, enrollment_status)
        VALUES (:first_name, :last_name, :email, :phone_number, 'pending')
    """), {
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "email": payload.email,
        "phone_number": payload.phone_number
    })
    new_student_id = student_result.lastrowid
    db.commit()

    # Fall back to whichever school year is marked current if the form
    # didn't specify one.
    school_year_id = payload.school_year_id
    if school_year_id is None:
        current_year = db.execute(text(
            "SELECT id FROM school_years WHERE is_current = 1 LIMIT 1"
        )).fetchone()
        school_year_id = current_year[0] if current_year else None

    # 2. Create the application record - basic fields + every detail field
    detail_values = {f: getattr(payload, f) for f in APPLICATION_DETAIL_FIELDS}
    # als_availability_schedule is JSON, needs serializing separately
    detail_values["als_availability_schedule"] = (
        json.dumps(payload.als_availability_schedule) if payload.als_availability_schedule else None
    )

    columns = ["student_id", "application_type", "grade_level", "school_year_id", "status"] + \
              APPLICATION_DETAIL_FIELDS + ["als_availability_schedule"]
    placeholders = ", ".join(f":{c}" for c in columns)
    column_list = ", ".join(columns)

    params = {
        "student_id": new_student_id,
        "application_type": payload.application_type,
        "grade_level": payload.grade_level,
        "school_year_id": school_year_id,
        "status": "pending",
        **detail_values,
    }

    application_result = db.execute(
        text(f"INSERT INTO applications ({column_list}) VALUES ({placeholders})"),
        params
    )
    new_app_id = application_result.lastrowid
    db.commit()

    # 3. Build the full requirements checklist for this application type
    #    ('both' requirements always included, plus type-specific ones)
    reqs = db.execute(text(
        "SELECT id FROM requirements WHERE application_type = 'both' OR application_type = :atype"
    ), {"atype": payload.application_type}).fetchall()

    declared_set = set(payload.requirement_ids_declared)
    for row in reqs:
        rid = row[0]
        db.execute(text("""
            INSERT INTO application_requirements
                (application_id, requirement_id, declared_by_student, verified_by_registrar)
            VALUES (:aid, :rid, :declared, 0)
        """), {
            "aid": new_app_id,
            "rid": rid,
            "declared": 1 if rid in declared_set else 0
        })
    db.commit()

    return {"message": "Application submitted", "application_id": new_app_id, "student_id": new_student_id}


# ---- School years ----
@app.get("/school-years")
def list_school_years(db: Session = Depends(get_db)):
    rows = db.execute(text(
        "SELECT id, label, is_current FROM school_years ORDER BY label DESC"
    )).fetchall()
    return [dict(r._mapping) for r in rows]


@app.put("/school-years/{school_year_id}/set-current")
def set_current_school_year(school_year_id: int, db: Session = Depends(get_db)):
    exists = db.execute(text("SELECT id FROM school_years WHERE id = :id"),
                         {"id": school_year_id}).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="School year not found")
    db.execute(text("UPDATE school_years SET is_current = 0"))
    db.execute(text("UPDATE school_years SET is_current = 1 WHERE id = :id"), {"id": school_year_id})
    db.commit()
    return {"message": "Current school year updated"}


@app.post("/school-years")
def create_school_year(label: str, db: Session = Depends(get_db)):
    result = db.execute(text("INSERT INTO school_years (label, is_current) VALUES (:label, 0)"),
                         {"label": label})
    db.commit()
    return {"id": result.lastrowid, "label": label}


# ---- REGISTRAR: list applications (filter by status / type, search by name) ----
@app.get("/applications")
def list_applications(
    status: Optional[str] = None,
    application_type: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = """
        SELECT a.id, a.application_type, a.grade_level, a.status,
               a.submitted_at, a.reviewed_at, a.enrolled_at,
               s.id AS student_id, s.first_name, s.last_name, s.email, s.phone_number
        FROM applications a
        JOIN students s ON a.student_id = s.id
        WHERE 1=1
    """
    params = {}
    if status:
        query += " AND a.status = :status"
        params["status"] = status
    if application_type:
        query += " AND a.application_type = :application_type"
        params["application_type"] = application_type
    if search:
        query += " AND (s.first_name LIKE :search OR s.last_name LIKE :search)"
        params["search"] = f"%{search}%"
    query += " ORDER BY a.submitted_at DESC"

    result = db.execute(text(query), params)
    rows = []
    for row in result:
        r = dict(row._mapping)
        if r.get("submitted_at"):
            r["submitted_at"] = str(r["submitted_at"])
        if r.get("reviewed_at"):
            r["reviewed_at"] = str(r["reviewed_at"])
        if r.get("enrolled_at"):
            r["enrolled_at"] = str(r["enrolled_at"])
        rows.append(r)
    return rows


# ---- REGISTRAR: full detail for one application, including checklist ----
@app.get("/applications/{application_id}")
def get_application(application_id: int, db: Session = Depends(get_db)):
    detail_columns = ", ".join(f"a.{f}" for f in APPLICATION_DETAIL_FIELDS)
    app_row = db.execute(text(f"""
        SELECT a.id, a.application_type, a.grade_level, a.status,
               a.school_year_id, sy.label AS school_year_label,
               {detail_columns},
               a.als_availability_schedule,
               a.submitted_at, a.reviewed_at, a.enrolled_at, a.reviewed_by,
               s.id AS student_id, s.first_name, s.last_name, s.email, s.phone_number,
               s.student_id_number
        FROM applications a
        JOIN students s ON a.student_id = s.id
        LEFT JOIN school_years sy ON a.school_year_id = sy.id
        WHERE a.id = :id
    """), {"id": application_id}).fetchone()

    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")

    application = dict(app_row._mapping)
    for date_field in ("submitted_at", "reviewed_at", "enrolled_at", "birthdate", "sign_date"):
        if application.get(date_field):
            application[date_field] = str(application[date_field])

    # als_availability_schedule comes back from MySQL as a JSON string (or
    # None/dict depending on driver version) - normalize it to a plain dict.
    raw_schedule = application.get("als_availability_schedule")
    if isinstance(raw_schedule, str):
        try:
            application["als_availability_schedule"] = json.loads(raw_schedule)
        except (ValueError, TypeError):
            application["als_availability_schedule"] = None
    elif not isinstance(raw_schedule, dict):
        application["als_availability_schedule"] = None

    checklist = db.execute(text("""
        SELECT ar.id, ar.requirement_id, r.name, ar.declared_by_student,
               ar.verified_by_registrar, ar.verified_at
        FROM application_requirements ar
        JOIN requirements r ON ar.requirement_id = r.id
        WHERE ar.application_id = :id
        ORDER BY r.id
    """), {"id": application_id}).fetchall()

    application["requirements"] = []
    for row in checklist:
        item = dict(row._mapping)
        if item.get("verified_at"):
            item["verified_at"] = str(item["verified_at"])
        application["requirements"].append(item)

    return application


# ---- REGISTRAR: approve an application (sends email #1) ----
@app.put("/applications/{application_id}/approve")
def approve_application(application_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT a.grade_level, a.application_type, s.email, s.first_name, s.last_name
        FROM applications a JOIN students s ON a.student_id = s.id
        WHERE a.id = :id
    """), {"id": application_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Application not found")

    db.execute(text("""
        UPDATE applications
        SET status = 'initially_approved', reviewed_at = NOW()
        WHERE id = :id
    """), {"id": application_id})
    db.execute(text("""
        UPDATE students s
        JOIN applications a ON a.student_id = s.id
        SET s.enrollment_status = 'initially_approved'
        WHERE a.id = :id
    """), {"id": application_id})
    db.commit()

    data = dict(row._mapping)
    full_name = f"{data['first_name']} {data['last_name']}"
    subject = "Enrollment Application Approved — TCTAR Integrated Farm School"
    body = (
        f"Kumusta {full_name},\n\n"
        f"Magandang balita! Na-approve na ang inyong enrollment application "
        f"({data['grade_level']}) sa Tiu Cho Teg - Ana Ros Foundation Integrated Farm School.\n\n"
        f"Sundan ang susunod na hakbang:\n"
        f"1. Pumunta sa paaralan sa Iloilo Radial By-Pass Rd 4, Lanit, Jaro, Iloilo City.\n"
        f"2. Dalhin ang lahat ng orihinal na kopya ng mga requirements na inyong idineklara "
        f"sa online enrollment form.\n"
        f"3. Hihintayin ng registrar ang inyong mga dokumento para sa huling pagpapatunay.\n\n"
        f"Para sa mga katanungan, maaari kayong tumawag sa +63 33 337 8522.\n\n"
        f"Salamat po,\nTCTAR Integrated Farm School"
    )
    send_email(data["email"], subject, body)

    return {"message": "Application approved, email sent"}


# ---- REGISTRAR: reject an application ----
@app.put("/applications/{application_id}/reject")
def reject_application(application_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT s.email, s.first_name, s.last_name
        FROM applications a JOIN students s ON a.student_id = s.id
        WHERE a.id = :id
    """), {"id": application_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Application not found")

    db.execute(text("""
        UPDATE applications
        SET status = 'rejected', reviewed_at = NOW()
        WHERE id = :id
    """), {"id": application_id})
    db.execute(text("""
        UPDATE students s
        JOIN applications a ON a.student_id = s.id
        SET s.enrollment_status = 'rejected'
        WHERE a.id = :id
    """), {"id": application_id})
    db.commit()

    data = dict(row._mapping)
    full_name = f"{data['first_name']} {data['last_name']}"
    subject = "Enrollment Application Update — TCTAR Integrated Farm School"
    body = (
        f"Kumusta {full_name},\n\n"
        f"Sa kasamaang palad, hindi po naaprubahan ang inyong enrollment application "
        f"sa ngayon. Para sa karagdagang impormasyon o tulong, maaari po kayong "
        f"tumawag sa amin sa +63 33 337 8522 o mag-email sa 500191@deped.gov.ph.\n\n"
        f"Salamat po,\nTCTAR Integrated Farm School"
    )
    send_email(data["email"], subject, body)

    return {"message": "Application rejected, email sent"}


# ---- REGISTRAR: toggle a single requirement as physically verified ----
@app.put("/application_requirements/{item_id}/verify")
def verify_requirement(item_id: int, verified: bool = True, db: Session = Depends(get_db)):
    result = db.execute(text("""
        UPDATE application_requirements
        SET verified_by_registrar = :verified,
            verified_at = CASE WHEN :verified = 1 THEN NOW() ELSE NULL END
        WHERE id = :id
    """), {"verified": 1 if verified else 0, "id": item_id})
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    return {"message": "Requirement updated"}


# ---- REGISTRAR: finalize enrollment once all requirements are verified (sends email #2) ----
@app.put("/applications/{application_id}/complete")
def complete_application(application_id: int, section_id: Optional[int] = None, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT a.student_id, a.school_year_id, a.middle_name, a.birthdate,
               s.email, s.first_name, s.last_name, s.user_id, s.student_id_number
        FROM applications a JOIN students s ON a.student_id = s.id
        WHERE a.id = :id
    """), {"id": application_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Application not found")

    unverified_count = db.execute(text("""
        SELECT COUNT(*) FROM application_requirements
        WHERE application_id = :id AND declared_by_student = 1 AND verified_by_registrar = 0
    """), {"id": application_id}).scalar()

    if unverified_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"{unverified_count} requirement(s) still unverified. Check them off first."
        )

    data = dict(row._mapping)

    # Create the student's login account now, if one doesn't already exist.
    # Per the current plan: username is first+middle+last name with all
    # spaces/punctuation stripped and lowercased, plus the day-of-month of
    # their birthdate (e.g. "John Michael Kintao", born Oct 14 ->
    # "johnmichaelkintao14"). Password is the generated student ID number.
    # If that combination still collides (e.g. twins sharing a birthdate),
    # a counter is appended to the username - the student ID number itself
    # stays unique regardless.
    # NOTE: password_hash stores the raw student ID as a placeholder,
    # same TODO as the teacher accounts above - replace with a real
    # hash before this handles real student data at scale.
    if not data["user_id"]:
        sy_row = db.execute(text(
            "SELECT label FROM school_years WHERE id = :id"
        ), {"id": data["school_year_id"]}).fetchone()
        sy_label = sy_row[0] if sy_row else None
        sy_prefix = (sy_label[:4] if sy_label else date.today().strftime("%Y"))

        count_row = db.execute(text("""
            SELECT COUNT(*) FROM students WHERE student_id_number LIKE :pattern
        """), {"pattern": f"{sy_prefix}-%"}).fetchone()
        seq = (count_row[0] if count_row else 0) + 1
        student_id_number = f"{sy_prefix}-{seq:04d}"

        base_username = re.sub(
            r"[^a-z]", "",
            f"{data['first_name']}{data['middle_name'] or ''}{data['last_name']}".lower()
        )
        birth_day = ""
        if data["birthdate"]:
            try:
                bd = data["birthdate"]
                if isinstance(bd, str):
                    bd = datetime.strptime(bd[:10], "%Y-%m-%d").date()
                birth_day = str(bd.day)
            except (ValueError, TypeError):
                birth_day = ""  # malformed/missing birthdate - fall back to name-only
        base_username = f"{base_username}{birth_day}"

        # Name + birth-day is usually unique, but not guaranteed (e.g. twins
        # sharing a birthdate). Fall back to appending a counter if needed.
        username = base_username
        attempt = 1
        while db.execute(text(
            "SELECT id FROM users WHERE username = :u"
        ), {"u": username}).fetchone():
            attempt += 1
            username = f"{base_username}{attempt}"

        user_result = db.execute(text("""
            INSERT INTO users (username, password_hash, role, status)
            VALUES (:username, :password_hash, 'student', 'active')
        """), {"username": username, "password_hash": student_id_number})
        new_user_id = user_result.lastrowid
        db.commit()

        db.execute(text("""
            UPDATE students
            SET user_id = :user_id, student_id_number = :sid_number
            WHERE id = :sid
        """), {"user_id": new_user_id, "sid_number": student_id_number, "sid": data["student_id"]})
        db.commit()

    if section_id is not None:
        db.execute(text("""
            UPDATE students SET section_id = :section_id WHERE id = :sid
        """), {"section_id": section_id, "sid": data["student_id"]})
        db.commit()

    db.execute(text("""
        UPDATE applications SET status = 'officially_enrolled', enrolled_at = NOW() WHERE id = :id
    """), {"id": application_id})
    db.execute(text("""
        UPDATE students SET enrollment_status = 'officially_enrolled' WHERE id = :sid
    """), {"sid": data["student_id"]})
    db.commit()

    full_name = f"{data['first_name']} {data['last_name']}"
    subject = "Opisyal na Naka-enroll! — TCTAR Integrated Farm School"
    body = (
        f"Kumusta {full_name},\n\n"
        f"Nakumpirma na ang lahat ng inyong requirements. Kayo po ay opisyal na "
        f"naka-enroll na sa Tiu Cho Teg - Ana Ros Foundation Integrated Farm School!\n\n"
        f"Maligayang pagdating sa aming paaralan. Susundan namin ng impormasyon "
        f"tungkol sa first day ng klase at seksyon.\n\n"
        f"Salamat po,\nTCTAR Integrated Farm School"
    )
    send_email(data["email"], subject, body)

    # Re-fetch the current login credentials (whether just generated above,
    # or already existing from a prior run) so the caller can pass them
    # along to the student in the enrollment confirmation.
    final_row = db.execute(text("""
        SELECT s.student_id_number, u.username
        FROM students s LEFT JOIN users u ON s.user_id = u.id
        WHERE s.id = :sid
    """), {"sid": data["student_id"]}).fetchone()
    student_id_number = final_row[0] if final_row else None
    login_username = final_row[1] if final_row else None

    return {
        "message": "Application marked officially enrolled, email sent",
        "student_id_number": student_id_number,
        "username": login_username
    }