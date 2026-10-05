-- OpPilot AI: synthetic operational data only; no patient or clinical fields.
-- Apply this entire file in one transaction (the existing initializer does so).
-- CREATE IF NOT EXISTS plus the additive ALTER supports the legacy schema.
-- This is not a general migration engine for independently modified databases.

CREATE TABLE IF NOT EXISTS specialty (
    specialty_id BIGSERIAL PRIMARY KEY,
    specialty_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS organization (
    organization_id BIGSERIAL PRIMARY KEY,
    organization_name TEXT NOT NULL UNIQUE CHECK (btrim(organization_name) <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS region (
    region_id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(organization_id),
    region_name TEXT NOT NULL CHECK (btrim(region_name) <> ''),
    region_code TEXT NOT NULL CHECK (btrim(region_code) <> ''),
    UNIQUE (organization_id, region_code)
);

CREATE TABLE IF NOT EXISTS practice (
    practice_id BIGSERIAL PRIMARY KEY,
    region_id BIGINT NOT NULL REFERENCES region(region_id),
    practice_name TEXT NOT NULL CHECK (btrim(practice_name) <> ''),
    practice_code TEXT NOT NULL CHECK (btrim(practice_code) <> ''),
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    practice_type TEXT NOT NULL CHECK (btrim(practice_type) <> ''),
    opening_date DATE NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (region_id, practice_code)
);

CREATE TABLE IF NOT EXISTS provider (
    provider_id TEXT PRIMARY KEY,
    provider_name TEXT NOT NULL,
    specialty_id BIGINT NOT NULL REFERENCES specialty(specialty_id),
    clinic_name TEXT NOT NULL,
    UNIQUE (provider_name, clinic_name)
);

-- Nullable deliberately: existing provider IDs, clinic filters, and loaders
-- remain valid without a hierarchy backfill. No clinic-name inference occurs.
ALTER TABLE provider ADD COLUMN IF NOT EXISTS practice_id BIGINT
    REFERENCES practice(practice_id);

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
    appointment_status TEXT NOT NULL,
    modeled_revenue NUMERIC(12,2) NOT NULL CHECK (modeled_revenue >= 0),
    practice_id BIGINT REFERENCES practice(practice_id),
    appointment_type TEXT CHECK (appointment_type IS NULL OR appointment_type IN
        ('new_patient', 'follow_up', 'annual', 'procedure', 'consult', 'urgent', 'telehealth')),
    scheduled_at TIMESTAMPTZ,
    slot_duration_minutes INTEGER CHECK (slot_duration_minutes IS NULL OR slot_duration_minutes IN (15, 20, 30, 45, 60)),
    payer_category TEXT CHECK (payer_category IS NULL OR payer_category IN
        ('Commercial', 'Medicare', 'Medicaid', 'Self Pay', 'Other'))
);

-- CREATE TABLE IF NOT EXISTS does not add the Phase 1D fields to legacy tables.
ALTER TABLE appointment_event ADD COLUMN IF NOT EXISTS practice_id BIGINT REFERENCES practice(practice_id);
ALTER TABLE appointment_event ADD COLUMN IF NOT EXISTS appointment_type TEXT
    CHECK (appointment_type IS NULL OR appointment_type IN
        ('new_patient', 'follow_up', 'annual', 'procedure', 'consult', 'urgent', 'telehealth'));
ALTER TABLE appointment_event ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ;
ALTER TABLE appointment_event ADD COLUMN IF NOT EXISTS slot_duration_minutes INTEGER
    CHECK (slot_duration_minutes IS NULL OR slot_duration_minutes IN (15, 20, 30, 45, 60));
ALTER TABLE appointment_event ADD COLUMN IF NOT EXISTS payer_category TEXT
    CHECK (payer_category IS NULL OR payer_category IN
        ('Commercial', 'Medicare', 'Medicaid', 'Self Pay', 'Other'));

-- CREATE TABLE IF NOT EXISTS does not update the old three-status constraint.
-- Replace old checks once; subsequent schema initialization avoids rescanning
-- the event table or taking an unnecessary exclusive DDL lock.
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'appointment_event'::regclass
          AND conname = 'appointment_event_appointment_status_check'
          AND pg_get_constraintdef(oid) LIKE '%cancelled_patient%'
    ) THEN
        ALTER TABLE appointment_event DROP CONSTRAINT IF EXISTS appointment_event_appointment_status_check;
        ALTER TABLE appointment_event ADD CONSTRAINT appointment_event_appointment_status_check
            CHECK (appointment_status IN ('completed', 'no_show', 'cancelled', 'cancelled_patient',
                                          'cancelled_provider', 'cancelled_practice', 'rescheduled'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'appointment_event'::regclass
          AND conname = 'appointment_event_scheduled_before_service_check'
    ) THEN
        ALTER TABLE appointment_event ADD CONSTRAINT appointment_event_scheduled_before_service_check
            CHECK (scheduled_at IS NULL OR scheduled_at < (appointment_date::timestamp AT TIME ZONE 'UTC'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS appointment_date_idx ON appointment (appointment_date);
CREATE INDEX IF NOT EXISTS performance_date_idx ON performance (performance_date);
CREATE INDEX IF NOT EXISTS appointment_event_date_provider_idx
    ON appointment_event (appointment_date, provider_id);
CREATE INDEX IF NOT EXISTS appointment_event_provider_date_idx
    ON appointment_event (provider_id, appointment_date, appointment_id);
CREATE INDEX IF NOT EXISTS appointment_event_status_date_idx
    ON appointment_event (appointment_status, appointment_date);
CREATE INDEX IF NOT EXISTS appointment_event_practice_date_idx
    ON appointment_event (practice_id, appointment_date);
CREATE INDEX IF NOT EXISTS appointment_event_type_date_idx
    ON appointment_event (appointment_type, appointment_date);

CREATE TABLE IF NOT EXISTS employee (
    employee_id BIGSERIAL PRIMARY KEY,
    practice_id BIGINT NOT NULL REFERENCES practice(practice_id),
    role TEXT NOT NULL CHECK (btrim(role) <> ''),
    fte NUMERIC(6,2) NOT NULL CHECK (fte >= 0 AND fte <> 'NaN'::numeric),
    hourly_cost NUMERIC(12,2) NOT NULL CHECK (hourly_cost >= 0 AND hourly_cost <> 'NaN'::numeric),
    hire_date DATE NOT NULL,
    termination_date DATE,
    status TEXT NOT NULL CHECK (status IN ('active', 'on_leave', 'terminated')),
    CHECK (termination_date IS NULL OR termination_date >= hire_date),
    CHECK ((status = 'terminated') = (termination_date IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS provider_capacity (
    provider_id TEXT NOT NULL REFERENCES provider(provider_id),
    capacity_date DATE NOT NULL,
    scheduled_hours NUMERIC(8,2) NOT NULL CHECK (scheduled_hours >= 0 AND scheduled_hours <> 'NaN'::numeric),
    clinical_hours NUMERIC(8,2) NOT NULL CHECK (clinical_hours >= 0 AND clinical_hours <> 'NaN'::numeric),
    available_slots INTEGER NOT NULL CHECK (available_slots >= 0),
    blocked_slots INTEGER NOT NULL CHECK (blocked_slots >= 0),
    pto_hours NUMERIC(8,2) NOT NULL CHECK (pto_hours >= 0 AND pto_hours <> 'NaN'::numeric),
    admin_hours NUMERIC(8,2) NOT NULL CHECK (admin_hours >= 0 AND admin_hours <> 'NaN'::numeric),
    PRIMARY KEY (provider_id, capacity_date)
);

CREATE TABLE IF NOT EXISTS staffing_daily (
    practice_id BIGINT NOT NULL REFERENCES practice(practice_id),
    staff_date DATE NOT NULL,
    role TEXT NOT NULL CHECK (btrim(role) <> ''),
    budgeted_fte NUMERIC(8,2) NOT NULL CHECK (budgeted_fte >= 0 AND budgeted_fte <> 'NaN'::numeric),
    scheduled_fte NUMERIC(8,2) NOT NULL CHECK (scheduled_fte >= 0 AND scheduled_fte <> 'NaN'::numeric),
    actual_fte NUMERIC(8,2) NOT NULL CHECK (actual_fte >= 0 AND actual_fte <> 'NaN'::numeric),
    overtime_hours NUMERIC(10,2) NOT NULL CHECK (overtime_hours >= 0 AND overtime_hours <> 'NaN'::numeric),
    agency_hours NUMERIC(10,2) NOT NULL CHECK (agency_hours >= 0 AND agency_hours <> 'NaN'::numeric),
    absence_hours NUMERIC(10,2) NOT NULL CHECK (absence_hours >= 0 AND absence_hours <> 'NaN'::numeric),
    PRIMARY KEY (practice_id, staff_date, role)
);

-- appointment_id references the event-grain table, NOT the daily aggregate.
-- Optional and unique: walk-ins may have no appointment; at most one encounter
-- per appointment event. Provider/practice describe the encounter's own scope.
CREATE TABLE IF NOT EXISTS encounter (
    encounter_id BIGSERIAL PRIMARY KEY,
    appointment_id BIGINT UNIQUE REFERENCES appointment_event(appointment_id),
    provider_id TEXT NOT NULL REFERENCES provider(provider_id),
    practice_id BIGINT NOT NULL REFERENCES practice(practice_id),
    encounter_date DATE NOT NULL,
    visit_type TEXT NOT NULL CHECK (btrim(visit_type) <> ''),
    work_rvu NUMERIC(10,3) NOT NULL CHECK (work_rvu >= 0 AND work_rvu <> 'NaN'::numeric),
    modeled_charge NUMERIC(14,2) NOT NULL CHECK (modeled_charge >= 0 AND modeled_charge <> 'NaN'::numeric),
    allowed_amount NUMERIC(14,2) NOT NULL CHECK (allowed_amount >= 0 AND allowed_amount <> 'NaN'::numeric)
);

CREATE TABLE IF NOT EXISTS referral (
    referral_id BIGSERIAL PRIMARY KEY,
    practice_id BIGINT NOT NULL REFERENCES practice(practice_id),
    specialty_id BIGINT NOT NULL REFERENCES specialty(specialty_id),
    referral_date DATE NOT NULL,
    scheduled_date DATE,
    referral_source TEXT NOT NULL CHECK (btrim(referral_source) <> ''),
    status TEXT NOT NULL CHECK (status IN ('pending', 'scheduled', 'completed', 'cancelled', 'declined')),
    CHECK (scheduled_date IS NULL OR scheduled_date >= referral_date),
    CHECK (status NOT IN ('scheduled', 'completed') OR scheduled_date IS NOT NULL)
);

-- Nonnegative synthetic payment components, not a signed refund ledger.
CREATE TABLE IF NOT EXISTS payment (
    payment_id BIGSERIAL PRIMARY KEY,
    encounter_id BIGINT NOT NULL REFERENCES encounter(encounter_id),
    payment_date DATE NOT NULL,
    payer_category TEXT NOT NULL CHECK (btrim(payer_category) <> ''),
    allowed_amount NUMERIC(14,2) NOT NULL CHECK (allowed_amount >= 0 AND allowed_amount <> 'NaN'::numeric),
    paid_amount NUMERIC(14,2) NOT NULL CHECK (paid_amount >= 0 AND paid_amount <> 'NaN'::numeric),
    patient_amount NUMERIC(14,2) NOT NULL CHECK (patient_amount >= 0 AND patient_amount <> 'NaN'::numeric),
    adjustment_amount NUMERIC(14,2) NOT NULL CHECK (adjustment_amount >= 0 AND adjustment_amount <> 'NaN'::numeric)
);

CREATE TABLE IF NOT EXISTS ground_truth_anomaly (
    anomaly_id BIGSERIAL PRIMARY KEY,
    practice_id BIGINT NOT NULL REFERENCES practice(practice_id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    anomaly_type TEXT NOT NULL CHECK (btrim(anomaly_type) <> ''),
    affected_metric TEXT NOT NULL CHECK (btrim(affected_metric) <> ''),
    expected_direction TEXT NOT NULL CHECK (expected_direction IN ('increase', 'decrease')),
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    description TEXT NOT NULL,
    CHECK (end_date >= start_date)
);

-- Region organization and practice region lookups use their UNIQUE indexes.
-- Capacity and staffing date lookups use their composite primary-key indexes.
CREATE INDEX IF NOT EXISTS provider_practice_idx ON provider (practice_id);
CREATE INDEX IF NOT EXISTS employee_practice_idx ON employee (practice_id);
CREATE INDEX IF NOT EXISTS encounter_practice_date_idx ON encounter (practice_id, encounter_date);
CREATE INDEX IF NOT EXISTS encounter_provider_date_idx ON encounter (provider_id, encounter_date);
CREATE INDEX IF NOT EXISTS referral_practice_date_idx ON referral (practice_id, referral_date);
CREATE INDEX IF NOT EXISTS referral_specialty_idx ON referral (specialty_id);
CREATE INDEX IF NOT EXISTS payment_encounter_date_idx ON payment (encounter_id, payment_date);
CREATE INDEX IF NOT EXISTS anomaly_practice_date_idx ON ground_truth_anomaly (practice_id, start_date, end_date);
