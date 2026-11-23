from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlmodel import Session, SQLModel, select

from main import (
    User,
    engine,
    hash_password,
    normalize_phone,
    validate_staff_email,
    validate_two_full_names,
)


class StaffSeedSchema(BaseModel):
    """Validates full name, staff email, 10-digit phone, role, and password rules before database insertion."""

    name: str
    email: str
    phone: str
    role: str
    staff_id: str
    facility: str
    responsibilities: str
    password: str

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

    @field_validator("role")
    @classmethod
    def check_role(cls, v: str) -> str:
        if v not in ("admin", "health_worker"):
            raise ValueError("Seeded staff role must be 'admin' or 'health_worker'.")
        return v

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str, info) -> str:
        role = info.data.get("role")
        if role == "admin" and v != "pass123":
            raise ValueError("Admin password must be 'pass123'.")
        if role == "health_worker" and v != "1234":
            raise ValueError("Health worker password must be '1234'.")
        return v


INITIAL_STAFF = [
    StaffSeedSchema(
        name="Sarah Namukasa",
        email="admin_sarah@mchclinic",
        phone="0700000000",
        role="admin",
        staff_id="ADM-001",
        facility="Main Maternal & Child Health Center",
        responsibilities="Creates and manages Health Worker accounts and views summarized clinic reports.",
        password="pass123",
    ),
    StaffSeedSchema(
        name="Grace Nabirye",
        email="nurse_grace@mchclinic",
        phone="0701234567",
        role="health_worker",
        staff_id="HW-101",
        facility="Antenatal Care Unit",
        responsibilities="Registers mothers and children, records antenatal visits, and schedules clinic appointments.",
        password="1234",
    ),
    StaffSeedSchema(
        name="Esther Nakato",
        email="midwife_esther@mchclinic",
        phone="0702345678",
        role="health_worker",
        staff_id="HW-102",
        facility="Maternity & Postnatal Ward",
        responsibilities="Tracks maternal blood pressure, delivery due dates, and postnatal follow-up visits.",
        password="1234",
    ),
    StaffSeedSchema(
        name="Faith Babirye",
        email="clinician_ruth@mchclinic",
        phone="0703123456",
        role="health_worker",
        staff_id="HW-103",
        facility="Immunization & Child Growth Clinic",
        responsibilities="Administers childhood vaccines, tracks child weight/height growth charts, and monitors overdue alerts.",
        password="1234",
    ),
]


def seed_database() -> None:
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        created_count = 0
        skipped_count = 0

        for staff in INITIAL_STAFF:
            exists = session.exec(
                select(User).where(
                    (func.lower(User.name) == staff.name.lower())
                    | (func.lower(User.email) == staff.email.lower())
                    | (User.phone == staff.phone)
                    | (func.lower(User.staff_id) == staff.staff_id.lower())
                )
            ).first()

            if exists:
                skipped_count += 1
                print(
                    f"[SKIPPED] '{staff.name}' already holds an account (Role: {exists.role}, ID: {exists.id})"
                )
                continue

            user = User(
                name=staff.name,
                email=staff.email,
                phone=staff.phone,
                role=staff.role,
                staff_id=staff.staff_id,
                facility=staff.facility,
                responsibilities=staff.responsibilities,
                password=hash_password(staff.password),
                is_active=True,
            )
            session.add(user)
            session.commit()
            created_count += 1
            print(
                f"[CREATED] Role: {staff.role:13} | Username (Full Name): {staff.name:16} | Email: {staff.email:24} | Password: {staff.password}"
            )

        print(f"\nSeeding complete: {created_count} created, {skipped_count} skipped.")


if __name__ == "__main__":
    seed_database()