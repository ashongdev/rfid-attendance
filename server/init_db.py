"""
One-time setup for the attendance database.

Creates:
  - the database        (DB_NAME)
  - a dedicated user    (APP_USER), limited to that one database
  - all the tables      (from schema_mysql.sql, which must sit next to this file)

Run it with:  python init_db.py
It asks for the MySQL root password (typed hidden) and a password for the new app user.
It is safe to run again: existing tables are left alone and the app user's
password is simply reset to whatever you type.
"""

import getpass
import pathlib
import sys

import pymysql

# Change these if your MySQL server uses a different address or port
HOST = "127.0.0.1"
PORT = 3306

DB_NAME = "attendance"
APP_USER = "attendance_app"

SCHEMA_FILE = pathlib.Path(__file__).with_name("schema.sql")


def read_statements(path):
    """Return the SQL statements in a file, ignoring '--' comment lines."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    text = "\n".join(lines)
    return [s.strip() for s in text.split(";") if s.strip()]


def main():
    if not SCHEMA_FILE.exists():
        sys.exit(
            f"Can't find {SCHEMA_FILE.name}. Put it in the same folder as this script."
        )

    root_pw = getpass.getpass("MySQL root password: ")
    app_pw = getpass.getpass(f"Choose a password for the app user '{APP_USER}': ")
    if app_pw != getpass.getpass("Type it again to confirm: "):
        sys.exit("The two passwords didn't match. Nothing was changed.")
    if len(app_pw) < 8:
        sys.exit("Please use at least 8 characters. Nothing was changed.")

    try:
        conn = pymysql.connect(
            host=HOST, port=PORT, user="root", password=root_pw, autocommit=True
        )
    except pymysql.err.OperationalError as e:
        sys.exit(f"Could not connect as root: {e}")

    with conn.cursor() as cur:
        cur.execute("SELECT VERSION()")
        print("Connected. MySQL version:", cur.fetchone()[0])

        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4")
        print(f"Database '{DB_NAME}' is ready.")

        # Create the app user for both ways a local connection can be matched
        for host in ("localhost", "127.0.0.1"):
            cur.execute(
                "CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s",
                (APP_USER, host, app_pw),
            )
            cur.execute("ALTER USER %s@%s IDENTIFIED BY %s", (APP_USER, host, app_pw))
            cur.execute(
                f"GRANT ALL PRIVILEGES ON `{DB_NAME}`.* TO %s@%s", (APP_USER, host)
            )
        cur.execute("FLUSH PRIVILEGES")
        print(f"App user '{APP_USER}' is ready (access to '{DB_NAME}' only).")

        cur.execute(f"USE `{DB_NAME}`")
        statements = read_statements(SCHEMA_FILE)
        for stmt in statements:
            cur.execute(stmt)
        print(f"Ran {len(statements)} schema statements.")

        cur.execute("SHOW TABLES")
        tables = [row[0] for row in cur.fetchall()]
        print("Tables:", ", ".join(tables))

    conn.close()

    print()
    print("Done. Put these lines in your Dreema project's .env file")
    print("(use the app password you just chose, never the root password):")
    print()
    print("DB_TYPE=mysql")
    print(f"DB_HOST={HOST}")
    print(f"DB_PORT={PORT}")
    print(f"DB_NAME={DB_NAME}")
    print(f"DB_USER={APP_USER}")
    print("DB_PASSWORD=<the app password you chose>")


if __name__ == "__main__":
    main()
