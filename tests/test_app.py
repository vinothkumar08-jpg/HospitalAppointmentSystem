import re
import sqlite3
from datetime import date, timedelta

from app import create_app
from werkzeug.security import check_password_hash


def get_csrf_token(response):
    page = response.get_data(as_text=True)
    match = re.search(r'name="_csrf_token" value="([^"]+)"', page)
    assert match is not None
    return match.group(1)


def test_homepage_shows_sample_doctors(tmp_path):
    database_path = tmp_path / "hospital.db"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(database_path),
            "SECRET_KEY": "test-secret",
        }
    )

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert b"Dr. Maya Patel" in response.data
    assert b"Cardiology" in response.data
    assert database_path.exists()


def test_patient_can_register_login_and_logout(tmp_path):
    database_path = tmp_path / "hospital.db"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(database_path),
            "SECRET_KEY": "test-secret",
        }
    )
    client = app.test_client()

    register_page = client.get("/register/patient")
    response = client.post(
        "/register/patient",
        data={
            "_csrf_token": get_csrf_token(register_page),
            "full_name": "Jamie Example",
            "email": "jamie@example.test",
            "password": "long-test-password",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Your account was created" in response.data

    connection = sqlite3.connect(database_path)
    password_hash = connection.execute(
        "SELECT password_hash FROM users WHERE email = ?",
        ("jamie@example.test",),
    ).fetchone()[0]
    connection.close()
    assert password_hash != "long-test-password"
    assert check_password_hash(password_hash, "long-test-password")

    login_page = client.get("/login")
    response = client.post(
        "/login",
        data={
            "_csrf_token": get_csrf_token(login_page),
            "email": "jamie@example.test",
            "password": "long-test-password",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Welcome, Jamie Example" in response.data

    logout_page = client.get("/dashboard")
    assert logout_page.status_code == 200
    csrf_token = get_csrf_token(logout_page)
    response = client.post(
        "/logout",
        data={"_csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"You have signed out" in response.data


def test_doctor_registration_creates_linked_profile_and_role_is_enforced(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "hospital.db"),
            "SECRET_KEY": "test-secret",
        }
    )
    client = app.test_client()
    register_page = client.get("/register/doctor")
    response = client.post(
        "/register/doctor",
        data={
            "_csrf_token": get_csrf_token(register_page),
            "full_name": "Alex Doctor",
            "email": "alex@example.test",
            "password": "long-test-password",
            "specialization": "Neurology",
            "experience_years": "7",
            "weekdays": ["0", "1", "2", "3", "4"],
            "start_time": "09:00",
            "end_time": "17:00",
            "bio": "Sample profile",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Your account was created" in response.data

    login_page = client.get("/login")
    response = client.post(
        "/login",
        data={
            "_csrf_token": get_csrf_token(login_page),
            "email": "alex@example.test",
            "password": "long-test-password",
        },
        follow_redirects=True,
    )
    assert b"Welcome, Alex Doctor" in response.data
    assert b"Your doctor profile" in response.data
    assert client.get("/dashboard").status_code == 403


def test_post_without_valid_csrf_token_is_rejected(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "hospital.db"),
            "SECRET_KEY": "test-secret",
        }
    )

    response = app.test_client().post(
        "/register/patient",
        data={
            "full_name": "Jamie Example",
            "email": "jamie@example.test",
            "password": "long-test-password",
        },
    )

    assert response.status_code == 400


def test_admin_can_manage_doctors_and_remove_only_profiles_without_appointments(
    tmp_path,
):
    database_path = tmp_path / "hospital.db"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(database_path),
            "SECRET_KEY": "test-secret",
        }
    )
    client = app.test_client()

    assert client.get("/admin/dashboard").status_code == 302
    assert "/admin/login" in client.get("/admin/dashboard").headers["Location"]

    result = app.test_cli_runner().invoke(
        args=["create-admin"],
        input="admin@example.test\nsecure-admin-password\nsecure-admin-password\n",
    )
    assert result.exit_code == 0, result.output
    assert b"secure-admin-password" not in result.output.encode()

    login_page = client.get("/admin/login")
    response = client.post(
        "/admin/login",
        data={
            "_csrf_token": get_csrf_token(login_page),
            "email": "admin@example.test",
            "password": "secure-admin-password",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Administrator dashboard" in response.data

    dashboard_page = client.get("/admin/dashboard")
    response = client.post(
        "/admin/doctors",
        data={
            "_csrf_token": get_csrf_token(dashboard_page),
            "name": "Taylor Sample",
            "specialization": "Neurology",
            "experience_years": "6",
            "weekdays": ["0", "1", "2", "3", "4"],
            "start_time": "09:00",
            "end_time": "17:00",
            "bio": "Sample profile",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Doctor profile added" in response.data

    connection = sqlite3.connect(database_path)
    doctor_id = connection.execute(
        "SELECT id FROM doctors WHERE name = 'Taylor Sample'"
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO users (full_name, email, password_hash, role)
        VALUES ('Dummy Patient', 'dummy@example.test', 'test-hash', 'patient')
        """
    )
    patient_id = connection.execute(
        "SELECT id FROM users WHERE email = 'dummy@example.test'"
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO appointments
            (patient_id, doctor_id, appointment_date, time_slot, status)
        VALUES (?, ?, '2030-04-05', '10:00', 'Cancelled')
        """,
        (patient_id, doctor_id),
    )
    connection.commit()
    connection.close()

    edit_page = client.get(f"/admin/doctors/{doctor_id}/edit")
    response = client.post(
        f"/admin/doctors/{doctor_id}/edit",
        data={
            "_csrf_token": get_csrf_token(edit_page),
            "name": "Taylor Updated",
            "specialization": "Neurology",
            "experience_years": "7",
            "weekdays": ["1", "3", "5"],
            "start_time": "10:00",
            "end_time": "14:00",
            "bio": "Updated sample profile",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Doctor profile updated" in response.data

    dashboard_page = client.get("/admin/dashboard")
    response = client.post(
        f"/admin/doctors/{doctor_id}/delete",
        data={"_csrf_token": get_csrf_token(dashboard_page)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"cannot be removed" in response.data

    connection = sqlite3.connect(database_path)
    profile_name = connection.execute(
        "SELECT name FROM doctors WHERE id = ?", (doctor_id,)
    ).fetchone()[0]
    unbooked_doctor_id = connection.execute(
        "SELECT id FROM doctors WHERE name = 'Dr. Ethan Brooks'"
    ).fetchone()[0]
    connection.close()
    assert profile_name == "Taylor Updated"

    dashboard_page = client.get("/admin/dashboard")
    response = client.post(
        f"/admin/doctors/{unbooked_doctor_id}/delete",
        data={"_csrf_token": get_csrf_token(dashboard_page)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Doctor profile removed" in response.data

    connection = sqlite3.connect(database_path)
    removed_profile = connection.execute(
        "SELECT 1 FROM doctors WHERE id = ?", (unbooked_doctor_id,)
    ).fetchone()
    connection.close()
    assert removed_profile is None


def test_search_booking_duplicate_prevention_cancellation_and_status_flow(tmp_path):
    database_path = tmp_path / "hospital.db"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(database_path),
            "SECRET_KEY": "test-secret",
        }
    )

    search_response = app.test_client().get("/?q=Maya")
    assert b"Dr. Maya Patel" in search_response.data
    assert b"Dr. Ethan Brooks" not in search_response.data
    specialization_response = app.test_client().get(
        "/?specialization=Cardiology"
    )
    assert b"Dr. Maya Patel" in specialization_response.data
    assert b"Dr. Sofia Nguyen" not in specialization_response.data

    connection = sqlite3.connect(database_path)
    doctor_id = connection.execute(
        "SELECT id FROM doctors WHERE name = 'Dr. Maya Patel'"
    ).fetchone()[0]
    connection.close()

    next_monday_offset = (0 - date.today().weekday()) % 7
    next_monday = date.today() + timedelta(days=next_monday_offset or 7)
    appointment_date = next_monday.isoformat()
    client = app.test_client()
    register_page = client.get("/register/patient")
    client.post(
        "/register/patient",
        data={
            "_csrf_token": get_csrf_token(register_page),
            "full_name": "Casey Patient",
            "email": "casey@example.test",
            "password": "long-test-password",
        },
    )
    login_page = client.get("/login")
    client.post(
        "/login",
        data={
            "_csrf_token": get_csrf_token(login_page),
            "email": "casey@example.test",
            "password": "long-test-password",
        },
    )

    invalid_booking_page = client.get(f"/appointments/book/{doctor_id}")
    invalid_date_response = client.post(
        f"/appointments/book/{doctor_id}",
        data={
            "_csrf_token": get_csrf_token(invalid_booking_page),
            "date": "not-a-date",
            "time_slot": "09:00",
        },
    )
    assert b"Choose a valid date today or later" in invalid_date_response.data
    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 0
    connection.close()

    booking_page = client.get(
        f"/appointments/book/{doctor_id}?date={appointment_date}"
    )
    assert booking_page.status_code == 200
    assert b'value="09:00"' in booking_page.data
    assert b'value="13:00"' not in booking_page.data

    next_sunday_offset = (6 - date.today().weekday()) % 7
    next_sunday = date.today() + timedelta(days=next_sunday_offset or 7)
    sunday_page = client.get(
        f"/appointments/book/{doctor_id}?date={next_sunday.isoformat()}"
    )
    assert b"No appointment times are available" in sunday_page.data
    csrf = get_csrf_token(booking_page)
    first_response = client.post(
        f"/appointments/book/{doctor_id}",
        data={
            "_csrf_token": csrf,
            "date": appointment_date,
            "time_slot": "09:00",
        },
        follow_redirects=True,
    )
    assert b"pending confirmation" in first_response.data

    duplicate_response = client.post(
        f"/appointments/book/{doctor_id}",
        data={
            "_csrf_token": csrf,
            "date": appointment_date,
            "time_slot": "09:00",
        },
        follow_redirects=True,
    )
    assert b"no longer available" in duplicate_response.data

    appointment_page = client.get("/appointments")
    connection = sqlite3.connect(database_path)
    appointment_id = connection.execute(
        """
        SELECT id FROM appointments
        WHERE doctor_id = ? AND appointment_date = ? AND time_slot = '09:00'
        """,
        (doctor_id, appointment_date),
    ).fetchone()[0]
    connection.close()
    cancelled_response = client.post(
        f"/appointments/{appointment_id}/cancel",
        data={"_csrf_token": get_csrf_token(appointment_page)},
        follow_redirects=True,
    )
    assert b"Appointment cancelled" in cancelled_response.data

    available_again = client.get(
        f"/appointments/book/{doctor_id}?date={appointment_date}"
    )
    assert b'value="09:00"' in available_again.data
    rebooked_response = client.post(
        f"/appointments/book/{doctor_id}",
        data={
            "_csrf_token": get_csrf_token(available_again),
            "date": appointment_date,
            "time_slot": "09:00",
        },
        follow_redirects=True,
    )
    assert b"pending confirmation" in rebooked_response.data

    second_response = client.post(
        f"/appointments/book/{doctor_id}",
        data={
            "_csrf_token": csrf,
            "date": appointment_date,
            "time_slot": "09:30",
        },
        follow_redirects=True,
    )
    assert b"pending confirmation" in second_response.data
    connection = sqlite3.connect(database_path)
    second_appointment_id = connection.execute(
        """
        SELECT id FROM appointments
        WHERE doctor_id = ? AND appointment_date = ? AND time_slot = '09:30'
        """,
        (doctor_id, appointment_date),
    ).fetchone()[0]
    connection.close()

    admin_result = app.test_cli_runner().invoke(
        args=["create-admin"],
        input="admin@example.test\nsecure-admin-password\nsecure-admin-password\n",
    )
    assert admin_result.exit_code == 0, admin_result.output
    admin_client = app.test_client()
    admin_login_page = admin_client.get("/admin/login")
    admin_client.post(
        "/admin/login",
        data={
            "_csrf_token": get_csrf_token(admin_login_page),
            "email": "admin@example.test",
            "password": "secure-admin-password",
        },
    )

    appointments_page = admin_client.get("/admin/appointments")
    assert appointments_page.status_code == 200
    assert b"Casey Patient" in appointments_page.data
    response = admin_client.post(
        f"/admin/appointments/{second_appointment_id}/status",
        data={
            "_csrf_token": get_csrf_token(appointments_page),
            "status": "Completed",
        },
        follow_redirects=True,
    )
    assert b"cannot be changed from Pending to Completed" in response.data

    appointments_page = admin_client.get("/admin/appointments")
    response = admin_client.post(
        f"/admin/appointments/{second_appointment_id}/status",
        data={
            "_csrf_token": get_csrf_token(appointments_page),
            "status": "Confirmed",
        },
        follow_redirects=True,
    )
    assert b"Appointment status updated" in response.data

    appointments_page = admin_client.get("/admin/appointments")
    response = admin_client.post(
        f"/admin/appointments/{second_appointment_id}/status",
        data={
            "_csrf_token": get_csrf_token(appointments_page),
            "status": "Completed",
        },
        follow_redirects=True,
    )
    assert b"Appointment status updated" in response.data

    connection = sqlite3.connect(database_path)
    final_status = connection.execute(
        "SELECT status FROM appointments WHERE id = ?",
        (second_appointment_id,),
    ).fetchone()[0]
    connection.close()
    assert final_status == "Completed"
    patient_history = client.get("/appointments")
    assert b"Cancelled" in patient_history.data
    assert b"Completed" in patient_history.data
    booking_after_completion = client.get(
        f"/appointments/book/{doctor_id}?date={appointment_date}"
    )
    assert b'value="09:30"' not in booking_after_completion.data


def test_database_has_unique_active_appointment_slots(tmp_path):
    database_path = tmp_path / "hospital.db"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(database_path),
            "SECRET_KEY": "test-secret",
        }
    )

    connection = sqlite3.connect(database_path)
    try:
        doctors = connection.execute("SELECT id FROM doctors LIMIT 1").fetchone()
        connection.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role)
            VALUES ('Test Patient', 'patient@example.test', 'test-hash', 'patient')
            """
        )
        patient_id = connection.execute(
            "SELECT id FROM users WHERE email = 'patient@example.test'"
        ).fetchone()[0]
        appointment = (
            patient_id,
            doctors[0],
            "2030-01-02",
            "09:00",
            "Pending",
        )
        connection.execute(
            """
            INSERT INTO appointments
                (patient_id, doctor_id, appointment_date, time_slot, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            appointment,
        )

        try:
            connection.execute(
                """
                INSERT INTO appointments
                    (patient_id, doctor_id, appointment_date, time_slot, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                appointment,
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("The same active doctor slot was booked twice.")
    finally:
        connection.close()
