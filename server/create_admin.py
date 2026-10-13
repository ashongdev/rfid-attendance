"""
Create an admin account for the dashboard.

Run from the project root (the folder with .env):

    python create_admin.py
"""

import getpass
import sys

import auth_service as auth
import scan_service as svc


def main():
    email = input("Admin email: ").strip()
    full_name = input("Full name (optional): ").strip()
    role = (
        input("Role, 'admin' can change things and 'viewer' is read-only [admin]: ")
        .strip()
        .lower()
        or "admin"
    )

    password = getpass.getpass(
        f"Password (at least {auth.MIN_PASSWORD_LENGTH} characters): "
    )
    if password != getpass.getpass("Type it again: "):
        sys.exit("The two passwords didn't match. Nothing was created.")

    conn = svc.connect()
    try:
        admin = auth.create_admin(conn, email, password, full_name or None, role)
    except svc.ServiceError as e:
        sys.exit(f"Could not create the account: {e.message}")
    finally:
        conn.close()

    print(f"Created {admin['role']} account for {admin['email']} (id {admin['id']}).")


if __name__ == "__main__":
    main()
