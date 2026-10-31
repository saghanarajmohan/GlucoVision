from backend.database import SessionLocal
from backend.models import User, Hospital, HealthCentre
from backend.auth import hash_password
from getpass import getpass


def _prompt_password(account_name):
    while True:
        password = getpass(f"Set password for {account_name} (minimum 12 characters): ")
        confirmation = getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords did not match. Try again.")
            continue
        if len(password) < 12:
            print("Use at least 12 characters.")
            continue
        return password


db = SessionLocal()

try:
    # ---------------------------------------------------------
    # Get existing hospital
    # ---------------------------------------------------------

    hospital = db.query(Hospital).filter(
        Hospital.name == "GlucoVision Main Hospital"
    ).first()

    if not hospital:
        print("Hospital not found. Run seed_data.py first.")
        exit()


    # ---------------------------------------------------------
    # Get existing health centre
    # ---------------------------------------------------------

    health_centre = db.query(HealthCentre).filter(
        HealthCentre.name == "GlucoVision Rural Health Centre"
    ).first()

    if not health_centre:
        print("Health centre not found. Run seed_data.py first.")
        exit()


    # ---------------------------------------------------------
    # Create Doctor account
    # ---------------------------------------------------------

    doctor = db.query(User).filter(
        User.username == "doctor"
    ).first()

    if not doctor:

        doctor = User(
            name="Dr. GlucoVision",
            username="doctor",
            password_hash=hash_password(_prompt_password("doctor")),
            role="DOCTOR",
            hospital_id=hospital.id
        )

        db.add(doctor)

        print("Doctor account created.")

    else:
        print("Doctor account already exists.")


    # ---------------------------------------------------------
    # Create Health Centre account
    # ---------------------------------------------------------

    health_centre_user = db.query(User).filter(
        User.username == "healthcentre"
    ).first()

    if not health_centre_user:

        health_centre_user = User(
            name="GlucoVision Health Centre",
            username="healthcentre",
            password_hash=hash_password(_prompt_password("healthcentre")),
            role="HEALTH_CENTRE",
            health_centre_id=health_centre.id
        )

        db.add(health_centre_user)

        print("Health Centre account created.")

    else:
        print("Health Centre account already exists.")


    db.commit()

    print("User setup complete. Passwords were entered locally and stored as hashes.")


finally:
    db.close()
