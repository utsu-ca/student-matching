PRAGMA foreign_keys = ON;

-- One row per AGM voter RSVP. Names and contact details are not stored here; student_uuid links to uoft_data.
CREATE TABLE IF NOT EXISTS agm_rsvp (
    uuid TEXT PRIMARY KEY,
    student_uuid TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    match_method TEXT,
    submission_ts TEXT,
    meeting_preference TEXT,
    contact_ok TEXT,
    flags TEXT,
    import_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
