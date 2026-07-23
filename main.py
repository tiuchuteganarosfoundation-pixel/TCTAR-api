from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import os
import smtplib
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
    db.execute(
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
    db.commit()
    new_user_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()

    # Create the teacher record, linked to that login
    db.execute(
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
    db.commit()
    new_teacher_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()

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
# WEBSITE CONTENT ENDPOINTS
# ============================================================

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

    # 2. Create the application record
    application_result = db.execute(text("""
        INSERT INTO applications (student_id, application_type, grade_level, status)
        VALUES (:student_id, :application_type, :grade_level, 'pending')
    """), {
        "student_id": new_student_id,
        "application_type": payload.application_type,
        "grade_level": payload.grade_level
    })
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
               a.submitted_at, a.reviewed_at,
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
        rows.append(r)
    return rows


# ---- REGISTRAR: full detail for one application, including checklist ----
@app.get("/applications/{application_id}")
def get_application(application_id: int, db: Session = Depends(get_db)):
    app_row = db.execute(text("""
        SELECT a.id, a.application_type, a.grade_level, a.status,
               a.submitted_at, a.reviewed_at, a.reviewed_by,
               s.id AS student_id, s.first_name, s.last_name, s.email, s.phone_number
        FROM applications a
        JOIN students s ON a.student_id = s.id
        WHERE a.id = :id
    """), {"id": application_id}).fetchone()

    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")

    application = dict(app_row._mapping)
    if application.get("submitted_at"):
        application["submitted_at"] = str(application["submitted_at"])
    if application.get("reviewed_at"):
        application["reviewed_at"] = str(application["reviewed_at"])

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
def complete_application(application_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT a.student_id, s.email, s.first_name, s.last_name
        FROM applications a JOIN students s ON a.student_id = s.id
        WHERE a.id = :id
    """), {"id": application_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Application not found")

    unverified_count = db.execute(text("""
        SELECT COUNT(*) FROM application_requirements
        WHERE application_id = :id AND verified_by_registrar = 0
    """), {"id": application_id}).scalar()

    if unverified_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"{unverified_count} requirement(s) still unverified. Check them off first."
        )

    data = dict(row._mapping)

    db.execute(text("""
        UPDATE applications SET status = 'officially_enrolled' WHERE id = :id
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

    return {"message": "Application marked officially enrolled, email sent"}