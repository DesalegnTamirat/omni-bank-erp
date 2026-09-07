# QA Review — `custom_hr_attendance` Module
**Scope:** Full technical + business QA of the custom Odoo attendance system (43 Python files, ~10,500 lines, plus controllers, security, cron/SQL, and frontend JS), with specific attention to correctness, incomplete/unclear logic, performance at 5,000+ concurrent employees (15-minute check-in/out window), and security.

**Method:** Full manual read of the core check-in/out engine, controllers, security layer, cron/SQL functions, discipline/payroll subsystems, batch/manual wizards, overtime, dashboard service, roster/shift/exception models, plus a static AST scan for duplicate field/method definitions and targeted greps for known anti-patterns (raw SQL injection, `unlink()` misuse, per-record write loops).

**Not covered in full depth:** report/view XML internals, `hr_attendance_reason.py`, `hr_attendance_notification_log.py`, `my_shift_schedule.py`, `over_time_report.py`, `job_position_exception_report.py`, `attendance_preapproval_report.py`, `acknowledged_attendance_report.py`, `manager_daily_attendance_wizard.py`, `hr_attendance_flag_wizard.py` — these were only spot-checked, not line-by-line reviewed.

---

## 1. Must-fix before go-live (Critical)

### 1.1 — Flagship "Discipline Integration" feature is completely unwired
The manifest advertises auto-flagging of repeated lateness/force-checkout with "rolling O(1) violation counters." None of it runs:

- `hr_attendance.py._enqueue_attendance_side_effects()` (called on every check-in) does:
  ```python
  if hasattr(self, '_process_attendance_violation_counters'):
      self._process_attendance_violation_counters()
  ```
  **`_process_attendance_violation_counters` is never defined anywhere in the codebase.** Always `False`. No-op forever.
- `hr_employee_discipline_profile.py` has fully-built, correctly-written atomic SQL increment/reset methods (`_increment_late_count`, `_increment_force_checkout_count`, `_increment_missing_lunch_tap_count`) — **nothing in the module calls them.**
- `discipline_case_attendance.py` (supervisor notification on violations) and `attendance_violation_rule.py` (`attendance.lateness.rule` / `attendance.absence.rule` models) are **not imported in `models/__init__.py`** — these classes never register with Odoo at all.
- `views/attendance_violation_rule_views.xml` exists but is **not referenced in the manifest's `data` list** — likely omitted because loading it would fail (view referencing an unregistered model).
- Two of the three related cron jobs ship with `active="False"` in `data/ir_cron_data.xml`:
  - `ir_cron_automatic_absence_detection`
  - `ir_cron_job_abandonment_detection`
- Settings fields `unexcused_consecutive_threshold` / `unexcused_monthly_threshold` exist in Settings UI but are **read nowhere** in the code.

**Impact:** An admin can configure lateness/absence discipline rules and thresholds through the UI, and literally nothing happens. Easy to miss in UAT because the code *looks* complete.

**Fix:** Either implement `_process_attendance_violation_counters()` to call the existing `_increment_*` methods and wire up `discipline_case_attendance.py`/`attendance_violation_rule.py` in `__init__.py` and the manifest, or remove the advertised feature from scope/documentation until it's built.

---

### 1.2 — Auto-absence payroll records use invalid enum values (silent data corruption)
`detect_daily_employee_absences()` — defined identically (and buggily) in both `data/sql_functions.xml` and `hr_attendance.py`'s `init()` — inserts directly into `attendance_payroll_payload` via raw SQL:

```sql
INSERT INTO attendance_payroll_payload (..., payload_type, state, ...)
SELECT ..., 'absence' AS payload_type, 'draft' AS state, ...
```

But the model's Selection fields only allow:
- `payload_type`: `'overtime'` / `'unauthorized_absence'` — **not `'absence'`**
- `state`: `'pending'` / `'transferred'` / `'processed'` — **not `'draft'`**

The correct ORM factory method `create_absence_payload()` (which uses the right values) exists in the same file but is **never called** — the raw SQL bypasses it entirely.

**Impact:** Even if the disabled cron from 1.1 is turned on, any downstream code that filters `payload_type = 'unauthorized_absence'` or `state = 'pending'` (e.g. a future Payroll module poll, per the documented contract) will **never see these rows**. Absence deductions silently vanish from the payroll pipeline.

**Fix:** Correct both enum values in the SQL (in both places it's defined), or switch the function to call `create_absence_payload()` via a server-side loop instead of raw SQL.

---

### 1.3 — "Overwrite Existing Attendance" crashes on every real use (2 call sites)
`hr_attendance.py` overrides `unlink()` to hard-block deletion unless `context.get('force_unlink_attendance')` is set (raises `UserError("Attendance records cannot be deleted...")`). Two workflows try to delete-and-recreate attendance without ever setting that flag:

- `hr_attendance_batch_request.py:194` — `_generate_batch_attendances()`, `overwrite_existing=True` path
- `wizard/hr_attendance_manual_wizard.py:842` — "Batch Operating Unit Entry" scenario, same pattern

Both call `existing.unlink()` directly with no `.with_context(force_unlink_attendance=True)`.

**Impact:** The moment a manager checks "Overwrite Existing Attendances" and there's actually something to overwrite, the whole request/wizard throws and fails. This is a visible UI feature (a checkbox), not dead code — it will fail the first time anyone tries to use it, and should be caught in a 10-minute UAT pass.

**Fix:** Add `.with_context(force_unlink_attendance=True)` at both call sites, or relax the `unlink()` guard for trusted internal calls.

---

### 1.4 — Broad models have zero row-level access control
In `security/ir.model.access.csv`, three models grant **full CRUD (read/write/create/unlink) to `base.group_user`** — i.e. every one of the 5,000+ employees — with **no accompanying `ir.rule`** anywhere in the module (confirmed via full-module grep):

| Model | Risk |
|---|---|
| `hr.employee.discipline.profile` | Any employee can read, edit, or delete **any other employee's** lateness/force-checkout counters via RPC. The `groups=` attribute on the counter fields only hides them in views — it is **not** ORM/RPC-level security. |
| `over.time.consumption` | Same exposure on overtime-balance-consumption records. |
| `my.shift.schedule` (TransientModel) | Lower risk (transient/scratch records) but still unrestricted. |

**Impact:** Any authenticated employee could, via a simple RPC call (browser dev console, no special access needed), erase evidence of their own violations, or tamper with a colleague's discipline/overtime records.

**Fix:** Add `ir.rule`s scoping these to the employee's own records / manager hierarchy, matching the pattern already used elsewhere in the module (e.g. `hr_attendance_record_rules.xml`).

---

### 1.5 — Broken access control on the attendance dashboard (IDOR-style)
In `attendance_dashboard_service.py`:

- `_resolve_user_access_level()` grants `has_corporate_access = True` to **any single-branch manager** (`access_level = 'ou_manager'` — simply "manages one operating unit or has subordinates"), not just true corporate/HQ roles.
- `_get_scoped_employee_ids()` only applies the `managed_ous` / `managed_districts` restriction in the **fallback branch, when the client does *not* supply `ou_id`/`dept_or_dist_id`**:
  ```python
  if level == 'ou_manager' and not ou_id: ...
  elif level == 'district_or_dept' and not (dept_or_dist_id or ou_id): ...
  ```
- When the client *does* supply `ou_id`/`dept_or_dist_id`, it's used directly to build the SQL domain with **no check that the unit is within the caller's `managed_ous`.**

**Impact:** Any of the hundreds of branch-level managers across the bank can call the `dashboard_analytics` JSON-RPC endpoint (`auth='user'`) with an arbitrary `ou_id` for a branch/district they don't manage and get back real KPI data (headcount, present/late/absent, hourly check-in distribution) for that unit — from the browser console, with an ordinary manager login.

**Fix:** Always intersect the requested `ou_id`/`dept_or_dist_id` against `access_info['managed_ous']`/`managed_districts` before building the query, regardless of whether the client supplied an explicit filter.

---

### 1.6 — Debug stub silently overrides a real inherited method
`models/over_time_leave_manager.py`, lines 40-41:
```python
def fetch(self):
    print("fetch")
```
This class does `_inherit = "leave.request.manager"` and overrides `fetch()` with nothing but a `print()` and no `return`. If the base `leave.request.manager` model (external dependency, not in this package) has a real `fetch()` used in its own workflow, this **silently replaces it with a no-op**.

**Fix:** Verify against the base module what `fetch()` is supposed to do; remove this stub or implement it properly. Using `print()` instead of `_logger` in production code should also be corrected wherever it occurs.

---

## 2. Performance — specifically relevant to 5,000 employees / 15-minute check-in window

### 2.1 — Dead performance indexes (duplicate `_auto_init`)
`hr_attendance.py` defines `_auto_init()` **twice** (once near the top of the class, once near the bottom). Python silently keeps only the second definition — the first block, explicitly commented **"High-Speed Performance Indexes for 6,000 Concurrent Check-Ins,"** never runs. The two versions also contradict each other (one drops an index the other recreates).
**Fix:** Merge into a single `_auto_init()` override that calls `super()._auto_init()` once and creates all intended indexes.

### 2.2 — Schedule resolution runs twice per check-in
`_select_applicable_shift()` re-resolves the employee's full schedule from scratch (`_resolve_employee_full_schedule`: up to 4 sequential searches — leave → roster exception → job exception → location exception) even though the caller (`_attendance_action_change`) already computed this moments earlier. It also accepts `location_exceptions`/`job_position_exceptions` parameters that callers spend a query fetching and passing in — **the method body never uses them**, re-querying internally instead.
**Impact:** Every single check-in pays for the expensive multi-query schedule resolution twice, and wastes an extra query pre-fetching exceptions that are then ignored.
**Fix:** Thread the already-computed `sched` (and the pre-fetched exceptions) through to `_select_applicable_shift()` instead of recomputing.

### 2.3 — ERP-wide request interception, not just attendance-scoped
`ir_http.py._dispatch()` runs on **every HTTP request across the entire ERP** (not just attendance routes) whenever the "check-in gate" is enabled, re-querying `employee.attendance_state` fresh on each request. Its own docstring calls this "session-cached," and a `_session_is_checked_in()` helper reads from `request.session` — but `_dispatch()` **never actually calls it**, so the caching is dead code and every request pays full cost.
**Fix:** Actually use the session cache to short-circuit the DB check for users already known to be checked in this session.

### 2.4 — Noisy hot-path logging
The check-in path logs routine, expected diagnostics at `_logger.warning(...)` (should be `debug`/`info`) and dumps full `vals` dicts via `_logger.info(...)` on every check-in. At burst volume (many employees clocking in around shift start) this is real I/O cost and pollutes WARNING-level alerting with non-issues.
**Fix:** Downgrade routine diagnostic logs to `DEBUG`.

### 2.5 — `mail.thread`/`mail.activity.mixin` on the highest-frequency table
`hr.attendance` inherits chatter/activity/tracking machinery, adding follower computation, tracking-value diffing, and subtype resolution overhead to every create/write on what should be the highest-frequency table in the system.
**Fix:** Consider whether full chatter is necessary here, or whether a lighter audit-log table would serve the same purpose with less overhead.

### 2.6 — Batch generation creates records one at a time
`hr_attendance_batch_request.py._generate_batch_attendances()` calls `Attendance.create(att_vals)` individually inside nested employee × day × session loops instead of building one `vals_list` and issuing a single batched `create()`. Since these records are created with `is_acknowledged: True`, each one also re-triggers the full `_apply_manager_logic()` path (including the double schedule-resolution from 2.2).
**Impact:** A batch request spanning many days/employees (the feature exists specifically for requests >3 days) can mean thousands of individual ORM calls to approve one request.
**Fix:** Build a `vals_list` and use a single batched `create()`; separately optimize `_apply_manager_logic()` per §2.2.

### 2.7 — `res.users` group sync writes one user at a time
`res_users.py._sync_attendance_manager_groups()` loops over `self` and calls `user.sudo().write(...)` **per user**. Called from `hooks.py.post_init_hook()` over **all non-portal users** at install/upgrade — for 5,000+ employees, that's up to 5,000 sequential writes (each invalidating security caches) during deployment. Also re-triggered on any bulk employee-onboarding `write()`/`create()` that touches `employee_id`/`employee_ids`.
**Fix:** Partition users into "needs group added" / "needs group removed" and issue at most two batched `write()` calls.

### 2.8 — Duplicate cost: schedule-resolution logic reimplemented 3 times
The shift/schedule-resolution business logic is independently reimplemented in `restrict_checkin.py._resolve_employee_full_schedule()`, `controllers.py._get_employee_shift_info()`, and an alias in `hr_attendance.py`. A future rule change (e.g. lunch policy) has to be correctly replicated in multiple places or will silently drift — not a runtime performance bug, but a latent correctness/perf risk every time this logic is touched.

### 2.9 — SQL functions defined twice, in two different mechanisms
The same PL/pgSQL functions (`detect_daily_employee_absences`, `auto_checkout_all_employees`, etc.) are defined both via Python `init()` hooks (re-run on every module upgrade) and via `data/sql_functions.xml` (loaded once at install). Confirmed identical (and identically buggy, see §1.2) in both places today — but this duplication is a standing maintenance risk if they're ever edited independently.

---

## 3. Business-logic gaps worth a product conversation

- **Hard check-in block with no fallback.** Self-service check-in is blocked entirely ~35 minutes after shift start (`grace + dead_time`). A legitimately late employee has no self-service way to record attendance. If the ERP access gate (§2.3) is also enabled, that same employee can simultaneously be locked out of the *entire* ERP — including submitting a leave request — creating a genuine dead-end scenario. Worth reviewing with the business: should late check-in create a flagged/pending record instead of being rejected outright?
- **Geolocation is scaffolded but never implemented end-to-end.** The controller route (`my_attendance_toggle`) and the JS (`_toggle(latitude, longitude)`) both have parameters for lat/long, but the JS's `onClickToggle()` calls `_toggle()` with no arguments, and the controller never forwards whatever it receives to `_attendance_action_change()`. If location-based fraud prevention was intended for a multi-branch bank, it doesn't currently exist — only IP address and User-Agent (both easily spoofed) are captured.
- **Global shared report table race condition.** The "Generate Detail Employee Attendance Report" wizard works by `TRUNCATE`-ing and refilling a single global table (`generate_employee_attendance_details`) inside a Postgres function, then opening an unfiltered list view on it. Two managers running the report concurrently will see each other's `TRUNCATE` wipe/overwrite their in-flight results — a real race, not theoretical, at 5,000-employee scale with multiple HR/branch managers.
- **Permanent shift-reuse block.** `job_position_exception.py._check_duplicate_exception()` permanently forbids an employee from ever having a second `job.position.exception` record referencing the same `job.shift`, even long after the first one has ended/archived (explicitly stated in the error text: "even if inactive/archived"). This blocks a plausible real-world case — an employee cycling back onto a shift they'd previously been on.
- **Location-exception duplicate check is too narrow / too broad in different ways.** `location_based_exception.py._check_duplicate_time_range()` compares only `(operating_unit, start_time, end_time)` — since those times are computed from `shift_id`, this effectively means two *different* shift templates with the same clock hours can't both apply to one branch (blocks legitimate cases like different lunch-break rules for different departments at the same branch). It also ignores `start_date`/`end_date`, so an expired-but-still-active old exception can block a genuinely non-overlapping new one. For multi-location exceptions, only the first ("primary") location in the list is checked at all.
- **Overtime cap docstring/code mismatch.** `over_time.py._check_total_hours_cap()`'s docstring says "Prevents employee from accumulating more than **18** hours of total unused OT," but the code enforces `> 8.0`. Worth confirming with the business owner which number is actually correct — this ambiguity should be resolved, not left as-is.
- **Fragile "head office" detection.** `job_shift.py.is_applicable_for()` identifies head office via string matching (`'HEAD' in name`, `'MAIN' in code`, `code == 'HO'`), while `attendance_dashboard_service.py` elsewhere uses the proper `work_unit_type == 'head_office'` field for the same concept. The string-matching version is fragile (a branch literally named "Main Street Branch" would be misclassified) and inconsistent with the rest of the codebase.

---

## 4. Code-quality / hygiene pattern across the whole module

A static AST scan for duplicate field/method definitions within the same class, plus manual review, surfaced a **recurring pattern of leftover/orphaned code** — not isolated incidents:

| Item | File |
|---|---|
| Duplicate `_auto_init()` definition (2nd silently wins) | `hr_attendance.py` |
| Duplicate `time_range` field definition; first references a compute method (`_compute_time_range`) that doesn't exist | `job_position_exception.py` |
| `_compute_employee_id` defined but never wired to any field's `compute=` | `attendance_preapproval.py` |
| `models/test.py` — file is just a comment, not even imported in `__init__.py` | `models/test.py` |
| `discipline_case_attendance.py` and `attendance_violation_rule.py` — never imported, models never register | see §1.1 |
| `views/test.xml`, `demo/demo.xml`, `data/attendance_dummy_data.xml` — not referenced by the manifest at all | package root |
| `create_absence_payload()` / `create_overtime_payload()` factory methods defined but never called | `attendance_payroll_payload.py` |
| Unreachable duplicate `return allowed.ids` statement | `job_shift.py` |
| `print("fetch")` debug stub | `over_time_leave_manager.py` (see §1.6) |

**Recommendation:** Add a lint/CI step that fails the build on duplicate class-level definitions and unused/unimported files — the simple AST script used in this review takes seconds to run and would have caught most of the above automatically.

---

## 5. Lower-priority / worth noting

- Inconsistent JSON-RPC route style: `type='jsonrpc'` in `controllers.py` vs `type='json'` in `dashboard_controller.py`.
- Windows CRLF line endings throughout much of the codebase (cosmetic, but worth normalizing for cleaner diffs).
- `gate_guard.js` attaches a `MutationObserver` on `document.body` with `{childList:true, subtree:true}` that runs `querySelectorAll` scans on every DOM mutation anywhere on the page — could get janky on busy list views or lower-end kiosk hardware.
- `write()` on `hr.attendance` applies a single `vals` dict to an entire recordset; a batch check-out write where only *some* records lack `out_mode` will force `'manual'` onto **all** records in that batch, including ones that already had a different valid `out_mode`.
- Several `sudo().search()` calls run **per record inside `for` loops** in constraint/audit-guard code (e.g. the "audit immutability" guard in `hr_attendance.write()`, duplicate-window check in `create()`) — fine for single check-ins, but O(n) query cost for any bulk operation (imports, batch wizards).
- `over_time_leave_manager.confirm_leave()` reads overtime balance then creates consumption records with no row-level locking — a genuine race is possible between two near-simultaneous confirmations for the same employee. The `CHECK(remaining_hours >= 0)` SQL constraint on `over.time` will likely prevent actual data corruption, but the user would see a raw database error instead of a friendly validation message in that edge case.
- `over_time_leave_manager._notify_rejection()` has no exception handling around Discuss/channel calls, unlike every other notification helper in the module — a messaging failure here would roll back the entire `reject()` transaction, including the state change itself.

---

## Priority summary

| Priority | Count | Items |
|---|---|---|
| 🔴 Critical (fix before go-live) | 6 | §1.1–§1.6 |
| 🟠 High (performance at scale) | 9 | §2.1–§2.9 |
| 🟡 Medium (business logic) | 6 | §3 |
| 🟢 Low / hygiene | 9+ | §4, §5 |

The most urgent items are §1.3 (guaranteed crash on first real use) and §1.4/§1.5 (active access-control gaps exploitable by any employee/manager today) — these should be prioritized ahead of the dead-feature findings in §1.1/§1.2, which are silent but not exploitable.
