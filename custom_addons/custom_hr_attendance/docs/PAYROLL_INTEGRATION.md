# Attendance → Payroll Integration Contract
## `attendance.payroll.payload` — Field and Lifecycle Documentation for Module 8

This document defines the interface contract between `custom_hr_attendance` and the future
Payroll module (Module 8). Module 8 developers should read this document before implementing
payroll consumption logic.

---

## Model: `attendance.payroll.payload`

### Purpose

A one-way staging table. The Attendance module writes records here; Payroll reads and updates them.
Neither module calls the other's methods directly.

---

## Field Contract

| Field | Type | Required | Description |
|---|---|---|---|
| `employee_id` | Many2one hr.employee | Yes | The affected employee. ondelete=restrict: payloads block employee deletion. |
| `payload_type` | Selection | Yes | `overtime` or `unauthorized_absence`. |
| `source_overtime_id` | Many2one over.time | No | Set for overtime type. Links to the approved overtime record. |
| `source_attendance_id` | Many2one hr.attendance | No | Set for unauthorized_absence type. Links to the triggering attendance record. |
| `hours` | Float(10,4) | No | Overtime or absent hours. Exact monetary calculation is Payroll's responsibility. |
| `effective_date` | Date | Yes | The payroll period date this payload applies to. |
| `state` | Selection | Yes | Lifecycle state. See below. |
| `payslip_reference` | Char | No | Written by Module 8 only. The payslip identifier once consumed. |
| `notes` | Text | No | Audit notes. Auto-populated on creation; Module 8 may append. |

---

## State Lifecycle

pending -> transferred -> processed

| State | Owner | When |
|---|---|---|
| `pending` | Attendance module sets on creation | Record ready for consumption |
| `transferred` | Module 8 sets | Module 8 has picked up this record and included it in a payslip batch |
| `processed` | Module 8 sets | Deduction or payment has been confirmed in the employee payslip |

Module 8 must NOT delete records. Mark them processed and set payslip_reference.

---

## Consumption Pattern for Module 8

```python
# Fetch all pending attendance payloads for a payroll period
pending = env['attendance.payroll.payload'].search([
    ('state', '=', 'pending'),
    ('effective_date', '>=', period_start),
    ('effective_date', '<=', period_end),
])

for payload in pending:
    # Apply overtime or deduction to payslip lines
    payload.write({
        'state': 'transferred',
        'payslip_reference': payslip.name,
    })

# On payslip confirm:
payload.state = 'processed'
```

---

## Creation Methods

Use the provided API methods — do NOT create raw records directly:

```python
# From overtime approval (called by over_time.py):
env['attendance.payroll.payload'].create_overtime_payload(overtime_record)

# From absence detection cron:
env['attendance.payroll.payload'].create_absence_payload(
    employee_id=emp.id,
    absence_date=date,
    hours=8.0,
    attendance_id=None,
)
```

---

## Security

Access is controlled via security/ir.model.access.csv:
- HR Attendance Manager: full CRUD
- HR Attendance Officer: read only
- Base User: no access
- Module 8 (Payroll) service user must have write access to update state and payslip_reference.

---

Last Updated: Phase 3 implementation — Attendance Module Enterprise Enhancement (Bunna Bank ERP v19)

