import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path


DEFAULT_DATABASE = Path(__file__).resolve().parent / "instance" / "hospital.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('patient', 'doctor', 'admin')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    specialization TEXT NOT NULL,
    experience_years INTEGER NOT NULL CHECK (experience_years >= 0),
    bio TEXT NOT NULL DEFAULT '',
    availability TEXT NOT NULL DEFAULT 'Contact the clinic for availability',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS doctor_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    UNIQUE (doctor_id, weekday),
    CHECK (start_time < end_time)
);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    appointment_date TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending'
        CHECK (status IN ('Pending', 'Confirmed', 'Cancelled', 'Completed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP INDEX IF EXISTS uq_active_doctor_appointment_slot;

CREATE UNIQUE INDEX IF NOT EXISTS uq_reserved_doctor_appointment_slot
ON appointments (doctor_id, appointment_date, time_slot)
WHERE status != 'Cancelled';

CREATE TABLE IF NOT EXISTS app_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

SAMPLE_DOCTORS = (
    (
        "Dr. Maya Patel",
        "Cardiology",
        12,
        "Specializes in preventive heart care and cardiovascular health.",
        "Monday-Friday, 9:00 AM-1:00 PM",
    ),
    (
        "Dr. Ethan Brooks",
        "Dermatology",
        8,
        "Provides care for common skin conditions and routine skin checks.",
        "Monday-Thursday, 10:00 AM-4:00 PM",
    ),
    (
        "Dr. Sofia Nguyen",
        "Pediatrics",
        10,
        "Focuses on general health and wellness for children and families.",
        "Tuesday-Saturday, 9:00 AM-3:00 PM",
    ),
    (
        "Dr. Noah Williams",
        "Orthopedics",
        15,
        "Treats bone, joint, and mobility concerns.",
        "Monday-Friday, 8:30 AM-12:30 PM",
    ),
)

SAMPLE_DOCTOR_SCHEDULES = {
    "Dr. Maya Patel": (range(0, 5), "09:00", "13:00"),
    "Dr. Ethan Brooks": (range(0, 4), "10:00", "16:00"),
    "Dr. Sofia Nguyen": (range(1, 6), "09:00", "15:00"),
    "Dr. Noah Williams": (range(0, 5), "08:30", "12:30"),
}

SLOT_LENGTH_MINUTES = 30


def initialize_database(database_path=DEFAULT_DATABASE):
    """Create the application tables and add the example doctors once."""
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.executescript(SCHEMA)

        seeded = connection.execute(
            "SELECT 1 FROM app_metadata WHERE key = ?",
            ("sample_doctors_seeded",),
        ).fetchone()
        if seeded is None:
            connection.executemany(
                """
                INSERT INTO doctors
                    (name, specialization, experience_years, bio, availability)
                VALUES (?, ?, ?, ?, ?)
                """,
                SAMPLE_DOCTORS,
            )
            connection.execute(
                "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
                ("sample_doctors_seeded", "true"),
            )

        schedules_seeded = connection.execute(
            "SELECT 1 FROM app_metadata WHERE key = ?",
            ("sample_doctor_schedules_seeded",),
        ).fetchone()
        if schedules_seeded is None:
            for doctor_name, (weekdays, start_time, end_time) in (
                SAMPLE_DOCTOR_SCHEDULES.items()
            ):
                doctor = connection.execute(
                    "SELECT id FROM doctors WHERE name = ?",
                    (doctor_name,),
                ).fetchone()
                if doctor is None:
                    continue
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO doctor_schedules
                        (doctor_id, weekday, start_time, end_time)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        (doctor["id"], weekday, start_time, end_time)
                        for weekday in weekdays
                    ),
                )
            connection.execute(
                "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
                ("sample_doctor_schedules_seeded", "true"),
            )

        connection.commit()
    finally:
        connection.close()


def list_doctors(database_path=DEFAULT_DATABASE, search_term="", specialization=""):
    """Return doctor profiles, optionally filtered by text and specialization."""
    connection = _connect(database_path)
    try:
        query = """
            SELECT id, name, specialization, experience_years, bio, availability
            FROM doctors
        """
        conditions = []
        parameters = []
        if search_term:
            conditions.append(
                "(name LIKE ? OR specialization LIKE ? OR bio LIKE ?)"
            )
            search_pattern = f"%{search_term}%"
            parameters.extend((search_pattern, search_pattern, search_pattern))
        if specialization:
            conditions.append("specialization = ?")
            parameters.append(specialization)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY name COLLATE NOCASE"
        return connection.execute(query, parameters).fetchall()
    finally:
        connection.close()


def list_specializations(database_path=DEFAULT_DATABASE):
    connection = _connect(database_path)
    try:
        return connection.execute(
            """
            SELECT DISTINCT specialization
            FROM doctors
            ORDER BY specialization COLLATE NOCASE
            """
        ).fetchall()
    finally:
        connection.close()


def get_doctor_schedules(database_path, doctor_id):
    connection = _connect(database_path)
    try:
        return connection.execute(
            """
            SELECT weekday, start_time, end_time
            FROM doctor_schedules
            WHERE doctor_id = ?
            ORDER BY weekday
            """,
            (doctor_id,),
        ).fetchall()
    finally:
        connection.close()


def _connect(database_path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_user_by_email(database_path, email):
    connection = _connect(database_path)
    try:
        return connection.execute(
            "SELECT id, full_name, email, password_hash, role FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        connection.close()


def get_user_by_id(database_path, user_id):
    connection = _connect(database_path)
    try:
        return connection.execute(
            "SELECT id, full_name, email, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        connection.close()


def create_account(
    database_path,
    full_name,
    email,
    password_hash,
    role,
    doctor_profile=None,
):
    if role not in {"patient", "doctor", "admin"}:
        raise ValueError("Unsupported account role.")
    if role == "doctor" and doctor_profile is None:
        raise ValueError("Doctor profile details are required.")
    if role != "doctor" and doctor_profile is not None:
        raise ValueError("Only doctor accounts can have doctor profile details.")

    connection = _connect(database_path)
    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO users (full_name, email, password_hash, role)
                VALUES (?, ?, ?, ?)
                """,
                (full_name, email, password_hash, role),
            )
            user_id = cursor.lastrowid

            if role == "doctor":
                doctor_cursor = connection.execute(
                    """
                    INSERT INTO doctors
                        (user_id, name, specialization, experience_years, bio, availability)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, full_name, *doctor_profile[:4]),
                )
                connection.executemany(
                    """
                    INSERT INTO doctor_schedules
                        (doctor_id, weekday, start_time, end_time)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        (doctor_cursor.lastrowid, weekday, start_time, end_time)
                        for weekday, start_time, end_time in doctor_profile[4]
                    ),
                )

        return user_id
    finally:
        connection.close()


def get_doctor_for_user(database_path, user_id):
    connection = _connect(database_path)
    try:
        return connection.execute(
            """
            SELECT name, specialization, experience_years, bio, availability
            FROM doctors
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    finally:
        connection.close()


def count_admins(database_path):
    connection = _connect(database_path)
    try:
        return connection.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin'"
        ).fetchone()[0]
    finally:
        connection.close()


def get_admin_dashboard_counts(database_path):
    connection = _connect(database_path)
    try:
        return {
            "doctors": connection.execute(
                "SELECT COUNT(*) FROM doctors"
            ).fetchone()[0],
            "patients": connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'patient'"
            ).fetchone()[0],
            "appointments": connection.execute(
                "SELECT COUNT(*) FROM appointments"
            ).fetchone()[0],
        }
    finally:
        connection.close()


def get_doctor_by_id(database_path, doctor_id):
    connection = _connect(database_path)
    try:
        return connection.execute(
            """
            SELECT id, user_id, name, specialization, experience_years, bio, availability
            FROM doctors
            WHERE id = ?
            """,
            (doctor_id,),
        ).fetchone()
    finally:
        connection.close()


def add_doctor_profile(
    database_path,
    name,
    specialization,
    experience_years,
    bio,
    availability,
    schedule_rows,
):
    connection = _connect(database_path)
    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO doctors
                    (name, specialization, experience_years, bio, availability)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, specialization, experience_years, bio, availability),
            )
            doctor_id = cursor.lastrowid
            connection.executemany(
                """
                INSERT INTO doctor_schedules
                    (doctor_id, weekday, start_time, end_time)
                VALUES (?, ?, ?, ?)
                """,
                (
                    (doctor_id, weekday, start_time, end_time)
                    for weekday, start_time, end_time in schedule_rows
                ),
            )
        return doctor_id
    finally:
        connection.close()


def update_doctor_profile(
    database_path,
    doctor_id,
    name,
    specialization,
    experience_years,
    bio,
    availability,
    schedule_rows,
):
    connection = _connect(database_path)
    try:
        with connection:
            connection.execute(
                """
                UPDATE doctors
                SET name = ?, specialization = ?, experience_years = ?,
                    bio = ?, availability = ?
                WHERE id = ?
                """,
                (
                    name,
                    specialization,
                    experience_years,
                    bio,
                    availability,
                    doctor_id,
                ),
            )
            connection.execute(
                """
                UPDATE users
                SET full_name = ?
                WHERE id = (
                    SELECT user_id FROM doctors WHERE id = ?
                )
                """,
                (name, doctor_id),
            )
            connection.execute(
                "DELETE FROM doctor_schedules WHERE doctor_id = ?",
                (doctor_id,),
            )
            connection.executemany(
                """
                INSERT INTO doctor_schedules
                    (doctor_id, weekday, start_time, end_time)
                VALUES (?, ?, ?, ?)
                """,
                (
                    (doctor_id, weekday, start_time, end_time)
                    for weekday, start_time, end_time in schedule_rows
                ),
            )
    finally:
        connection.close()


def delete_doctor_profile(database_path, doctor_id):
    connection = _connect(database_path)
    try:
        with connection:
            appointment_count = connection.execute(
                "SELECT COUNT(*) FROM appointments WHERE doctor_id = ?",
                (doctor_id,),
            ).fetchone()[0]
            if appointment_count:
                return False

            connection.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
            return connection.total_changes > 0
    finally:
        connection.close()


def get_available_slots(database_path, doctor_id, appointment_date):
    selected_date = date.fromisoformat(appointment_date)
    if selected_date.isoformat() != appointment_date:
        raise ValueError("Use a date in YYYY-MM-DD format.")
    if selected_date < date.today():
        return []

    connection = _connect(database_path)
    try:
        schedule = connection.execute(
            """
            SELECT start_time, end_time
            FROM doctor_schedules
            WHERE doctor_id = ? AND weekday = ?
            """,
            (doctor_id, selected_date.weekday()),
        ).fetchone()
        if schedule is None:
            return []

        booked_slots = {
            row["time_slot"]
            for row in connection.execute(
                """
                SELECT time_slot
                FROM appointments
                WHERE doctor_id = ? AND appointment_date = ?
                    AND status != 'Cancelled'
                """,
                (doctor_id, appointment_date),
            )
        }
        start = time.fromisoformat(schedule["start_time"])
        end = time.fromisoformat(schedule["end_time"])
        candidate = datetime.combine(selected_date, start)
        closing_time = datetime.combine(selected_date, end)
        now = datetime.now()
        slots = []

        while candidate + timedelta(minutes=SLOT_LENGTH_MINUTES) <= closing_time:
            slot = candidate.strftime("%H:%M")
            if (
                slot not in booked_slots
                and (selected_date != date.today() or candidate >= now)
            ):
                slots.append(slot)
            candidate += timedelta(minutes=SLOT_LENGTH_MINUTES)

        return slots
    finally:
        connection.close()


def create_appointment(
    database_path, patient_id, doctor_id, appointment_date, time_slot
):
    selected_date = date.fromisoformat(appointment_date)
    selected_time = time.fromisoformat(time_slot)
    if (
        selected_date.isoformat() != appointment_date
        or selected_time.strftime("%H:%M") != time_slot
    ):
        raise ValueError("Choose a valid date and time slot.")
    if selected_date < date.today():
        raise ValueError("Appointments cannot be booked in the past.")

    connection = _connect(database_path)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            schedule = connection.execute(
                """
                SELECT start_time, end_time
                FROM doctor_schedules
                WHERE doctor_id = ? AND weekday = ?
                """,
                (doctor_id, selected_date.weekday()),
            ).fetchone()
            if schedule is None:
                raise ValueError("The doctor is not available on that day.")

            start = time.fromisoformat(schedule["start_time"])
            end = time.fromisoformat(schedule["end_time"])
            start_minutes = start.hour * 60 + start.minute
            slot_minutes = selected_time.hour * 60 + selected_time.minute
            end_minutes = end.hour * 60 + end.minute
            if (
                slot_minutes < start_minutes
                or slot_minutes + SLOT_LENGTH_MINUTES > end_minutes
                or (slot_minutes - start_minutes) % SLOT_LENGTH_MINUTES != 0
            ):
                raise ValueError("That time is outside the doctor's available slots.")

            now = datetime.now()
            appointment_start = datetime.combine(selected_date, selected_time)
            if selected_date == date.today() and appointment_start < now:
                raise ValueError("Appointments cannot be booked in the past.")

            booked = connection.execute(
                """
                SELECT 1
                FROM appointments
                WHERE doctor_id = ? AND appointment_date = ? AND time_slot = ?
                    AND status != 'Cancelled'
                """,
                (doctor_id, appointment_date, time_slot),
            ).fetchone()
            if booked is not None:
                raise ValueError("That appointment slot has already been booked.")

            cursor = connection.execute(
                """
                INSERT INTO appointments
                    (patient_id, doctor_id, appointment_date, time_slot, status)
                VALUES (?, ?, ?, ?, 'Pending')
                """,
                (patient_id, doctor_id, appointment_date, time_slot),
            )
            return cursor.lastrowid
    finally:
        connection.close()


def get_patient_appointments(database_path, patient_id):
    today = date.today().isoformat()
    current_time = datetime.now().strftime("%H:%M")
    connection = _connect(database_path)
    try:
        rows = connection.execute(
            """
            SELECT a.id, a.appointment_date, a.time_slot, a.status,
                   d.name AS doctor_name, d.specialization
            FROM appointments AS a
            JOIN doctors AS d ON d.id = a.doctor_id
            WHERE a.patient_id = ?
            ORDER BY a.appointment_date DESC, a.time_slot DESC
            """,
            (patient_id,),
        ).fetchall()
        upcoming = []
        previous = []
        for appointment in rows:
            is_upcoming = (
                appointment["status"] in {"Pending", "Confirmed"}
                and (
                    appointment["appointment_date"] > today
                    or (
                        appointment["appointment_date"] == today
                        and appointment["time_slot"] > current_time
                    )
                )
            )
            (upcoming if is_upcoming else previous).append(appointment)
        return upcoming, previous
    finally:
        connection.close()


def cancel_patient_appointment(database_path, appointment_id, patient_id):
    today = date.today().isoformat()
    current_time = datetime.now().strftime("%H:%M")
    connection = _connect(database_path)
    try:
        with connection:
            cursor = connection.execute(
                """
                UPDATE appointments
                SET status = 'Cancelled'
                WHERE id = ? AND patient_id = ?
                    AND status IN ('Pending', 'Confirmed')
                    AND (
                        appointment_date > ?
                        OR (appointment_date = ? AND time_slot > ?)
                    )
                """,
                (
                    appointment_id,
                    patient_id,
                    today,
                    today,
                    current_time,
                ),
            )
            return cursor.rowcount == 1
    finally:
        connection.close()


def list_all_appointments(database_path):
    connection = _connect(database_path)
    try:
        return connection.execute(
            """
            SELECT a.id, a.appointment_date, a.time_slot, a.status,
                   u.full_name AS patient_name, u.email AS patient_email,
                   d.name AS doctor_name, d.specialization
            FROM appointments AS a
            JOIN users AS u ON u.id = a.patient_id
            JOIN doctors AS d ON d.id = a.doctor_id
            ORDER BY a.appointment_date DESC, a.time_slot DESC
            """
        ).fetchall()
    finally:
        connection.close()


def update_appointment_status(database_path, appointment_id, new_status):
    transitions = {
        "Pending": {"Confirmed", "Cancelled"},
        "Confirmed": {"Completed", "Cancelled"},
    }
    connection = _connect(database_path)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            appointment = connection.execute(
                "SELECT status FROM appointments WHERE id = ?",
                (appointment_id,),
            ).fetchone()
            if appointment is None:
                raise LookupError("Appointment not found.")
            current_status = appointment["status"]
            if new_status not in transitions.get(current_status, set()):
                raise ValueError(
                    f"An appointment cannot be changed from {current_status} to {new_status}."
                )

            connection.execute(
                "UPDATE appointments SET status = ? WHERE id = ?",
                (new_status, appointment_id),
            )
    finally:
        connection.close()
