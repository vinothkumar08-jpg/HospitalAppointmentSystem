import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

import click
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    DEFAULT_DATABASE,
    add_doctor_profile,
    cancel_patient_appointment,
    create_account,
    create_appointment,
    count_admins,
    delete_doctor_profile,
    get_available_slots,
    get_admin_dashboard_counts,
    get_doctor_by_id,
    get_doctor_for_user,
    get_doctor_schedules,
    get_patient_appointments,
    get_user_by_email,
    get_user_by_id,
    initialize_database,
    list_all_appointments,
    list_doctors,
    list_specializations,
    update_doctor_profile,
    update_appointment_status,
)

WEEKDAYS = (
    ("0", "Monday"),
    ("1", "Tuesday"),
    ("2", "Wednesday"),
    ("3", "Thursday"),
    ("4", "Friday"),
    ("5", "Saturday"),
    ("6", "Sunday"),
)


def csrf_token():
    token = session.get("_csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def role_required(required_role):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Please sign in to view that page.", "error")
                login_endpoint = "admin_login" if required_role == "admin" else "login"
                return redirect(url_for(login_endpoint))
            if g.user["role"] != required_role:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorate


def dashboard_location(user):
    if user["role"] == "doctor":
        return url_for("doctor_dashboard")
    if user["role"] == "patient":
        return url_for("dashboard")
    if user["role"] == "admin":
        return url_for("admin_dashboard")
    return url_for("home")


def validate_doctor_form(form):
    name = form.get("name", "").strip()
    specialization = form.get("specialization", "").strip()
    experience_value = form.get("experience_years", "").strip()
    bio = form.get("bio", "").strip()

    if not name or len(name) > 120:
        return None, "Enter a doctor name using no more than 120 characters."
    if not specialization or len(specialization) > 100:
        return None, "Enter a specialization using no more than 100 characters."
    try:
        experience_years = int(experience_value)
    except ValueError:
        experience_years = -1
    if not 0 <= experience_years <= 80:
        return None, "Experience must be a number from 0 to 80."
    if len(bio) > 500:
        return None, "The profile description must be 500 characters or fewer."

    schedule_rows, availability, error = validate_weekly_schedule(form)
    if error:
        return None, error

    return (
        name,
        specialization,
        experience_years,
        bio,
        availability,
        schedule_rows,
    ), None


def validate_weekly_schedule(form):
    selected_days = form.getlist("weekdays")
    valid_day_values = {value for value, _ in WEEKDAYS}
    if not selected_days or any(day not in valid_day_values for day in selected_days):
        return None, None, "Select at least one valid day for the doctor's schedule."

    start_value = form.get("start_time", "").strip()
    end_value = form.get("end_time", "").strip()
    try:
        start = datetime.strptime(start_value, "%H:%M").time()
        end = datetime.strptime(end_value, "%H:%M").time()
    except ValueError:
        return None, None, "Enter a valid start and end time."

    if end <= start:
        return None, None, "The schedule end time must be later than the start time."
    schedule_length = (
        datetime.combine(date.today(), end)
        - datetime.combine(date.today(), start)
    ).total_seconds()
    if schedule_length < 1800:
        return None, None, "A working day must include at least one 30-minute slot."

    day_numbers = sorted({int(day) for day in selected_days})
    names = [name for value, name in WEEKDAYS if int(value) in day_numbers]
    if len(day_numbers) > 1 and all(
        right == left + 1 for left, right in zip(day_numbers, day_numbers[1:])
    ):
        day_label = f"{names[0]}-{names[-1]}"
    else:
        day_label = ", ".join(names)

    start_text = start.strftime("%H:%M")
    end_text = end.strftime("%H:%M")
    schedule_rows = tuple(
        (weekday, start_text, end_text) for weekday in day_numbers
    )
    return (
        schedule_rows,
        f"{day_label}, {start_text}-{end_text}",
        None,
    )


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=str(DEFAULT_DATABASE),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=60),
    )

    if test_config:
        app.config.update(test_config)

    initialize_database(app.config["DATABASE"])
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def load_logged_in_user():
        user_id = session.get("user_id")
        g.user = (
            get_user_by_id(app.config["DATABASE"], user_id)
            if user_id is not None
            else None
        )

    @app.before_request
    def protect_state_changes():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return

        expected_token = session.get("_csrf_token")
        submitted_token = request.form.get("_csrf_token") or request.headers.get(
            "X-CSRF-Token"
        )
        if (
            expected_token is None
            or submitted_token is None
            or not secrets.compare_digest(expected_token, submitted_token)
        ):
            abort(400, description="The form expired or its security token is invalid.")

    @app.route("/")
    def home():
        search_term = request.args.get("q", "").strip()
        specialization = request.args.get("specialization", "").strip()
        doctors = list_doctors(
            app.config["DATABASE"],
            search_term=search_term,
            specialization=specialization,
        )
        specializations = list_specializations(app.config["DATABASE"])
        return render_template(
            "index.html",
            doctors=doctors,
            search_term=search_term,
            selected_specialization=specialization,
            specializations=specializations,
        )

    @app.route("/register/<role>", methods=["GET", "POST"])
    def register(role):
        if role not in {"patient", "doctor"}:
            abort(404)
        if g.user is not None:
            return redirect(dashboard_location(g.user))

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            error = None
            doctor_profile = None

            if not full_name or len(full_name) > 120:
                error = "Enter your name using no more than 120 characters."
            elif not email or len(email) > 254 or "@" not in email:
                error = "Enter a valid email address."
            elif len(password) < 10:
                error = "Choose a password with at least 10 characters."

            if error is None and role == "doctor":
                specialization = request.form.get("specialization", "").strip()
                experience_value = request.form.get("experience_years", "").strip()
                bio = request.form.get("bio", "").strip()

                try:
                    experience_years = int(experience_value)
                except ValueError:
                    experience_years = -1

                if not specialization or len(specialization) > 100:
                    error = "Enter a specialization using no more than 100 characters."
                elif not 0 <= experience_years <= 80:
                    error = "Experience must be a number from 0 to 80."
                elif len(bio) > 500:
                    error = "The profile description must be 500 characters or fewer."
                else:
                    schedule_rows, availability, error = validate_weekly_schedule(
                        request.form
                    )
                    if error is None:
                        doctor_profile = (
                            specialization,
                            experience_years,
                            bio,
                            availability,
                            schedule_rows,
                        )

            if error is not None:
                flash(error, "error")
            else:
                password_hash = generate_password_hash(password)
                try:
                    create_account(
                        app.config["DATABASE"],
                        full_name,
                        email,
                        password_hash,
                        role,
                        doctor_profile,
                    )
                except sqlite3.IntegrityError:
                    if get_user_by_email(app.config["DATABASE"], email) is None:
                        raise
                    flash("An account with that email address already exists.", "error")
                else:
                    flash("Your account was created. You can now sign in.", "success")
                    return redirect(url_for("login"))

        return render_template(
            "register.html",
            role=role,
            weekday_options=WEEKDAYS,
            selected_weekdays=request.form.getlist("weekdays"),
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user is not None:
            return redirect(dashboard_location(g.user))

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = get_user_by_email(app.config["DATABASE"], email)
            if user is None or not check_password_hash(
                user["password_hash"], password
            ):
                flash("Email or password is incorrect.", "error")
            else:
                session.clear()
                session.permanent = True
                session["user_id"] = user["id"]
                flash("You are signed in.", "success")
                return redirect(dashboard_location(user))

        return render_template("login.html")

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if g.user is not None:
            if g.user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            flash("Sign out before using a different account.", "error")
            return redirect(dashboard_location(g.user))

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = get_user_by_email(app.config["DATABASE"], email)
            if (
                user is None
                or user["role"] != "admin"
                or not check_password_hash(user["password_hash"], password)
            ):
                flash("Administrator email or password is incorrect.", "error")
            else:
                session.clear()
                session.permanent = True
                session["user_id"] = user["id"]
                flash("Administrator signed in.", "success")
                return redirect(url_for("admin_dashboard"))

        return render_template("login.html", admin_login=True)

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have signed out.", "success")
        return redirect(url_for("home"))

    @app.get("/dashboard")
    @role_required("patient")
    def dashboard():
        upcoming, previous = get_patient_appointments(
            app.config["DATABASE"], g.user["id"]
        )
        return render_template(
            "dashboard.html",
            role="patient",
            doctor=None,
            upcoming_count=len(upcoming),
            previous_count=len(previous),
        )

    @app.get("/doctor/dashboard")
    @role_required("doctor")
    def doctor_dashboard():
        doctor = get_doctor_for_user(app.config["DATABASE"], g.user["id"])
        return render_template("dashboard.html", role="doctor", doctor=doctor)

    @app.get("/appointments")
    @role_required("patient")
    def patient_appointments():
        upcoming, previous = get_patient_appointments(
            app.config["DATABASE"], g.user["id"]
        )
        return render_template(
            "appointments.html",
            upcoming=upcoming,
            previous=previous,
            today=date.today().isoformat(),
        )

    @app.route("/appointments/book/<int:doctor_id>", methods=["GET", "POST"])
    @role_required("patient")
    def book_appointment(doctor_id):
        doctor = get_doctor_by_id(app.config["DATABASE"], doctor_id)
        if doctor is None:
            abort(404)

        today = date.today()
        selected_date = (
            request.form.get("date", today.isoformat())
            if request.method == "POST"
            else request.args.get("date", today.isoformat())
        )
        parsed_date = None
        try:
            parsed_date = date.fromisoformat(selected_date)
            if parsed_date.isoformat() != selected_date:
                parsed_date = None
        except ValueError:
            parsed_date = None
        valid_date = parsed_date is not None and parsed_date >= today
        if not valid_date:
            if request.method == "POST" or "date" in request.values:
                flash("Choose a valid date today or later.", "error")
            selected_date = today.isoformat()

        slots = get_available_slots(
            app.config["DATABASE"], doctor_id, selected_date
        )

        if request.method == "POST" and valid_date:
            time_slot = request.form.get("time_slot", "")
            if time_slot not in slots:
                flash(
                    "That time is no longer available. Choose another available slot.",
                    "error",
                )
            else:
                try:
                    create_appointment(
                        app.config["DATABASE"],
                        g.user["id"],
                        doctor_id,
                        selected_date,
                        time_slot,
                    )
                except ValueError as error:
                    flash(str(error), "error")
                except sqlite3.IntegrityError:
                    flash(
                        "That time was just booked. Choose another available slot.",
                        "error",
                    )
                else:
                    flash("Your appointment request is pending confirmation.", "success")
                    return redirect(url_for("patient_appointments"))

        return render_template(
            "book_appointment.html",
            doctor=doctor,
            selected_date=selected_date,
            today=today.isoformat(),
            slots=slots,
        )

    @app.post("/appointments/<int:appointment_id>/cancel")
    @role_required("patient")
    def cancel_appointment(appointment_id):
        cancelled = cancel_patient_appointment(
            app.config["DATABASE"],
            appointment_id,
            g.user["id"],
        )
        if cancelled:
            flash("Appointment cancelled.", "success")
        else:
            flash(
                "This appointment cannot be cancelled because it is not upcoming or is no longer active.",
                "error",
            )
        return redirect(url_for("patient_appointments"))

    @app.get("/admin/dashboard")
    @role_required("admin")
    def admin_dashboard():
        return render_template(
            "admin_dashboard.html",
            doctors=list_doctors(app.config["DATABASE"]),
            counts=get_admin_dashboard_counts(app.config["DATABASE"]),
            weekday_options=WEEKDAYS,
        )

    @app.post("/admin/doctors")
    @role_required("admin")
    def admin_add_doctor():
        profile, error = validate_doctor_form(request.form)
        if error:
            flash(error, "error")
        else:
            add_doctor_profile(app.config["DATABASE"], *profile)
            flash("Doctor profile added.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/doctors/<int:doctor_id>/edit", methods=["GET", "POST"])
    @role_required("admin")
    def admin_edit_doctor(doctor_id):
        doctor = get_doctor_by_id(app.config["DATABASE"], doctor_id)
        if doctor is None:
            abort(404)
        schedules = get_doctor_schedules(app.config["DATABASE"], doctor_id)

        if request.method == "POST":
            profile, error = validate_doctor_form(request.form)
            if error:
                flash(error, "error")
            else:
                update_doctor_profile(
                    app.config["DATABASE"],
                    doctor_id,
                    *profile,
                )
                flash("Doctor profile updated.", "success")
                return redirect(url_for("admin_dashboard"))
            doctor = {
                "id": doctor_id,
                "name": request.form.get("name", ""),
                "specialization": request.form.get("specialization", ""),
                "experience_years": request.form.get("experience_years", ""),
                "bio": request.form.get("bio", ""),
            }

        if request.method == "POST":
            selected_weekdays = request.form.getlist("weekdays")
            start_time = request.form.get("start_time", "")
            end_time = request.form.get("end_time", "")
        else:
            selected_weekdays = [str(schedule["weekday"]) for schedule in schedules]
            start_time = schedules[0]["start_time"] if schedules else "09:00"
            end_time = schedules[0]["end_time"] if schedules else "17:00"

        return render_template(
            "admin_edit_doctor.html",
            doctor=doctor,
            weekday_options=WEEKDAYS,
            selected_weekdays=selected_weekdays,
            start_time=start_time,
            end_time=end_time,
        )

    @app.post("/admin/doctors/<int:doctor_id>/delete")
    @role_required("admin")
    def admin_delete_doctor(doctor_id):
        doctor = get_doctor_by_id(app.config["DATABASE"], doctor_id)
        if doctor is None:
            abort(404)

        if delete_doctor_profile(app.config["DATABASE"], doctor_id):
            flash("Doctor profile removed.", "success")
        else:
            flash(
                "This profile has appointment history and cannot be removed. "
                "Keep it for the appointment records.",
                "error",
            )
        return redirect(url_for("admin_dashboard"))

    @app.get("/admin/appointments")
    @role_required("admin")
    def admin_appointments():
        return render_template(
            "admin_appointments.html",
            appointments=list_all_appointments(app.config["DATABASE"]),
        )

    @app.post("/admin/appointments/<int:appointment_id>/status")
    @role_required("admin")
    def admin_update_appointment_status(appointment_id):
        new_status = request.form.get("status", "")
        try:
            update_appointment_status(
                app.config["DATABASE"],
                appointment_id,
                new_status,
            )
        except LookupError:
            abort(404)
        except ValueError as error:
            flash(str(error), "error")
        else:
            flash("Appointment status updated.", "success")
        return redirect(url_for("admin_appointments"))

    @app.cli.command("create-admin")
    def create_admin_command():
        """Create the first administrator account without storing a plain password."""
        if count_admins(app.config["DATABASE"]):
            raise click.ClickException(
                "An administrator account already exists; this command only bootstraps the first one."
            )

        email = click.prompt("Administrator email").strip().lower()
        password = click.prompt(
            "Administrator password",
            hide_input=True,
            confirmation_prompt=True,
        )
        if not email or len(email) > 254 or "@" not in email:
            raise click.ClickException("Enter a valid email address.")
        if len(password) < 10:
            raise click.ClickException("Use a password with at least 10 characters.")

        try:
            create_account(
                app.config["DATABASE"],
                "Hospital Administrator",
                email,
                generate_password_hash(password),
                "admin",
            )
        except sqlite3.IntegrityError:
            if get_user_by_email(app.config["DATABASE"], email) is None:
                raise
            raise click.ClickException(
                "This email address is already registered to another account."
            )
        click.echo("Administrator account created. Sign in at /admin/login.")

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
