### Integrated Maternal and Child Health Monitoring System
REST API Documentation (FastAPI + SQLModel Backend)
Group Member	Registration Number
LUBEGA SHAWUTHABU	241_21301_7381
AYUGI FAITH	241_22302_7231
NAJJINGO FAIZAH	241_22302_7021

### 1. API Overview & Configuration
•	Backend Stack: Python FastAPI + SQLModel ORM + SQLite (maternal.db)
•	Local Base URL: http://127.0.0.1:8000 (Web/Desktop) | http://10.0.2.2:8000 (Android Emulator)
•	Authentication Scheme: JWT Bearer Token (Authorization: Bearer <access_token>), Algorithm HS256, 120-minute expiry
•	Authorized Roles: mother, worker, admin
•	Date & Time Standard: ISO 8601 format (YYYY-MM-DD for dates, YYYY-MM-DDTHH:MM:SS for timestamps)


### 2. Complete API Endpoint Summary Table
Method	Endpoint Path	Purpose	Auth	Request Body / Params	Success Response

GET	/	Health check confirming API is live	No	None	200 OK: {"message": "..."}
POST	/register	Register a new user account	No	JSON: name, phone, role, password	201 Created: UserRead JSON

POST	/login	Authenticate user & issue JWT token	No	Form: username (phone), password	200 OK: access_token, token_type

GET	/me	Retrieve logged-in user's profile	Bearer	None	200 OK: UserRead JSON

GET	/users	List all registered users	Bearer	None	200 OK: 

## list[UserRead]
POST	/users	Create a new user (admin/staff)	Bearer	JSON: name, phone, role, password	201 Created: UserRead JSON

GET	/users/{user_id}	Fetch a single user by ID	Bearer	Path: user_id (int)	200 OK: UserRead JSON

PUT	/users/{user_id}	Update user name, phone, or role	Bearer	

JSON: name, phone, role	200 OK: UserRead JSON

DELETE	/users/{user_id}	Delete a user account	Bearer	Path: user_id (int)	204 No Content

GET	/mothers	List all registered mothers	Bearer	None	200 OK: 

## list[Mother]

POST	/mothers	Register a new mother profile	Bearer	JSON: MotherCreate	201 Created: Mother JSON

GET	/mothers/{item_id}	Get details of a specific mother	Bearer	Path: item_id (int)	200 OK: Mother JSON

PUT	/mothers/{item_id}	Update mother profile (owner only)	Bearer	JSON: MotherCreate	200 OK: Mother JSON

DELETE	/mothers/{item_id}	Delete mother record (owner only)	Bearer	Path: item_id (int)	204 No Content

GET	/children	List all registered children	Bearer	None	200 OK: 

## list[Child]
POST	/children	Register a child linked to a mother	Bearer	JSON: ChildCreate	201 Created: Child JSON

GET	/children/{item_id}	Get details of a specific child	Bearer	Path: item_id (int)	200 OK: Child JSON

PUT	/children/{item_id}	Update child record (owner only)	Bearer	

JSON: ChildCreate	200 OK: Child JSON

DELETE	/children/{item_id}	Delete child record (owner only)	Bearer	Path: item_id (int)	204 No Content

GET	/visits	List all antenatal/clinical visits	Bearer	None	200 OK: 

## list[Visit]

POST	/visits	Record a new clinical/ANC visit	Bearer	JSON: VisitCreate	201 Created: Visit JSON

GET	/visits/{item_id}	Get a single visit record	Bearer	Path: item_id (int)	200 OK: Visit JSON

PUT	/visits/{item_id}	Update a visit record (owner only)	Bearer	

JSON: VisitCreate	200 OK: Visit JSON

DELETE	/visits/{item_id}	Delete a visit record (owner only)	Bearer	Path: item_id (int)	204 No Content

GET	/vaccinations	List all child vaccination records	Bearer	None	

## 200 OK: list[Vaccination]

POST	/vaccinations	Record a child vaccination/schedule	Bearer	

JSON: VaccinationCreate	201 Created: Vaccination JSON

GET	/vaccinations/{item_id}	Get a specific vaccination record	Bearer	Path: item_id (int)	200 OK: Vaccination JSON

PUT	/vaccinations/{item_id}	Update vaccination status/dates	Bearer	

JSON: VaccinationCreate	200 OK: Vaccination JSON

DELETE	/vaccinations/{item_id}	Delete vaccination record	Bearer	Path: item_id (int)	204 No Content

GET	/appointments	List all scheduled appointments	Bearer	None	200 

## OK: list[Appointment]
POST	/appointments	Schedule a new appointment	Bearer	JSON: AppointmentCreate	201 Created: Appointment JSON
GET	/appointments/{item_id}	Get a single appointment	Bearer	Path: item_id (int)	200 OK: Appointment JSON
PUT	/appointments/{item_id}	Update appointment date/status	Bearer	JSON: AppointmentCreate	200 OK: Appointment JSON
DELETE	/appointments/{item_id}	Cancel/delete appointment	Bearer	Path: item_id (int)	204 No Content
GET	/reminders	List all SMS/app reminders	Bearer	None	200 OK: 

## list[Reminder]
POST	/reminders	Create a new reminder message	Bearer	JSON: ReminderCreate	201 Created: Reminder JSON
GET	/reminders/{item_id}	Get a specific reminder	Bearer	Path: item_id (int)	200 OK: Reminder JSON
PUT	/reminders/{item_id}	Update reminder content/sent flag	Bearer	JSON: ReminderCreate	200 OK: Reminder JSON
DELETE	/reminders/{item_id}	Delete a reminder	Bearer	Path: 
item_id (int)	204 No Content

### 3. Detailed Endpoint Specifications & JSON Payloads

## 3.1 POST /register — Register User Account
Creates a new user account with a bcrypt-hashed password. Role must be 'mother', 'worker', or 'admin'. Password length: 4–50 characters.
// Request Body (application/json)
{
  "name": "Mary Namukasa",
  "phone": "0700000003",
  "role": "mother",
  "password": "password123"
}

// Response 201 Created (UserRead)
{
  "id": 1,
  "name": "Mary Namukasa",
  "phone": "0700000003",
  "role": "mother"
}

## 3.2 POST /login — Authenticate User
Accepts OAuth2 form data (application/x-www-form-urlencoded) where 'username' is the user's phone number.
// Form Data (application/x-www-form-urlencoded)
username=0700000003&password=password123

// Response 200 OK (Token)
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}

## 3.3 GET /me — Current Authenticated User
Requires header: Authorization: Bearer <access_token>. Returns 200 OK with UserRead JSON or 401 Unauthorized.


## 3.4 CRUD Request Body Schemas (/mothers, /children, /visits, /vaccinations, /appointments, /reminders)
All protected CRUD endpoints require a Bearer token. POST automatically assigns owner_id = current_user.id. PUT and DELETE verify ownership (returning 403 Forbidden if item.owner_id != current_user.id).
// POST /mothers (MotherCreate)
{
  "user_id": 1,
  "dob": "1995-03-12",
  "village": "Nabbingo, Wakiso",
  "due_date": "2027-01-20"
}

// POST /children (ChildCreate)
{
  "mother_id": 1,
  "name": "Baby Joy",
  "dob": "2026-07-25",
  "sex": "Female",
  "birth_weight": 3.2
}

// POST /visits (VisitCreate)
{
  "mother_id": 1,
  "child_id": 1,
  "health_worker_id": 2,
  "visit_date": "2026-11-22",
  "weight": 62.5,
  "bp": "118/76",
  "notes": "Routine antenatal check; vitals within normal range"
}

// POST /vaccinations (VaccinationCreate)
{
  "child_id": 1,
  "vaccine": "Pentavalent (Dose 1)",
  "date_due": "2026-12-10",
  "date_given": null,
  "status": "Pending"
}

// POST /appointments (AppointmentCreate)
{
  "mother_id": 1,
  "appt_date": "2026-12-01",
  "type": "Antenatal",
  "status": "Pending"
}

// POST /reminders (ReminderCreate)
{
  "user_id": 1,
  "message": "Reminder: Antenatal visit scheduled for 2026-12-01 at Nabbingo Clinic.",
  "send_date": "2026-11-30",
  "sent": false
}

## 4. Standard HTTP Status Codes
Status Code	Meaning	When Returned
200 OK	Success	Successful GET, PUT, or POST /login request
201 Created	Resource Created	Successful POST /register, POST /users, or POST CRUD creation
204 No Content	Deleted	Successful DELETE request
400 Bad Request	Validation / Duplicate Error	Invalid role or phone number already registered
401 Unauthorized	Authentication Failed	Invalid credentials or missing/expired JWT Bearer token
403 Forbidden	Permission Denied	Attempting to PUT/DELETE a record owned by another user
404 Not Found	Missing Record	Requested item_id or user_id does not exist in maternal.db

