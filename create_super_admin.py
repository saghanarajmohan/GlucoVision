"""Create the first (or an additional) super administrator interactively."""
from getpass import getpass

from backend import main as _schema_migrations  # noqa: F401
from backend.auth import hash_password
from backend.database import SessionLocal
from backend.models import User


def main():
    username = input("Super-admin username: ").strip()
    name = input("Display name: ").strip() or "Super Administrator"
    password = getpass("Password (minimum 12 characters): ")
    confirmation = getpass("Confirm password: ")
    if not username or len(password) < 12 or password != confirmation:
        raise SystemExit("Username is required; passwords must match and contain at least 12 characters")
    db = SessionLocal()
    try:
        if db.query(User).filter_by(username=username).first():
            raise SystemExit("Username already exists")
        db.add(User(name=name, username=username, password_hash=hash_password(password), role="SUPER_ADMIN"))
        db.commit()
        print(f"Created super-admin account {username}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
