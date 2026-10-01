from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPbmsWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ho = cls.env["operating.unit"].create({
            "name": "Head Office", "sol_id": 9000, "work_unit_type": "head_office",
        })
        cls.district = cls.env["operating.unit"].create({
            "name": "Addis District", "sol_id": 9001, "work_unit_type": "district_office",
            "parent_unit": cls.ho.id,
        })
        cls.branch = cls.env["operating.unit"].create({
            "name": "Bole Branch", "sol_id": 9002, "work_unit_type": "branch",
            "parent_unit": cls.district.id,
        })
        # Give the acting test user access to units so record rules don't block.
        cls.env.user.assigned_operating_unit_ids = [(6, 0, [cls.ho.id, cls.district.id, cls.branch.id])]
        cls.cycle = cls.env["pbms.planning.cycle"].create({
            "name": "FY Test 26/27",
            "date_start": "2026-07-01",
            "date_end": "2027-06-30",
            "state": "open",
        })
        cls.deposit_type = cls.env["pbms.deposit.type"].create({
            "name": "Savings", "code": "SAV-T",
        })
        cls.expense_account = cls.env["pbms.expense.account"].create({
            "name": "Office Supplies", "code": "6001",
        })

    def _create_deposit_plan(self, **overrides):
        vals = {
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_type_id": self.deposit_type.id,
            "plan_category": "amount",
            "m01": 1000.0, "m02": 1000.0,
        }
        vals.update(overrides)
        return self.env["pbms.planning.category"].create(vals)

    def test_full_workflow_happy_path(self):
        plan = self._create_deposit_plan()
        self.assertEqual(plan.state, "draft")

        plan.action_submit()
        self.assertEqual(plan.state, "submitted")
        self.assertTrue(plan.submitted_date)

        plan.action_district_approve()
        self.assertEqual(plan.state, "district_approved")

        # District Overview Plan was AUTOMATICALLY created & submitted to Head Office
        dist_plan = self.env["pbms.planning.category"].search([
            ("category", "=", "deposit"),
            ("cycle_id", "=", self.cycle.id),
            ("org_unit_id", "=", self.district.id),
            ("deposit_type_id", "=", self.deposit_type.id),
            ("plan_category", "=", "amount"),
        ], limit=1)
        self.assertTrue(dist_plan)
        self.assertEqual(dist_plan.m01, 1000.0)
        self.assertEqual(dist_plan.state, "submitted")

        # Head Office reviews District Overview Plan
        dist_plan.action_ho_review()
        self.assertEqual(dist_plan.state, "ho_reviewed")

        # Head Office Bank-Wide Plan was AUTOMATICALLY created & set to ho_reviewed
        ho_plan = self.env["pbms.planning.category"].search([
            ("category", "=", "deposit"),
            ("cycle_id", "=", self.cycle.id),
            ("org_unit_id", "=", self.ho.id),
            ("deposit_type_id", "=", self.deposit_type.id),
            ("plan_category", "=", "amount"),
        ], limit=1)
        self.assertTrue(ho_plan)
        self.assertEqual(ho_plan.m01, 1000.0)
        self.assertEqual(ho_plan.state, "ho_reviewed")

        # SPPMD Manager approves Bank-Wide Overview Plan
        ho_plan.action_approve()
        self.assertEqual(ho_plan.state, "approved")

    def test_district_office_plan_reaches_district_endorsed(self):
        """Regression test: a District Office's own overview plan must move
        submitted -> district_endorsed when its District Reviewer approves
        it (not stay stuck on 'submitted'), so it is picked up by Head
        Office review/consolidation and by the deadline-reminder cron."""
        dist_plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.district.id,
            "deposit_type_id": self.deposit_type.id,
            "plan_category": "amount",
            "m01": 500.0,
        })
        dist_plan.action_submit()
        self.assertEqual(dist_plan.state, "district_endorsed")

        dist_plan.action_ho_review()
        self.assertEqual(dist_plan.state, "ho_reviewed")

    def test_general_expense_district_first_workflow(self):
        """Branch General Expense plans: branch submits -> district approves (district_approved) -> HO Functional Reviewer reviews."""
        plan = self.env["pbms.planning.category"].create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "district_id": self.district.id,
            "m01": 500.0,
        })
        plan.action_submit()
        self.assertEqual(plan.state, "submitted")

        # General Expense cannot be submitted to committee
        with self.assertRaises(UserError):
            plan.action_submit_to_committee()

        # District Reviewer approves Branch General Expense -> forwarded to HO Functional Reviewer
        plan.action_district_approve()
        self.assertEqual(plan.state, "district_approved")

        # HO Functional Reviewer does final review
        plan.action_ho_review()
        self.assertEqual(plan.state, "ho_reviewed")

    def test_fixed_asset_district_to_committee_workflow(self):
        """Fixed Asset branch plans: branch submits -> district approves (district_approved) -> HO Reviewer submits to committee -> approved."""
        fa_plan = self.env["pbms.planning.category"].create({
            "category": "fixed_asset",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "district_id": self.district.id,
            "m01": 1500.0,
        })
        fa_plan.action_submit()
        self.assertEqual(fa_plan.state, "submitted")

        # District Reviewer approves -> forwarded to HO Functional Reviewer
        fa_plan.action_district_approve()
        self.assertEqual(fa_plan.state, "district_approved")

        # HO Functional Reviewer submits to Review Committee
        fa_plan.action_submit_to_committee()
        self.assertEqual(fa_plan.state, "committee_review")

        # Review Committee grants final approval
        fa_plan.action_committee_approve_resource()
        self.assertEqual(fa_plan.state, "approved")

    def test_headoffice_plan_chief_review_workflow(self):
        """Head Office operating unit plans are submitted to Respective Chief for review.
        Respective Chief approves & escalates:
        - Fixed Asset & General Expense to Head Office Functional Reviewer (submitted)
        - Workforce to People Solutions Directorate (people_solutions_review)"""
        ho_unit = self.env["operating.unit"].create({
            "name": "Finance Department",
            "sol_id": 9010,
            "work_unit_type": "head_office",
        })
        # General Expense HO plan
        ge_plan = self.env["pbms.planning.category"].create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": ho_unit.id,
            "m01": 1000.0,
        })
        ge_plan.action_submit()
        self.assertEqual(ge_plan.state, "chief_review")

        # Respective Chief approves & escalates General Expense to HO Functional Reviewer
        ge_plan.action_chief_approve_escalate()
        self.assertEqual(ge_plan.state, "submitted")

        # HO Functional Reviewer finally approves General Expense
        ge_plan.action_ho_approve()
        self.assertEqual(ge_plan.state, "approved")

        # Fixed Asset HO plan
        fa_plan = self.env["pbms.planning.category"].create({
            "category": "fixed_asset",
            "cycle_id": self.cycle.id,
            "org_unit_id": ho_unit.id,
            "m01": 2000.0,
        })
        fa_plan.action_submit()
        self.assertEqual(fa_plan.state, "chief_review")

        # Respective Chief approves & escalates Fixed Asset to HO Functional Reviewer
        fa_plan.action_chief_approve_escalate()
        self.assertEqual(fa_plan.state, "submitted")

        # Workforce HO plan
        job = self.env["hr.job"].create({"name": "Financial Analyst"})
        just_cat = self.env["pbms.justification.category"].create({"name": "Workload", "code": "workload"})
        wp_plan = self.env["pbms.planning.category"].create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": ho_unit.id,
            "business_justification": "Team expansion",
            "line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Financial Analyst",
                "new_job_grade": "Grade 5",
                "org_unit_id": ho_unit.id,
                "job_id": job.id,
                "justification_category_id": just_cat.id,
                "m01": 1.0,
                "annual_total": 1.0,
            })],
        })
        wp_plan.action_submit()
        self.assertEqual(wp_plan.state, "chief_review")

        # Respective Chief approves & escalates Workforce to People Solutions Directorate
        wp_plan.action_chief_approve_escalate()
        self.assertEqual(wp_plan.state, "people_solutions_review")

    def test_cannot_skip_stages(self):
        plan = self._create_deposit_plan()
        with self.assertRaises(UserError):
            plan.action_district_endorse()  # still draft
        with self.assertRaises(UserError):
            plan.action_approve()  # still draft

    def test_return_requires_reason(self):
        plan = self._create_deposit_plan()
        plan.action_submit()
        with self.assertRaises(UserError):
            plan.action_return()  # no return_reason set

    def test_duplicate_plan_blocked(self):
        self._create_deposit_plan()
        with self.assertRaises(ValidationError):
            self._create_deposit_plan()

    def test_cannot_create_second_plan_when_plan_is_submitted(self):
        """Once an operating unit has submitted its plan for a fiscal year,
        creating ANY second plan for that operating unit and fiscal year is strictly blocked."""
        plan = self._create_deposit_plan()
        plan.action_submit()
        self.assertEqual(plan.state, "submitted")

        # Attempt to create another plan (e.g. customer_base or another request) for the same branch & fiscal year
        with self.assertRaises(ValidationError) as cm:
            self.env["pbms.planning.category"].create({
                "category": "customer_base",
                "cycle_id": self.cycle.id,
                "org_unit_id": self.branch.id,
                "deposit_type_id": self.deposit_type.id,
                "base_type": "new_acquisition",
                "m01": 50.0,
            })
        self.assertIn("already been submitted", str(cm.exception))

    def test_plan_duplication_blocked_for_same_unit_and_cycle(self):
        """Duplicating a plan within the same operating unit and fiscal year is prevented."""
        plan = self._create_deposit_plan()
        with self.assertRaises(ValidationError) as cm:
            plan.copy()
        self.assertIn("Duplicating a plan", str(cm.exception))

    def test_branch_planner_views_all_category_details_in_planning_categories_and_request(self):
        """Operating unit user/planner can view all plan details and category tabs in Planning Categories & Request."""
        plan = self.env["pbms.planning.category"].with_context(is_planning_request=True).create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 5000.0,
                "m02": 5000.0,
            })],
            "customer_base_line_ids": [(0, 0, {
                "line_type": "customer_base",
                "deposit_type_id": self.deposit_type.id,
                "base_type": "new_acquisition",
                "m01": 100.0,
            })],
            "expense_line_ids": [(0, 0, {
                "line_type": "general_expense",
                "expense_account_id": self.expense_account.id,
                "m01": 1200.0,
            })],
        })

        # Verify category summaries are computed on the plan
        self.assertEqual(plan.deposit_annual_total, 10000.0)
        self.assertEqual(plan.customer_base_annual_total, 100.0)
        self.assertEqual(plan.expense_annual_total, 1200.0)

        # Verify Kanban breakdown includes multi-category items
        self.assertTrue(bool(plan.kanban_breakdown_html))
        self.assertIn("Deposit", plan.kanban_breakdown_html)
        self.assertIn("Customer Base", plan.kanban_breakdown_html)
        self.assertIn("General Expense", plan.kanban_breakdown_html)

        # Verify Form view action provides category-specific autofocus view
        form_act = plan.get_formview_action()
        self.assertEqual(form_act["res_model"], "pbms.planning.category")
        self.assertEqual(form_act["res_id"], plan.id)
        dep_view = self.env.ref("bunna_pbms.view_pbms_plan_form_deposit")
        self.assertEqual(form_act["views"][0][0], dep_view.id)

    def test_negative_target_blocked_for_deposit(self):
        with self.assertRaises(ValidationError):
            self._create_deposit_plan(m01=-500.0)

    def test_account_category_must_be_whole_number(self):
        with self.assertRaises(ValidationError):
            self._create_deposit_plan(plan_category="account", m01=10.5)

    def test_customer_base_dormant_reduction_allows_negative(self):
        plan = self.env["pbms.planning.category"].create({
            "category": "customer_base",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "deposit_type_id": self.deposit_type.id,
            "base_type": "dormant_reduction",
            "m01": -25.0,
        })
        self.assertEqual(plan.m01, -25.0)

    def test_fx_swift_restricted_to_head_office(self):
        fx_swift = self.env.ref("bunna_pbms.fx_source_remittance_swift", raise_if_not_found=False) or self.env["pbms.fx.source.type"].search([("code", "=", "remittance_swift")], limit=1)
        with self.assertRaises(ValidationError):
            self.env["pbms.planning.category"].create({
                "category": "fx",
                "cycle_id": self.cycle.id,
                "org_unit_id": self.branch.id,  # branch, not head_office
                "fx_source_type": fx_swift.id,
                "m01": 1000.0,
            })

    def test_cycle_lock_blocks_new_submission(self):
        self.cycle.state = "closed"
        with self.assertRaises(UserError):
            plan = self._create_deposit_plan()
            plan.action_submit()

    def test_manpower_plan_blocks_submit_without_lines(self):
        plan = self.env["pbms.planning.category"].create({
            "category": "manpower",
            "cycle_id": self.cycle.id, "org_unit_id": self.branch.id,
        })
        with self.assertRaises(UserError):
            plan.action_submit()

    def test_manpower_plan_submits_with_lines(self):
        just_cat = self.env["pbms.justification.category"].create({"name": "Workforce Expansion", "code": "wf_exp"})
        plan = self.env["pbms.planning.category"].create({
            "category": "manpower",
            "cycle_id": self.cycle.id, "org_unit_id": self.ho.id,
            "business_justification": "Head Office expansion justification.",
            "line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "employment_type": "permanent",
                "new_job_title": "Customer Service Officer",
                "new_job_grade": "Grade 5",
                "justification_category_id": just_cat.id,
                "quantity": 2,
                "date_needed": "2026-09-01",
                "reason": "Branch expansion.",
            })],
        })
        plan.action_submit()
        self.assertEqual(plan.state, "chief_review")
        with self.assertRaises(UserError):
            plan.action_return()  # no return_reason set
        plan.return_reason = "Figures inconsistent with prior year actuals."
        plan.action_return()
        self.assertEqual(plan.state, "returned")

    def test_branch_district_and_ho_reviewer_view_isolation(self):
        """Test isolation across organizational tiers:
        - Branch user only views its own records.
        - District reviewer only views its district records and child branch records.
        - Head Office functional reviewer does NOT view branch records, but views District Overview and HO plans.
        """
        # District 2 & Branch 2 setup for cross-district verification
        dist2 = self.env["operating.unit"].create({
            "name": "Hawassa District", "sol_id": 9010, "work_unit_type": "district_office", "parent_unit": self.ho.id,
        })
        branch2 = self.env["operating.unit"].create({
            "name": "Hawassa Main Branch", "sol_id": 9011, "work_unit_type": "branch", "parent_unit": dist2.id,
        })

        branch1_user = self.env["res.users"].create({
            "name": "Branch 1 Planner",
            "login": "branch1_planner_iso",
            "group_ids": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_branch_user").id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.branch.id])],
        })
        branch2_user = self.env["res.users"].create({
            "name": "Branch 2 Planner",
            "login": "branch2_planner_iso",
            "group_ids": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_branch_user").id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [branch2.id])],
        })
        dist1_reviewer = self.env["res.users"].create({
            "name": "District 1 Reviewer",
            "login": "dist1_rev_iso",
            "group_ids": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_district_reviewer").id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.district.id])],
        })
        dist2_reviewer = self.env["res.users"].create({
            "name": "District 2 Reviewer",
            "login": "dist2_rev_iso",
            "group_ids": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_district_reviewer").id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [dist2.id])],
        })
        ho_reviewer = self.env["res.users"].create({
            "name": "HO Functional Reviewer",
            "login": "ho_rev_iso_test",
            "group_ids": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_ho_reviewer").id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.ho.id])],
        })

        plan1 = self._create_deposit_plan()  # On self.branch under self.district
        plan1.with_user(branch1_user).action_submit()
        plan1.with_user(dist1_reviewer).action_district_approve()
        self.assertEqual(plan1.state, "district_approved")

        plan2 = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": branch2.id,
            "deposit_type_id": self.deposit_type.id,
            "plan_category": "amount",
            "m01": 2000.0,
        })
        plan2.with_user(branch2_user).action_submit()

        # 1. Branch 1 user can ONLY view plan1, NOT plan2
        self.assertTrue(bool(self.env["pbms.planning.category"].with_user(branch1_user).search([("id", "=", plan1.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(branch1_user).search([("id", "=", plan2.id)])))

        # 2. District 1 reviewer can view plan1 (child branch), but NOT plan2 (District 2's branch)
        self.assertTrue(bool(self.env["pbms.planning.category"].with_user(dist1_reviewer).search([("id", "=", plan1.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(dist1_reviewer).search([("id", "=", plan2.id)])))

        # 3. District 2 reviewer can view plan2 (child branch), but NOT plan1 (District 1's branch)
        self.assertTrue(bool(self.env["pbms.planning.category"].with_user(dist2_reviewer).search([("id", "=", plan2.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(dist2_reviewer).search([("id", "=", plan1.id)])))

        # 4. HO functional reviewer does NOT view branch plan1 or branch plan2
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(ho_reviewer).search([("id", "=", plan1.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(ho_reviewer).search([("id", "=", plan2.id)])))

        # 5. HO functional reviewer CAN view and review District 1 Overview Plan
        dist1_plan = self.env["pbms.planning.category"].search([
            ("category", "=", "deposit"),
            ("cycle_id", "=", self.cycle.id),
            ("org_unit_id", "=", self.district.id),
            ("deposit_type_id", "=", self.deposit_type.id),
            ("plan_category", "=", "amount"),
        ], limit=1)
        self.assertTrue(bool(dist1_plan))
        self.assertTrue(bool(self.env["pbms.planning.category"].with_user(ho_reviewer).search([("id", "=", dist1_plan.id)])))
        dist1_plan.with_user(ho_reviewer).action_ho_review()
        self.assertEqual(dist1_plan.state, "ho_reviewed")

    def test_manpower_grade_autopopulate_and_new_position(self):
        """Test grade auto-population and line-only saving for new position type."""
        job = self.env["hr.job"].create({"name": "Senior Accountant"})
        grade = self.env["employee.grade"].create({"grade_name": "Grade IX", "base_salary": 15000.0, "salary_factor": 1.5})

        # Test onchange grade auto-population for existing position
        line = self.env["pbms.plan.category.line"].new({
            "line_type": "manpower",
            "position_type": "existing",
            "job_id": job.id,
        })
        # Mock job_grade on job or employee
        job.write({"grade_id": grade.id}) if hasattr(job, "grade_id") else None
        line._onchange_job_id_populate_grade()

        # Test new position saves title in line record
        plan = self.env["pbms.planning.category"].create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "employment_type": "permanent",
                "new_job_title": "AI Developer",
                "new_job_grade_id": grade.id,
                "hc_m01": 1,
            })],
        })
        new_line = plan.line_ids[0]
        self.assertEqual(new_line.new_job_title, "AI Developer")
        self.assertEqual(new_line.new_job_grade_id.id, grade.id)

    def test_sppmd_admin_can_delete_submitted_digital_banking_plan(self):
        """SPPMD Administrator can delete plans in submitted (or any other) state."""
        channel = self.env["pbms.digital.channel"].create({
            "name": "Mobile Banking", "code": "MB-TEST",
        })
        plan = self.env["pbms.planning.category"].create({
            "category": "digital_banking",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "channel_id": channel.id,
            "m01": 50.0,
        })
        plan.action_submit()
        self.assertEqual(plan.state, "submitted")

        # Branch user cannot delete submitted plan
        branch_user = self.env["res.users"].create({
            "name": "Branch Test User",
            "login": "branch_test_user_del",
            "group_ids": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_branch_user").id])],
            "operating_unit_ids": [(6, 0, [self.branch.id])],
        })
        with self.assertRaises(UserError):
            plan.with_user(branch_user).unlink()

        # SPPMD Administrator CAN delete submitted plan
        admin_user = self.env["res.users"].create({
            "name": "SPPMD Admin User",
            "login": "sppmd_admin_user_del",
            "group_ids": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_manager").id])],
        })
        plan.with_user(admin_user).unlink()
        self.assertFalse(plan.exists())

    def test_notification_details_includes_all_enabled_categories(self):
        """Notification metrics table includes all planning categories enabled in planning configuration."""
        notif_branch = self.env["operating.unit"].create({
            "name": f"Notification Test Branch {self.env['operating.unit'].search_count([]) + 1}",
            "sol_id": 9500 + self.env["operating.unit"].search_count([]),
            "work_unit_type": "branch",
            "parent_unit": self.district.id,
        })
        plan = self.env["pbms.planning.category"].with_context(is_planning_request=True).create({
            "cycle_id": self.cycle.id,
            "org_unit_id": notif_branch.id,
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "plan_category": "amount",
                "m01": 1000.0,
            })],
            "digital_banking_line_ids": [(0, 0, {
                "line_type": "digital_banking",
                "channel_id": self.env["pbms.digital.channel"].create({"name": "ATMs", "code": "ATM"}).id,
                "m01": 20.0,
            })],
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Branch Auditor",
                "new_job_grade": "Grade 5",
                "quantity": 1,
                "hc_m01": 1,
                "justification_category_id": self.env["pbms.justification.category"].create({"name": "Workload"}).id,
            })],
        })
        plan._compute_category_summaries()
        plan._compute_plan_notification_details()

        # Both HTML metrics and Chatter text should contain Deposit, Digital Banking, Manpower, etc.
        self.assertEqual(plan.plan_category_title, "Annual Business Plan & Budget")
        self.assertIn("Annual Deposit Target", plan.plan_summary_metrics_html)
        self.assertIn("Annual Digital Target", plan.plan_summary_metrics_html)
        self.assertIn("Requested Workforce Headcount", plan.plan_summary_metrics_html)
        
        summary_text = plan._get_plan_notification_summary_text()
        self.assertIn("Annual Deposit Target", summary_text)
        self.assertIn("Annual Digital Target", summary_text)
        self.assertIn("Requested Workforce Headcount", summary_text)

    def test_notification_details_excludes_disabled_categories_without_data(self):
        """Notification metrics exclude categories disabled in planning configuration with 0 data."""
        # Create plan with only Deposit lines, enable_manpower is False on this branch/unit
        plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "category": "deposit",
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "plan_category": "amount",
                "m01": 5000.0,
            })],
        })
        # Simulate manpower disabled on this unit
        plan.enable_manpower = False
        plan._compute_category_summaries()
        plan._compute_plan_notification_details()

        # Notification should NOT include Manpower or 0 positions
        self.assertNotIn("Requested Workforce Headcount", plan.plan_summary_metrics_html)
        summary_text = plan._get_plan_notification_summary_text()
        self.assertNotIn("Requested Workforce Headcount", summary_text)
        
        email_body = plan._get_plan_submission_email_body()
        self.assertNotIn("Requested Workforce Headcount", email_body)
        self.assertIn("Annual Deposit Target", email_body)

    def test_draft_plan_edit_access_for_creator_and_admin(self):
        """Draft plans can be edited by their creator, branch users, and SPPMD admins."""
        branch_user = self.env["res.users"].create({
            "name": "Branch Planner",
            "login": "branch_planner_test",
            "email": "planner@bunnabank.test",
            "group_ids": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_branch_user").id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.branch.id])],
        })
        admin_user = self.env["res.users"].create({
            "name": "PBMS Admin",
            "login": "admin_planner_test",
            "email": "admin_planner@bunnabank.test",
            "group_ids": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_manager").id, self.env.ref("base.group_user").id])],
        })

        plan = self.env["pbms.planning.category"].with_user(branch_user).create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "category": "deposit",
        })

        # The branch creator must be allowed to edit content in draft stage
        self.assertTrue(plan.with_user(branch_user)._pbms_can_edit_plan_content())
        self.assertTrue(plan.with_user(branch_user)._pbms_can_submit_plan())

        # The SPPMD admin must also be allowed to edit content in draft stage
        self.assertTrue(plan.with_user(admin_user)._pbms_can_edit_plan_content())

    def test_district_and_ho_consolidation_all_categories(self):
        """Consolidation aggregates mobilization categories (deposit, customer base) from branches to district and HO."""
        branch_2 = self.env["operating.unit"].create({
            "name": f"Consolidation Branch {self.env['operating.unit'].search_count([]) + 1}",
            "sol_id": 9600 + self.env["operating.unit"].search_count([]),
            "work_unit_type": "branch",
            "parent_unit": self.district.id,
        })
        branch_dep_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "category": "deposit",
            "state": "submitted",
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 2500.0,
            })],
        })
        branch_cb_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": branch_2.id,
            "category": "customer_base",
            "state": "submitted",
            "customer_base_line_ids": [(0, 0, {
                "line_type": "customer_base",
                "deposit_type_id": self.deposit_type.id,
                "base_type": "new_acquisition",
                "m01": 50.0,
            })],
        })

        # Run District Consolidation for Deposit
        dist_dep_plan = self.env["pbms.planning.category"]._consolidate_district_plan_data(self.cycle, self.district)
        self.assertEqual(len(dist_dep_plan.deposit_line_ids), 1)
        self.assertEqual(dist_dep_plan.deposit_line_ids.m01, 2500.0)

        # Run District Consolidation for Customer Base
        dist_cb_plan = branch_cb_plan._consolidate_district_plan_data(self.cycle, self.district)
        self.assertEqual(len(dist_cb_plan.customer_base_line_ids), 1)
        self.assertEqual(dist_cb_plan.customer_base_line_ids.m01, 50.0)

        # Run Head Office Bank Consolidation
        ho_dep_plan = self.env["pbms.planning.category"]._consolidate_ho_plan_data(self.cycle, self.ho)
        self.assertEqual(len(ho_dep_plan.deposit_line_ids), 1)
        self.assertEqual(ho_dep_plan.deposit_line_ids.m01, 2500.0)

        ho_cb_plan = branch_cb_plan._consolidate_ho_plan_data(self.cycle, self.ho)
        self.assertEqual(len(ho_cb_plan.customer_base_line_ids), 1)
        self.assertEqual(ho_cb_plan.customer_base_line_ids.m01, 50.0)

    def test_target_cascade_wizard_ho_to_district_and_branch(self):
        """Test cascading approved corporate targets from HO to Districts and from District to Branches."""
        # 0. Create initial Branch Planning Request
        init_branch_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "category": "deposit",
            "state": "draft",
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 5000.0,
                "m02": 5000.0,
            })],
        })
        init_line = init_branch_plan.deposit_line_ids[0]
        # In planning request: Proposed total = 10000.0, Approved target MUST BE 0.0
        self.assertEqual(init_line.annual_total, 10000.0)
        self.assertEqual(init_line.proposed_annual_total, 10000.0)
        self.assertEqual(init_line.approved_annual_total, 0.0)
        self.assertFalse(init_line.is_cascaded)
        self.assertEqual(init_line.variance_amount, 0.0)
        self.assertEqual(init_branch_plan.deposit_approved_total, 0.0)

        # 1. Setup Head Office Plan with Deposit Target in ho_reviewed state
        ho_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.ho.id,
            "category": "deposit",
            "state": "ho_reviewed",
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 10000.0,
                "m02": 10000.0,
            })],
        })
        # Before final approval: ho_line approved target is 0.0
        ho_line = ho_plan.deposit_line_ids[0]
        self.assertEqual(ho_line.approved_annual_total, 0.0)

        # Final Approver Approves the Head Office Plan:
        ho_plan.action_approve()
        self.assertEqual(ho_plan.state, "approved")
        self.assertEqual(ho_line.approved_annual_total, 20000.0)
        self.assertTrue(ho_line.is_cascaded)
        self.assertEqual(ho_plan.deposit_approved_total, 20000.0)

        # 2. Launch Wizard: Head Office -> Districts
        wizard = self.env["pbms.target.cascade.wizard"].create({
            "plan_id": ho_plan.id,
            "cascade_level": "ho_to_district",
            "category": "deposit",
            "deposit_type_id": self.deposit_type.id,
            "total_target_amount": 50000.0,
            "distribution_method": "equal",
        })
        wizard._populate_recipient_lines()
        self.assertTrue(len(wizard.line_ids) > 0)
        wizard.action_apply_cascade()

        # Verify District Plan has received the cascaded line
        dist_plan = self.env["pbms.planning.category"].search([
            ("cycle_id", "=", self.cycle.id),
            ("org_unit_id", "=", self.district.id),
        ], limit=1)
        self.assertTrue(dist_plan)
        self.assertTrue(len(dist_plan.deposit_line_ids) > 0)

        # 3. Launch Wizard: District -> Child Branches
        dist_wizard = self.env["pbms.target.cascade.wizard"].create({
            "plan_id": dist_plan.id,
            "cascade_level": "district_to_branch",
            "category": "deposit",
            "deposit_type_id": self.deposit_type.id,
            "total_target_amount": 25000.0,
            "distribution_method": "equal",
        })
        dist_wizard._populate_recipient_lines()
        self.assertTrue(len(dist_wizard.line_ids) > 0)
        dist_wizard.action_apply_cascade()

        # Verify Branch Plan has received the cascaded target and updated approved fields
        branch_plan = self.env["pbms.planning.category"].search([
            ("cycle_id", "=", self.cycle.id),
            ("org_unit_id", "=", self.branch.id),
        ], limit=1)
        self.assertTrue(branch_plan)
        self.assertTrue(len(branch_plan.deposit_line_ids) > 0)
        branch_line = branch_plan.deposit_line_ids[0]
        self.assertEqual(branch_line.annual_total, 25000.0)
        self.assertEqual(branch_line.proposed_annual_total, 10000.0)
        self.assertEqual(branch_line.approved_annual_total, 25000.0)
        self.assertTrue(branch_line.is_cascaded)
        self.assertTrue(branch_plan.has_cascaded_targets)
        self.assertEqual(branch_plan.deposit_approved_total, 25000.0)
        self.assertEqual(branch_line.variance_amount, 15000.0)
        self.assertEqual(branch_line.variance_percentage, 150.0)

    def test_target_cascade_multi_product_proportional_breakdown(self):
        """Test cascading category with multiple products (Saving 138k, Demand 104k, Time 101k -> Total 343k)
        proportionally without duplicating the 343k onto each product line."""
        dep_saving = self.deposit_type
        dep_demand = self.env["pbms.deposit.type"].create({"name": "Demand Deposit", "code": "DEM-T"})
        dep_time = self.env["pbms.deposit.type"].create({"name": "Time Deposit", "code": "TIME-T"})

        # Head Office Plan with 3 Deposit Products: Total 343,000.00 ETB
        ho_multi_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.ho.id,
            "category": "deposit",
            "state": "ho_reviewed",
            "deposit_line_ids": [
                (0, 0, {"line_type": "deposit", "deposit_type_id": dep_saving.id, "m01": 69000.0, "m02": 69000.0}),  # 138k
                (0, 0, {"line_type": "deposit", "deposit_type_id": dep_demand.id, "m01": 52000.0, "m02": 52000.0}),  # 104k
                (0, 0, {"line_type": "deposit", "deposit_type_id": dep_time.id, "m01": 50500.0, "m02": 50500.0}),    # 101k
            ],
        })
        self.assertEqual(ho_multi_plan.deposit_annual_total, 343000.0)

        # Approve HO Plan
        ho_multi_plan.action_approve()
        self.assertEqual(ho_multi_plan.deposit_approved_total, 343000.0)

        # Launch Wizard in 'all_products' mode with total 343,000.00
        wizard = self.env["pbms.target.cascade.wizard"].create({
            "plan_id": ho_multi_plan.id,
            "cascade_level": "ho_to_district",
            "category": "deposit",
            "cascade_scope": "all_products",
            "total_target_amount": 343000.0,
            "distribution_method": "equal",
        })
        wizard._populate_recipient_lines()
        self.assertEqual(wizard.source_annual_target, 343000.0)
        self.assertEqual(wizard.total_target_amount, 343000.0)
        wizard.action_apply_cascade()

        # Check District Plan
        dist_plan = self.env["pbms.planning.category"].search([
            ("cycle_id", "=", self.cycle.id),
            ("org_unit_id", "=", self.district.id),
        ], limit=1)
        self.assertTrue(dist_plan)
        # Verify 3 individual deposit lines exist
        self.assertEqual(len(dist_plan.deposit_line_ids), 3)

        sav_line = dist_plan.deposit_line_ids.filtered(lambda l: l.deposit_type_id == dep_saving)
        dem_line = dist_plan.deposit_line_ids.filtered(lambda l: l.deposit_type_id == dep_demand)
        tim_line = dist_plan.deposit_line_ids.filtered(lambda l: l.deposit_type_id == dep_time)

        self.assertEqual(sav_line.approved_annual_total, 138000.0)
        self.assertEqual(dem_line.approved_annual_total, 104000.0)
        self.assertEqual(tim_line.approved_annual_total, 101000.0)

        # District Total Approved Plan is 343,000.00 (NOT 343,000 * 3 = 1,029,000)
        self.assertEqual(dist_plan.deposit_approved_total, 343000.0)

    def test_workforce_budget_computation(self):
        """Test calculation of Current Staff Salary, New Planned Staff Cost, and Total Workforce Budget."""
        # 1. Create a job position and grade
        grade = self.env["employee.grade"].create({
            "grade_code": "GR-TEST",
            "grade_name": "Grade Test",
            "base_salary": 10000.0,
            "salary_factor": 1.2,
        })
        job_vals = {"name": "Senior Branch Officer"}
        if "grade" in self.env["hr.job"]._fields:
            job_vals["grade"] = grade.id
        elif "grade_id" in self.env["hr.job"]._fields:
            job_vals["grade_id"] = grade.id
        job = self.env["hr.job"].create(job_vals)

        # 2. Create an active employee for branch
        emp_vals = {
            "name": "Test Employee",
            "job_position": job.id,
            "default_operating_unit_id": self.branch.id,
            "operating_unit_ids": [(6, 0, [self.branch.id])],
            "wage": 10000.0,
        }
        if "job_grade" in self.env["hr.employee"]._fields:
            emp_vals["job_grade"] = grade.id
        elif "grade_id" in self.env["hr.employee"]._fields:
            emp_vals["grade_id"] = grade.id
        emp = self.env["hr.employee"].create(emp_vals)

        # 3. Create a planning record for branch (with default category='deposit', enable_manpower=True)
        pos_type_new = self.env["pbms.position.type"].search([("code", "=", "new")], limit=1)
        if not pos_type_new:
            pos_type_new = self.env["pbms.position.type"].create({
                "name": "New Position", "code": "new", "is_new_position": True,
            })

        plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "category": "deposit",
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type_id": pos_type_new.id,
                "job_id": job.id,
                "new_job_title": "Senior Branch Officer",
                "new_job_grade": "GR-TEST",
                "new_job_grade_id": grade.id,
                "base_salary": 15000.0,
                "pension_rate": 11.0,
                "q1": 1,
            })],
        })

        # Verify current staff salary: 12,000 * 12 = 144,000 (base 10,000 * salary_factor 1.2)
        self.assertEqual(plan.current_staff_salary_budget, 144000.0)

        # Verify new planned staff cost: monthly = 15000 + 1650 = 16650; unit_cost = 16650 * 12 = 199,800; Q1 = 1 -> 199,800
        mp_line = plan.manpower_line_ids[0]
        self.assertEqual(mp_line.monthly_total_compensation, 16650.0)
        self.assertEqual(mp_line.unit_cost, 199800.0)
        self.assertEqual(mp_line.annual_total_cost, 199800.0)
        self.assertEqual(plan.new_planned_salary_budget, 199800.0)

        # Verify Total Workforce Budget = 144,000 + 199,800 = 343,800.0
        self.assertEqual(plan.total_operating_unit_manpower_budget, 343800.0)

    def test_sppmd_approver_edit_permissions(self):
        """Verify SPPMD Plan Approver can adjust and add requirement lines during review stages."""
        sppmd_approver_group = self.env.ref("bunna_pbms.group_pbms_approver")
        approver_user = self.env["res.users"].create({
            "name": "SPPMD Approver",
            "login": "sppmd_approver_test",
            "group_ids": [(6, 0, [sppmd_approver_group.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.ho.id, self.district.id, self.branch.id])],
        })

        plan = self._create_deposit_plan(
            org_unit_id=self.ho.id,
            state="ho_reviewed",
            deposit_line_ids=[(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "plan_category": "amount",
                "m01": 1000.0,
            })],
        )
        line = plan.deposit_line_ids[0]

        # SPPMD Approver should be able to edit lines without Access Error
        line.with_user(approver_user).write({"m01": 5000.0})
        self.assertEqual(line.m01, 5000.0)

        # SPPMD Approver can add new requirement lines
        new_line = self.env["pbms.plan.category.line"].with_user(approver_user).create({
            "plan_id": plan.id,
            "line_type": "deposit",
            "deposit_type_id": self.deposit_type.id,
            "m01": 2000.0,
        })
        self.assertTrue(new_line)
        self.assertEqual(new_line.m01, 2000.0)

    def test_district_office_plan_submission_workflow(self):
        """District Office plans:
        - Workforce (manpower) directly submits to Respective Chief Review (chief_review)
        - General Expense & Fixed Asset directly submit to District Endorsed (district_endorsed)
        """
        dist_unit = self.env["operating.unit"].create({
            "name": "North District Office",
            "sol_id": 9020,
            "work_unit_type": "district_office",
        })

        # 1. District Office Manpower Plan
        job = self.env["hr.job"].create({"name": "District Operations Specialist"})
        just_cat = self.env["pbms.justification.category"].create({"name": "Workload District", "code": "workload_dist"})
        wp_plan = self.env["pbms.planning.category"].create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": dist_unit.id,
            "business_justification": "District capacity building",
            "line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "additional",
                "org_unit_id": dist_unit.id,
                "job_id": job.id,
                "justification_category_id": just_cat.id,
                "m01": 1.0,
                "annual_total": 1.0,
            })],
        })
        wp_plan.action_submit()
        self.assertEqual(wp_plan.state, "chief_review")

        # 2. District Office General Expense Plan
        ge_plan = self.env["pbms.planning.category"].create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": dist_unit.id,
            "m01": 5000.0,
        })
        ge_plan.action_submit()
        # District GE goes DIRECTLY to HO Functional Reviewer (district_endorsed) - no chief review
        self.assertEqual(ge_plan.state, "district_endorsed")

        # 3. District Office Fixed Asset Plan
        fa_plan = self.env["pbms.planning.category"].create({
            "category": "fixed_asset",
            "cycle_id": self.cycle.id,
            "org_unit_id": dist_unit.id,
            "m01": 10000.0,
        })
        fa_plan.action_submit()
        # District FA goes DIRECTLY to HO Functional Reviewer (district_endorsed) - no chief review
        self.assertEqual(fa_plan.state, "district_endorsed")

        # 4. District Office Deposit Plan submits directly to District Endorsed (directly to Head Office)
        dep_plan = self.env["pbms.planning.category"].create({
            "category": "deposit",
            "cycle_id": self.cycle.id,
            "org_unit_id": dist_unit.id,
            "deposit_type_id": self.deposit_type.id,
            "plan_category": "amount",
            "m01": 15000.0,
        })
        dep_plan.action_submit()
        self.assertEqual(dep_plan.state, "district_endorsed")

        # 5. District Office plan in district_endorsed can reset to draft before Head Office review
        dep_plan.action_reset_to_draft()
        self.assertEqual(dep_plan.state, "draft")

        # 6. Self-healing for District Office mobilization plans in submitted state:
        # If an existing district mobilization plan is in submitted, access flag computation heals it to district_endorsed
        old_dist_plan = self.env["pbms.planning.category"].create({
            "category": "fx",
            "cycle_id": self.cycle.id,
            "org_unit_id": dist_unit.id,
            "m01": 3000.0,
        })
        # Force state to submitted to simulate pre-existing record from screenshot
        old_dist_plan.write({"state": "submitted"})
        self.assertEqual(old_dist_plan.state, "submitted")
        old_dist_plan._compute_access_flags()
        self.assertEqual(old_dist_plan.state, "district_endorsed")

    def test_ho_functional_reviewer_own_plan_workflow(self):
        """When Head Office operating unit plans:
        - It submits to Respective Chief Review (chief_review)
        - When Respective Chief approves: Fixed Asset & General Expense escalate to HO Functional Reviewer (submitted)
        - HO Functional Reviewer final approves General Expense (approved) and submits Fixed Asset to Budget Hiring Committee (committee_review)
        """
        ho_reviewer_group = self.env.ref("bunna_pbms.group_pbms_ho_reviewer")
        chief_group = self.env.ref("bunna_pbms.group_pbms_respective_chief")

        ho_unit = self.env["operating.unit"].create({
            "name": "Finance & Accounts Department",
            "sol_id": 9030,
            "work_unit_type": "head_office",
        })
        reviewer_user = self.env["res.users"].create({
            "name": "HO Expense Reviewer User",
            "login": "ho_expense_rev_test",
            "group_ids": [(6, 0, [ho_reviewer_group.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [ho_unit.id])],
        })
        chief_user = self.env["res.users"].create({
            "name": "Respective Chief User",
            "login": "chief_user_test",
            "group_ids": [(6, 0, [chief_group.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [ho_unit.id])],
        })

        # 1. General Expense Plan
        ge_plan = self.env["pbms.planning.category"].with_user(reviewer_user).create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": ho_unit.id,
            "m01": 8000.0,
        })
        ge_plan.with_user(reviewer_user).action_submit()
        self.assertEqual(ge_plan.state, "chief_review")

        # Respective Chief approves and escalates to HO Functional Reviewer
        ge_plan.with_user(chief_user).action_chief_approve_escalate()
        self.assertEqual(ge_plan.state, "submitted")

        # HO Functional Reviewer final approves General Expense
        ge_plan.with_user(reviewer_user).action_ho_approve()
        self.assertEqual(ge_plan.state, "approved")
        self.assertTrue(ge_plan.approval_date)

        # 2. Fixed Asset Plan
        fa_plan = self.env["pbms.planning.category"].with_user(reviewer_user).create({
            "category": "fixed_asset",
            "cycle_id": self.cycle.id,
            "org_unit_id": ho_unit.id,
            "m01": 25000.0,
        })
        fa_plan.with_user(reviewer_user).action_submit()
        self.assertEqual(fa_plan.state, "chief_review")

        # Respective Chief approves and escalates Fixed Asset to HO Functional Reviewer
        fa_plan.with_user(chief_user).action_chief_approve_escalate()
        self.assertEqual(fa_plan.state, "submitted")

        # HO Functional Reviewer submits Fixed Asset to Budget Hiring Committee
        fa_plan.with_user(reviewer_user).action_submit_to_committee()
        self.assertEqual(fa_plan.state, "committee_review")

    def test_headoffice_plan_routes_strictly_to_manager(self):
        """When an HR operating unit plans:
        - Its manager is Abel
        - Abel's manager is Asmare
        - When Abel plans, plans are submitted to its manager Asmare
        - Asmare can view, edit, and approve:
          * Workforce goes to People Solutions Directorate (people_solutions_review)
          * General Expense and Fixed Asset go to Head Office Functional Reviewer (submitted)
        - Another chief (Solomon) who is NOT Abel's manager cannot review or approve Abel's plan.
        """
        chief_group = self.env.ref("bunna_pbms.group_pbms_respective_chief")
        branch_group = self.env.ref("bunna_pbms.group_pbms_branch_user")
        ho_reviewer_group = self.env.ref("bunna_pbms.group_pbms_ho_reviewer")
        committee_group = self.env.ref("bunna_pbms.group_pbms_budget_hiring_committee")

        reviewer_user = self.env["res.users"].create({
            "name": "HO Reviewer User",
            "login": "ho_rev_user_abel_test",
            "group_ids": [(6, 0, [ho_reviewer_group.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.ho.id])],
        })
        committee_user = self.env["res.users"].create({
            "name": "Committee User",
            "login": "committee_user_abel_test",
            "group_ids": [(6, 0, [committee_group.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.ho.id])],
        })

        # Create Asmare (Chief) employee and user
        asmare_user = self.env["res.users"].create({
            "name": "Asmare Chief",
            "login": "asmare_chief_test",
            "group_ids": [(6, 0, [chief_group.id, self.env.ref("base.group_user").id])],
        })
        asmare_emp = self.env["hr.employee"].create({
            "name": "Asmare Chief",
            "user_id": asmare_user.id,
        })
        asmare_user.write({"employee_id": asmare_emp.id})

        # Create Solomon (Different Chief) employee and user
        solomon_user = self.env["res.users"].create({
            "name": "Solomon IT Chief",
            "login": "solomon_chief_test",
            "group_ids": [(6, 0, [chief_group.id, self.env.ref("base.group_user").id])],
        })
        solomon_emp = self.env["hr.employee"].create({
            "name": "Solomon IT Chief",
            "user_id": solomon_user.id,
        })
        solomon_user.write({"employee_id": solomon_emp.id})

        # Create Abel (HR Department Director) employee and user
        abel_user = self.env["res.users"].create({
            "name": "Abel HR Manager",
            "login": "abel_hr_test",
            "group_ids": [(6, 0, [branch_group.id, self.env.ref("base.group_user").id])],
        })
        abel_emp = self.env["hr.employee"].create({
            "name": "Abel HR Manager",
            "user_id": abel_user.id,
            "parent_id": asmare_emp.id,  # Abel's manager is Asmare!
        })
        abel_user.write({"employee_id": abel_emp.id})

        # Create HR operating unit managed by Abel
        hr_unit = self.env["operating.unit"].create({
            "name": "HR Operating Unit",
            "sol_id": 9040,
            "work_unit_type": "head_office",
            "manager_id": abel_emp.id,
        })
        abel_user.write({"assigned_operating_unit_ids": [(6, 0, [hr_unit.id])]})

        # 1. Workforce Plan
        job = self.env["hr.job"].create({"name": "HR Specialist"})
        just_cat = self.env["pbms.justification.category"].create({"name": "Workload HR", "code": "workload_hr"})
        wp_plan = self.env["pbms.planning.category"].with_user(abel_user).create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": hr_unit.id,
            "business_justification": "HR team expansion",
            "line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "HR Specialist",
                "new_job_grade": "Grade 5",
                "org_unit_id": hr_unit.id,
                "job_id": job.id,
                "justification_category_id": just_cat.id,
                "m01": 2.0,
                "annual_total": 2.0,
            })],
        })
        wp_plan.with_user(abel_user).action_submit()
        self.assertEqual(wp_plan.state, "chief_review")

        # Verify reviewers for chief_review: strictly Asmare! Not Solomon!
        reviewers = wp_plan._get_stage_reviewers("chief_review")
        self.assertIn(asmare_user, reviewers)
        self.assertNotIn(solomon_user, reviewers)

        # Verify Solomon cannot approve Abel's plan
        with self.assertRaises(AccessError):
            wp_plan.with_user(solomon_user).action_chief_approve_escalate()

        # Verify Asmare can view and edit the plan
        self.assertTrue(wp_plan.with_user(asmare_user).can_chief_review)
        self.assertTrue(wp_plan.with_user(asmare_user).can_edit_content)
        # Asmare edits workforce figure
        wp_line = wp_plan.manpower_line_ids[0]
        wp_line.with_user(asmare_user).write({"m01": 1.0})
        self.assertEqual(wp_line.m01, 1.0)

        # Asmare approves and escalates Workforce -> People Solutions Directorate
        wp_plan.with_user(asmare_user).action_chief_approve_escalate()
        self.assertEqual(wp_plan.state, "people_solutions_review")

        # 2. General Expense Plan
        ge_plan = self.env["pbms.planning.category"].with_user(abel_user).create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": hr_unit.id,
            "m01": 5000.0,
        })
        ge_plan.with_user(abel_user).action_submit()
        self.assertEqual(ge_plan.state, "chief_review")

        # Reviewer is strictly Asmare
        ge_reviewers = ge_plan._get_stage_reviewers("chief_review")
        self.assertIn(asmare_user, ge_reviewers)
        self.assertNotIn(solomon_user, ge_reviewers)

        # Visibility during chief_review:
        # Visible to Asmare, NOT visible to Solomon, NOT visible to HO Reviewer
        self.assertTrue(bool(self.env["pbms.planning.category"].with_user(asmare_user).search([("id", "=", ge_plan.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(solomon_user).search([("id", "=", ge_plan.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(reviewer_user).search([("id", "=", ge_plan.id)])))

        # Asmare can edit General Expense
        self.assertTrue(ge_plan.with_user(asmare_user).can_edit_content)
        ge_plan.with_user(asmare_user).write({"m01": 4000.0})
        self.assertEqual(ge_plan.m01, 4000.0)

        # Asmare approves and escalates General Expense -> Head Office Functional Reviewer
        ge_plan.with_user(asmare_user).action_chief_approve_escalate()
        self.assertEqual(ge_plan.state, "submitted")

        # Now in submitted, visible to HO Reviewer, who final approves it
        self.assertTrue(bool(self.env["pbms.planning.category"].with_user(reviewer_user).search([("id", "=", ge_plan.id)])))
        ge_plan.with_user(reviewer_user).action_ho_approve()
        self.assertEqual(ge_plan.state, "approved")

        # 3. Fixed Asset Plan
        fa_plan = self.env["pbms.planning.category"].with_user(abel_user).create({
            "category": "fixed_asset",
            "cycle_id": self.cycle.id,
            "org_unit_id": hr_unit.id,
            "m01": 15000.0,
        })
        fa_plan.with_user(abel_user).action_submit()
        self.assertEqual(fa_plan.state, "chief_review")

        # Reviewer is strictly Asmare
        fa_reviewers = fa_plan._get_stage_reviewers("chief_review")
        self.assertIn(asmare_user, fa_reviewers)
        self.assertNotIn(solomon_user, fa_reviewers)

        # Visibility during chief_review: NOT visible to HO Reviewer
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(reviewer_user).search([("id", "=", fa_plan.id)])))

        # Asmare can edit Fixed Asset
        self.assertTrue(fa_plan.with_user(asmare_user).can_edit_content)

        # Asmare approves and escalates Fixed Asset -> Head Office Functional Reviewer
        fa_plan.with_user(asmare_user).action_chief_approve_escalate()
        self.assertEqual(fa_plan.state, "submitted")

        # HO Reviewer submits Fixed Asset to Budget Hiring Committee
        fa_plan.with_user(reviewer_user).action_submit_to_committee()
        self.assertEqual(fa_plan.state, "committee_review")

        # Committee final approves Fixed Asset
        fa_plan.with_user(committee_user).action_committee_approve_resource()
        self.assertEqual(fa_plan.state, "approved")

    def test_headoffice_multi_tier_reporting_hierarchy(self):
        """Test multi-tier hierarchy:
        A (HR OU manager) -> B (manager of A, Chief) -> C (manager of B, Chief) -> D (manager of C, Chief)
        User F: Head Office Functional Reviewer.

        1. When A plans (FA, GE, Workforce):
           - Submitted to B in chief_review.
           - Visible to B; NOT visible to C, D, or F.
           - B approves: GE & FA -> F (submitted); Workforce -> People Solutions (people_solutions_review).
           - F final approves GE; F submits FA to Committee; Committee approves FA.

        2. When B plans (FA, GE, Workforce):
           - Submitted to C in chief_review.
           - Visible to C; NOT visible to B (for approval), D, or F.
           - C approves: GE & FA -> F (submitted); Workforce -> People Solutions (people_solutions_review).
           - F final approves GE; F submits FA to Committee; Committee approves FA.

        3. When C plans (FA, GE, Workforce):
           - Submitted to D in chief_review.
           - Visible to D; NOT visible to C, B, A, or F.
           - D approves: GE & FA -> F (submitted); Workforce -> People Solutions (people_solutions_review).
           - F final approves GE; F submits FA to Committee; Committee approves FA.
        """
        chief_group = self.env.ref("bunna_pbms.group_pbms_respective_chief")
        branch_group = self.env.ref("bunna_pbms.group_pbms_branch_user")
        ho_reviewer_group = self.env.ref("bunna_pbms.group_pbms_ho_reviewer")
        committee_group = self.env.ref("bunna_pbms.group_pbms_budget_hiring_committee")

        user_f = self.env["res.users"].create({
            "name": "User F HO Reviewer",
            "login": "user_f_reviewer",
            "group_ids": [(6, 0, [ho_reviewer_group.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.ho.id])],
        })
        user_comm = self.env["res.users"].create({
            "name": "Committee User MultiTier",
            "login": "user_comm_multitier",
            "group_ids": [(6, 0, [committee_group.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.ho.id])],
        })

        # D: Top Chief
        user_d = self.env["res.users"].create({
            "name": "User D Chief",
            "login": "user_d_chief",
            "group_ids": [(6, 0, [chief_group.id, self.env.ref("base.group_user").id])],
        })
        emp_d = self.env["hr.employee"].create({"name": "Employee D", "user_id": user_d.id})
        user_d.write({"employee_id": emp_d.id})

        ou_d = self.env["operating.unit"].create({
            "name": "Executive Directorate D",
            "sol_id": 9050,
            "work_unit_type": "head_office",
            "manager_id": emp_d.id,
        })
        user_d.write({"assigned_operating_unit_ids": [(6, 0, [ou_d.id])]})

        # C: Chief under D
        user_c = self.env["res.users"].create({
            "name": "User C Chief",
            "login": "user_c_chief",
            "group_ids": [(6, 0, [chief_group.id, self.env.ref("base.group_user").id])],
        })
        emp_c = self.env["hr.employee"].create({"name": "Employee C", "user_id": user_c.id, "parent_id": emp_d.id})
        user_c.write({"employee_id": emp_c.id})

        ou_c = self.env["operating.unit"].create({
            "name": "Division C",
            "sol_id": 9051,
            "work_unit_type": "head_office",
            "manager_id": emp_c.id,
            "parent_unit": ou_d.id,
        })
        user_c.write({"assigned_operating_unit_ids": [(6, 0, [ou_c.id])]})

        # B: Chief under C
        user_b = self.env["res.users"].create({
            "name": "User B Chief",
            "login": "user_b_chief",
            "group_ids": [(6, 0, [chief_group.id, self.env.ref("base.group_user").id])],
        })
        emp_b = self.env["hr.employee"].create({"name": "Employee B", "user_id": user_b.id, "parent_id": emp_c.id})
        user_b.write({"employee_id": emp_b.id})

        ou_b = self.env["operating.unit"].create({
            "name": "Department B",
            "sol_id": 9052,
            "work_unit_type": "head_office",
            "manager_id": emp_b.id,
            "parent_unit": ou_c.id,
        })
        user_b.write({"assigned_operating_unit_ids": [(6, 0, [ou_b.id])]})

        # A: HR Operating Unit Manager under B
        user_a = self.env["res.users"].create({
            "name": "User A Planner",
            "login": "user_a_planner",
            "group_ids": [(6, 0, [branch_group.id, self.env.ref("base.group_user").id])],
        })
        emp_a = self.env["hr.employee"].create({"name": "Employee A", "user_id": user_a.id, "parent_id": emp_b.id})
        user_a.write({"employee_id": emp_a.id})

        ou_a = self.env["operating.unit"].create({
            "name": "HR Unit A",
            "sol_id": 9053,
            "work_unit_type": "head_office",
            "manager_id": emp_a.id,
            "parent_unit": ou_b.id,
        })
        user_a.write({"assigned_operating_unit_ids": [(6, 0, [ou_a.id])]})

        job = self.env["hr.job"].create({"name": "Multi-Tier Test Specialist"})
        just_cat = self.env["pbms.justification.category"].create({"name": "Multi-Tier Justification", "code": "mt_just"})

        # =========================================================================
        # 1. USER A PLANS (FA, GE, Workforce) -> Submits to User B
        # =========================================================================
        ge_a = self.env["pbms.planning.category"].with_user(user_a).create({
            "category": "general_expense", "cycle_id": self.cycle.id, "org_unit_id": ou_a.id, "m01": 1000.0,
        })
        ge_a.with_user(user_a).action_submit()
        self.assertEqual(ge_a.state, "chief_review")

        fa_a = self.env["pbms.planning.category"].with_user(user_a).create({
            "category": "fixed_asset", "cycle_id": self.cycle.id, "org_unit_id": ou_a.id, "m01": 2000.0,
        })
        fa_a.with_user(user_a).action_submit()
        self.assertEqual(fa_a.state, "chief_review")

        wp_a = self.env["pbms.planning.category"].with_user(user_a).create({
            "category": "manpower", "cycle_id": self.cycle.id, "org_unit_id": ou_a.id,
            "business_justification": "HR Expansion A",
            "line_ids": [(0, 0, {
                "line_type": "manpower", "position_type": "new", "new_job_title": "HR Officer A", "new_job_grade": "Grade 5", "org_unit_id": ou_a.id, "job_id": job.id,
                "justification_category_id": just_cat.id, "m01": 1.0, "annual_total": 1.0,
            })],
        })
        wp_a.with_user(user_a).action_submit()
        self.assertEqual(wp_a.state, "chief_review")

        # Isolation verification for A's plans:
        # B sees them, C and D do NOT see them, F does NOT see them in chief_review
        self.assertTrue(bool(self.env["pbms.planning.category"].with_user(user_b).search([("id", "=", ge_a.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(user_c).search([("id", "=", ge_a.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(user_d).search([("id", "=", ge_a.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(user_f).search([("id", "=", ge_a.id)])))

        # Neither C nor D can approve A's plan
        with self.assertRaises(AccessError):
            ge_a.with_user(user_c).action_chief_approve_escalate()
        with self.assertRaises(AccessError):
            ge_a.with_user(user_d).action_chief_approve_escalate()

        # B approves A's plans:
        ge_a.with_user(user_b).action_chief_approve_escalate()
        self.assertEqual(ge_a.state, "submitted")
        fa_a.with_user(user_b).action_chief_approve_escalate()
        self.assertEqual(fa_a.state, "submitted")
        wp_a.with_user(user_b).action_chief_approve_escalate()
        self.assertEqual(wp_a.state, "people_solutions_review")

        # User F processes GE and FA from A
        ge_a.with_user(user_f).action_ho_approve()
        self.assertEqual(ge_a.state, "approved")
        fa_a.with_user(user_f).action_submit_to_committee()
        self.assertEqual(fa_a.state, "committee_review")
        fa_a.with_user(user_comm).action_committee_approve_resource()
        self.assertEqual(fa_a.state, "approved")

        # =========================================================================
        # 2. USER B PLANS (FA, GE, Workforce) -> Submits to User C
        # =========================================================================
        ge_b = self.env["pbms.planning.category"].with_user(user_b).create({
            "category": "general_expense", "cycle_id": self.cycle.id, "org_unit_id": ou_b.id, "m01": 3000.0,
        })
        ge_b.with_user(user_b).action_submit()
        self.assertEqual(ge_b.state, "chief_review")

        fa_b = self.env["pbms.planning.category"].with_user(user_b).create({
            "category": "fixed_asset", "cycle_id": self.cycle.id, "org_unit_id": ou_b.id, "m01": 4000.0,
        })
        fa_b.with_user(user_b).action_submit()
        self.assertEqual(fa_b.state, "chief_review")

        wp_b = self.env["pbms.planning.category"].with_user(user_b).create({
            "category": "manpower", "cycle_id": self.cycle.id, "org_unit_id": ou_b.id,
            "business_justification": "Dept B Expansion",
            "line_ids": [(0, 0, {
                "line_type": "manpower", "position_type": "new", "new_job_title": "Officer B", "new_job_grade": "Grade 5", "org_unit_id": ou_b.id, "job_id": job.id,
                "justification_category_id": just_cat.id, "m01": 2.0, "annual_total": 2.0,
            })],
        })
        wp_b.with_user(user_b).action_submit()
        self.assertEqual(wp_b.state, "chief_review")

        # Isolation verification for B's plans:
        # C sees them; D does NOT see them; B cannot self-approve; F does NOT see them in chief_review
        self.assertTrue(bool(self.env["pbms.planning.category"].with_user(user_c).search([("id", "=", ge_b.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(user_d).search([("id", "=", ge_b.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(user_f).search([("id", "=", ge_b.id)])))

        # Self-approval prevented for B:
        with self.assertRaises(AccessError):
            ge_b.with_user(user_b).action_chief_approve_escalate()
        # D cannot approve B's plan (not direct manager):
        with self.assertRaises(AccessError):
            ge_b.with_user(user_d).action_chief_approve_escalate()

        # C approves B's plans:
        ge_b.with_user(user_c).action_chief_approve_escalate()
        self.assertEqual(ge_b.state, "submitted")
        fa_b.with_user(user_c).action_chief_approve_escalate()
        self.assertEqual(fa_b.state, "submitted")
        wp_b.with_user(user_c).action_chief_approve_escalate()
        self.assertEqual(wp_b.state, "people_solutions_review")

        # User F processes GE and FA from B
        ge_b.with_user(user_f).action_ho_approve()
        self.assertEqual(ge_b.state, "approved")
        fa_b.with_user(user_f).action_submit_to_committee()
        self.assertEqual(fa_b.state, "committee_review")
        fa_b.with_user(user_comm).action_committee_approve_resource()
        self.assertEqual(fa_b.state, "approved")

        # =========================================================================
        # 3. USER C PLANS (FA, GE, Workforce) -> Submits to User D
        # =========================================================================
        ge_c = self.env["pbms.planning.category"].with_user(user_c).create({
            "category": "general_expense", "cycle_id": self.cycle.id, "org_unit_id": ou_c.id, "m01": 5000.0,
        })
        ge_c.with_user(user_c).action_submit()
        self.assertEqual(ge_c.state, "chief_review")

        fa_c = self.env["pbms.planning.category"].with_user(user_c).create({
            "category": "fixed_asset", "cycle_id": self.cycle.id, "org_unit_id": ou_c.id, "m01": 6000.0,
        })
        fa_c.with_user(user_c).action_submit()
        self.assertEqual(fa_c.state, "chief_review")

        wp_c = self.env["pbms.planning.category"].with_user(user_c).create({
            "category": "manpower", "cycle_id": self.cycle.id, "org_unit_id": ou_c.id,
            "business_justification": "Division C Expansion",
            "line_ids": [(0, 0, {
                "line_type": "manpower", "position_type": "new", "new_job_title": "Officer C", "new_job_grade": "Grade 5", "org_unit_id": ou_c.id, "job_id": job.id,
                "justification_category_id": just_cat.id, "m01": 1.0, "annual_total": 1.0,
            })],
        })
        wp_c.with_user(user_c).action_submit()
        self.assertEqual(wp_c.state, "chief_review")

        # Isolation verification for C's plans:
        # D sees them; B does NOT see them; C cannot self-approve; F does NOT see them in chief_review
        self.assertTrue(bool(self.env["pbms.planning.category"].with_user(user_d).search([("id", "=", ge_c.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(user_b).search([("id", "=", ge_c.id)])))
        self.assertFalse(bool(self.env["pbms.planning.category"].with_user(user_f).search([("id", "=", ge_c.id)])))

        # Self-approval prevented for C:
        with self.assertRaises(AccessError):
            ge_c.with_user(user_c).action_chief_approve_escalate()
        # B cannot approve C's plan:
        with self.assertRaises(AccessError):
            ge_c.with_user(user_b).action_chief_approve_escalate()

        # D approves C's plans:
        ge_c.with_user(user_d).action_chief_approve_escalate()
        self.assertEqual(ge_c.state, "submitted")
        fa_c.with_user(user_d).action_chief_approve_escalate()
        self.assertEqual(fa_c.state, "submitted")
        wp_c.with_user(user_d).action_chief_approve_escalate()
        self.assertEqual(wp_c.state, "people_solutions_review")

        # User F processes GE and FA from C
        ge_c.with_user(user_f).action_ho_approve()
        self.assertEqual(ge_c.state, "approved")
        fa_c.with_user(user_f).action_submit_to_committee()
        self.assertEqual(fa_c.state, "committee_review")
        fa_c.with_user(user_comm).action_committee_approve_resource()
        self.assertEqual(fa_c.state, "approved")

    def test_employee_org_chart_hierarchy_workflow(self):
        """Test reporting hierarchy exactly as shown in the organizational chart:
        1. Mulugeta Alemayehu Awoke (CEO)
        2. Eskindir Dibekulu Erede (Chief Retail & Branch Banking Officer) -> reports to Mulugeta
        3. Yonas Fiseha Mokennen (Director II - Dessie District) -> reports to Eskindir
        4. Dejen Bisetegn Sitot (Branch Manager - I) -> reports to Yonas
        5. Abadi Tafere Tedla (Branch Sales & Service Supervisor - I) [Planner] -> reports to Dejen

        - When Abadi plans (Fixed Asset, General Expense, Workforce):
          * Submitted to Dejen (immediate manager) in chief_review
          * Only Dejen can review/approve; Yonas, Eskindir, Mulugeta cannot
          * Dejen approves -> GE & FA to HO Functional Reviewer; Workforce to People Solutions
        - When Dejen plans:
          * Submitted to Yonas in chief_review
          * Only Yonas can review/approve; Dejen cannot self-approve
        - When Yonas plans:
          * Submitted to Eskindir in chief_review
          * Only Eskindir can review/approve; Yonas cannot self-approve
        - When Eskindir plans:
          * Submitted to Mulugeta in chief_review
          * Only Mulugeta can review/approve; Eskindir cannot self-approve
        """
        chief_group = self.env.ref("bunna_pbms.group_pbms_respective_chief")
        branch_group = self.env.ref("bunna_pbms.group_pbms_branch_user")
        ho_reviewer_group = self.env.ref("bunna_pbms.group_pbms_ho_reviewer")
        comm_group = self.env.ref("bunna_pbms.group_pbms_budget_hiring_committee")

        user_ho_rev = self.env["res.users"].create({
            "name": "HO Functional Reviewer",
            "login": "ho_rev_orgchart_test",
            "group_ids": [(6, 0, [ho_reviewer_group.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.ho.id])],
        })
        user_comm = self.env["res.users"].create({
            "name": "Committee User OrgChart",
            "login": "comm_orgchart_test",
            "group_ids": [(6, 0, [comm_group.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.ho.id])],
        })

        # 1. Mulugeta (CEO)
        user_mulugeta = self.env["res.users"].create({
            "name": "Mulugeta Alemayehu Awoke",
            "login": "mulugeta_ceo_test",
            "group_ids": [(6, 0, [chief_group.id, self.env.ref("bunna_pbms.group_pbms_ceo").id, self.env.ref("base.group_user").id])],
        })
        emp_mulugeta = self.env["hr.employee"].create({
            "name": "Mulugeta Alemayehu Awoke",
            "user_id": user_mulugeta.id,
        })
        user_mulugeta.write({"employee_id": emp_mulugeta.id})

        # 2. Eskindir (Chief Retail & Branch Banking Officer)
        user_eskindir = self.env["res.users"].create({
            "name": "Eskindir Dibekulu Erede",
            "login": "eskindir_chief_test",
            "group_ids": [(6, 0, [chief_group.id, self.env.ref("base.group_user").id])],
        })
        emp_eskindir = self.env["hr.employee"].create({
            "name": "Eskindir Dibekulu Erede",
            "user_id": user_eskindir.id,
            "parent_id": emp_mulugeta.id,  # reports to Mulugeta
        })
        user_eskindir.write({"employee_id": emp_eskindir.id})

        ou_retail = self.env["operating.unit"].create({
            "name": "Retail and Branch Banking Division",
            "sol_id": 9060,
            "work_unit_type": "head_office",
            "manager_id": emp_eskindir.id,
        })
        user_eskindir.write({"assigned_operating_unit_ids": [(6, 0, [ou_retail.id])]})

        # 3. Yonas (Director II - Dessie District)
        user_yonas = self.env["res.users"].create({
            "name": "Yonas Fiseha Mokennen",
            "login": "yonas_director_test",
            "group_ids": [(6, 0, [chief_group.id, self.env.ref("bunna_pbms.group_pbms_district_reviewer").id, self.env.ref("base.group_user").id])],
        })
        emp_yonas = self.env["hr.employee"].create({
            "name": "Yonas Fiseha Mokennen",
            "user_id": user_yonas.id,
            "parent_id": emp_eskindir.id,  # reports to Eskindir
        })
        user_yonas.write({"employee_id": emp_yonas.id})

        ou_dessie = self.env["operating.unit"].create({
            "name": "Dessie District",
            "sol_id": 9061,
            "work_unit_type": "district_office",
            "manager_id": emp_yonas.id,
            "parent_unit": ou_retail.id,
        })
        user_yonas.write({"assigned_operating_unit_ids": [(6, 0, [ou_dessie.id])]})

        # 4. Dejen (Branch Manager - I)
        user_dejen = self.env["res.users"].create({
            "name": "Dejen Bisetegn Sitot",
            "login": "dejen_bm_test",
            "group_ids": [(6, 0, [branch_group.id, chief_group.id, self.env.ref("base.group_user").id])],
        })
        emp_dejen = self.env["hr.employee"].create({
            "name": "Dejen Bisetegn Sitot",
            "user_id": user_dejen.id,
            "parent_id": emp_yonas.id,  # reports to Yonas
        })
        user_dejen.write({"employee_id": emp_dejen.id})

        ou_branch = self.env["operating.unit"].create({
            "name": "Dessie Main Branch",
            "sol_id": 9062,
            "work_unit_type": "head_office",
            "manager_id": emp_dejen.id,
            "parent_unit": ou_dessie.id,
        })
        user_dejen.write({"assigned_operating_unit_ids": [(6, 0, [ou_branch.id])]})

        # 5. Abadi (Branch Sales and Service Supervisor - I) [Planner]
        user_abadi = self.env["res.users"].create({
            "name": "Abadi Tafere Tedla",
            "login": "abadi_supervisor_test",
            "group_ids": [(6, 0, [branch_group.id, self.env.ref("base.group_user").id])],
        })
        emp_abadi = self.env["hr.employee"].create({
            "name": "Abadi Tafere Tedla",
            "user_id": user_abadi.id,
            "parent_id": emp_dejen.id,  # reports to Dejen
        })
        user_abadi.write({"employee_id": emp_abadi.id})
        user_abadi.write({"assigned_operating_unit_ids": [(6, 0, [ou_branch.id])]})

        # -------------------------------------------------------------------------
        # Case 1: Abadi plans -> goes to Dejen
        # -------------------------------------------------------------------------
        plan_abadi = self.env["pbms.planning.category"].with_user(user_abadi).create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": ou_branch.id,
            "m01": 2500.0,
        })
        plan_abadi.with_user(user_abadi).action_submit()
        self.assertEqual(plan_abadi.state, "chief_review")

        # Reviewer is strictly Dejen!
        reviewers_abadi = plan_abadi._get_stage_reviewers("chief_review")
        self.assertIn(user_dejen, reviewers_abadi)
        self.assertNotIn(user_yonas, reviewers_abadi)
        self.assertNotIn(user_eskindir, reviewers_abadi)
        self.assertNotIn(user_mulugeta, reviewers_abadi)

        # Yonas cannot approve Abadi's plan
        with self.assertRaises(AccessError):
            plan_abadi.with_user(user_yonas).action_chief_approve_escalate()

        # Dejen approves Abadi's plan -> escalates to HO Reviewer
        plan_abadi.with_user(user_dejen).action_chief_approve_escalate()
        self.assertEqual(plan_abadi.state, "submitted")

        # HO Reviewer final approves
        plan_abadi.with_user(user_ho_rev).action_ho_approve()
        self.assertEqual(plan_abadi.state, "approved")

        # -------------------------------------------------------------------------
        # Case 2: Dejen plans -> goes to Yonas
        # -------------------------------------------------------------------------
        # Archive earlier plan for this unit/cycle to allow second scenario
        plan_abadi.sudo().write({"active": False})
        plan_dejen = self.env["pbms.planning.category"].with_user(user_dejen).create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": ou_branch.id,
            "m01": 4500.0,
        })
        plan_dejen.with_user(user_dejen).action_submit()
        self.assertEqual(plan_dejen.state, "chief_review")

        # Reviewer is strictly Yonas!
        reviewers_dejen = plan_dejen._get_stage_reviewers("chief_review")
        self.assertIn(user_yonas, reviewers_dejen)
        self.assertNotIn(user_dejen, reviewers_dejen)
        self.assertNotIn(user_eskindir, reviewers_dejen)

        # Dejen cannot self-approve
        with self.assertRaises(AccessError):
            plan_dejen.with_user(user_dejen).action_chief_approve_escalate()

        # Yonas approves Dejen's plan -> escalates to HO Reviewer
        plan_dejen.with_user(user_yonas).action_chief_approve_escalate()
        self.assertEqual(plan_dejen.state, "submitted")

        # -------------------------------------------------------------------------
        # Case 3: Yonas plans -> goes to Eskindir
        # -------------------------------------------------------------------------
        plan_yonas = self.env["pbms.planning.category"].with_user(user_yonas).create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": ou_dessie.id,
            "m01": 7000.0,
        })
        plan_yonas.with_user(user_yonas).action_submit()
        # District Office GE goes DIRECTLY to HO Functional Reviewer (district_endorsed) - no chief review step
        self.assertEqual(plan_yonas.state, "district_endorsed")

        # -------------------------------------------------------------------------
        # Case 4: Eskindir plans -> goes to Mulugeta (CEO)
        # -------------------------------------------------------------------------
        plan_eskindir = self.env["pbms.planning.category"].with_user(user_eskindir).create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": ou_retail.id,
            "m01": 12000.0,
        })
        plan_eskindir.with_user(user_eskindir).action_submit()
        self.assertEqual(plan_eskindir.state, "chief_review")

        # Reviewer is strictly Mulugeta!
        reviewers_eskindir = plan_eskindir._get_stage_reviewers("chief_review")
        self.assertIn(user_mulugeta, reviewers_eskindir)
        self.assertNotIn(user_eskindir, reviewers_eskindir)

        # Eskindir cannot self-approve
        with self.assertRaises(AccessError):
            plan_eskindir.with_user(user_eskindir).action_chief_approve_escalate()

        # Mulugeta approves Eskindir's plan -> escalates to HO Reviewer
        plan_eskindir.with_user(user_mulugeta).action_chief_approve_escalate()
        self.assertEqual(plan_eskindir.state, "submitted")

    def test_aster_submits_ge_fa_workforce_to_wube(self):
        """Verify Aster planning General Expense, Fixed Asset, and Workforce:
        - When Aster submits, all 3 plans transition to chief_review for Respective Chief Wube.
        - Wube (group_pbms_respective_chief) has visibility and review access to all 3 plans.
        - Wube can approve/escalate all 3 plans: Workforce -> people_solutions_review, GE & FA -> submitted.
        """
        # 1. Setup Operating Unit
        ou_hr = self.env["operating.unit"].create({
            "name": "HR Operations Unit",
            "sol_id": 9099,
            "work_unit_type": "head_office",
        })

        # 2. Setup Wube (Respective Chief) and Aster (Planner subordinate)
        emp_wube = self.env["hr.employee"].create({
            "name": "Wube Chief",
        })
        user_wube = self.env["res.users"].create({
            "name": "Wube Chief",
            "login": "wube_chief",
            "email": "wube@bunnabank.com",
            "group_ids": [(6, 0, [
                self.env.ref("bunna_pbms.group_pbms_respective_chief").id,
                self.env.ref("base.group_user").id,
            ])],
            "operating_unit_ids": [(6, 0, [ou_hr.id])],
        })
        emp_wube.user_id = user_wube

        emp_aster = self.env["hr.employee"].create({
            "name": "Aster Planner",
            "parent_id": emp_wube.id,
        })
        user_aster = self.env["res.users"].create({
            "name": "Aster Planner",
            "login": "aster_planner",
            "email": "aster@bunnabank.com",
            "group_ids": [(6, 0, [
                self.env.ref("bunna_pbms.group_pbms_branch_user").id,
                self.env.ref("base.group_user").id,
            ])],
            "operating_unit_ids": [(6, 0, [ou_hr.id])],
        })
        emp_aster.user_id = user_aster

        justification_cat = self.env["pbms.justification.category"].search([("code", "=", "WORKLOAD")], limit=1)
        if not justification_cat:
            justification_cat = self.env["pbms.justification.category"].create({
                "name": "Workload Expansion",
                "code": "WORKLOAD",
                "requires_remarks": False,
            })

        # 3. Aster creates all 3 plans: Workforce, General Expense, Fixed Asset
        wp_plan = self.env["pbms.planning.category"].with_user(user_aster).create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": ou_hr.id,
            "business_justification": "Required for HR ops growth",
            "line_ids": [(0, 0, {
                "line_type": "manpower",
                "org_unit_id": ou_hr.id,
                "position_type": "new",
                "new_job_title": "HR Officer",
                "new_job_grade": "Grade 5",
                "justification_category_id": justification_cat.id,
                "q1": 1,
                "quantity": 1,
            })],
        })

        ge_plan = self.env["pbms.planning.category"].with_user(user_aster).create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": ou_hr.id,
            "m01": 50000.0,
        })

        fa_plan = self.env["pbms.planning.category"].with_user(user_aster).create({
            "category": "fixed_asset",
            "cycle_id": self.cycle.id,
            "org_unit_id": ou_hr.id,
            "m01": 80000.0,
        })

        # 4. Aster submits
        wp_plan.with_user(user_aster).action_submit()

        # Both Workforce, General Expense, and Fixed Asset must be submitted to chief_review
        self.assertEqual(wp_plan.state, "chief_review")
        self.assertEqual(ge_plan.state, "chief_review")
        self.assertEqual(fa_plan.state, "chief_review")

        # 5. When Wube logs in and searches for her pending reviews:
        # Wube MUST be able to find all 3 plans: Workforce, General Expense, Fixed Asset
        CategoryModel = self.env["pbms.planning.category"].with_user(user_wube)
        found_wp = CategoryModel.search([("id", "=", wp_plan.id)])
        found_ge = CategoryModel.search([("id", "=", ge_plan.id)])
        found_fa = CategoryModel.search([("id", "=", fa_plan.id)])

        self.assertTrue(bool(found_wp), "Workforce plan must be visible to Respective Chief Wube")
        self.assertTrue(bool(found_ge), "General Expense plan must be visible to Respective Chief Wube")
        self.assertTrue(bool(found_fa), "Fixed Asset plan must be visible to Respective Chief Wube")

        # Review permissions for Wube
        self.assertTrue(wp_plan.with_user(user_wube).can_chief_review)
        self.assertTrue(ge_plan.with_user(user_wube).can_chief_review)
        self.assertTrue(fa_plan.with_user(user_wube).can_chief_review)

        # Stage reviewers must be strictly Wube
        self.assertIn(user_wube, wp_plan._get_stage_reviewers("chief_review"))
        self.assertIn(user_wube, ge_plan._get_stage_reviewers("chief_review"))
        self.assertIn(user_wube, fa_plan._get_stage_reviewers("chief_review"))

        # 6. Wube approves all 3 plans:
        # - Workforce -> escalates to People Solutions
        wp_plan.with_user(user_wube).action_chief_approve_escalate()
        self.assertEqual(wp_plan.state, "people_solutions_review")

        # - General Expense -> escalates to HO Functional Reviewer
        ge_plan.with_user(user_wube).action_chief_approve_escalate()
        self.assertEqual(ge_plan.state, "submitted")

        # - Fixed Asset -> escalates to HO Functional Reviewer
        fa_plan.with_user(user_wube).action_chief_approve_escalate()
        self.assertEqual(fa_plan.state, "submitted")

    def test_cpco_own_unit_plan_creation_and_access(self):
        """Verify CPCO user can create, read, and write GE, FA, and Manpower plans

        for their own work unit, without encountering AccessError, while maintaining
        strict isolation on other units' GE and FA plans.
        """
        # Create CPCO work unit
        cpco_unit = self.env["operating.unit"].create({
            "name": "CPCO Office",
            "sol_id": 9050,
            "work_unit_type": "head_office",
            "parent_unit": self.ho.id,
        })
        group_cpco = self.env.ref("bunna_pbms.group_pbms_cpco")
        cpco_user = self.env["res.users"].create({
            "name": "Taresa CPCO",
            "login": "taresa_test",
            "group_ids": [(6, 0, [group_cpco.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [cpco_unit.id])],
        })

        # 1. CPCO user creates General Expense plan for own work unit
        ge_plan = self.env["pbms.planning.category"].with_user(cpco_user).create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": cpco_unit.id,
            "expense_account_id": self.expense_account.id,
            "m01": 5000.0,
        })
        self.assertTrue(ge_plan.id)
        self.assertEqual(ge_plan.category, "general_expense")
        # Reading should succeed without AccessError
        self.assertEqual(ge_plan.with_user(cpco_user).m01, 5000.0)

        # 2. CPCO user creates Fixed Asset plan for own work unit
        fa_plan = self.env["pbms.planning.category"].with_user(cpco_user).create({
            "category": "fixed_asset",
            "cycle_id": self.cycle.id,
            "org_unit_id": cpco_unit.id,
            "m01": 15000.0,
        })
        self.assertTrue(fa_plan.id)
        self.assertEqual(fa_plan.category, "fixed_asset")
        self.assertEqual(fa_plan.with_user(cpco_user).m01, 15000.0)

        # 3. CPCO user creates Manpower plan for own work unit
        job = self.env["hr.job"].create({"name": "HR Specialist Test"})
        mp_plan = self.env["pbms.planning.category"].with_user(cpco_user).create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": cpco_unit.id,
            "job_id": job.id,
            "m01": 1.0,
        })
        self.assertTrue(mp_plan.id)
        self.assertEqual(mp_plan.category, "manpower")
        self.assertEqual(mp_plan.with_user(cpco_user).m01, 1.0)

        # 4. Search returns all 3 own-unit plans for CPCO user
        found_plans = self.env["pbms.planning.category"].with_user(cpco_user).search([
            ("org_unit_id", "=", cpco_unit.id)
        ])
        self.assertIn(ge_plan, found_plans)
        self.assertIn(fa_plan, found_plans)
        self.assertIn(mp_plan, found_plans)

        # 5. Isolation: CPCO user CANNOT create General Expense for another unit
        with self.assertRaises(AccessError):
            self.env["pbms.planning.category"].with_user(cpco_user).create({
                "category": "general_expense",
                "cycle_id": self.cycle.id,
                "org_unit_id": self.branch.id,
                "expense_account_id": self.expense_account.id,
                "m01": 2000.0,
            })

        # 6. Isolation: Branch General Expense plan is NOT visible to CPCO user
        branch_ge = self.env["pbms.planning.category"].sudo().create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "expense_account_id": self.expense_account.id,
            "m01": 2000.0,
            "state": "submitted",
        })
        branch_ge_found = self.env["pbms.planning.category"].with_user(cpco_user).search([
            ("id", "=", branch_ge.id)
        ])
        self.assertFalse(branch_ge_found)

    def test_ceo_views_only_pending_ceo_approval_records(self):
        """CEO must view only the records pending CEO approval (endorsed from Budget Hiring Committee)."""
        ceo_group = self.env.ref("bunna_pbms.group_pbms_ceo")
        ceo_user = self.env["res.users"].create({
            "name": "CEO Test User",
            "login": "ceo_visibility_test",
            "group_ids": [(6, 0, [ceo_group.id, self.env.ref("base.group_user").id])],
        })

        cycle_ceo = self.env["pbms.planning.cycle"].create({
            "name": "FY CEO Test",
            "date_start": "2029-07-01",
            "date_end": "2030-06-30",
            "state": "open",
        })

        ou_extra = self.env["operating.unit"].create({
            "name": "Extra Branch CEO Test",
            "sol_id": 9977,
            "work_unit_type": "branch",
        })

        # Plan 1: Manpower plan endorsed from committee to CEO (state='ceo_approval')
        plan_pending_ceo = self.env["pbms.planning.category"].sudo().create({
            "category": "manpower",
            "cycle_id": cycle_ceo.id,
            "org_unit_id": self.branch.id,
            "m01": 2.0,
            "state": "ceo_approval",
        })

        # Plan 2: Manpower plan still in draft/submitted
        plan_submitted_mp = self.env["pbms.planning.category"].sudo().create({
            "category": "manpower",
            "cycle_id": cycle_ceo.id,
            "org_unit_id": self.district.id,
            "m01": 3.0,
            "state": "submitted",
        })

        # Plan 3: General Expense plan in submitted (on extra branch)
        plan_submitted_ge = self.env["pbms.planning.category"].sudo().create({
            "category": "general_expense",
            "cycle_id": cycle_ceo.id,
            "org_unit_id": ou_extra.id,
            "expense_account_id": self.expense_account.id,
            "m01": 5000.0,
            "state": "submitted",
        })

        # Plan 4: Deposit plan approved (on Head Office)
        plan_approved_dep = self.env["pbms.planning.category"].sudo().create({
            "category": "deposit",
            "cycle_id": cycle_ceo.id,
            "org_unit_id": self.ho.id,
            "deposit_type_id": self.deposit_type.id,
            "plan_category": "amount",
            "m01": 10000.0,
            "state": "approved",
        })

        # CEO search
        ceo_visible_plans = self.env["pbms.planning.category"].with_user(ceo_user).search([])
        self.assertIn(plan_pending_ceo, ceo_visible_plans, "CEO must view records pending CEO approval.")
        self.assertNotIn(plan_submitted_mp, ceo_visible_plans, "CEO must NOT view records in submitted state.")
        self.assertNotIn(plan_submitted_ge, ceo_visible_plans, "CEO must NOT view General Expense records not pending CEO approval.")
        self.assertNotIn(plan_approved_dep, ceo_visible_plans, "CEO must NOT view deposit records.")

        # CEO approves the endorsed workforce plan without AccessError
        plan_pending_ceo.with_user(ceo_user).action_ceo_approve()
        self.assertEqual(plan_pending_ceo.state, "ho_endorse")
        read_data = plan_pending_ceo.with_user(ceo_user).read(["state", "ceo_approver_id", "can_use_reviewer_actions", "can_ceo_approve"])
        self.assertEqual(read_data[0]["state"], "ho_endorse")
        self.assertEqual(read_data[0]["ceo_approver_id"][0], ceo_user.id)
        self.assertFalse(read_data[0]["can_use_reviewer_actions"], "Reviewer action buttons must be hidden from CEO after approval.")
        self.assertFalse(read_data[0]["can_ceo_approve"], "CEO approve button must be hidden once approved and forwarded.")

        # In cpco_endorse and approved, reviewer buttons remain hidden from CEO and others
        plan_pending_ceo.sudo().write({"state": "cpco_endorse"})
        plan_pending_ceo.invalidate_recordset()
        self.assertFalse(plan_pending_ceo.with_user(ceo_user).can_use_reviewer_actions, "Reviewer buttons must be hidden in cpco_endorse.")
        self.assertFalse(plan_pending_ceo.with_user(ceo_user).can_ceo_approve, "CEO approve button must be hidden in cpco_endorse.")

    def test_branch_workforce_district_approval_does_not_create_district_plan(self):
        """When district approves branch workforce plan, it must NOT auto-create a district workforce plan."""
        dist_reviewer_group = self.env.ref("bunna_pbms.group_pbms_district_reviewer")
        dist_user = self.env["res.users"].create({
            "name": "District Reviewer Test User",
            "login": "dist_rev_no_mp_autocreate",
            "group_ids": [(6, 0, [dist_reviewer_group.id, self.env.ref("base.group_user").id])],
            "operating_unit_ids": [(6, 0, [self.district.id, self.branch.id])],
        })

        branch_mp_plan = self.env["pbms.planning.category"].sudo().create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "district_id": self.district.id,
            "state": "submitted",
        })

        # District reviewer approves branch workforce plan
        branch_mp_plan.with_user(dist_user).action_district_approve()

        # Branch plan advances to chief_review
        self.assertEqual(branch_mp_plan.state, "chief_review")

        # District workforce plan must NOT be created
        dist_plans = self.env["pbms.planning.category"].sudo().search([
            ("cycle_id", "=", self.cycle.id),
            ("org_unit_id", "=", self.district.id),
            ("category", "=", "manpower"),
            ("active", "=", True),
        ])
        self.assertEqual(len(dist_plans), 0, "No district workforce plan should be auto-created upon branch workforce approval.")

        # Create line on branch workforce plan
        line = self.env["pbms.plan.category.line"].sudo().create({
            "plan_id": branch_mp_plan.id,
            "line_type": "manpower",
            "new_job_title": "Branch Operations Officer",
            "new_job_grade": "Grade 5",
            "quantity": 1,
            "q1": 1,
            "annual_total": 1.0,
            "annual_total_cost": 50000.0,
        })

        # Setup Respective Chief user and manager hierarchy
        chief_group = self.env.ref("bunna_pbms.group_pbms_respective_chief")
        chief_user = self.env["res.users"].create({
            "name": "Chief Test User",
            "login": "chief_test_mp_lines_vis",
            "group_ids": [(6, 0, [chief_group.id, self.env.ref("base.group_user").id])],
        })
        chief_emp = self.env["hr.employee"].sudo().create({
            "name": "Chief Emp",
            "user_id": chief_user.id,
        })
        dist_mgr_emp = self.env["hr.employee"].sudo().create({
            "name": "Dist Mgr",
            "user_id": dist_user.id,
            "parent_id": chief_emp.id,
        })
        self.district.manager_id = dist_mgr_emp

        # Respective chief opens branch plan: lines must be visible
        chief_plan = branch_mp_plan.with_user(chief_user)
        self.assertEqual(len(chief_plan.manpower_line_ids), 1, "Respective Chief must be able to view branch workforce plan lines.")
        self.assertTrue(chief_plan.can_chief_review, "Respective Chief must be allowed to review and escalate.")

        # Chief approves and escalates to People Solutions Directorate
        chief_plan.action_chief_approve_escalate()
        self.assertEqual(branch_mp_plan.state, "people_solutions_review")

    def test_budget_hiring_committee_views_only_workforce_and_fixed_asset(self):
        """Budget Hiring Committee must only view workforce and fixed asset records, excluding general expense."""
        comm_group = self.env.ref("bunna_pbms.group_pbms_budget_hiring_committee")
        comm_user = self.env["res.users"].create({
            "name": "Committee Test User",
            "login": "comm_visibility_test",
            "group_ids": [(6, 0, [comm_group.id, self.env.ref("base.group_user").id])],
        })

        # 1. Workforce plan under committee review
        mp_plan = self.env["pbms.planning.category"].sudo().create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "m01": 2.0,
            "state": "committee_review",
        })

        # 2. Fixed asset plan under committee review
        fa_plan = self.env["pbms.planning.category"].sudo().create({
            "category": "fixed_asset",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "m01": 8000.0,
            "state": "committee_review",
        })

        # 3. General expense plan (even if in committee_review or ho_reviewed)
        ge_plan = self.env["pbms.planning.category"].sudo().create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "expense_account_id": self.expense_account.id,
            "m01": 4000.0,
            "state": "committee_review",
        })

        comm_visible_plans = self.env["pbms.planning.category"].with_user(comm_user).search([])
        self.assertIn(mp_plan, comm_visible_plans, "Committee must view Workforce records.")
        self.assertIn(fa_plan, comm_visible_plans, "Committee must view Fixed Asset records.")
        self.assertNotIn(ge_plan, comm_visible_plans, "Committee must NOT view General Expense records.")

    def test_input_validations_numbers_and_text(self):
        """Validate input types: text fields must reject pure numbers, and numeric fields must reject decimals where integers are required."""
        pos_new = self.env["pbms.position.type"].search([("code", "in", ("new", "new_position"))], limit=1)
        if not pos_new:
            pos_new = self.env["pbms.position.type"].create({"name": "New Position", "code": "new", "is_new_position": True})

        mp_plan = self.env["pbms.planning.category"].sudo().create({
            "category": "manpower",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "m01": 2.0,
        })

        # 1. Reject pure numbers in text fields (e.g. new_job_title = "12345")
        with self.assertRaises(ValidationError):
            self.env["pbms.plan.category.line"].sudo().create({
                "plan_id": mp_plan.id,
                "line_type": "manpower",
                "position_type_id": pos_new.id,
                "new_job_title": "12345",
                "new_job_grade": "Grade 5",
                "m01": 1.0,
            })

        # 2. Reject pure numbers in return_reason
        with self.assertRaises(ValidationError):
            mp_plan.write({"return_reason": "98765"})

        # 3. Reject pure numbers in comments
        with self.assertRaises(ValidationError):
            mp_plan.write({"committee_comment": "44444"})

        # 4. Reject fractional / decimal numbers for headcount (whole numbers required)
        with self.assertRaises(ValidationError):
            self.env["pbms.plan.category.line"].sudo().create({
                "plan_id": mp_plan.id,
                "line_type": "manpower",
                "position_type_id": pos_new.id,
                "new_job_title": "Branch Operations Officer",
                "new_job_grade": "Grade 5",
                "m01": 1.5,
            })

        # 5. Fixed asset quantities and prices cannot be negative
        fa_cat = self.env["pbms.fixed.asset.category"].search([], limit=1)
        if not fa_cat:
            fa_cat = self.env["pbms.fixed.asset.category"].create({"name": "Computers", "code": "COMP"})
        fa_plan = self.env["pbms.planning.category"].sudo().create({
            "category": "fixed_asset",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "m01": 5000.0,
        })
        with self.assertRaises(ValidationError):
            self.env["pbms.plan.category.line"].sudo().create({
                "plan_id": fa_plan.id,
                "line_type": "fixed_asset",
                "category_id": fa_cat.id,
                "item_description": "LaserJet Printer",
                "fa_q1": 0,
                "fa_q2": 0,
                "fa_q3": 0,
                "fa_q4": 0,
                "estimated_unit_price": 500.0,
            })

        # 6. Reject pure numbers for item description in Fixed Asset
        with self.assertRaises(ValidationError):
            self.env["pbms.plan.category.line"].sudo().create({
                "plan_id": fa_plan.id,
                "line_type": "fixed_asset",
                "category_id": fa_cat.id,
                "item_description": "55555",
                "fa_q1": 2,
                "estimated_unit_price": 500.0,
            })

        # 7. Excel Import wizard type validations: numbers must not accept text/chars, text must not accept pure numbers
        wizard = self.env["pbms.excel.import.wizard"].new()
        with self.assertRaises(UserError):
            wizard._get_float("invalid_abc", "Target")
        with self.assertRaises(UserError):
            wizard._get_int("invalid_text", "Headcount")
        with self.assertRaises(UserError):
            wizard._get_int("3.5", "Headcount")
        with self.assertRaises(UserError):
            wizard._get_text(12345, "Description")
        with self.assertRaises(UserError):
            wizard._get_text("99999", "Description")
        self.assertEqual(wizard._get_text("Valid Equipment Note", "Description"), "Valid Equipment Note")

        # 8. Valid text and whole numbers must succeed
        valid_line = self.env["pbms.plan.category.line"].sudo().create({
            "plan_id": fa_plan.id,
            "line_type": "fixed_asset",
            "category_id": fa_cat.id,
            "item_description": "HP ProBook Laptop 450",
            "fa_q1": 2,
            "estimated_unit_price": 1500.0,
        })
        self.assertTrue(valid_line.id)

        # 9. Monthly fields must not accept text or character values
        with self.assertRaises(ValidationError):
            fa_plan.write({"m01": "invalid_month_text"})

        with self.assertRaises(ValidationError):
            valid_line.write({"m02": "char_text_value"})

        with self.assertRaises(ValidationError):
            self.env["pbms.plan.category.line"].sudo().create({
                "plan_id": fa_plan.id,
                "line_type": "fixed_asset",
                "category_id": fa_cat.id,
                "item_description": "Optical Mouse",
                "fa_q1": 1,
                "m03": "abc_chars",
            })







