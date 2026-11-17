-- =========================================================================
-- BUNNA BANK: SAFE RECONCILIATION SCRIPT FOR HISTORICAL ACKNOWLEDGED HOURS
-- RUN IN POSTGRESQL ONLY AFTER UPGRADING THE MODULE AND TAKING A DB BACKUP
-- =========================================================================
-- This script does NOT divide by 60 or use arbitrary value heuristics (> 12).
-- Instead, it directly reconciles acknowledged hours from the authoritative
-- engine-computed columns (late_time_hour and early_exit_hour) for records
-- marked with acknowledged status.

BEGIN;

-- -------------------------------------------------------------------------
-- STEP 1: Diagnostic Preview (Run these manually in staging to inspect rows)
-- -------------------------------------------------------------------------
-- SELECT COUNT(*) AS late_count_to_sync
-- FROM hr_attendance
-- WHERE check_in_status IN ('Acknowledged Lateness', 'acknowledged_late')
--   AND late_time_hour > 0
--   AND (acknowledged_late IS NULL OR acknowledged_late != ROUND(late_time_hour::numeric, 2));
--
-- SELECT COUNT(*) AS exit_count_to_sync
-- FROM hr_attendance
-- WHERE check_out_status IN ('Acknowledged Early Exit', 'acknowledged_early_exit')
--   AND early_exit_hour > 0
--   AND (acknowledged_exit IS NULL OR acknowledged_exit != ROUND(early_exit_hour::numeric, 2));

-- -------------------------------------------------------------------------
-- STEP 2: Reconcile Acknowledged Lateness from Authoritative late_time_hour
-- -------------------------------------------------------------------------
UPDATE hr_attendance
SET acknowledged_late = ROUND(late_time_hour::numeric, 2)
WHERE check_in_status IN ('Acknowledged Lateness', 'acknowledged_late')
  AND late_time_hour > 0
  AND (acknowledged_late IS NULL OR acknowledged_late != ROUND(late_time_hour::numeric, 2));

-- -------------------------------------------------------------------------
-- STEP 3: Reconcile Acknowledged Early Exit from Authoritative early_exit_hour
-- -------------------------------------------------------------------------
UPDATE hr_attendance
SET acknowledged_exit = ROUND(early_exit_hour::numeric, 2)
WHERE check_out_status IN ('Acknowledged Early Exit', 'acknowledged_early_exit')
  AND early_exit_hour > 0
  AND (acknowledged_exit IS NULL OR acknowledged_exit != ROUND(early_exit_hour::numeric, 2));

-- -------------------------------------------------------------------------
-- STEP 4: Align Shift Scopes for Legacy Shifts (Run only after module upgrade)
-- -------------------------------------------------------------------------
-- Note: Review shift scope assignments in Attendance > Configuration > Job Shift
-- or selectively update branch shifts that explicitly have branch operating units:
UPDATE job_shift
SET scope_type = 'branches'
WHERE (scope_type IS NULL OR scope_type = 'all')
  AND id IN (
      SELECT DISTINCT job_shift_id 
      FROM rel_job_shift_operating_unit
  );

COMMIT;
