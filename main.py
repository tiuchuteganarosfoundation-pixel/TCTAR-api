from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

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

MAX_TESTIMONIALS = 5

@app.get("/website/testimonials")
def get_testimonials(db: Session = Depends(get_db)):
    result = db.execute(text(
        "SELECT id, name, role, quote, rating, created_at "
        "FROM website_testimonials ORDER BY created_at ASC"
    ))
    rows = []
    for row in result:
        r = dict(row._mapping)
        if r.get("created_at"):
            r["created_at"] = str(r["created_at"])
        rows.append(r)
    return rows

@app.post("/website/testimonials")
def create_testimonial(payload: TestimonialCreate, db: Session = Depends(get_db)):
    count = db.execute(text("SELECT COUNT(*) FROM website_testimonials")).scalar()
    if count >= MAX_TESTIMONIALS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum of {MAX_TESTIMONIALS} testimonials reached. Delete one first."
        )
    rating = payload.rating if payload.rating and 1 <= payload.rating <= 5 else 5
    db.execute(text(
        "INSERT INTO website_testimonials (name, role, quote, rating) "
        "VALUES (:name, :role, :quote, :rating)"
    ), {"name": payload.name, "role": payload.role, "quote": payload.quote, "rating": rating})
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {"message": "Testimonial created", "id": new_id}

@app.delete("/website/testimonials/{testimonial_id}")
def delete_testimonial(testimonial_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM website_testimonials WHERE id = :id"), {"id": testimonial_id})
    db.commit()
    return {"message": "Testimonial deleted"}