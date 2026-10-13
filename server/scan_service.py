"""
Core logic for the attendance system. It has no dependency on Dreema:
it takes a pymysql connection and does everything inside database transactions.

Main entry points
  connect()                         open a connection using the DB_* values from .env
  process_scan(conn, ...)           handle one scan from a reader (attendance, tap-to-assign, ...)
  start_assignment(conn, ...)       admin: "the next card tapped on this reader is for this person"
  get_session(conn, session_id)     admin: check on an assignment session (for the dashboard)
  cancel_session(conn, ...)         admin: cancel a pending assignment session

Problems the caller should show to the admin are raised as ServiceError(code, message).
"""

import json
import os
import pathlib
import re
from datetime import datetime, timedelta, timezone

import pymysql
from pymysql.cursors import DictCursor

SESSION_SECONDS = 60  # how long an assignment session stays open
CLOCK_SKEW_TOLERANCE = timedelta(seconds=3)  # reader clock vs server clock
MAX_FUTURE_SKEW = timedelta(minutes=2)  # taps "from the future" are clamped to now
MIN_VALID_EPOCH = 1700000000  # anything smaller means the reader had no clock
UID_PATTERN = re.compile(r"^[0-9A-F]{8,20}$")


class ServiceError(Exception):
    """An expected problem (bad input, person already has a card...). Safe to show to an admin."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------
def utcnow():
    """Current UTC time as a naive datetime (that's what the DATETIME columns hold)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    """datetime -> '2026-10-12T23:35:01.211Z'"""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _load_env_file():
    values = {}
    path = pathlib.Path(".env")
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def setting(name, default=None):
    """A value from the environment or the .env file (for example an API key)."""
    return {**_load_env_file(), **os.environ}.get(name, default)


def connect():
    """Open a connection using DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    (from the environment, or from a .env file in the current folder)."""
    env = {**_load_env_file(), **os.environ}
    return pymysql.connect(
        host=env.get("DB_HOST", "127.0.0.1"),
        port=int(env.get("DB_PORT", "3306")),
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
        database=env["DB_NAME"],
        charset="utf8mb4",
        autocommit=False,
    )


def _tap_time(scanned_at, now):
    """The time the card was tapped: the reader's timestamp if it looks sane, else 'now'."""
    try:
        epoch = int(scanned_at or 0)
    except (TypeError, ValueError):
        epoch = 0
    if epoch < MIN_VALID_EPOCH:
        return now
    tapped = datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)
    if tapped > now + MAX_FUTURE_SKEW:
        return now
    return min(tapped, now)


def _result(status, uid, name=None, when=None, **extra):
    out = {"status": status, "uid": uid}
    if name:
        out["name"] = name
    if when:
        out["time"] = iso(when)
    out.update(extra)
    return out


def _audit(cur, admin_id, action, target_type, target_id, details=None):
    cur.execute(
        "INSERT INTO audit_log (at, admin_id, action, target_type, target_id, details) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            utcnow(),
            admin_id,
            action,
            target_type,
            str(target_id),
            json.dumps(details or {}),
        ),
    )


def _record_outcome(cur, scan_id, outcome, person_id):
    """Remember what we did with this scan_id, so a retry gets the same answer."""
    if scan_id:
        cur.execute(
            "INSERT INTO processed_scans (scan_id, outcome, person_id, processed_at) "
            "VALUES (%s, %s, %s, %s)",
            (scan_id, outcome, person_id, utcnow()),
        )


def _duplicate_result(cur, uid, scan_id):
    cur.execute(
        "SELECT ps.outcome, p.full_name FROM processed_scans ps "
        "LEFT JOIN people p ON p.id = ps.person_id WHERE ps.scan_id = %s",
        (scan_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return _result(
        "duplicate", uid, name=row["full_name"], original_status=row["outcome"]
    )


def _expire_old_sessions(cur, now):
    cur.execute(
        "UPDATE assignment_sessions SET status = 'expired' "
        "WHERE status = 'pending' AND expires_at < %s",
        (now,),
    )


# ---------------------------------------------------------------
# Scans from readers
# ---------------------------------------------------------------
def process_scan(conn, uid, device_id, scan_id=None, scanned_at=0):
    """Handle one scan. Returns a dict whose 'status' is one of:

    ok                 recognised card, attendance recorded
    assigned           an assignment session was open, the card is now linked to that person
    already_assigned   an assignment session was open but the card already belongs to someone
    unknown            card isn't registered
    disabled           card (or its person) is lost, disabled or inactive
    duplicate          this scan_id was handled before (a retry), nothing new was saved
                       ('original_status' says what happened the first time)
    """
    uid = (uid or "").strip().upper()
    if not UID_PATTERN.match(uid):
        raise ServiceError("bad_uid", "uid must be 8 to 20 hex characters")

    device_id = (device_id or "").strip()
    if not device_id or len(device_id) > 64:
        raise ServiceError("bad_device", "device_id is required (max 64 characters)")

    scan_id = (str(scan_id).strip()[:64] or None) if scan_id else None

    now = utcnow()
    tapped = _tap_time(scanned_at, now)

    try:
        with conn.cursor(DictCursor) as cur:
            return _process(conn, cur, uid, device_id, scan_id, tapped, now)
    except pymysql.err.IntegrityError:
        conn.rollback()
        # Most likely another request handled this same scan_id at the same moment
        if scan_id:
            with conn.cursor(DictCursor) as cur:
                dup = _duplicate_result(cur, uid, scan_id)
            conn.commit()
            if dup:
                return dup
        raise
    except Exception:
        conn.rollback()
        raise


def _process(conn, cur, uid, device_id, scan_id, tapped, now):
    # Remember that this reader is alive (also creates it the first time we see it)
    cur.execute(
        "INSERT INTO devices (device_id, last_seen_at) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE last_seen_at = %s",
        (device_id, now, now),
    )

    # Is this a retry of a scan we already handled?
    if scan_id:
        dup = _duplicate_result(cur, uid, scan_id)
        if dup:
            conn.commit()
            return dup

    _expire_old_sessions(cur, now)

    # Is there an assignment session waiting on this reader, started before this tap?
    cur.execute(
        "SELECT s.id, s.person_id, s.created_by, p.full_name "
        "FROM assignment_sessions s JOIN people p ON p.id = s.person_id "
        "WHERE s.device_id = %s AND s.status = 'pending' AND s.created_at <= %s "
        "ORDER BY s.created_at DESC LIMIT 1 FOR UPDATE",
        (device_id, tapped + CLOCK_SKEW_TOLERANCE),
    )
    session = cur.fetchone()

    cur.execute(
        "SELECT c.id, c.person_id, c.status, p.full_name, p.active "
        "FROM cards c JOIN people p ON p.id = c.person_id WHERE c.uid = %s",
        (uid,),
    )
    card = cur.fetchone()

    # ---------- Tap-to-assign ----------
    if session:
        person_id = session["person_id"]

        # The same person tapped the card that is already theirs: treat as success
        if card and card["person_id"] == person_id and card["status"] == "active":
            _complete_session(cur, session["id"], card["id"], now)
            _record_outcome(cur, scan_id, "assigned", person_id)
            conn.commit()
            return _result("assigned", uid, name=session["full_name"], when=tapped)

        # The card belongs to someone else (or is lost/disabled): refuse, keep the session open
        if card:
            _audit(
                cur,
                session["created_by"],
                "card.assign_conflict",
                "person",
                person_id,
                {
                    "uid": uid,
                    "owner_person_id": card["person_id"],
                    "owner_status": card["status"],
                },
            )
            _record_outcome(cur, scan_id, "already_assigned", None)
            conn.commit()
            return _result("already_assigned", uid, when=tapped)

        # A brand-new card: link it
        try:
            cur.execute(
                "INSERT INTO cards (uid, person_id, status, assigned_at, assigned_by) "
                "VALUES (%s, %s, 'active', %s, %s)",
                (uid, person_id, now, session["created_by"]),
            )
        except pymysql.err.IntegrityError:
            # Lost a race: the card appeared elsewhere, or the person just got another active card
            conn.rollback()
            _record_outcome(cur, scan_id, "already_assigned", None)
            conn.commit()
            return _result("already_assigned", uid, when=tapped)

        card_id = cur.lastrowid
        _complete_session(cur, session["id"], card_id, now)
        _audit(
            cur,
            session["created_by"],
            "card.assign",
            "person",
            person_id,
            {"uid": uid, "card_id": card_id, "device_id": device_id},
        )
        _record_outcome(cur, scan_id, "assigned", person_id)
        conn.commit()
        return _result("assigned", uid, name=session["full_name"], when=tapped)

    # ---------- Normal attendance ----------
    if not card:
        cur.execute(
            "INSERT INTO unknown_scans (uid, device_id, scanned_at) VALUES (%s, %s, %s)",
            (uid, device_id, tapped),
        )
        _record_outcome(cur, scan_id, "unknown", None)
        conn.commit()
        return _result("unknown", uid, when=tapped)

    if card["status"] != "active" or not card["active"]:
        _record_outcome(cur, scan_id, "disabled", None)
        conn.commit()
        return _result("disabled", uid, when=tapped)

    cur.execute(
        "INSERT INTO attendance (person_id, card_id, device_id, scanned_at, received_at, scan_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (card["person_id"], card["id"], device_id, tapped, now, scan_id),
    )
    _record_outcome(cur, scan_id, "ok", card["person_id"])
    conn.commit()
    return _result("ok", uid, name=card["full_name"], when=tapped)


def _complete_session(cur, session_id, card_id, now):
    cur.execute(
        "UPDATE assignment_sessions SET status = 'completed', completed_at = %s, card_id = %s "
        "WHERE id = %s",
        (now, card_id, session_id),
    )


# ---------------------------------------------------------------
# Tap-to-assign: admin side
# ---------------------------------------------------------------
def start_assignment(
    conn, person_id, device_id, admin_id=None, seconds=SESSION_SECONDS
):
    """Open a session: the next card tapped on this reader gets linked to this person."""
    now = utcnow()
    expires = now + timedelta(seconds=seconds)
    try:
        with conn.cursor(DictCursor) as cur:
            cur.execute(
                "SELECT id, full_name, active FROM people WHERE id = %s FOR UPDATE",
                (person_id,),
            )
            person = cur.fetchone()
            if not person:
                raise ServiceError("person_not_found", "That person doesn't exist.")
            if not person["active"]:
                raise ServiceError("person_inactive", "That person is deactivated.")

            cur.execute(
                "SELECT device_id FROM devices WHERE device_id = %s", (device_id,)
            )
            if not cur.fetchone():
                raise ServiceError(
                    "device_not_found",
                    "That reader hasn't connected yet. Tap any card on it once, then try again.",
                )

            cur.execute(
                "SELECT id FROM cards WHERE person_id = %s AND status = 'active'",
                (person_id,),
            )
            if cur.fetchone():
                raise ServiceError(
                    "person_has_card",
                    "This person already has an active card. Mark it lost or disabled first.",
                )

            _expire_old_sessions(cur, now)
            try:
                cur.execute(
                    "INSERT INTO assignment_sessions (person_id, device_id, status, created_at, expires_at, created_by) "
                    "VALUES (%s, %s, 'pending', %s, %s, %s)",
                    (person_id, device_id, now, expires, admin_id),
                )
            except pymysql.err.IntegrityError:
                raise ServiceError(
                    "session_busy",
                    "That reader (or that person) already has an assignment in progress.",
                )

            session_id = cur.lastrowid
            _audit(
                cur,
                admin_id,
                "card.assign_started",
                "person",
                person_id,
                {"device_id": device_id},
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "session_id": session_id,
        "status": "pending",
        "person_id": person_id,
        "person_name": person["full_name"],
        "device_id": device_id,
        "created_at": iso(now),
        "expires_at": iso(expires),
        "seconds_left": seconds,
    }


def get_session(conn, session_id):
    """Current state of a session. The dashboard can poll this every second or so."""
    now = utcnow()
    with conn.cursor(DictCursor) as cur:
        _expire_old_sessions(cur, now)
        cur.execute(
            "SELECT s.id, s.status, s.person_id, s.device_id, s.created_at, s.expires_at, "
            "s.completed_at, p.full_name, c.uid AS card_uid "
            "FROM assignment_sessions s JOIN people p ON p.id = s.person_id "
            "LEFT JOIN cards c ON c.id = s.card_id WHERE s.id = %s",
            (session_id,),
        )
        row = cur.fetchone()
    conn.commit()
    if not row:
        raise ServiceError("session_not_found", "No such assignment session.")

    seconds_left = 0
    if row["status"] == "pending":
        seconds_left = max(0, int((row["expires_at"] - now).total_seconds()))
    return {
        "session_id": row["id"],
        "status": row["status"],
        "person_id": row["person_id"],
        "person_name": row["full_name"],
        "device_id": row["device_id"],
        "card_uid": row["card_uid"],
        "created_at": iso(row["created_at"]),
        "expires_at": iso(row["expires_at"]),
        "completed_at": iso(row["completed_at"]),
        "seconds_left": seconds_left,
    }


def cancel_session(conn, session_id, admin_id=None):
    """Cancel a pending session. Returns True if one was cancelled."""
    try:
        with conn.cursor(DictCursor) as cur:
            cur.execute(
                "UPDATE assignment_sessions SET status = 'cancelled' WHERE id = %s AND status = 'pending'",
                (session_id,),
            )
            cancelled = cur.rowcount > 0
            if cancelled:
                _audit(cur, admin_id, "card.assign_cancelled", "session", session_id)
        conn.commit()
        return cancelled
    except Exception:
        conn.rollback()
        raise
