"""
Basic admin queries for the dashboard: people and readers.
Same style as scan_service.py: plain functions that take a pymysql connection.
"""

import pymysql
from pymysql.cursors import DictCursor
from scan_service import ServiceError, _audit, iso


def create_person(
    conn, full_name, external_id=None, group_name=None, email=None, admin_id=None
):
    full_name = (full_name or "").strip()
    if not full_name:
        raise ServiceError("bad_input", "A name is required.")
    if len(full_name) > 150:
        raise ServiceError("bad_input", "The name is too long (150 characters max).")

    def clean(value, limit):
        value = (str(value).strip() if value is not None else "") or None
        if value and len(value) > limit:
            raise ServiceError(
                "bad_input", f"A value is too long ({limit} characters max)."
            )
        return value

    external_id = clean(external_id, 64)
    group_name = clean(group_name, 100)
    email = clean(email, 190)

    try:
        with conn.cursor(DictCursor) as cur:
            try:
                cur.execute(
                    "INSERT INTO people (full_name, external_id, group_name, email) VALUES (%s, %s, %s, %s)",
                    (full_name, external_id, group_name, email),
                )
            except pymysql.err.IntegrityError:
                raise ServiceError(
                    "duplicate_external_id",
                    "Someone with that ID number already exists.",
                )
            person_id = cur.lastrowid
            _audit(
                cur,
                admin_id,
                "person.create",
                "person",
                person_id,
                {"full_name": full_name},
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "id": person_id,
        "full_name": full_name,
        "external_id": external_id,
        "group_name": group_name,
        "email": email,
        "active": True,
        "card_uid": None,
    }


def list_people(conn, search=None, limit=100, offset=0):
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    sql = (
        "SELECT p.id, p.full_name, p.external_id, p.group_name, p.email, p.active, "
        "       c.uid AS card_uid "
        "FROM people p LEFT JOIN cards c ON c.person_id = p.id AND c.status = 'active' "
    )
    params = []
    if search:
        like = f"%{search.strip()}%"
        sql += "WHERE p.full_name LIKE %s OR p.external_id LIKE %s OR p.group_name LIKE %s "
        params += [like, like, like]
    sql += "ORDER BY p.full_name LIMIT %s OFFSET %s"
    params += [limit, offset]

    with conn.cursor(DictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    conn.commit()

    for row in rows:
        row["active"] = bool(row["active"])
    return rows


def list_devices(conn):
    with conn.cursor(DictCursor) as cur:
        cur.execute(
            "SELECT device_id, label, last_seen_at FROM devices ORDER BY device_id"
        )
        rows = cur.fetchall()
    conn.commit()
    for row in rows:
        row["last_seen_at"] = iso(row["last_seen_at"])
    return rows
