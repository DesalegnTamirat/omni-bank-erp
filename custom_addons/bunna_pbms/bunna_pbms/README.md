# Bunna Bank - Plan and Budget Management System (bunna_pbms)

Odoo 19 module implementing the BRD "Plan and Budget Management System
(PBMS)" for the Strategic Planning and Performance Management
Directorate (SPPMD).

## Install

1. Make sure `hr_employee_custom` is installed first (PBMS depends on it for
   the branch/district/head-office org structure — PBMS does **not** define
   or let you configure org units itself).
2. Copy the `bunna_pbms` folder into your Odoo `addons_path`.
3. If you want the Excel import wizard to work, install the optional
   dependency on the server: `pip install openpyxl`.
4. Update Apps list, search "Plan and Budget Management System", Install.
5. As an SPPMD Administrator:
   - **Configuration > Org Units (Operating Units)** opens
     `hr_employee_custom`'s existing Operating Unit list — this is where
     Branch / District Office / Head Office records and their hierarchy
     (`parent_unit`) already live. PBMS just reads this data; nothing to
     configure on the PBMS side.
   - Each planner needs `default_operating_unit_id` (and/or
     `assigned_operating_unit_ids`) set on their user record — this is
     `hr_employee_custom`'s own field, also unrelated to PBMS.
   - **Configuration > Planning Cycles**: create the FY cycle (e.g.
     "FY 2026/27"), set deadlines, click *Open for Input*.
   - Add each planner to the **Branch / Head Office User**, **District
     Reviewer**, **Head Office Functional Reviewer** or **SPPMD
     Administrator** PBMS group as appropriate (Settings > Users).

## Architecture

```
operating.unit (from hr_employee_custom)        <- Branch / District Office /
  work_unit_type, parent_unit, sol_id,              Head Office hierarchy.
  user_ids / res.users.operating_unit_ids           PBMS never writes to this
                    ^                                model, only reads it.
                    | org_unit_id (M2O)
                    |
pbms.workflow.mixin (abstract)
  org_unit_id, cycle_id, state, submit/endorse/review/approve/return actions
        |
        +-- pbms.plan.line.mixin (abstract)
        |     adds the Jul-Jun monthly grid + stored quarterly/annual totals
        |       |
        |       +-- pbms.cumulative.plan.mixin (abstract)
        |       |     adds opening balance + running cumulative/outstanding
        |       |       |
        |       |       +-- pbms.deposit.plan          (BB-APF1)
        |       |       +-- pbms.customer.base.plan
        |       |       +-- pbms.fx.plan
        |       |       +-- pbms.digital.banking.plan
        |       |
        |       +-- pbms.general.expense.plan          (BB-APF4)
        |
        +-- pbms.manpower.plan (header) + pbms.manpower.plan.line     (BB-APF6)
        +-- pbms.fixed.asset.plan (header) + pbms.fixed.asset.plan.line (BB-APF7)

pbms.consolidation.line   - PostgreSQL VIEW (not a synced table) UNIONing
                             every monthly-grid format for fast, always-
                             consistent bank-wide aggregation.

pbms.dashboard            - AbstractModel exposing two read_group-backed
                             RPC methods, consumed by the OWL dashboard
                             (static/src/js/pbms_dashboard.js).
```

**Why two mixin layers (`pbms.workflow.mixin` / `pbms.plan.line.mixin`)
instead of one?** Manpower and Fixed Asset requests are itemized (header
+ N lines), not monthly figures, but they still need the identical
4-stage approval workflow. Splitting `pbms.workflow.mixin` out means
those two formats get the workflow for free without inheriting 12
unused Monetary fields.

**Why is consolidation a SQL view, not a stored table?** A synced/copy
table needs write-override or cron code to stay in sync and can go
stale; a view is always correct and pushes the aggregation into
PostgreSQL (one indexed scan per UNIONed table) instead of Python.

**Why is `district_id` computed by walking `parent_unit`?** `operating.unit`
doesn't have a fixed 3-level branch/district/bank shape — `work_unit_type`
has 7 values (branch, sub_branch, head_office, regional_office,
district_office, service_center, other) and the hierarchy depth under
`parent_unit` isn't fixed. `_find_district_ancestor()` walks upward
(bounded to 20 hops) until it hits a `district_office` unit, so it works
whether a branch reports directly to a district or through a sub-branch.

**Why is `pbms.workflow.mixin`'s `org_unit_id` scoped via
`user.operating_unit_ids` in record rules, not a single "my unit" field?**
Because that's the field `hr_employee_custom` already uses for the same
purpose in its own `operating_unit_security.xml` (see
`ir_rule_operating_unit_allowed_operating_units`) — reusing it means a
user's operating-unit assignment is configured in exactly one place for
both HR and PBMS, and a user who covers more than one branch is already
supported for free.

## Adding a new monthly-grid planning format later

1. Create a model inheriting `["pbms.plan.line.mixin", "mail.thread",
   "mail.activity.mixin"]` (or `pbms.cumulative.plan.mixin` if it needs
   an outstanding-balance concept), add your 1-3 identifying fields,
   override `_get_duplicate_domain()`.
2. Add list/form views following any existing `pbms_*_plan_views.xml`
   file as a template, an `ir.actions.act_window`, a menu item, and an
   ACL row.
3. Add it to the `_REMINDER_MODELS` list in `pbms_planning_cycle.py`
   and the `models_to_check` list in `pbms_dashboard.py` if you want it
   on the dashboard/reminders.
4. If it needs to appear in bank-wide consolidation, add one more
   `UNION ALL` branch in `pbms_consolidation.py`.

## Tests

`tests/test_pbms_workflow.py` and `tests/test_pbms_computations.py`
cover: full workflow happy path, stage-skipping guard, return-requires-
reason, duplicate-submission guard, negative-target guard (and the
dormant-reduction exception), whole-number-for-account-counts guard,
FX SWIFT head-office-only guard, cycle-lock guard, manpower empty-lines
guard, quarterly/annual total computation, and cumulative/outstanding
running-total computation.

Run with:
```
odoo-bin -d your_test_db -i bunna_pbms --test-enable --stop-after-init
```

## Not yet implemented (straightforward follow-ups)

- Fixed asset / manpower items are not yet wired into the SQL
  consolidation view (they're itemized, not monthly-grid, so they'd
  need their own aggregation query rather than a UNION column match).
- No demo data / demo users.
- Excel *export* (only import) - the BRD's own BB-APF layouts weren't
  available as files to match column-for-column, so the import wizard
  assumes a simple Code | Name | Category | Jan..Dec column layout;
  adjust `_import_deposit_row` / `_import_expense_row` in
  `wizard/pbms_excel_import_wizard.py` to match the Bank's actual
  sheet layout before go-live.
