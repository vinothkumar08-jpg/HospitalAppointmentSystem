# Hospital Appointment Booking System

A local learning project built with HTML, CSS, JavaScript, Flask, and SQLite.
The app will use sample doctor records and dummy patient data only. Do not enter
real patient information.

## Project layout

```text
HospitalAppointmentSystem/
├── app.py                  # Flask routes and application startup
├── database.py             # SQLite setup and database helpers
├── requirements.txt        # Python packages
├── README.md               # Setup and usage instructions
├── .gitignore              # Files that should not be saved in Git
├── instance/               # Local SQLite database (created when the app runs)
├── templates/              # Shared layout, home, login, registration, dashboards
├── static/
│   ├── css/styles.css      # Responsive hospital-themed styles
│   └── js/app.js           # Confirmation prompts for destructive actions
└── tests/test_app.py       # Automated app and database tests
```

## Windows 11 setup

Install a stable Python 3.13 release, then open this folder in VS Code and
select **Terminal → New Terminal**. The explicit version flag avoids creating
the environment with a Python preview release:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use Command Prompt instead:

```bat
.\.venv\Scripts\activate.bat
```

Start the local development server with:

```powershell
python app.py
```

Then open the local URL printed in the terminal (by default,
`http://127.0.0.1:5000`).

## Current build stage

The home page currently shows sample doctor profiles. Patient and doctor
registration, sign-in, sign-out, and role-specific dashboards are also
available. Passwords are stored as one-way hashes, and form submissions include
CSRF protection. Admins can add and edit doctor profiles, and can remove
profiles that have no appointment history. Patients can search doctors, book
from each doctor's weekly schedule, review or cancel appointments, and see
their appointment status. Admins can confirm, cancel, or complete appointments.
Bookable times are 30-minute slots generated from each doctor's selected
weekdays and working hours. If you already had a doctor profile before weekly
schedules were added, an admin must edit that profile and save its schedule
before it has bookable slots.
The admin dashboard is available at `/admin/dashboard`; create its first
account from the terminal as described below.

Create the first administrator from the VS Code terminal after activating the
virtual environment. The password is entered at a hidden prompt and stored only
as a one-way hash:

```powershell
flask --app app create-admin
```

Then sign in at `http://127.0.0.1:5000/admin/login`. The administrator setup
command is only for the first admin account; it will not create duplicate
administrator accounts.

Run the automated tests from the VS Code terminal with:

```powershell
python -m pytest
```

## VS Code

1. Open this project folder in VS Code.
2. Open the integrated terminal and run the setup commands above.
3. If VS Code asks you to choose a Python interpreter, select
   `.venv\Scripts\python.exe`.
4. Run `python app.py` in the integrated terminal.
5. To stop the server, focus the terminal and press **Ctrl+C**.

This project is for local development and education. Before deploying an
appointment system for real use, it would need a security and privacy review,
production configuration, and appropriate operational safeguards.
