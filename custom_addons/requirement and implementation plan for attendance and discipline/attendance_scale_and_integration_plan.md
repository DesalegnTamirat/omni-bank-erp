# Attendance Module — Scale, Discipline Integration & Payroll/Time-Off Readiness
### Implementation Plan for Antigravity Agent
**Target system:** `custom_hr_attendance` (Odoo 19) + `discipline_management` (Odoo 19)
**Hard requirement:** 6,000+ employees checking in within a 15-minute window with no perceptible delay.

---

## 0. Governing Principle

There are two fundamentally different kinds of logic in this module, and they must be treated differently:

| Kind | Example | Where it must live |
|---|---|---|
| **Hot-path, per-check-in work** | Recording the check-in, computing Late/Normal status, blocking on suspension/leave | Synchronous, inside the request, but strictly O(1) and indexed — this runs 6,000 times in 15 minutes |
| **Side-effect / cross-module work** | Creating a discipline case, sending a violation notification, flagging a payroll payload | **Asynchronous**, off the request path entirely — must never add latency to the check-in transaction, regardless of how many employees trigger it |

Every phase below is designed around keeping the first column untouched and pushing everything else into the second.

---

## 1. Architecture Decision: `queue_job` (OCA) as the async backbone

**Why not cron for reactive logic:** cron is poll-based — it either runs too often (wasted table scans) or too rarely (stale escalations), and a periodic full/broad scan scheduled near 8:00 AM risks contending with the exact traffic spike we're protecting.

**Why not an ad-hoc thread/background task:** not transactional, not persisted, no retry on failure, and unsafe inside Odoo's worker model.

**Why `queue_job`:** it's the standard OCA solution for this exact problem — jobs are persisted DB records (`queue.job`), executed by dedicated job-runner workers *separate from* the web workers serving check-in requests, with automatic retry and channel-based capacity control. This is production-proven at bank scale and is the correct tool here, not a workaround.

**Action for the agent:**
- Add `queue_job` to `custom_hr_attendance/__manifest__.py` → `depends`.
- Define a dedicated channel `root.attendance_integration` (separate from the default channel) so a burst of discipline/payroll jobs never starves other background work, and vice versa.
- If `queue_job` cannot be installed in this environment, fall back to the narrow micro-cron pattern in §4 — but this is the fallback, not the primary design.

---

## 2. Phase 1 — Harden the Hot Path (refactor only, no new behavior)

Before adding anything, make sure `hr.employee._attendance_action_change()` in `custom_hr_attendance/models/restrict_checkin.py` stays exactly as cheap as it is today:

- **Confirm indexes exist** (add via `_sql_constraints`/`_auto_init` or a `post_init_hook` if missing):
  - `hr_attendance(employee_id) WHERE check_out IS NULL` (partial index — used by every check-out lookup)
  - `hr_attendance(employee_id, check_in)`
  - `hr_attendance(check_in_status)` — used by discipline counter logic in Phase 3
- **Do not** add any cross-module call (discipline, payroll) directly inside `_attendance_action_change`. Instead, add exactly one call at the very end:
  ```python
  attendance._enqueue_attendance_side_effects()
  ```
  This method's only synchronous work is a single indexed counter increment (§3). Everything else it does is `.with_delay(channel='root.attendance_integration')`.
- **Load-test gate before proceeding**: build a Locust/JMeter script simulating 6,000 unique employees hitting `/custom_hr_attendance/my_attendance_toggle` over a 15-minute bell curve (peak concentration in the first 3 minutes). Target: p95 < 300ms, zero deadlocks, zero row-lock timeouts. Run this **before** Phase 4 (§6) is enabled anywhere, since that's the one piece touching every request from every user, not just check-in.

---

## 3. Phase 2 — Discipline Integration (reuse `discipline_management`'s existing pattern)

The discipline module already has the right shape for this — mirror it, don't reinvent it.

### 3.1 Seed two new offenses under the existing category

`discipline_management` already ships `offense_cat_attendance` (code `ATT`). Add a new data file:

`custom_hr_attendance/data/discipline_offense_attendance_data.xml`
```xml
<record id="offense_repeated_lateness" model="discipline.offense">
    <field name="name">Repeated Lateness Violation</field>
    <field name="category_id" ref="discipline_management.offense_cat_attendance"/>
    <field name="severity_level">level_4</field>
    <field name="punishment_type">first_warning_penalty</field>
    <field name="penalty_percentage">5.0</field>
    <field name="approval_authority">direct_manager</field>
</record>
<record id="offense_repeated_force_checkout" model="discipline.offense">
    <field name="name">Repeated Force Checkout / Attendance Irregularity</field>
    <field name="category_id" ref="discipline_management.offense_cat_attendance"/>
    <field name="severity_level">level_3</field>
    <field name="punishment_type">second_warning_penalty</field>
    <field name="penalty_percentage">10.0</field>
    <field name="approval_authority">hr_manager</field>
</record>
```
Add `discipline_management` to `depends` in the manifest, and this file to `data`.

### 3.2 O(1) counters instead of table scans

`custom_hr_attendance/models/hr_employee_counters.py` (new file — keep separate from discipline's own `hr_employee.py` to avoid merge conflicts):
```python
class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    late_count_rolling = fields.Integer(default=0)
    force_checkout_count_rolling = fields.Integer(default=0)
```
At check-in/check-out time, increment with a single-row `UPDATE`, never a `search()`/aggregate:
```python
def _enqueue_attendance_side_effects(self):
    self.ensure_one()
    if self.check_in_status == 'Late':
        self.employee_id.sudo().late_count_rolling += 1
        self._maybe_flag_discipline_violation('lateness')
    if self.is_force_checkout:
        self.employee_id.sudo().force_checkout_count_rolling += 1
        self._maybe_flag_discipline_violation('force_checkout')
```
This is a single-row write per employee — cost is identical whether 1 or 6,000 employees are checking in simultaneously, because each write touches only that employee's row.

### 3.3 Threshold check + async case creation

```python
def _maybe_flag_discipline_violation(self, kind):
    params = self.env['ir.config_parameter'].sudo()
    threshold = int(params.get_param(f'hr_attendance.{kind}_violation_threshold', 3))
    counter_field = 'late_count_rolling' if kind == 'lateness' else 'force_checkout_count_rolling'
    if getattr(self.employee_id, counter_field) >= threshold:
        self.employee_id.sudo().write({counter_field: 0})  # reset, avoid duplicate cases
        self.env['discipline.case'].sudo().with_delay(
            channel='root.attendance_integration'
        )._create_from_attendance(self.employee_id.id, kind, self.id)
```

New thin-inherit file `custom_hr_attendance/models/discipline_case_attendance.py`:
```python
class DisciplineCase(models.Model):
    _inherit = 'discipline.case'

    @api.model
    def _create_from_attendance(self, employee_id, kind, attendance_id):
        offense_xmlid = ('custom_hr_attendance.offense_repeated_lateness' if kind == 'lateness'
                          else 'custom_hr_attendance.offense_repeated_force_checkout')
        offense = self.env.ref(offense_xmlid, raise_if_not_found=False)
        if not offense:
            return
        case = self.create({
            'employee_id': employee_id,
            'offense_id': offense.id,
            'description': _('Automatically flagged by Attendance module: threshold for %s exceeded.') % kind,
            'reference': f'ATT-{attendance_id}',
        })
        case.action_initiate()  # system is Initiator only — reviewer/approver still required (segregation of duties, unchanged)
        return case
```
This respects `discipline.case`'s existing segregation-of-duties rule (`initiator_id != reviewer_id != approver_id`) — the attendance module only *opens* the case; a human still reviews and approves it. Nothing here bypasses discipline's own workflow.

### 3.4 Config additions (`res.config.settings`)
Add: `hr_attendance.lateness_violation_threshold` (default 3), `hr_attendance.force_checkout_violation_threshold` (default 2). Keep these as plain integers, same pattern as your existing toggles in `res_config_settings.py`.

### 3.5 One existing gap to flag back to the discipline module owner

`discipline_management/models/hr_attendance.py` → `_check_unpaid_suspension_attendance` currently has a `pass` where the actual block should be — it computes `is_suspended_attendance` correctly but never raises. This should be completed (raise `ValidationError` on unpaid-suspension check-in) as part of this integration, since your attendance module's own suspension check in `restrict_checkin.py` only queries `hr.discipline` (a model that doesn't exist in this codebase) rather than the real `discipline.case`/`is_suspended` field discipline_management provides. **Recommend the agent update `restrict_checkin.py`'s suspension check to use `employee.is_suspended` / `employee.suspension_type` directly** instead of the dangling `hr.discipline` reference — this is a real bug fix, not just an integration nicety.

---

## 4. Phase 3 — Force-Checkout & Absence Detection: keep the SQL crons, just isolate them from the rush window

These two are **inherently time-based** — there's no event to hook when someone *fails* to act. Keep your existing set-based SQL (`cron_automatic_force_checkout`, `cron_automatic_absence_detection`) exactly as they are; they are already single indexed `UPDATE`/anti-join statements, not per-row loops, so they are not the performance risk.

The only change needed:
- **Reschedule absence detection to run well outside the check-in window** — e.g. 09:30 daily instead of whatever it currently defaults to — a one-line change to `nextcall`/`interval` in `data/ir_cron_data.xml`. This guarantees zero interaction with the 8,000-in-15-minutes burst, since it's a different time of day entirely.
- **Fallback pattern (only if `queue_job` is unavailable):** instead of a broad periodic scan, mark rows with a boolean the moment they become eligible (`is_force_checkout = True`, already done), then run a **micro-cron** every 1–2 minutes that only touches `WHERE is_force_checkout = TRUE AND discipline_flagged = FALSE` — an indexed boolean lookup touching a handful of rows, not the table. This is a legitimate middle ground if OCA modules can't be installed, and is explicitly *not* the same cost profile as a naive "scan everyone every N minutes" cron.

---

## 5. Phase 4 — ERP Access Gate (FR-ATT-023/024) — highest performance risk, roll out last

This is the one piece that runs on **every request from every one of 6,000 users**, not just at check-in — treat it with the most caution.

- **Do not** query `hr.attendance` inside `ir.http._dispatch` on every request — that alone would add thousands of queries/second on top of the check-in burst.
- **Cache the state in the HTTP session** instead:
  ```python
  # models/ir_http.py
  class IrHttp(models.AbstractModel):
      _inherit = 'ir.http'

      @classmethod
      def _dispatch(cls, endpoint):
          if cls._route_requires_attendance_gate(request):
              if not request.session.get('attendance_checked_in'):
                  employee = request.env.user.employee_id
                  if employee and employee.attendance_state == 'checked_in':
                      request.session['attendance_checked_in'] = True
                  else:
                      return cls._attendance_gate_response()
          return super()._dispatch(endpoint)
  ```
  Set the session flag on successful check-in (in the same controller that calls `_attendance_action_change`), and clear it on check-out/logout. This bounds DB access to roughly once per session, not once per request.
- **Maintain an exempt-route allowlist** via config (Settings, Discuss, My Profile, and the check-in screen itself must always be reachable) so nobody gets fully locked out.
- **Roll out branch-by-branch**, feature-flagged (`enable_checkin_gate`, same pattern as your other `enable_*` toggles) — this is the highest blast-radius change in the whole plan.

---

## 6. Phase 5 — Payroll-Ready Hooks (Module 8 doesn't exist yet — build the contract, not the integration)

Mirror `discipline.payroll.penalty`'s exact shape (`pending → transferred → deducted`, `calculated_amount` computed off `hr.contract.wage`) so both modules feed the future payroll module through the same contract.

New file `custom_hr_attendance/models/attendance_payroll_payload.py`:
```python
class AttendancePayrollPayload(models.Model):
    _name = 'attendance.payroll.payload'
    _description = 'Attendance Payroll Integration Payload'

    employee_id = fields.Many2one('hr.employee', required=True)
    payload_type = fields.Selection([
        ('overtime', 'Approved Overtime'),
        ('unauthorized_absence', 'Unauthorized Absence Deduction'),
    ], required=True)
    source_over_time_id = fields.Many2one('over.time')
    source_attendance_id = fields.Many2one('hr.attendance')
    hours = fields.Float()
    effective_date = fields.Date(required=True)
    state = fields.Selection([
        ('pending', 'Pending Transmission'),
        ('transferred', 'Transmitted to Payroll'),
        ('processed', 'Processed in Payslip'),
    ], default='pending')
    payslip_reference = fields.Char()
```
Populate this from `over.time` approval and from the absence-detection cron output, instead of writing directly into a payroll table that doesn't exist yet. When Module 8 is built, it polls `state = 'pending'` here — one clean interface, matching the pattern already proven in discipline_management. Document the field contract in `docs/PAYROLL_INTEGRATION.md` so whoever builds Module 8 doesn't need to reverse-engineer it.

---

## 7. Phase 6 — Time-Off Integration: formalize what already works

Leave sync is already correctly implemented as an O(1) indexed check inside `_attendance_action_change`. No redesign needed — just:
- Extract the inline leave-search block into a named, reusable method `_is_covered_by_approved_leave(employee_id, date)` so the Leave module (or its wizards) can call the identical logic instead of duplicating the query later.
- No other change required for Phase 6 — this is a documentation/extraction task, not new logic.

---

## 8. Rollout Order (risk-ascending)

1. **Phase 1** — hot-path hardening + load-test harness (invisible to users, do first, blocks everything else)
2. **Phase 3** — cron rescheduling (zero risk, one config change)
3. **Phase 6** — time-off method extraction (zero risk, refactor only)
4. **Phase 5** — payroll payload model (additive only, no behavior change until Module 8 exists)
5. **Phase 2** — discipline integration (feature-flagged, real behavior change, needs a pilot group)
6. **Phase 4** — ERP access gate (highest blast radius — branch-by-branch rollout, only after Phase 1's load test passes at target scale)

---

## 9. File Manifest for the Agent

| File | Action |
|---|---|
| `custom_hr_attendance/__manifest__.py` | Add `queue_job`, `discipline_management` to `depends`; register new data/model files |
| `custom_hr_attendance/models/restrict_checkin.py` | Fix dangling `hr.discipline` reference → use `employee.is_suspended`; add `_enqueue_attendance_side_effects()` call |
| `custom_hr_attendance/models/hr_employee_counters.py` | **New** — rolling violation counters |
| `custom_hr_attendance/models/discipline_case_attendance.py` | **New** — `_create_from_attendance()` |
| `custom_hr_attendance/models/attendance_payroll_payload.py` | **New** — payroll contract model |
| `custom_hr_attendance/models/ir_http.py` | **New** — session-cached access gate (Phase 4 only) |
| `custom_hr_attendance/models/res_config_settings.py` | Extend — violation thresholds, gate toggle |
| `custom_hr_attendance/data/discipline_offense_attendance_data.xml` | **New** — seeds 2 offenses |
| `custom_hr_attendance/data/ir_cron_data.xml` | Edit — reschedule absence-detection cron time |
| `docs/PAYROLL_INTEGRATION.md` | **New** — contract documentation for future Module 8 |

---

## 10. Definition of Done

- Load test: 6,000 simulated check-ins over 15 minutes, p95 < 300ms, zero deadlocks.
- A repeated-lateness employee gets a `discipline.case` created (state `initiated`) without the triggering check-in request slowing down.
- Force-checkout and absence-detection crons run measurably outside the 08:00–08:15 window in the schedule.
- `attendance.payroll.payload` rows are created for approved overtime with `state='pending'`, ready for Module 8 to consume — no payroll module dependency added yet.
- Access gate (if enabled) adds no DB query on requests within an existing checked-in session.
