import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional

import bcrypt
import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import field_validator
from sqlalchemy import func
from sqlmodel import Field, Session, SQLModel, create_engine, select

SECRET_KEY = os.getenv(
    "MCH_SECRET_KEY", "dev-only-secret-key-change-before-production"
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

ROLES = ("mother", "health_worker", "admin")


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    name: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def create_access_token(user_id: int, role: str, session_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "role": role, "sid": session_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def validate_two_full_names(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    parts = cleaned.split(" ")
    if len(parts) < 2:
        raise ValueError(
            "Full name must contain at least two full names (e.g., 'Sarah Namukasa')."
        )
    for part in parts:
        if not re.fullmatch(r"[A-Za-z]{2,}", part):
            raise ValueError(
                f"Invalid name part '{part}': each name must be at least 2 letters with no single letters, numbers, or symbols."
            )
    return cleaned


def validate_staff_email(email: str) -> str:
    """Staff (Admin & Health Worker) emails must contain a special character and NO full stop."""
    cleaned = email.strip().lower()
    if "." in cleaned:
        raise ValueError("Staff email must not contain any full stop ('.').")
    if cleaned.count("@") != 1:
        raise ValueError("Email must contain exactly one '@' symbol.")

    local_part, domain_part = cleaned.split("@")
    if not local_part or not domain_part:
        raise ValueError("Email must have both a username before '@' and a domain after '@'.")
    if not re.search(r"[_\-+!#$%&*]", local_part):
        raise ValueError(
            "Staff email username must include at least one special character (e.g., '_', '-', '+', '#')."
        )
    if not re.fullmatch(r"[a-z0-9_\-+!#$%&*]+", local_part):
        raise ValueError("Email username contains invalid characters.")
    if not re.fullmatch(r"[a-z0-9\-]+", domain_part):
        raise ValueError("Email domain must contain letters/numbers/hyphens only (no full stop).")
    return cleaned


def validate_mother_gmail(email: str) -> str:
    """Mother emails must strictly end with '@gmail.com'."""
    cleaned = email.strip().lower()
    if not cleaned.endswith("@gmail.com"):
        raise ValueError("Mother's email must end with '@gmail.com' only.")
    local_part = cleaned[: -len("@gmail.com")]
    if len(local_part) < 3 or not re.fullmatch(r"[a-z0-9._+-]+", local_part):
        raise ValueError(
            "Mother's Gmail username must be at least 3 characters (letters, numbers, '.', '_', '-', '+')."
        )
    return cleaned


def normalize_phone(phone: str) -> str:
    cleaned = phone.strip()
    if not cleaned.isdigit() or len(cleaned) != 10 or not cleaned.startswith("07"):
        raise ValueError("Phone must be a 10-digit number starting with 07.")
    return cleaned


def validate_mother_dob(dob: date) -> date:
    today = date.today()
    if dob >= today:
        raise ValueError("Mother's date of birth cannot be today or in the future.")
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < 14:
        raise ValueError("Mother must be at least 14 years old.")
    if age > 55:
        raise ValueError("Mother's date of birth indicates an age over 55; please verify the year.")
    return dob


def validate_mother_due_date(due_date: Optional[date]) -> Optional[date]:
    if due_date is None:
        return None
    today = date.today()
    earliest_allowed = today - timedelta(days=30)
    latest_allowed = today + timedelta(days=280)
    if due_date < earliest_allowed:
        raise ValueError("Expected due date cannot be more than 30 days in the past.")
    if due_date > latest_allowed:
        raise ValueError("Expected due date cannot be more than 40 weeks (280 days) in the future.")
    return due_date


engine = create_engine(
    "sqlite:///maternal.db", connect_args={"check_same_thread": False}
)


# ---------- USERS (MASTER ACCOUNT TABLE) ----------


class UserBase(SQLModel):
    name: str = Field(unique=True, index=True)
    email: Optional[str] = Field(default=None, unique=True, index=True)
    phone: str = Field(unique=True, index=True)
    role: str = "mother"  # Immutable: mother | health_worker | admin
    staff_id: Optional[str] = Field(default=None, unique=True, index=True)
    facility: Optional[str] = None
    responsibilities: Optional[str] = None
    is_active: bool = True


class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    password: str
    active_session_id: Optional[str] = Field(default=None)


class UserRead(UserBase):
    id: int


class HealthWorkerCreate(SQLModel):
    """Guided policy schema enforced when Admin creates a Health Worker account."""

    name: str = Field(min_length=5, max_length=100)
    email: str
    phone: str
    staff_id: str = Field(min_length=3, max_length=30)
    facility: str = Field(min_length=2, max_length=100)
    responsibilities: str = Field(min_length=5, max_length=250)
    password: str = Field(default="1234", min_length=4, max_length=64)

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return validate_two_full_names(v)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return validate_staff_email(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        return normalize_phone(v)

    @field_validator("staff_id", "facility", "responsibilities")
    @classmethod
    def check_not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be blank")
        return cleaned


class HealthWorkerUpdate(SQLModel):
    """Role is intentionally excluded so a user's role can NEVER be changed."""

    name: Optional[str] = Field(default=None, min_length=5, max_length=100)
    email: Optional[str] = None
    phone: Optional[str] = None
    facility: Optional[str] = Field(default=None, min_length=2, max_length=100)
    responsibilities: Optional[str] = Field(default=None, min_length=5, max_length=250)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return validate_two_full_names(v)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return validate_staff_email(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return normalize_phone(v)


class MotherRegistrationCreate(SQLModel):
    """Used by a Health Worker to register a Mother + create her single login account."""

    name: str = Field(min_length=5, max_length=100)
    email: Optional[str] = None  # Optional: auto-generates clinic @gmail.com if omitted
    phone: str
    password: str = Field(default="1234", min_length=4, max_length=64)
    dob: date
    village: str = ""
    due_date: Optional[date] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return validate_two_full_names(v)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        return validate_mother_gmail(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        return normalize_phone(v)

    @field_validator("dob")
    @classmethod
    def check_dob(cls, v: date) -> date:
        return validate_mother_dob(v)

    @field_validator("due_date")
    @classmethod
    def check_due_date(cls, v: Optional[date]) -> Optional[date]:
        return validate_mother_due_date(v)


# ---------- DOMAIN TABLES ----------


class Mother(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True)
    dob: Optional[date] = None
    village: str = ""
    due_date: Optional[date] = None
    owner_id: int = Field(foreign_key="user.id")


class MotherUpdate(SQLModel):
    dob: Optional[date] = None
    village: Optional[str] = None
    due_date: Optional[date] = None

    @field_validator("dob")
    @classmethod
    def check_dob(cls, v: Optional[date]) -> Optional[date]:
        if v is None:
            return None
        return validate_mother_dob(v)

    @field_validator("due_date")
    @classmethod
    def check_due_date(cls, v: Optional[date]) -> Optional[date]:
        return validate_mother_due_date(v)


class MotherRead(SQLModel):
    id: int
    user_id: int
    name: str
    email: Optional[str] = None
    phone: str
    dob: Optional[date] = None
    village: str = ""
    due_date: Optional[date] = None
    owner_id: int


class ChildCreate(SQLModel):
    mother_id: int = Field(foreign_key="mother.id")
    name: str
    dob: date
    sex: str = ""
    birth_weight: Optional[float] = None


class ChildUpdate(SQLModel):
    name: Optional[str] = None
    dob: Optional[date] = None
    sex: Optional[str] = None
    birth_weight: Optional[float] = None


class Child(ChildCreate, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")


class VisitCreate(SQLModel):
    mother_id: int = Field(foreign_key="mother.id")
    child_id: Optional[int] = Field(default=None, foreign_key="child.id")
    visit_date: date
    weight: Optional[float] = None
    height_cm: Optional[float] = None
    bp: str = ""
    notes: str = ""


class VisitUpdate(SQLModel):
    visit_date: Optional[date] = None
    weight: Optional[float] = None
    height_cm: Optional[float] = None
    bp: Optional[str] = None
    notes: Optional[str] = None


class Visit(VisitCreate, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    health_worker_id: int = Field(foreign_key="user.id")
    owner_id: int = Field(foreign_key="user.id")


class VaccinationCreate(SQLModel):
    child_id: int = Field(foreign_key="child.id")
    vaccine: str
    date_due: date
    date_given: Optional[date] = None
    status: str = "Pending"


class VaccinationUpdate(SQLModel):
    vaccine: Optional[str] = None
    date_due: Optional[date] = None
    date_given: Optional[date] = None
    status: Optional[str] = None


class Vaccination(VaccinationCreate, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")


class AppointmentCreate(SQLModel):
    mother_id: int = Field(foreign_key="mother.id")
    appt_date: date
    type: str = "Antenatal"
    status: str = "Pending"
    send_sms_reminder: bool = True


class AppointmentUpdate(SQLModel):
    appt_date: Optional[date] = None
    type: Optional[str] = None
    status: Optional[str] = None


class Appointment(AppointmentCreate, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    mother_id: int = Field(foreign_key="mother.id")
    appt_date: date
    type: str = "Antenatal"
    status: str = "Pending"
    owner_id: int = Field(foreign_key="user.id")


class ReminderCreate(SQLModel):
    user_id: int = Field(foreign_key="user.id")
    message: str
    send_date: date
    sent: bool = False


class ReminderUpdate(SQLModel):
    message: Optional[str] = None
    send_date: Optional[date] = None
    sent: Optional[bool] = None


class Reminder(ReminderCreate, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")


SQLModel.metadata.create_all(engine)


def ensure_unique_person(
    session: Session,
    name: str,
    phone: str,
    email: Optional[str] = None,
    staff_id: Optional[str] = None,
    exclude_user_id: Optional[int] = None,
):
    """Guarantees one person = one account = one permanent role across the entire app."""
    name_stmt = select(User).where(func.lower(User.name) == name.lower())
    if exclude_user_id is not None:
        name_stmt = name_stmt.where(User.id != exclude_user_id)
    existing_name = session.exec(name_stmt).first()
    if existing_name:
        raise HTTPException(
            status_code=409,
            detail=f"Policy violation: '{name}' already holds an account with role '{existing_name.role}'.",
        )

    phone_stmt = select(User).where(User.phone == phone)
    if exclude_user_id is not None:
        phone_stmt = phone_stmt.where(User.id != exclude_user_id)
    existing_phone = session.exec(phone_stmt).first()
    if existing_phone:
        raise HTTPException(
            status_code=409,
            detail=f"Policy violation: Phone '{phone}' is already registered under role '{existing_phone.role}'.",
        )

    if email:
        email_stmt = select(User).where(func.lower(User.email) == email.lower())
        if exclude_user_id is not None:
            email_stmt = email_stmt.where(User.id != exclude_user_id)
        existing_email = session.exec(email_stmt).first()
        if existing_email:
            raise HTTPException(
                status_code=409,
                detail=f"Policy violation: Email '{email}' is already registered under role '{existing_email.role}'.",
            )

    if staff_id:
        staff_stmt = select(User).where(func.lower(User.staff_id) == staff_id.lower())
        if exclude_user_id is not None:
            staff_stmt = staff_stmt.where(User.id != exclude_user_id)
        if session.exec(staff_stmt).first():
            raise HTTPException(
                status_code=409,
                detail=f"Policy violation: Staff ID '{staff_id}' is already assigned to a health worker.",
            )


tags_metadata = [
    {
        "name": "Authentication",
        "description": "Login by full name (username) and password, logout, and current user profile.",
    },
    {
        "name": "Admin",
        "description": "Admin-only account management for Health Workers and summarized clinic reports.",
    },
    {
        "name": "Mothers",
        "description": "Mother registration (Health Worker) and isolated mother profile access.",
    },
    {
        "name": "Children",
        "description": "Child registration and records linked to a mother.",
    },
    {
        "name": "Visits & Growth",
        "description": "Antenatal visits and child weight/height growth tracking.",
    },
    {
        "name": "Vaccinations",
        "description": "Child immunization schedules and vaccination status updates.",
    },
    {
        "name": "Appointments",
        "description": "Booking and tracking antenatal/child clinic appointments.",
    },
    {
        "name": "Reminders",
        "description": "Automated and manual SMS reminders for mothers.",
    },
    {
        "name": "Health Worker Alerts",
        "description": "Overdue vaccinations and missed appointments list for Health Workers.",
    },
]

app = FastAPI(
    title="Maternal and Child Health API",
    openapi_tags=tags_metadata,
)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


# ---------- AUTH & ROLE GUARDS ----------


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: SessionDep,
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        token_role = payload.get("role")
        sid = payload.get("sid")
        if sub is None or token_role is None or sid is None:
            raise credentials_exception
        user_id = int(sub)
    except (jwt.PyJWTError, ValueError):
        raise credentials_exception

    user = session.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or user.role != token_role
        or user.active_session_id != sid
    ):
        raise credentials_exception
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_admin(current_user: CurrentUserDep) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


def require_health_worker(current_user: CurrentUserDep) -> User:
    if current_user.role != "health_worker":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Health worker privileges required",
        )
    return current_user


AdminDep = Annotated[User, Depends(require_admin)]
HealthWorkerDep = Annotated[User, Depends(require_health_worker)]


def get_mother_profile_for_user(session: Session, user_id: int) -> Mother:
    mother = session.exec(select(Mother).where(Mother.user_id == user_id)).first()
    if not mother:
        raise HTTPException(status_code=404, detail="Mother profile not found")
    return mother


def build_mother_read(session: Session, mother: Mother) -> MotherRead:
    user = session.get(User, mother.user_id)
    return MotherRead(
        id=mother.id,
        user_id=mother.user_id,
        name=user.name if user else "",
        email=user.email if user else None,
        phone=user.phone if user else "",
        dob=mother.dob,
        village=mother.village,
        due_date=mother.due_date,
        owner_id=mother.owner_id,
    )


def apply_partial_update(item, patch_model: SQLModel):
    updates = patch_model.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(item, field, value)
    return item


# ---------- AUTHENTICATION ----------


@app.get("/", tags=["Authentication"])
def home():
    return {"message": "Maternal and Child Health API is running"}


@app.post("/login", response_model=Token, tags=["Authentication"])
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
):
    name_input = " ".join(form_data.username.strip().split())
    user = session.exec(
        select(User).where(func.lower(User.name) == name_input.lower())
    ).first()

    if user is None or not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid full name (username) or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact Admin.",
        )

    if user.role == "health_worker" and user.active_session_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This health worker account is already logged in. Log out first.",
        )

    session_id = str(uuid.uuid4())
    user.active_session_id = session_id
    session.add(user)
    session.commit()

    return Token(
        access_token=create_access_token(user.id, user.role, session_id),
        role=user.role,
        user_id=user.id,
        name=user.name,
    )


@app.post("/logout", tags=["Authentication"])
def logout(current_user: CurrentUserDep, session: SessionDep):
    current_user.active_session_id = None
    session.add(current_user)
    session.commit()
    return {"message": f"{current_user.name} logged out successfully"}


@app.get("/me", response_model=UserRead, tags=["Authentication"])
def read_me(current_user: CurrentUserDep):
    return current_user


# ---------- ADMIN: MANAGE USER ACCOUNTS & VIEW REPORTS ----------


@app.post(
    "/admin/health-workers",
    status_code=201,
    response_model=UserRead,
    tags=["Admin"],
)
def create_health_worker(
    data: HealthWorkerCreate,
    admin: AdminDep,
    session: SessionDep,
):
    ensure_unique_person(
        session=session,
        name=data.name,
        phone=data.phone,
        email=data.email,
        staff_id=data.staff_id,
    )

    worker = User(
        name=data.name,
        email=data.email,
        phone=data.phone,
        role="health_worker",
        staff_id=data.staff_id,
        facility=data.facility,
        responsibilities=data.responsibilities,
        password=hash_password(data.password),
    )
    session.add(worker)
    session.commit()
    session.refresh(worker)
    return worker


@app.get("/admin/users", response_model=list[UserRead], tags=["Admin"])
def list_all_users(admin: AdminDep, session: SessionDep):
    return session.exec(select(User)).all()


@app.get("/admin/users/{user_id}", response_model=UserRead, tags=["Admin"])
def get_user_by_admin(user_id: int, admin: AdminDep, session: SessionDep):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.put("/admin/users/{user_id}", response_model=UserRead, tags=["Admin"])
def update_user_by_admin(
    user_id: int,
    data: HealthWorkerUpdate,
    admin: AdminDep,
    session: SessionDep,
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and data.is_active is False:
        raise HTTPException(status_code=400, detail="Admin cannot deactivate own account")

    ensure_unique_person(
        session=session,
        name=data.name or user.name,
        phone=data.phone or user.phone,
        email=data.email if data.email is not None else user.email,
        exclude_user_id=user.id,
    )

    apply_partial_update(user, data)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@app.delete("/admin/users/{user_id}", status_code=204, tags=["Admin"])
def delete_user_by_admin(user_id: int, admin: AdminDep, session: SessionDep):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Admin cannot delete own account")
    session.delete(user)
    session.commit()


@app.get("/admin/reports/summary", tags=["Admin"])
def view_summarized_reports(admin: AdminDep, session: SessionDep):
    today = date.today()
    total_mothers = len(session.exec(select(Mother)).all())
    total_children = len(session.exec(select(Child)).all())
    total_health_workers = len(
        session.exec(select(User).where(User.role == "health_worker")).all()
    )
    total_visits = len(session.exec(select(Visit)).all())

    vaccinations = session.exec(select(Vaccination)).all()
    given_vaccines = sum(1 for v in vaccinations if v.status == "Given")
    overdue_vaccines = sum(
        1 for v in vaccinations if v.status == "Pending" and v.date_due < today
    )

    appointments = session.exec(select(Appointment)).all()
    upcoming_appts = sum(
        1 for a in appointments if a.status == "Pending" and a.appt_date >= today
    )
    missed_appts = sum(
        1
        for a in appointments
        if a.status == "Missed" or (a.status == "Pending" and a.appt_date < today)
    )

    return {
        "total_mothers": total_mothers,
        "total_children": total_children,
        "total_health_workers": total_health_workers,
        "total_antenatal_and_growth_visits": total_visits,
        "vaccinations": {
            "total": len(vaccinations),
            "given": given_vaccines,
            "overdue": overdue_vaccines,
        },
        "appointments": {
            "total": len(appointments),
            "upcoming": upcoming_appts,
            "missed_or_overdue": missed_appts,
        },
    }


# ---------- MOTHERS ----------


@app.post("/health-worker/register-mother", status_code=201, tags=["Mothers"])
def register_mother_and_account(
    data: MotherRegistrationCreate,
    worker: HealthWorkerDep,
    session: SessionDep,
):
    mother_email = (
        data.email
        or f"{data.name.lower().replace(' ', '.')}.{data.phone[-4:]}@gmail.com"
    )

    ensure_unique_person(
        session=session,
        name=data.name,
        phone=data.phone,
        email=mother_email,
    )

    mother_user = User(
        name=data.name,
        email=mother_email,
        phone=data.phone,
        role="mother",
        password=hash_password(data.password),
    )
    session.add(mother_user)
    session.commit()
    session.refresh(mother_user)

    mother_profile = Mother(
        user_id=mother_user.id,
        dob=data.dob,
        village=data.village,
        due_date=data.due_date,
        owner_id=worker.id,
    )
    session.add(mother_profile)
    session.commit()
    session.refresh(mother_profile)

    return {
        "user": UserRead.model_validate(mother_user),
        "mother": mother_profile,
    }


@app.get("/mothers", response_model=list[MotherRead], tags=["Mothers"])
def list_mothers(current_user: CurrentUserDep, session: SessionDep):
    if current_user.role == "mother":
        mothers = session.exec(
            select(Mother).where(Mother.user_id == current_user.id)
        ).all()
        return [build_mother_read(session, m) for m in mothers]
    if current_user.role == "health_worker":
        mothers = session.exec(select(Mother)).all()
        return [build_mother_read(session, m) for m in mothers]
    raise HTTPException(status_code=403, detail="Not authorized to view mother records")


@app.get("/mothers/{mother_id}", response_model=MotherRead, tags=["Mothers"])
def get_mother(mother_id: int, current_user: CurrentUserDep, session: SessionDep):
    mother = session.get(Mother, mother_id)
    if not mother:
        raise HTTPException(status_code=404, detail="Mother not found")
    if current_user.role == "mother" and mother.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot view another mother's record")
    if current_user.role == "admin":
        raise HTTPException(status_code=403, detail="Admin cannot view clinical records")
    return build_mother_read(session, mother)


@app.put("/mothers/{mother_id}", response_model=MotherRead, tags=["Mothers"])
def update_mother(
    mother_id: int,
    data: MotherUpdate,
    worker: HealthWorkerDep,
    session: SessionDep,
):
    mother = session.get(Mother, mother_id)
    if not mother:
        raise HTTPException(status_code=404, detail="Mother not found")
    apply_partial_update(mother, data)
    session.add(mother)
    session.commit()
    session.refresh(mother)
    return build_mother_read(session, mother)


@app.delete("/mothers/{mother_id}", status_code=204, tags=["Mothers"])
def delete_mother(mother_id: int, worker: HealthWorkerDep, session: SessionDep):
    mother = session.get(Mother, mother_id)
    if not mother:
        raise HTTPException(status_code=404, detail="Mother not found")
    session.delete(mother)
    session.commit()


# ---------- CHILDREN ----------


@app.post("/children", status_code=201, response_model=Child, tags=["Children"])
def create_child(data: ChildCreate, worker: HealthWorkerDep, session: SessionDep):
    if not session.get(Mother, data.mother_id):
        raise HTTPException(status_code=404, detail="Mother not found")
    existing_child = session.exec(
        select(Child).where(
            Child.mother_id == data.mother_id,
            func.lower(Child.name) == data.name.strip().lower(),
            Child.dob == data.dob,
        )
    ).first()
    if existing_child:
        raise HTTPException(
            status_code=409,
            detail="Duplicate child record for this mother",
        )
    child = Child.model_validate(data, update={"owner_id": worker.id})
    session.add(child)
    session.commit()
    session.refresh(child)
    return child


@app.get("/children", response_model=list[Child], tags=["Children"])
def list_children(current_user: CurrentUserDep, session: SessionDep):
    if current_user.role == "mother":
        mother = get_mother_profile_for_user(session, current_user.id)
        return session.exec(select(Child).where(Child.mother_id == mother.id)).all()
    if current_user.role == "health_worker":
        return session.exec(select(Child)).all()
    raise HTTPException(status_code=403, detail="Not authorized")


@app.get("/children/{child_id}", response_model=Child, tags=["Children"])
def get_child(child_id: int, current_user: CurrentUserDep, session: SessionDep):
    child = session.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role == "mother":
        mother = get_mother_profile_for_user(session, current_user.id)
        if child.mother_id != mother.id:
            raise HTTPException(status_code=403, detail="Cannot view another family's child")
        return child
    if current_user.role == "health_worker":
        return child
    raise HTTPException(status_code=403, detail="Not authorized")


@app.put("/children/{child_id}", response_model=Child, tags=["Children"])
def update_child(
    child_id: int,
    data: ChildUpdate,
    worker: HealthWorkerDep,
    session: SessionDep,
):
    child = session.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    apply_partial_update(child, data)
    session.add(child)
    session.commit()
    session.refresh(child)
    return child


@app.delete("/children/{child_id}", status_code=204, tags=["Children"])
def delete_child(child_id: int, worker: HealthWorkerDep, session: SessionDep):
    child = session.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    session.delete(child)
    session.commit()


# ---------- VISITS & GROWTH CHARTS ----------


@app.post("/visits", status_code=201, response_model=Visit, tags=["Visits & Growth"])
def record_visit_or_growth(
    data: VisitCreate, worker: HealthWorkerDep, session: SessionDep
):
    if not session.get(Mother, data.mother_id):
        raise HTTPException(status_code=404, detail="Mother not found")
    if data.child_id is not None and not session.get(Child, data.child_id):
        raise HTTPException(status_code=404, detail="Child not found")
    visit = Visit.model_validate(
        data, update={"health_worker_id": worker.id, "owner_id": worker.id}
    )
    session.add(visit)
    session.commit()
    session.refresh(visit)
    return visit


@app.get("/visits", response_model=list[Visit], tags=["Visits & Growth"])
def list_visits_and_growth(current_user: CurrentUserDep, session: SessionDep):
    if current_user.role == "mother":
        mother = get_mother_profile_for_user(session, current_user.id)
        return session.exec(select(Visit).where(Visit.mother_id == mother.id)).all()
    if current_user.role == "health_worker":
        return session.exec(select(Visit)).all()
    raise HTTPException(status_code=403, detail="Not authorized")


@app.get("/visits/{visit_id}", response_model=Visit, tags=["Visits & Growth"])
def get_visit(visit_id: int, current_user: CurrentUserDep, session: SessionDep):
    visit = session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    if current_user.role == "mother":
        mother = get_mother_profile_for_user(session, current_user.id)
        if visit.mother_id != mother.id:
            raise HTTPException(status_code=403, detail="Not authorized")
        return visit
    if current_user.role == "health_worker":
        return visit
    raise HTTPException(status_code=403, detail="Not authorized")


@app.put("/visits/{visit_id}", response_model=Visit, tags=["Visits & Growth"])
def update_visit(
    visit_id: int,
    data: VisitUpdate,
    worker: HealthWorkerDep,
    session: SessionDep,
):
    visit = session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    apply_partial_update(visit, data)
    session.add(visit)
    session.commit()
    session.refresh(visit)
    return visit


@app.delete("/visits/{visit_id}", status_code=204, tags=["Visits & Growth"])
def delete_visit(visit_id: int, worker: HealthWorkerDep, session: SessionDep):
    visit = session.get(Visit, visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    session.delete(visit)
    session.commit()


# ---------- VACCINATIONS & IMMUNIZATION SCHEDULE ----------


@app.post(
    "/vaccinations",
    status_code=201,
    response_model=Vaccination,
    tags=["Vaccinations"],
)
def record_immunization(
    data: VaccinationCreate, worker: HealthWorkerDep, session: SessionDep
):
    if not session.get(Child, data.child_id):
        raise HTTPException(status_code=404, detail="Child not found")
    vaccination = Vaccination.model_validate(data, update={"owner_id": worker.id})
    session.add(vaccination)
    session.commit()
    session.refresh(vaccination)
    return vaccination


@app.get("/vaccinations", response_model=list[Vaccination], tags=["Vaccinations"])
def view_vaccine_schedule(current_user: CurrentUserDep, session: SessionDep):
    if current_user.role == "mother":
        mother = get_mother_profile_for_user(session, current_user.id)
        children = session.exec(select(Child).where(Child.mother_id == mother.id)).all()
        child_ids = [c.id for c in children if c.id is not None]
        if not child_ids:
            return []
        return session.exec(
            select(Vaccination).where(Vaccination.child_id.in_(child_ids))
        ).all()
    if current_user.role == "health_worker":
        return session.exec(select(Vaccination)).all()
    raise HTTPException(status_code=403, detail="Not authorized")


@app.get(
    "/vaccinations/{vaccination_id}",
    response_model=Vaccination,
    tags=["Vaccinations"],
)
def get_vaccination(
    vaccination_id: int, current_user: CurrentUserDep, session: SessionDep
):
    vaccination = session.get(Vaccination, vaccination_id)
    if not vaccination:
        raise HTTPException(status_code=404, detail="Vaccination not found")
    if current_user.role == "mother":
        mother = get_mother_profile_for_user(session, current_user.id)
        child = session.get(Child, vaccination.child_id)
        if not child or child.mother_id != mother.id:
            raise HTTPException(status_code=403, detail="Not authorized")
        return vaccination
    if current_user.role == "health_worker":
        return vaccination
    raise HTTPException(status_code=403, detail="Not authorized")


@app.put(
    "/vaccinations/{vaccination_id}",
    response_model=Vaccination,
    tags=["Vaccinations"],
)
def update_vaccination(
    vaccination_id: int,
    data: VaccinationUpdate,
    worker: HealthWorkerDep,
    session: SessionDep,
):
    vaccination = session.get(Vaccination, vaccination_id)
    if not vaccination:
        raise HTTPException(status_code=404, detail="Vaccination not found")
    apply_partial_update(vaccination, data)
    session.add(vaccination)
    session.commit()
    session.refresh(vaccination)
    return vaccination


@app.delete("/vaccinations/{vaccination_id}", status_code=204, tags=["Vaccinations"])
def delete_vaccination(
    vaccination_id: int, worker: HealthWorkerDep, session: SessionDep
):
    vaccination = session.get(Vaccination, vaccination_id)
    if not vaccination:
        raise HTTPException(status_code=404, detail="Vaccination not found")
    session.delete(vaccination)
    session.commit()


# ---------- APPOINTMENTS & SMS REMINDERS ----------


@app.post(
    "/appointments",
    status_code=201,
    response_model=Appointment,
    tags=["Appointments"],
)
def book_appointment(
    data: AppointmentCreate, worker: HealthWorkerDep, session: SessionDep
):
    mother = session.get(Mother, data.mother_id)
    if not mother:
        raise HTTPException(status_code=404, detail="Mother not found")

    appt = Appointment(
        mother_id=data.mother_id,
        appt_date=data.appt_date,
        type=data.type,
        status=data.status,
        send_sms_reminder=data.send_sms_reminder,
        owner_id=worker.id,
    )
    session.add(appt)
    session.commit()
    session.refresh(appt)

    if data.send_sms_reminder:
        reminder = Reminder(
            user_id=mother.user_id,
            message=f"Reminder: Your {data.type} appointment is scheduled for {data.appt_date}.",
            send_date=data.appt_date - timedelta(days=1),
            sent=False,
            owner_id=worker.id,
        )
        session.add(reminder)
        session.commit()

    return appt


@app.get("/appointments", response_model=list[Appointment], tags=["Appointments"])
def view_appointments(current_user: CurrentUserDep, session: SessionDep):
    if current_user.role == "mother":
        mother = get_mother_profile_for_user(session, current_user.id)
        return session.exec(
            select(Appointment).where(Appointment.mother_id == mother.id)
        ).all()
    if current_user.role == "health_worker":
        return session.exec(select(Appointment)).all()
    raise HTTPException(status_code=403, detail="Not authorized")


@app.get(
    "/appointments/{appointment_id}",
    response_model=Appointment,
    tags=["Appointments"],
)
def get_appointment(
    appointment_id: int, current_user: CurrentUserDep, session: SessionDep
):
    appt = session.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if current_user.role == "mother":
        mother = get_mother_profile_for_user(session, current_user.id)
        if appt.mother_id != mother.id:
            raise HTTPException(status_code=403, detail="Not authorized")
        return appt
    if current_user.role == "health_worker":
        return appt
    raise HTTPException(status_code=403, detail="Not authorized")


@app.put(
    "/appointments/{appointment_id}",
    response_model=Appointment,
    tags=["Appointments"],
)
def update_appointment(
    appointment_id: int,
    data: AppointmentUpdate,
    worker: HealthWorkerDep,
    session: SessionDep,
):
    appt = session.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    apply_partial_update(appt, data)
    session.add(appt)
    session.commit()
    session.refresh(appt)
    return appt


@app.delete("/appointments/{appointment_id}", status_code=204, tags=["Appointments"])
def delete_appointment(
    appointment_id: int, worker: HealthWorkerDep, session: SessionDep
):
    appt = session.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    session.delete(appt)
    session.commit()


@app.post("/reminders", status_code=201, response_model=Reminder, tags=["Reminders"])
def create_reminder(
    data: ReminderCreate, worker: HealthWorkerDep, session: SessionDep
):
    if not session.get(User, data.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    reminder = Reminder.model_validate(data, update={"owner_id": worker.id})
    session.add(reminder)
    session.commit()
    session.refresh(reminder)
    return reminder


@app.get("/reminders", response_model=list[Reminder], tags=["Reminders"])
def view_sms_reminders(current_user: CurrentUserDep, session: SessionDep):
    if current_user.role == "mother":
        return session.exec(
            select(Reminder).where(Reminder.user_id == current_user.id)
        ).all()
    if current_user.role == "health_worker":
        return session.exec(select(Reminder)).all()
    raise HTTPException(status_code=403, detail="Not authorized")


@app.get("/reminders/{reminder_id}", response_model=Reminder, tags=["Reminders"])
def get_reminder(
    reminder_id: int, current_user: CurrentUserDep, session: SessionDep
):
    reminder = session.get(Reminder, reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if current_user.role == "mother" and reminder.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_user.role in ("mother", "health_worker"):
        return reminder
    raise HTTPException(status_code=403, detail="Not authorized")


@app.put("/reminders/{reminder_id}", response_model=Reminder, tags=["Reminders"])
def update_reminder(
    reminder_id: int,
    data: ReminderUpdate,
    worker: HealthWorkerDep,
    session: SessionDep,
):
    reminder = session.get(Reminder, reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    apply_partial_update(reminder, data)
    session.add(reminder)
    session.commit()
    session.refresh(reminder)
    return reminder


@app.delete("/reminders/{reminder_id}", status_code=204, tags=["Reminders"])
def delete_reminder(
    reminder_id: int, worker: HealthWorkerDep, session: SessionDep
):
    reminder = session.get(Reminder, reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    session.delete(reminder)
    session.commit()


# ---------- HEALTH WORKER: OVERDUE LIST ----------


@app.get("/health-worker/overdue", tags=["Health Worker Alerts"])
def view_overdue_list(worker: HealthWorkerDep, session: SessionDep):
    today = date.today()
    overdue_vaccinations = session.exec(
        select(Vaccination).where(
            Vaccination.status == "Pending", Vaccination.date_due < today
        )
    ).all()
    overdue_appointments = session.exec(
        select(Appointment).where(
            Appointment.status == "Pending", Appointment.appt_date < today
        )
    ).all()
    return {
        "date": today,
        "overdue_vaccinations": overdue_vaccinations,
        "overdue_appointments": overdue_appointments,
    }