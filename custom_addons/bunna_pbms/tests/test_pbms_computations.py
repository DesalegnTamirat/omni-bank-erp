from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPbmsComputations(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env["operating.unit"].create({
            "name": "Merkato Branch", "sol_id": 9003, "work_unit_type": "branch",
        })
        cls.env.user.assigned_operating_unit_ids = [(4, cls.branch.id)]
        cls.branch_user = cls.env["res.users"].create({
            "name": "Branch Test User Comp",
            "login": "branch_test_user_comp",
            "assigned_operating_unit_ids": [(4, cls.branch.id)],
            "group_ids": [(6, 0, [cls.env.ref("bunna_pbms.group_pbms_branch_user").id, cls.env.ref("base.group_user").id])],
        })
        cls.cycle = cls.env["pbms.planning.cycle"].create({
            "name": "FY Test Comp 26/27",
            "date_start": "2026-07-01",
            "date_end": "2027-06-30",
            "state": "open",
        })
        cls.deposit_type = cls.env["pbms.deposit.type"].create({
            "name": "Demand", "code": "DEM-T",
        })

    def _deposit(self, **overrides):
        vals = {
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_type_id": self.deposit_type.id,
            "plan_category": "amount",
        }
        vals.update(overrides)
        return self.env["pbms.planning.category"].create(vals)

    def test_quarterly_and_annual_totals(self):
        plan = self._deposit(
            m01=100, m02=100, m03=100,   # Q1 = 300
            m04=200, m05=200, m06=200,   # Q2 = 600
            m07=50, m08=50, m09=50,      # Q3 = 150
            m10=10, m11=10, m12=10,      # Q4 = 30
        )
        self.assertEqual(plan.quarter1_total, 300)
        self.assertEqual(plan.quarter2_total, 600)
        self.assertEqual(plan.quarter3_total, 150)
        self.assertEqual(plan.quarter4_total, 30)
        self.assertEqual(plan.annual_total, 1080)

    def test_totals_recompute_on_change(self):
        plan = self._deposit(m01=100)
        self.assertEqual(plan.annual_total, 100)
        plan.m02 = 400
        self.assertEqual(plan.annual_total, 500)

    def test_cumulative_outstanding_running_total(self):
        plan = self._deposit(
            opening_balance=10000,
            m01=500, m02=500, m03=0, m04=0, m05=0, m06=0,
            m07=0, m08=0, m09=0, m10=0, m11=0, m12=1000,
        )
        self.assertEqual(plan.cumulative_m01, 10500)
        self.assertEqual(plan.cumulative_m02, 11000)
        self.assertEqual(plan.cumulative_m03, 11000)
        # outstanding_year_end = cumulative through May (11000) + June (1000)
        self.assertEqual(plan.outstanding_year_end, 12000)

    def test_protected_fields_blocked_after_endorsement(self):
        plan = self._deposit(m01=100)
        plan.action_submit()
        plan.action_district_endorse()
        with self.assertRaises(UserError):
            plan.with_user(self.branch_user).write({"m01": 999})

    def test_kanban_breakdown_html_manpower_draft_and_approved(self):
        pos_additional = self.env["pbms.position.type"].search([("code", "=", "additional")], limit=1)
        if not pos_additional:
            pos_additional = self.env["pbms.position.type"].create({
                "name": "Additional Position", "code": "additional", "is_new_position": False,
            })
        pos_new = self.env["pbms.position.type"].search([("code", "=", "new")], limit=1)
        if not pos_new:
            pos_new = self.env["pbms.position.type"].create({
                "name": "New Position", "code": "new", "is_new_position": True,
            })

        job = self.env["hr.job"].create({"name": "Branch Auditor Test"})
        grade = self.env["employee.grade"].create({
            "grade_code": "GR-IX",
            "grade_name": "Grade IX",
            "base_salary": 20000.0,
            "salary_factor": 1.5,
        })

        plan = self.env["pbms.planning.category"].create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "state": "draft",
            "manpower_line_ids": [
                (0, 0, {
                    "line_type": "manpower",
                    "position_type_id": pos_additional.id,
                    "job_id": job.id,
                    "job_grade_id": grade.id,
                    "base_salary": 20000.0,
                    "q1": 4,
                }),
                (0, 0, {
                    "line_type": "manpower",
                    "position_type_id": pos_new.id,
                    "new_job_title": "Digital Officer",
                    "new_job_grade_id": grade.id,
                    "base_salary": 20000.0,
                    "q1": 1,
                }),
            ],
        })

        # Draft state: should show "4 Requested" and "1 Requested"
        plan._compute_kanban_breakdown_html()
        plan._compute_plan_notification_details()
        self.assertEqual(plan.plan_category_title, "Workforce / Manpower Plan")
        self.assertTrue(plan.kanban_breakdown_html)
        self.assertIn("Additional Position", plan.kanban_breakdown_html)
        self.assertIn("4 Requested", plan.kanban_breakdown_html)
        self.assertIn("New Position", plan.kanban_breakdown_html)
        self.assertIn("1 Requested", plan.kanban_breakdown_html)

        # Approved state: should switch to "4 Approved" and "1 Approved"
        plan.state = "approved"
        plan._compute_kanban_breakdown_html()
        self.assertIn("4 Approved", plan.kanban_breakdown_html)
        self.assertIn("1 Approved", plan.kanban_breakdown_html)
        self.assertNotIn("4 Requested", plan.kanban_breakdown_html)

    def test_kanban_breakdown_html_deposit_breakdown(self):
        dep_savings = self.env["pbms.deposit.type"].create({"name": "Savings Deposit Test", "code": "SAV-KB"})
        dep_demand = self.env["pbms.deposit.type"].create({"name": "Demand Deposit Test", "code": "DEM-KB"})

        plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [
                (0, 0, {"line_type": "deposit", "deposit_type_id": dep_savings.id, "m01": 5000.0, "m02": 5000.0}),
                (0, 0, {"line_type": "deposit", "deposit_type_id": dep_demand.id, "m01": 3000.0, "m02": 3000.0}),
            ],
        })

        plan._compute_kanban_breakdown_html()
        plan._compute_plan_notification_details()
        self.assertEqual(plan.plan_category_title, "Deposit Mobilization Plan")
        self.assertTrue(plan.kanban_breakdown_html)
        self.assertIn("Savings Deposit Test", plan.kanban_breakdown_html)
        self.assertIn("10,000.00", plan.kanban_breakdown_html)
        self.assertIn("Demand Deposit Test", plan.kanban_breakdown_html)
        self.assertIn("6,000.00", plan.kanban_breakdown_html)

    def test_plan_category_title_inferred_from_lines_even_if_header_category_default(self):
        """If a plan has category='deposit' by default, but only contains manpower lines,
        the title MUST be 'Workforce / Manpower Plan' (not 'Deposit Mobilization Plan')."""
        plan = self.env["pbms.planning.category"].create({
            "category": "deposit",  # default header category
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Branch Teller",
                "new_job_grade": "Grade 14",
                "quantity": 2,
            })],
        })
        plan._compute_plan_notification_details()
        self.assertEqual(plan.plan_category_title, "Workforce / Manpower Plan")

    def test_get_formview_action_opens_correct_category_tab(self):
        """Clicking on a manpower card opens the form with category='manpower' context,
        and clicking deposit card opens with category='deposit' context."""
        mp_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "IT Specialist",
                "new_job_grade": "Grade 14",
                "quantity": 1,
            })],
        })
        action = mp_plan.action_open_plan_form()
        self.assertEqual(action["context"].get("default_category"), "manpower")
        self.assertEqual(mp_plan.category, "manpower")

        dep_plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 1000.0,
            })],
        })
        dep_action = dep_plan.action_open_plan_form()
        self.assertEqual(dep_action["context"].get("default_category"), "deposit")
        self.assertEqual(dep_plan.category, "deposit")

    def test_manpower_line_type_not_overwritten_by_compute_line_type(self):
        """Ensure that creating a manpower plan does not accidentally overwrite
        line_type to 'deposit' and trigger 'Deposit Type is required' ValidationError."""
        plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Loan Officer",
                "new_job_grade": "Grade 14",
                "quantity": 1,
            })],
        })
        # Trigger recomputations
        plan.line_ids._compute_line_type()
        plan._compute_category()
        self.assertEqual(plan.line_ids[0].line_type, "manpower")
        self.assertEqual(plan.category, "manpower")

    def test_deleted_or_rejected_position_can_be_re_requested(self):
        """Ensure that if a position line was deleted or belongs to a rejected plan,
        a new request for the same position title is allowed without validation errors."""
        # 1. Create a plan with a new position, then delete the line and add a replacement
        plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Chief Technical Officer",
                "new_job_grade": "Grade 15",
                "quantity": 1,
            })],
        })
        line_id = plan.manpower_line_ids[0].id
        # Delete old line and add new one
        plan.write({
            "manpower_line_ids": [
                (2, line_id),
                (0, 0, {
                    "line_type": "manpower",
                    "position_type": "new",
                    "new_job_title": "Chief Technical Officer",
                    "new_job_grade": "Grade 15",
                    "quantity": 2,
                }),
            ],
        })
        self.assertEqual(len(plan.manpower_line_ids), 1)
        self.assertEqual(plan.manpower_line_ids[0].quantity, 2)

    def test_auto_split_mixed_lines_into_separate_cards(self):
        """Ensure that if a plan has mixed deposit and manpower lines, _split_mixed_lines
        splits them into independent single-category plans so each has its own card."""
        plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 5000.0,
            })],
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Database Admin",
                "new_job_grade": "Grade 14",
                "base_salary": 25000.0,
                "quantity": 1,
                "q1": 1,
            })],
        })
        # Execute split
        plan._split_mixed_lines()

        # The original plan should now contain only deposit lines
        self.assertEqual(plan.category, "deposit")
        self.assertEqual(len(plan.deposit_line_ids), 1)
        self.assertEqual(len(plan.manpower_line_ids), 0)

        # A new manpower plan should exist for the same branch and cycle
        mp_plan = self.env["pbms.planning.category"].search([
            ("org_unit_id", "=", self.branch.id),
            ("cycle_id", "=", self.cycle.id),
            ("category", "=", "manpower"),
        ])
        self.assertTrue(mp_plan)
        self.assertEqual(len(mp_plan.manpower_line_ids), 1)
        self.assertEqual(mp_plan.manpower_line_ids[0].new_job_title, "Database Admin")

    def test_same_job_allowed_under_different_position_types(self):
        """Ensure that the same Job Position can be requested under different Position Types
        (e.g., 'Additional Position' and 'New Position') in the same manpower plan."""
        pt_additional = self.env["pbms.position.type"].create({"name": "Additional Position", "code": "additional"})
        pt_new = self.env["pbms.position.type"].create({"name": "New Position", "code": "new", "is_new_position": True})
        job = self.env["hr.job"].create({"name": "Chief Technical Officer"})
        grade = self.env["employee.grade"].create({"grade_name": "Grade 16", "salary_factor": 1.5, "base_salary": 20000.0})

        plan = self.env["pbms.planning.category"].create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "manpower_line_ids": [
                (0, 0, {
                    "line_type": "manpower",
                    "position_type_id": pt_additional.id,
                    "position_type": "additional",
                    "job_id": job.id,
                    "job_grade_id": grade.id,
                    "base_salary": 30000.0,
                    "quantity": 1,
                    "q1": 1,
                }),
                (0, 0, {
                    "line_type": "manpower",
                    "position_type_id": pt_new.id,
                    "position_type": "new",
                    "new_job_title": "Chief Technical Officer",
                    "new_job_grade": "Grade 16",
                    "job_id": job.id,
                    "job_grade_id": grade.id,
                    "base_salary": 30000.0,
                    "quantity": 1,
                    "q1": 1,
                }),
            ],
        })
        self.assertEqual(len(plan.manpower_line_ids), 2)

    def test_submitting_mixed_request_splits_both_into_submitted_plans(self):
        """When a branch user plans both Deposit and Manpower in a single workspace and submits,
        both categories become independent submitted plans appearing as separate cards."""
        justification_cat = self.env["pbms.justification.category"].create({
            "name": "Workload Increase",
            "requires_remarks": False,
        })
        plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 2000.0,
            })],
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Risk Analyst",
                "new_job_grade": "Grade 13",
                "justification_category_id": justification_cat.id,
                "quantity": 1,
                "q1": 1,
            })],
        })

        # Submit plan
        plan.action_submit()

        # Both the deposit plan and the manpower plan must exist in submitted state
        dep_plan = self.env["pbms.planning.category"].search([
            ("org_unit_id", "=", self.branch.id),
            ("cycle_id", "=", self.cycle.id),
            ("category", "=", "deposit"),
        ])
        mp_plan = self.env["pbms.planning.category"].search([
            ("org_unit_id", "=", self.branch.id),
            ("cycle_id", "=", self.cycle.id),
            ("category", "=", "manpower"),
        ])

        self.assertTrue(dep_plan)
        self.assertEqual(dep_plan.state, "submitted")
        self.assertTrue(mp_plan)
        self.assertEqual(mp_plan.state, "submitted")
        self.assertEqual(len(dep_plan.deposit_line_ids), 1)
        self.assertEqual(len(mp_plan.manpower_line_ids), 1)

    def test_lines_never_disappear_on_save_in_planning_request(self):
        """Ensure that when a user adds both deposit and manpower lines in a single planning request
        and saves (write), the lines in both tabs remain intact on the record and never disappear."""
        plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 10000.0,
            })],
        })

        # User adds a manpower line to the request form and saves
        plan.write({
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Senior Accountant",
                "new_job_grade": "Grade 14",
                "base_salary": 20000.0,
                "quantity": 1,
                "q1": 1,
            })],
        })

        # Verify that both tabs retain their lines on the primary plan record
        self.assertEqual(len(plan.deposit_line_ids), 1)
        self.assertEqual(len(plan._get_category_lines("manpower")), 1)
        self.assertEqual(plan._get_category_lines("manpower")[0].new_job_title, "Senior Accountant")

        # In planning request view, read() returns both tabs intact
        read_vals = plan.with_context(is_planning_request=True).read(["deposit_line_ids", "manpower_line_ids"])[0]
        self.assertEqual(len(read_vals["deposit_line_ids"]), 1)
        self.assertEqual(len(read_vals["manpower_line_ids"]), 1)

        # Verify that the companion manpower plan record also exists and is synced
        mp_plan = self.env["pbms.planning.category"].search([
            ("org_unit_id", "=", self.branch.id),
            ("cycle_id", "=", self.cycle.id),
            ("category", "=", "manpower"),
        ])
        self.assertTrue(mp_plan)
        self.assertEqual(len(mp_plan.manpower_line_ids), 1)
        self.assertEqual(mp_plan.manpower_line_ids[0].new_job_title, "Senior Accountant")

    def test_submitting_any_category_submits_all_categories_together(self):
        """Clicking submit on any plan record submits all active category plans for that unit and cycle at once."""
        justification_cat = self.env["pbms.justification.category"].create({
            "name": "Branch Expansion",
            "requires_remarks": False,
        })
        dep_plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 5000.0,
            })],
        })
        mp_plan = self.env["pbms.planning.category"].create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Branch Auditor",
                "new_job_grade": "Grade 13",
                "justification_category_id": justification_cat.id,
                "quantity": 1,
                "q1": 1,
            })],
        })

        # Submit from the deposit plan
        dep_plan.action_submit()

        # Both the deposit plan and manpower plan must be submitted
        self.assertEqual(dep_plan.state, "submitted")
        self.assertEqual(mp_plan.state, "submitted")

    def test_submitting_skips_empty_unpopulated_category_records(self):
        """If an empty draft category plan exists (e.g. Customer Base with 0 lines),
        submitting other populated plans does not crash with 'no requirement lines'."""
        empty_cb_plan = self.env["pbms.planning.category"].create({
            "category": "customer_base",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
        })
        dep_plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 2500.0,
            })],
        })

        # Submit populated plan
        dep_plan.action_submit()
        self.assertEqual(dep_plan.state, "submitted")
        self.assertTrue(not empty_cb_plan.exists() or empty_cb_plan.state == "draft")

    def test_all_seven_planning_categories_submit_successfully(self):
        """Ensure that every one of the 7 planning categories (Deposit, Customer Base, FX, Digital Banking,
        General Expense, Manpower, Fixed Asset) submits without any validation errors."""
        fx_source = self.env["pbms.fx.source.type"].create({"name": "Export", "code": "EXP"})
        channel = self.env["pbms.digital.channel"].create({"name": "Mobile Banking", "code": "MB", "unit_of_measure": "count"})
        account = self.env["pbms.expense.account"].create({
            "name": "Office Supplies",
            "code": "601199",
        })
        asset_cat = self.env["pbms.fixed.asset.category"].create({"name": "IT Equipment", "code": "IT"})
        justification_cat = self.env["pbms.justification.category"].create({
            "name": "Operational Need",
            "requires_remarks": False,
        })

        plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 1000.0,
            })],
            "customer_base_line_ids": [(0, 0, {
                "line_type": "customer_base",
                "deposit_type_id": self.deposit_type.id,
                "base_type": "new_acquisition",
                "m01": 50.0,
            })],
            "fx_line_ids": [(0, 0, {
                "line_type": "fx",
                "fx_source_type": fx_source.id,
                "m01": 500.0,
            })],
            "digital_banking_line_ids": [(0, 0, {
                "line_type": "digital_banking",
                "channel_id": channel.id,
                "m01": 20.0,
            })],
            "expense_line_ids": [(0, 0, {
                "line_type": "general_expense",
                "expense_account_id": account.id,
                "m01": 3000.0,
            })],
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Database Engineer",
                "new_job_grade": "Grade 14",
                "justification_category_id": justification_cat.id,
                "quantity": 1,
                "q1": 1,
            })],
            "fixed_asset_line_ids": [(0, 0, {
                "line_type": "fixed_asset",
                "category_id": asset_cat.id,
                "item_description": "Dell Workstation",
                "estimated_unit_price": 45000.0,
                "fa_q1": 1,
            })],
        })

        # Submit plan containing all categories
        plan.action_submit()

        self.assertEqual(plan.state, "submitted")

        # Verify companion plans exist, are submitted, and have non-zero totals
        all_submitted_plans = self.env["pbms.planning.category"].search([
            ("org_unit_id", "=", self.branch.id),
            ("cycle_id", "=", self.cycle.id),
        ])
        for p in all_submitted_plans:
            self.assertEqual(p.state, "submitted", f"Plan category='{p.category}' (id={p.id}) is in state='{p.state}', lines={len(p.line_ids)}, annual_total={p.annual_total}")
            self.assertTrue(p.annual_total > 0.0 or len(p.line_ids) > 0)

    def test_lines_never_disappear_and_submit_all_categories_to_district(self):
        """Verify that multiple category lines never disappear after save in the planning form,
        and all category cards submit with full non-zero records to district review."""
        justification_cat = self.env["pbms.justification.category"].create({
            "name": "Branch Growth",
            "requires_remarks": False,
        })
        plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 15300.0,
            })],
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Branch Operations Manager",
                "new_job_grade": "Grade 15",
                "justification_category_id": justification_cat.id,
                "quantity": 2,
                "q1": 2,
                "base_salary": 30000.0,
            })],
        })

        # Verify lines are present on plan after initial creation
        self.assertEqual(len(plan.deposit_line_ids), 1)
        self.assertEqual(len(plan._get_category_lines("manpower")), 1)

        # Trigger write/save on the plan
        plan.write({"business_justification": "Branch expansion strategy for FY2026/27."})

        # Verify lines DID NOT disappear after save
        self.assertEqual(len(plan.deposit_line_ids), 1)
        self.assertEqual(len(plan._get_category_lines("manpower")), 1)
        self.assertEqual(plan._get_category_lines("manpower")[0].new_job_title, "Branch Operations Manager")

        # Submit plan
        plan.action_submit()

        # Both the deposit plan and companion manpower plan must be submitted with non-zero totals
        all_branch_plans = self.env["pbms.planning.category"].search([
            ("org_unit_id", "=", self.branch.id),
            ("cycle_id", "=", self.cycle.id),
        ])
        for p in all_branch_plans:
            self.assertEqual(p.state, "submitted")
            self.assertTrue(p.annual_total > 0.0)

    def test_duplicate_planning_is_strictly_prevented(self):
        """Verify that an operating unit cannot create duplicate plans for the same category and cycle."""
        # Create first deposit plan
        self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 5000.0,
            })],
        })

        # Attempt to create duplicate deposit plan for the same branch and cycle
        with self.assertRaises(ValidationError):
            self.env["pbms.planning.category"].create({
                "category": "deposit",
                "cycle_id": self.cycle.id,
                "org_unit_id": self.branch.id,
                "deposit_line_ids": [(0, 0, {
                    "line_type": "deposit",
                    "deposit_type_id": self.deposit_type.id,
                    "m01": 2000.0,
                })],
            })

    def test_submitted_plan_blocks_second_plan_creation(self):
        """Verify that an operating unit cannot create a second plan once its plan is submitted."""
        plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 5000.0,
            })],
        })
        plan.action_submit()
        self.assertEqual(plan.state, "submitted")

        # Attempt to create another plan for the same branch and fiscal year
        with self.assertRaises(ValidationError) as cm:
            self.env["pbms.planning.category"].create({
                "category": "general_expense",
                "cycle_id": self.cycle.id,
                "org_unit_id": self.branch.id,
            })
        self.assertIn("already been submitted", str(cm.exception))

    def test_branch_can_reset_submitted_plan_to_draft_to_continue_editing(self):
        """Verify that a branch can reset its submitted plan back to draft to pause, edit, and resume planning."""
        plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 8000.0,
            })],
        })

        # Submit plan
        plan.action_submit()
        self.assertEqual(plan.state, "submitted")

        # Reset plan to draft to continue editing
        plan.action_reset_to_draft()
        self.assertEqual(plan.state, "draft")

        # Can now edit again in draft
        plan.write({"business_justification": "Updated draft notes."})
        self.assertEqual(plan.business_justification, "Updated draft notes.")

    def test_planning_request_view_and_category_card_navigation(self):
        """Verify that opening planning request opens the multi-tab form with submitted status,
        and opening from a category card opens the isolated category form."""
        plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 12000.0,
            })],
        })

        # Submit plan
        plan.action_submit()
        self.assertEqual(plan.state, "submitted")

        # 1. Opening via Planning Request menu
        req_action = self.env["pbms.planning.category"].with_user(self.branch_user).action_open_planning_request()
        self.assertEqual(req_action["res_model"], "pbms.planning.category")
        self.assertTrue(req_action.get("res_id"))

        # 2. Opening via Planning Category card
        card_action = plan.with_user(self.branch_user).get_formview_action()
        self.assertEqual(card_action["res_model"], "pbms.planning.category")
        self.assertEqual(card_action["res_id"], plan.id)
        self.assertEqual(card_action["context"].get("default_category"), "deposit")

    def test_category_card_displays_its_own_lines_and_totals_when_opened(self):
        """Verify that when lines are entered across multiple categories, each category card owns and displays its lines."""
        # Create a unified planning request with both Deposit and Customer Base lines
        req = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 15000.0,
            })],
            "customer_base_line_ids": [(0, 0, {
                "line_type": "customer_base",
                "deposit_type_id": self.deposit_type.id,
                "base_type": "new_acquisition",
                "m01": 10.0,
            })],
        })

        # Verify plan retains both deposit and customer base lines
        self.assertEqual(len(req.deposit_line_ids), 1)
        self.assertEqual(len(req._get_category_lines("customer_base")), 1)
        self.assertEqual(req.deposit_annual_total, 15000.0)
        self.assertEqual(req.customer_base_annual_total, 10.0)

        # Verify dedicated customer base card exists and owns customer base lines
        cb_plan = self.env["pbms.planning.category"].search([
            ("org_unit_id", "=", self.branch.id),
            ("cycle_id", "=", self.cycle.id),
            ("category", "=", "customer_base"),
        ])
        self.assertTrue(cb_plan)
        self.assertEqual(len(cb_plan.customer_base_line_ids), 1)

    def test_manpower_headcount_and_quarterly_cost_rollup_non_zero(self):
        """Verify that Headcount & Cost Overview and Quarterly Cost Rollup compute accurately non-zero."""
        pos_type = self.env["pbms.position.type"].search([("code", "=", "new")], limit=1)
        grade = self.env["employee.grade"].create({
            "grade_code": "GR-SO",
            "grade_name": "Senior Officer Grade",
            "base_salary": 25000.0,
            "salary_factor": 1.5,
        })
        plan = self.env["pbms.planning.category"].create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type_id": pos_type.id,
                "new_job_title": "Senior Core Banking Specialist",
                "new_job_grade_id": grade.id,
                "q1": 2,
                "q2": 1,
                "q3": 0,
                "q4": 0,
            })],
        })

        # Verify manpower overview fields compute non-zero
        self.assertEqual(plan.manpower_line_count, 1)
        self.assertTrue(plan.new_planned_salary_budget > 0.0)
        self.assertTrue(plan.total_operating_unit_manpower_budget > 0.0)
        self.assertTrue(plan.q1_total_cost > 0.0)
        self.assertTrue(plan.q2_total_cost > 0.0)

    def test_consolidate_district_overview_with_mobilization_plans(self):
        """Verify that District Overview consolidates branch mobilization plans without ValidationError."""
        district = self.env["operating.unit"].create({
            "name": "Central District Office",
            "work_unit_type": "district_office",
            "sol_id": 9010,
        })
        branch = self.env["operating.unit"].create({
            "name": "Stadium Branch",
            "work_unit_type": "branch",
            "parent_unit": district.id,
            "sol_id": 9011,
        })
        branch_plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 15000.0,
            })],
        })

        # Submit branch plan
        branch_plan.action_submit()
        branch_plan.action_district_approve()

        # Consolidate District Overview
        res = branch_plan.action_consolidate_district_overview()
        self.assertEqual(res.get("params", {}).get("type"), "success")

        # Verify District Overview record has consolidated deposit line
        dist_plan = self.env["pbms.planning.category"].search([
            ("cycle_id", "=", self.cycle.id),
            ("org_unit_id", "=", district.id),
            ("category", "=", "deposit"),
            ("active", "=", True),
        ], limit=1)
        self.assertTrue(dist_plan)
        self.assertTrue(len(dist_plan.deposit_line_ids) > 0 or dist_plan.annual_total > 0)



















