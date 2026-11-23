# OVERVIEW

The backend is responsible for processing application requests, managing health records, handling authentication, and communicating with the database.

It will act as the connection between the Flutter mobile application and the database.

## MAIN RESPONSIBILITIES

- Register and authenticate system users.
- Store and retrieve maternal health records.
- Manage antenatal and postnatal visit information.
- Store and update child immunization records.
- Monitor child growth information.
- Manage appointment schedules and reminders.
- Identify and flag high-risk cases for review by authorized healthcare workers.
- Generate reports for healthcare workers and administrators.

## PROPOSED BACKEND STRUCTURE

- "main.py": Entry point of the backend application.
- "database.sql": Contains the proposed database structure and SQL commands.
- "models/": Defines the data structures used by the backend.
- "routers/": Organizes application endpoints and requests.
- "authentication/": Handles user registration, login, and access control.
- "requirements.txt": Lists the Python packages required by the backend.

## TECHNOLOGY SELECTION

The backend framework, API design, database connection, and hosting server will be selected and agreed upon by the project team.

## SECURITY CONSIDERATIONS

- Protect users' login credentials.
- Restrict access to confidential health records.
- Allow only authorized users to access or update relevant information.
- Protect maternal and child health information from unauthorized access.

## DEVELOPMENT STATUS

This directory contains the initial backend project structure. Backend implementation and technology selection will be completed as the project progresses.

## Setup
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
## Run
```
fastapi dev main.py
```
API docs: http://127.0.0.1:8000/docs

## Tables

Users, Mothers, Children, Visits, Vaccinations, Appointments, Reminders
Each table has GET, POST, PUT and DELETE endpoints.
The first run creates maternal.db, which is not committed.
Login will be added in a later.

# Maternal and Child Health API — Backend Documentation

## Overview
This backend powers the **Maternal and Child Health App**, built with **FastAPI**, **SQLModel**, and **SQLite** (`maternal.db`). It manages role-based authentication (`admin`, `health_worker`, `mother`), maternal and child clinical records, antenatal and growth visits, immunization schedules, clinic appointments, automated SMS reminders, and overdue clinical alerts.

## Backend Files & Their Purpose

 ##---`main.py`---##: Core FastAPI application. Defines the SQLite database connection, SQLModel tables, Pydantic validation schemas, bcrypt password hashing, JWT authentication and single-session enforcement, role-based dependency guards, and all REST API endpoints.
 **`seed.py`**: Initial database seeding script. Creates the database tables and inserts initial staff accounts (`Sarah Namukasa` as `admin`, and `Grace Nabirye`, `Esther Nakato`, and `Ruth Babirye` as `health_worker`) using the exact validators imported from `main.py` while skipping already existing accounts to prevent duplicates.
 **`database.sql`**: Reference SQL structure and table definitions for the database schema.
 **`requirements.txt`**: Lists all Python packages required to run the backend environment.
 **`.gitignore`**: Excludes local virtual environments (`venv/`), generated SQLite databases (`maternal.db`), and Python cache files (`__pycache__/`) from version control.

---

## Imports in `main.py` & Why Each Was Used

 **`os`**: Used to read environment variables (`os.getenv("MCH_SECRET_KEY", ...)`), keeping cryptographic secret keys configurable outside source code while providing a local development fallback.
 **`re`**: Used for regular expression validation (`re.fullmatch`, `re.search`) to enforce strict formatting rules on full names (at least two letter-only names), staff emails (special character required, no full stops), and mother Gmail usernames.
 **`uuid`**: Used to generate unique session identifiers (`uuid.uuid4()`) at login so the backend can bind each JWT to an active database session (`active_session_id`) and enforce single-session login rules for health workers.
 **`datetime` (`date`, `datetime`, `timedelta`, `timezone`)**:
   `datetime` & `timezone`: Used to generate UTC expiration timestamps (`exp`) for JWT access tokens.
   `date` & `timedelta`: Used to calculate maternal age from `dob` (14–55 years), bound expected `due_date` values (-30 days to +280 days), schedule automatic SMS reminders one day before appointments (`appt_date - timedelta(days=1)`), and identify overdue vaccinations and missed appointments (`date_due < today`).

 **`typing` (`Annotated`, `Optional`)**:
   `Optional`: Marks nullable database columns and optional request/patch fields.Nullable databses are columns in the SQLite database (via SQLModel / Field(default=None, ...)) that are allowed to store NULL (empty/missing values) instead of requiring a value every time e.g the email of the mother is left empty and is auto-generated by the system since mothers may fail to remember their emails.
   
   `Annotated`: Attaches FastAPI `Depends(...)` metadata cleanly to reusable type aliases (`SessionDep`, `CurrentUserDep`, `AdminDep`, `HealthWorkerDep`) and OAuth2 login form inputs.
 **`bcrypt`**: Used to securely hash plain-text passwords (`bcrypt.hashpw` with `bcrypt.gensalt()`) before saving to SQLite and to verify passwords during `/login` (`bcrypt.checkpw`).
 **`jwt` (`PyJWT`)**: Used to sign `HS256` JSON Web Tokens upon login (`jwt.encode`) and decode/verify bearer tokens on protected endpoints (`jwt.decode`).
 **`fastapi` (`Depends`, `FastAPI`, `HTTPException`, `status`)**:
   `FastAPI`: Initializes the API application and OpenAPI/Swagger tag groups.
   `Depends`: Injects database sessions and role-verification guards into route handlers.
   `HTTPException` & `status`: Returns standardized HTTP error codes (`400`, `401`, `403`, `404`, `409`, `422`) when authentication, role permissions, uniqueness, or validation checks fail.
 **`fastapi.security` (`OAuth2PasswordBearer`, `OAuth2PasswordRequestForm`)**:
   `OAuth2PasswordBearer(tokenUrl="/login")`: Extracts `Authorization: Bearer <token>` headers from incoming requests and enables the **Authorize** button in Swagger UI.
   `OAuth2PasswordRequestForm`: Parses standard `username` (full name) and `password` form submissions on `POST /login`.
 **`pydantic` (`field_validator`)**: Attaches custom field-level validation functions directly onto request and update schemas (`HealthWorkerCreate`, `HealthWorkerUpdate`, `MotherRegistrationCreate`, `MotherUpdate`).
 **`sqlalchemy` (`func`)**: Provides `func.lower(...)` for case-insensitive SQL queries during login lookups and duplicate person/email/staff ID checks.
 **`sqlmodel` (`Field`, `Session`, `SQLModel`, `create_engine`, `select`)**:
   `SQLModel` & `Field`: Unifies SQLAlchemy database tables (`table=True`) and Pydantic request/response schemas in a single class hierarchy.
   `create_engine`: Connects SQLModel to `sqlite:///maternal.db` with `check_same_thread=False` for FastAPI request handling.
   `Session` & `select`: Manages database transactions and executes type-safe SQL queries.

## Core Backend Architecture & Code Explanation (`main.py`)

### 1. Security & Authentication Helpers
 **`hash_password` / `verify_password`**: Ensures plain-text passwords are never stored in `maternal.db`.
 **`create_access_token`**: Embeds `sub` (`user_id`), `role`, `sid` (`session_id`), and `exp` (120 minutes) into a signed JWT.
 **`get_current_user`**: Decodes the bearer token, verifies the user exists and `is_active` is `True`, confirms the token `role` matches the database `role`, and checks that `sid` matches `user.active_session_id` (invalidating tokens immediately after `/logout`).
 **`require_admin` & `require_health_worker`**: Role-based dependency guards returning `403 Forbidden` if a user attempts to access endpoints outside their role.

### 2. Data Integrity & Validation Rules* **`validate_two_full_names`**: Requires at least two full words containing only letters (`[A-Za-z]{2,}`).
 **`validate_staff_email`**: Enforces that `admin` and `health_worker` emails contain at least one special character (`_`, `-`, `+`, `!`, `#`, `$`, `%`, `&`, `*`) and zero full stops (`.`).
 **`validate_mother_gmail`**: Enforces that mother emails strictly end with `@gmail.com`. When left blank during registration, `register_mother_and_account` auto-generates a unique clinic Gmail address (`firstname.lastname.last4digits@gmail.com`) so mothers without personal email accounts can still be registered smoothly.
 **`normalize_phone`**: Enforces 10-digit phone numbers starting with `07`.

 **`validate_mother_dob` & `validate_mother_due_date`**: Blocks today or future birth dates, restricts maternal age to 14–55 years, and ensures `due_date` falls between 30 days in the past and 280 days (~40 weeks) in the future.

 **`ensure_unique_person`**: Prevents duplicate accounts across `name`, `phone`, `email`, and `staff_id`, guaranteeing one person holds one permanent role (`409 Conflict` on duplicates).

### 3. Database Models & Joined Read Schemas
 **`User` & `UserRead`**: Stores login credentials, immutable `role`, `staff_id`, `facility`, `responsibilities`, `is_active`, and `active_session_id`. `UserRead` strips sensitive fields (`password`, `active_session_id`) from API responses.
 **`Mother`, `MotherUpdate`, & `MotherRead`**: Links a mother's clinical record (`dob`, `village`, `due_date`) to her `User` account (`user_id`) and registering health worker (`owner_id`). `MotherRead` and `build_mother_read` join `User` fields (`name`, `email`, `phone`) onto `Mother` clinical fields so `GET /mothers` and `GET /mothers/{mother_id}` return complete mother profiles in a single call.
##`Child`, `Visit`, `Vaccination`, `Appointment`, & `Reminder`##: Track child profiles, antenatal/growth measurements (`weight`, `height_cm`, `bp`), immunization schedules, clinic appointments (which auto-generate a `Reminder` 1 day prior when `send_sms_reminder=True`), and SMS alerts.

### 4. Endpoint Groups & Access Isolation
##---Authentication (`/`, `/login`, `/logout`, `/me`)**: Authenticates users by full name and password, blocks concurrent logins for `health_worker` accounts (`409 Conflict`) until `/logout` is called, and returns the active user's profile.

 ##---Admin (`/admin/health-workers`, `/admin/users`, `/admin/reports/summary`)---##: Allows admins to create, view, update, deactivate, or delete user accounts and view aggregated clinic statistics without exposing private mother clinical records.

 ##---Mothers (`/health-worker/register-mother`, `/mothers`, `/mothers/{mother_id}`)---##: Allows health workers to register and manage mothers while restricting logged-in mothers to viewing only their own record.

 ##---Children, Visits & Growth, Vaccinations, Appointments, Reminders---##: Health workers create, update, and delete clinical records; mothers have read-only access isolated strictly to their own and their children's records.##

 ##---Health Worker Alerts (`/health-worker/overdue`)---##: Queries all `Pending` vaccinations with `date_due < today` and `Pending` appointments with `appt_date < today` for clinical follow-up.


## How the Backend Was Set Up & Run

1. **Navigated through the backend directory and activated the virtual environment (Windows PowerShell):**
   ```powershell
   cd flutter_2026\capstone\maternal_child_health_app\backend
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   