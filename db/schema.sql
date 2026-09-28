-- PostgreSQL schema for the synthetic Provider Performance Copilot demo.
-- It stores aggregate provider-day operations data only.  There are no patient
-- identifiers, clinical notes, diagnoses, or individual appointment records.

CREATE TABLE IF NOT EXISTS specialty (
    specialty_id BIGSERIAL PRIMARY KEY,
    specialty_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS provider (
    provider_id TEXT PRIMARY KEY,
    provider_name TEXT NOT NULL,
    specialty_id BIGINT NOT NULL REFERENCES specialty(specialty_id),
    clinic_name TEXT NOT NULL,
    UNIQUE (provider_name, clinic_name)
);

-- Daily aggregate appointment activity for one provider.  This table is
-- deliberately not patient-grain data, so importing it cannot introduce PHI.
CREATE TABLE IF NOT EXISTS appointment (
    provider_id TEXT NOT NULL REFERENCES provider(provider_id),
    appointment_date DATE NOT NULL,
    available_slots INTEGER NOT NULL CHECK (available_slots > 0),
    booked_appointments INTEGER NOT NULL CHECK (booked_appointments >= 0),
    no_shows INTEGER NOT NULL CHECK (no_shows >= 0),
    PRIMARY KEY (provider_id, appointment_date),
    CHECK (booked_appointments <= available_slots),
    CHECK (no_shows <= booked_appointments)
);

-- Daily aggregate staffing, completed visits, and revenue for one provider.
CREATE TABLE IF NOT EXISTS performance (
    provider_id TEXT NOT NULL REFERENCES provider(provider_id),
    performance_date DATE NOT NULL,
    fte NUMERIC(5,2) NOT NULL CHECK (fte > 0),
    staffed_hours NUMERIC(8,2) NOT NULL CHECK (staffed_hours > 0),
    completed_visits INTEGER NOT NULL CHECK (completed_visits >= 0),
    realized_revenue NUMERIC(14,2) NOT NULL CHECK (realized_revenue >= 0),
    PRIMARY KEY (provider_id, performance_date)
);

-- Optional scale-test fact table. Rows represent fictional appointment events
-- with no patient identifier, name, diagnosis, or clinical content. It lets
-- the project demonstrate SQL aggregation at realistic row volumes while the
-- production-style dashboard continues to consume aggregate provider-day data.
CREATE TABLE IF NOT EXISTS appointment_event (
    appointment_id BIGINT PRIMARY KEY,
    provider_id TEXT NOT NULL REFERENCES provider(provider_id),
    appointment_date DATE NOT NULL,
    appointment_status TEXT NOT NULL CHECK (appointment_status IN ('completed', 'no_show', 'cancelled')),
    modeled_revenue NUMERIC(12,2) NOT NULL CHECK (modeled_revenue >= 0)
);

CREATE INDEX IF NOT EXISTS appointment_date_idx ON appointment (appointment_date);
CREATE INDEX IF NOT EXISTS performance_date_idx ON performance (performance_date);
CREATE INDEX IF NOT EXISTS appointment_event_date_provider_idx
    ON appointment_event (appointment_date, provider_id);
CREATE INDEX IF NOT EXISTS appointment_event_provider_date_idx
    ON appointment_event (provider_id, appointment_date, appointment_id);
CREATE INDEX IF NOT EXISTS appointment_event_status_date_idx
    ON appointment_event (appointment_status, appointment_date);
