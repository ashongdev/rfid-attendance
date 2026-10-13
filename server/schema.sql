-- RFID attendance system: MySQL schema
-- All timestamps are DATETIME(3) in UTC.
-- Keep ";" out of comments: init_db.py splits this file on semicolons.

-- ---------------------------------------------------------------
-- Admins who can log in to the dashboard
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admins (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    email         VARCHAR(190) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name     VARCHAR(150),
    role          ENUM('admin', 'viewer') NOT NULL DEFAULT 'admin',
    active        TINYINT(1) NOT NULL DEFAULT 1,
    created_at    DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    UNIQUE KEY uq_admins_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------
-- People being tracked. Deactivate instead of deleting, so old
-- attendance reports stay accurate.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS people (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    full_name   VARCHAR(150) NOT NULL,
    external_id VARCHAR(64) NULL,
    group_name  VARCHAR(100) NULL,
    email       VARCHAR(190) NULL,
    active      TINYINT(1) NOT NULL DEFAULT 1,
    created_at  DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    UNIQUE KEY uq_people_external_id (external_id),
    KEY idx_people_group (group_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------
-- Cards. A person can own several cards over time, but a card UID
-- belongs to exactly one person. Only ONE active card per person:
-- active_person_id is person_id while the card is active and NULL
-- otherwise, and a unique index ignores NULLs.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cards (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    uid              VARCHAR(20) NOT NULL,
    person_id        INT NOT NULL,
    status           ENUM('active', 'lost', 'disabled') NOT NULL DEFAULT 'active',
    assigned_at      DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    assigned_by      INT NULL,
    active_person_id INT GENERATED ALWAYS AS (IF(status = 'active', person_id, NULL)) STORED,
    UNIQUE KEY uq_cards_uid (uid),
    UNIQUE KEY one_active_card_per_person (active_person_id),
    CONSTRAINT fk_cards_person FOREIGN KEY (person_id) REFERENCES people (id),
    CONSTRAINT fk_cards_admin  FOREIGN KEY (assigned_by) REFERENCES admins (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------
-- Readers (ESP32 devices). Created automatically when a reader
-- sends its first scan.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    device_id    VARCHAR(64) PRIMARY KEY,
    label        VARCHAR(100) NULL,
    last_seen_at DATETIME(3) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------
-- Attendance records (one row per recognised scan)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attendance (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    person_id   INT NOT NULL,
    card_id     INT NOT NULL,
    device_id   VARCHAR(64) NOT NULL,
    scanned_at  DATETIME(3) NOT NULL,
    received_at DATETIME(3) NOT NULL,
    scan_id     VARCHAR(64) NULL,
    KEY idx_attendance_person_time (person_id, scanned_at),
    KEY idx_attendance_time (scanned_at),
    KEY idx_attendance_device_time (device_id, scanned_at),
    CONSTRAINT fk_attendance_person FOREIGN KEY (person_id) REFERENCES people (id),
    CONSTRAINT fk_attendance_card   FOREIGN KEY (card_id)   REFERENCES cards (id),
    CONSTRAINT fk_attendance_device FOREIGN KEY (device_id) REFERENCES devices (device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------
-- Every scan_id the server has handled, whatever the outcome.
-- Makes retries safe and survives server restarts.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processed_scans (
    scan_id      VARCHAR(64) PRIMARY KEY,
    outcome      ENUM('ok', 'assigned', 'already_assigned', 'unknown', 'disabled') NOT NULL,
    person_id    INT NULL,
    processed_at DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    CONSTRAINT fk_processed_person FOREIGN KEY (person_id) REFERENCES people (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------
-- Taps from cards nobody owns. Delete old rows regularly.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS unknown_scans (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    uid        VARCHAR(20) NOT NULL,
    device_id  VARCHAR(64) NOT NULL,
    scanned_at DATETIME(3) NOT NULL,
    KEY idx_unknown_scans_time (scanned_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------
-- Tap-to-assign sessions: "the next card tapped on this reader
-- belongs to this person". At most one open (pending) session per
-- reader and per person, using the same generated-column trick.
-- The server must mark timed-out sessions expired before opening a new one.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assignment_sessions (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    person_id         INT NOT NULL,
    device_id         VARCHAR(64) NOT NULL,
    status            ENUM('pending', 'completed', 'cancelled', 'expired') NOT NULL DEFAULT 'pending',
    created_at        DATETIME(3) NOT NULL,
    expires_at        DATETIME(3) NOT NULL,
    completed_at      DATETIME(3) NULL,
    card_id           INT NULL,
    created_by        INT NULL,
    pending_device_id VARCHAR(64) GENERATED ALWAYS AS (IF(status = 'pending', device_id, NULL)) STORED,
    pending_person_id INT GENERATED ALWAYS AS (IF(status = 'pending', person_id, NULL)) STORED,
    UNIQUE KEY one_pending_session_per_device (pending_device_id),
    UNIQUE KEY one_pending_session_per_person (pending_person_id),
    CONSTRAINT fk_sessions_person FOREIGN KEY (person_id) REFERENCES people (id),
    CONSTRAINT fk_sessions_device FOREIGN KEY (device_id) REFERENCES devices (device_id),
    CONSTRAINT fk_sessions_card   FOREIGN KEY (card_id)   REFERENCES cards (id),
    CONSTRAINT fk_sessions_admin  FOREIGN KEY (created_by) REFERENCES admins (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------
-- Audit trail: who did what, and when
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    at          DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    admin_id    INT NULL,
    action      VARCHAR(64) NOT NULL,
    target_type VARCHAR(32) NULL,
    target_id   VARCHAR(64) NULL,
    details     JSON NULL,
    KEY idx_audit_time (at),
    CONSTRAINT fk_audit_admin FOREIGN KEY (admin_id) REFERENCES admins (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;