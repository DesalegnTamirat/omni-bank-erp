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
        self.assertEqual(dist_plan.state, "submitted")

        dist_plan.action_district_approve()
        self.assertEqual(dist_plan.state, "district_endorsed")

        dist_plan.action_ho_review()
        self.assertEqual(dist_plan.state, "ho_reviewed")

    def test_general_expense_district_first_workflow(self):
        """Branch General Expense and Fixed Asset plans must be approved by the District
        Reviewer first before Head Office Functional Reviewers can view or submit them to committee."""
        plan = self.env["pbms.planning.category"].create({
            "category": "general_expense",
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "district_id": self.district.id,
            "m01": 500.0,
        })
        plan.action_submit()
        self.assertEqual(plan.state, "submitted")

        # Branch plan in 'submitted' state cannot be submitted to committee before district approval
        with self.assertRaises(UserError):
            plan.action_submit_to_committee()

        # District Reviewer approves
        plan.action_district_approve()
        self.assertEqual(plan.state, "district_approved")

        # Head Office Functional Reviewer can now submit to committee
        plan.action_submit_to_committee()
        self.assertEqual(plan.state, "committee_review")

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
                "base_type": "new_account",
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
        plan = self.env["pbms.planning.category"].create({
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
        with self.assertRaises(ValidationError):
            self.env["pbms.planning.category"].create({
                "category": "fx",
                "cycle_id": self.cycle.id,
                "org_unit_id": self.branch.id,  # branch, not head_office
                "fx_source_type": "remittance_swift",
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
        with self.assertRaises(ValidationError):
            plan.action_submit()

    def test_manpower_plan_submits_with_lines(self):
        plan = self.env["pbms.planning.category"].create({
            "category": "manpower",
            "cycle_id": self.cycle.id, "org_unit_id": self.branch.id,
            "line_ids": [(0, 0, {
                "position_type": "new",
                "employment_type": "permanent",
                "job_title": "Customer Service Officer",
                "quantity": 2,
                "date_needed": "2026-09-01",
                "reason": "Branch expansion.",
            })],
        })
        plan.action_submit()
        self.assertEqual(plan.state, "submitted")
        with self.assertRaises(UserError):
            plan.action_return()  # no return_reason set
        plan.return_reason = "Figures inconsistent with prior year actuals."
        plan.action_return()
        self.assertEqual(plan.state, "returned")

    def test_ho_reviewer_bank_wide_access_and_review(self):
        """Test that HO Reviewers have bank-wide access and can edit/review branch plans."""
        plan = self._create_deposit_plan()
        plan.action_submit()
        plan.action_district_approve()
        self.assertEqual(plan.state, "district_approved")

        ho_user = self.env["res.users"].create({
            "name": "HO Reviewer Test User",
            "login": "ho_rev_test",
            "groups_id": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_ho_reviewer").id])],
        })
        plan.with_user(ho_user).action_ho_review()
        self.assertEqual(plan.state, "ho_reviewed")

    def test_manpower_grade_autopopulate_and_new_position(self):
        """Test grade auto-population and line-only saving for new position type."""
        job = self.env["hr.job"].create({"name": "Senior Accountant"})
        grade = self.env["employee.grade"].create({"grade_name": "Grade IX", "base_salary": 15000.0})

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
            "groups_id": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_branch_user").id])],
            "operating_unit_ids": [(6, 0, [self.branch.id])],
        })
        with self.assertRaises(UserError):
            plan.with_user(branch_user).unlink()

        # SPPMD Administrator CAN delete submitted plan
        admin_user = self.env["res.users"].create({
            "name": "SPPMD Admin User",
            "login": "sppmd_admin_user_del",
            "groups_id": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_manager").id])],
        })
        plan.with_user(admin_user).unlink()
        self.assertFalse(plan.exists())

    def test_notification_details_includes_all_enabled_categories(self):
        """Notification metrics table includes all planning categories enabled in planning configuration."""
        plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
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
            "groups_id": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_branch_user").id])],
        })
        admin_user = self.env["res.users"].create({
            "name": "PBMS Admin",
            "login": "admin_planner_test",
            "email": "admin_planner@bunnabank.test",
            "groups_id": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_manager").id])],
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
        """Consolidation aggregates deposit, customer base, fixed asset, and expense from branches to district and HO."""
        fa_cat = self.env["pbms.fixed.asset.category"].create({"name": "IT Equipment", "code": "IT"})
        branch_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.branch.id,
            "category": "deposit",
            "state": "submitted",
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": self.deposit_type.id,
                "m01": 2500.0,
            })],
            "fixed_asset_line_ids": [(0, 0, {
                "line_type": "fixed_asset",
                "category_id": fa_cat.id,
                "item_description": "Desktop Computers",
                "estimated_unit_price": 50000.0,
                "fa_q1": 3,
                "quantity": 3,
            })],
        })

        # Run District Consolidation
        dist_plan = self.env["pbms.planning.category"]._consolidate_district_plan_data(self.cycle, self.district)
        self.assertEqual(len(dist_plan.deposit_line_ids), 1)
        self.assertEqual(dist_plan.deposit_line_ids.m01, 2500.0)
        self.assertEqual(len(dist_plan.fixed_asset_line_ids), 1)
        self.assertEqual(dist_plan.fixed_asset_line_ids.quantity, 3)

        # Run Head Office Bank Consolidation
        ho_plan = self.env["pbms.planning.category"]._consolidate_ho_plan_data(self.cycle, self.ho)
        self.assertEqual(len(ho_plan.deposit_line_ids), 1)
        self.assertEqual(ho_plan.deposit_line_ids.m01, 2500.0)
        self.assertEqual(len(ho_plan.fixed_asset_line_ids), 1)
        self.assertEqual(ho_plan.fixed_asset_line_ids.quantity, 3)

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
        })
        job = self.env["hr.job"].create({
            "name": "Senior Branch Officer",
            "job_grade": grade.id,
        })

        # 2. Create an active employee for branch
        emp = self.env["hr.employee"].create({
            "name": "Test Employee",
            "job_position": job.id,
            "job_grade": grade.id,
            "default_operating_unit_id": self.branch.id,
            "operating_unit_ids": [(6, 0, [self.branch.id])],
            "wage": 10000.0,
        })

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
                "base_salary": 15000.0,
                "pension_rate": 11.0,
                "benefit_factor": 10.0,
                "allowance_monthly": 1000.0,
                "q1": 1,
            })],
        })

        # Verify current staff salary: 10,000 * 12 = 120,000
        self.assertEqual(plan.current_staff_salary_budget, 120000.0)

        # Verify new planned staff cost: monthly = 15000 + 1650 + 1500 + 1000 = 19150; annual unit_cost = 229,800; Q1 = 1 -> 229,800
        mp_line = plan.manpower_line_ids[0]
        self.assertEqual(mp_line.monthly_total_compensation, 19150.0)
        self.assertEqual(mp_line.unit_cost, 229800.0)
        self.assertEqual(mp_line.annual_total_cost, 229800.0)
        self.assertEqual(plan.new_planned_salary_budget, 229800.0)

        # Verify Total Workforce Budget = 120,000 + 229,800 = 349,800.0
        self.assertEqual(plan.total_operating_unit_manpower_budget, 349800.0)

    def test_sppmd_approver_edit_permissions(self):
        """Verify SPPMD Plan Approver can adjust and add requirement lines during review stages."""
        sppmd_approver_group = self.env.ref("bunna_pbms.group_pbms_approver")
        approver_user = self.env["res.users"].create({
            "name": "SPPMD Approver",
            "login": "sppmd_approver_test",
            "groups_id": [(6, 0, [sppmd_approver_group.id, self.env.ref("base.group_user").id])],
            "assigned_operating_unit_ids": [(6, 0, [self.ho.id, self.district.id, self.branch.id])],
        })

        plan = self._create_deposit_plan(state="ho_reviewed")
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


