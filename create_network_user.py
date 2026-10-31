"""Interactively provision a hospital or health-centre account."""
from getpass import getpass

from backend import main as _schema_migrations  # noqa: F401
from backend.database import SessionLocal
from backend.models import Hospital, HealthCentre, User
from backend.auth import hash_password


def main():
    role = input("Role (HOSPITAL_ADMIN or HEALTH_CENTRE_STAFF): ").strip().upper()
    if role not in {"HOSPITAL_ADMIN", "HEALTH_CENTRE_STAFF"}:
        raise SystemExit("Unsupported role")
    username = input("Username: ").strip()
    name = input("User's display name: ").strip()
    password = getpass("Password (minimum 12 characters): ")
    confirmation = getpass("Confirm password: ")
    if not username or not name or len(password) < 12 or password != confirmation:
        raise SystemExit("Username/name are required; passwords must match and contain at least 12 characters")
    db = SessionLocal()
    try:
        if db.query(User).filter_by(username=username).first():
            raise SystemExit("Username already exists")
        user = User(username=username, name=name, password_hash=hash_password(password), role=role)
        if role == "HOSPITAL_ADMIN":
            hospitals = db.query(Hospital).filter_by(is_active=True).order_by(Hospital.name).all()
            for hospital in hospitals:
                print(f"{hospital.id}: {hospital.name} ({hospital.code})")
            hospital_id = int(input("Hospital ID: "))
            if not any(h.id == hospital_id for h in hospitals):
                raise SystemExit("Select an active hospital")
            user.hospital_id = hospital_id
        else:
            centres = db.query(HealthCentre).filter_by(is_active=True).order_by(HealthCentre.name).all()
            for centre in centres:
                print(f"{centre.id}: {centre.name} ({centre.code})")
            centre_id = int(input("Health-centre ID: "))
            centre = next((c for c in centres if c.id == centre_id), None)
            if not centre:
                raise SystemExit("Select an active health centre")
            user.health_centre_id = centre_id
        db.add(user)
        db.commit()
        print(f"Created {role} account {username}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
