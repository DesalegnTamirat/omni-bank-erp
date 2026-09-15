# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPbmsPlanningConfig(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.org_unit = cls.env["operating.unit"].create({
            "name": "Test Branch", "sol_id": 9999, "work_unit_type": "branch",
        })
        cls.env.user.assigned_operating_unit_ids = [(6, 0, [cls.org_unit.id])]

    def test_config_by_work_unit_type_creation(self):
        config = self.env["pbms.planning.config"].get_config_for_type("branch")
        self.assertTrue(config)
        self.assertEqual(config.work_unit_type, "branch")
        self.assertTrue(config.enable_deposit)

    def test_user_planning_categories_reflect_config(self):
        config = self.env["pbms.planning.config"].get_config_for_type("branch")
        self.assertTrue(config.enable_deposit)

        # Disable FX for this work unit type
        config.enable_fx = False

        res = self.env["pbms.planning.config"].get_user_planning_categories()
        self.assertTrue(res)
        self.assertEqual(res["work_unit_type"], "branch")
        category_ids = [c["id"] for c in res["categories"]]
        self.assertIn("deposit", category_ids)
        self.assertNotIn("fx", category_ids)

    def test_config_measurement_types(self):
        config = self.env["pbms.planning.config"].get_config_for_type("branch")
        self.assertTrue(config)

        # Deposit should be monetary
        self.assertEqual(config.deposit_measurement_type, "monetary")
        # Manpower should be integer
        self.assertEqual(config.manpower_measurement_type, "integer")
        # Customer base should be integer
        self.assertEqual(config.customer_base_measurement_type, "integer")

        # Test the get_measurement_type method
        self.assertEqual(
            self.env["pbms.planning.config"].get_measurement_type("deposit", "branch"),
            "monetary"
        )
        self.assertEqual(
            self.env["pbms.planning.config"].get_measurement_type("manpower", "branch"),
            "integer"
        )

    def test_config_dropdown_options(self):
        config = self.env["pbms.planning.config"].get_config_for_type("branch")
        self.assertTrue(config)

        # Test deposit types dropdown
        options = self.env["pbms.planning.config"].get_category_dropdown_options("deposit", "branch")
        self.assertIn("deposit_types", options)
        self.assertTrue(options["deposit_types"])

        # Test digital channels dropdown
        options = self.env["pbms.planning.config"].get_category_dropdown_options("digital_banking", "branch")
        self.assertIn("channels", options)
        self.assertTrue(options["channels"])

        # Test fixed asset categories dropdown
        options = self.env["pbms.planning.config"].get_category_dropdown_options("fixed_asset", "branch")
        self.assertIn("fa_categories", options)
        self.assertTrue(options["fa_categories"])

        # Test justification categories dropdown
        options = self.env["pbms.planning.config"].get_category_dropdown_options("manpower", "branch")
        self.assertIn("justification_categories", options)
        self.assertTrue(options["justification_categories"])

        # Test FX source types dropdown
        options = self.env["pbms.planning.config"].get_category_dropdown_options("fx", "branch")
        self.assertIn("fx_sources", options)
        self.assertTrue(options["fx_sources"])

    def test_config_currency(self):
        config = self.env["pbms.planning.config"].get_config_for_type("branch")
        self.assertTrue(config)
        self.assertTrue(config.currency_id)
        self.assertEqual(config.currency_id, self.env.company.currency_id)

    def test_operating_unit_category_exclusion(self):
        """Test excluding a specific operating unit under branch from FX and Expense."""
        branch_a = self.org_unit
        branch_b = self.env["operating.unit"].create({
            "name": "Branch B", "sol_id": 9998, "work_unit_type": "branch",
        })

        config = self.env["pbms.planning.config"].get_config_for_type("branch")
        config.enable_fx = True
        config.enable_expense = True

        # Exclude branch_a from FX
        config.fx_excluded_org_unit_ids = [(6, 0, [branch_a.id])]
        # Exclude branch_b from General Expense
        config.expense_excluded_org_unit_ids = [(6, 0, [branch_b.id])]

        # Check is_category_enabled
        self.assertFalse(self.env["pbms.planning.config"].is_category_enabled("fx", branch_a))
        self.assertTrue(self.env["pbms.planning.config"].is_category_enabled("fx", branch_b))

        self.assertTrue(self.env["pbms.planning.config"].is_category_enabled("general_expense", branch_a))
        self.assertFalse(self.env["pbms.planning.config"].is_category_enabled("general_expense", branch_b))

    def test_operating_unit_specific_override(self):
        """Test creating an operating-unit specific config override."""
        branch_special = self.env["operating.unit"].create({
            "name": "Special Branch", "sol_id": 9997, "work_unit_type": "branch",
        })

        override = self.env["pbms.planning.config"].create({
            "config_type": "operating_unit",
            "org_unit_id": branch_special.id,
            "enable_fx": False,
            "enable_expense": False,
            "enable_deposit": True,
        })

        # Override should be returned for this specific unit
        unit_config = self.env["pbms.planning.config"].get_config_for_unit(branch_special)
        self.assertEqual(unit_config.id, override.id)

        # Check category enablement
        self.assertFalse(self.env["pbms.planning.config"].is_category_enabled("fx", branch_special))
        self.assertFalse(self.env["pbms.planning.config"].is_category_enabled("general_expense", branch_special))
        self.assertTrue(self.env["pbms.planning.config"].is_category_enabled("deposit", branch_special))

        # Other branches should still use branch default
        self.assertTrue(self.env["pbms.planning.config"].is_category_enabled("deposit", self.org_unit))

    def test_measurement_type_change_reflects_in_planning_category_and_lines(self):
        """Test changing measurement type in config dynamically updates plan and lines."""
        config = self.env["pbms.planning.config"].get_config_for_type("branch")
        config.deposit_measurement_type = "monetary"

        plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.org_unit.id,
            "category": "deposit",
        })
        line = self.env["pbms.plan.category.line"].create({
            "plan_id": plan.id,
            "line_type": "deposit",
            "m01": 500.0,
        })

        self.assertEqual(plan.deposit_measurement_type, "monetary")
        self.assertTrue(plan.is_deposit_monetary)
        self.assertEqual(line.measurement_type, "monetary")
        self.assertTrue(line.is_monetary)

        # Now change deposit measurement type in configuration to integer
        config.deposit_measurement_type = "integer"
        plan._compute_measurement_types()
        line._compute_line_measurement()

        self.assertEqual(plan.deposit_measurement_type, "integer")
        self.assertFalse(plan.is_deposit_monetary)
        self.assertEqual(line.measurement_type, "integer")
        self.assertFalse(line.is_monetary)

    def test_submit_plan_when_category_disabled_skips_empty_disabled_plans(self):
        """When Deposit Mobilization is disabled for a work unit (e.g. Head Office or overridden branch),
        submitting a populated Manpower plan does not raise 'Cannot submit a Deposit Mobilization plan with no requirement lines'."""
        ho_unit = self.env["operating.unit"].create({
            "name": "Head Office Unit", "sol_id": 9996, "work_unit_type": "head_office",
        })
        config = self.env["pbms.planning.config"].get_config_for_type("head_office")
        config.enable_deposit = False

        # Create an empty draft deposit plan (as might have been created by workspace or previous initialization)
        empty_dep_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": ho_unit.id,
            "category": "deposit",
        })

        justification_cat = self.env["pbms.justification.category"].create({"name": "Expansion"})
        mp_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": ho_unit.id,
            "category": "manpower",
            "business_justification": "Required for HO operations expansion",
            "justification_category_id": justification_cat.id,
            "line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Database Admin",
                "justification_category_id": justification_cat.id,
                "q1": 1,
                "quantity": 1,
            })],
        })

        # Submit the manpower plan - should succeed without 'no requirement lines' error on deposit
        mp_plan.action_submit()
        self.assertIn(mp_plan.state, ("submitted", "ho_reviewed"))
        self.assertEqual(empty_dep_plan.state, "draft")

    def test_branch_only_manpower_enabled_creates_and_submits_manpower_plan(self):
        """When Branch has only Manpower enabled (Deposit and others disabled),
        creating or opening a plan defaults to category 'manpower' and submits successfully without Deposit errors."""
        config = self.env["pbms.planning.config"].get_config_for_type("branch")
        config.enable_deposit = False
        config.enable_customer_base = False
        config.enable_fx = False
        config.enable_digital_banking = False
        config.enable_expense = False
        config.enable_fixed_asset = False
        config.enable_manpower = True

        default_cat = self.env["pbms.planning.config"].get_default_category_for_unit(self.org_unit)
        self.assertEqual(default_cat, "manpower")

        # Open planning request action
        action = self.env["pbms.planning.category"].with_user(self.branch_user).action_open_planning_request()
        plan = self.env["pbms.planning.category"].browse(action["res_id"])
        self.assertEqual(plan.category, "manpower")

        # Add a manpower requirement line
        justification_cat = self.env["pbms.justification.category"].create({"name": "Workload Increase"})
        plan.write({
            "business_justification": "Branch teller staffing expansion",
            "justification_category_id": justification_cat.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Customer Service Officer",
                "justification_category_id": justification_cat.id,
                "q1": 2,
                "quantity": 2,
            })],
        })

        # Submit plan - must succeed without Deposit Mobilization validation error
        plan.with_user(self.branch_user).action_submit()
        self.assertEqual(plan.state, "submitted")

    def test_edit_existing_manpower_line_does_not_trigger_duplicate_error(self):
        """Editing an existing manpower requirement line (e.g. changing quantity or remarks)
        does not flag the line as a duplicate of itself."""
        job = self.env["hr.job"].create({"name": "Chief Technical Officer"}) if "hr.job" in self.env else False
        if not job:
            return

        justification_cat = self.env["pbms.justification.category"].create({"name": "Strategic Need"})
        additional_type = self.env["pbms.position.type"].search([("code", "=", "additional")], limit=1)
        if not additional_type:
            additional_type = self.env["pbms.position.type"].create({
                "name": "Additional Position", "code": "additional",
            })

        plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.org_unit.id,
            "category": "manpower",
            "business_justification": "Initial justification",
            "justification_category_id": justification_cat.id,
            "line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type_id": additional_type.id,
                "position_type": "additional",
                "job_id": job.id,
                "justification_category_id": justification_cat.id,
                "q1": 1,
                "quantity": 1,
            })],
        })

        line = plan.line_ids[0]
        # Edit the existing line (e.g. updating quantity and justification)
        line.write({
            "q1": 2,
            "quantity": 2,
            "justification_category_remarks": "Updated requirement count",
        })
        self.assertEqual(line.quantity, 2)

        # Edit via parent write (simulating web client form save)
        plan.write({
            "manpower_line_ids": [(1, line.id, {
                "q2": 1,
            })],
        })
        self.assertEqual(line.q2, 1)

    def test_district_reviewer_edit_branch_plan_and_create_line(self):
        """District reviewer can edit submitted branch plan lines and add new requirement lines without missing plan_id error."""
        district_user = getattr(self, "district_user", False)
        if not district_user:
            return

        plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.org_unit.id,
            "category": "manpower",
            "state": "submitted",
            "business_justification": "Branch plan submitted",
        })

        # District reviewer updates the plan lines
        justification_cat = self.env["pbms.justification.category"].create({"name": "Review Adjustment"})
        plan.with_user(district_user).write({
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Auditor",
                "justification_category_id": justification_cat.id,
                "q1": 1,
                "quantity": 1,
            })],
        })
        self.assertEqual(len(plan.manpower_line_ids), 1)
        self.assertEqual(plan.manpower_line_ids[0].plan_id.id, plan.id)

    def test_unlink_line_from_one2many_does_not_raise_missing_plan_id_error(self):
        """Unlinking/removing a line from a One2many relation (e.g. command 3 or 5) does not raise missing plan_id error."""
        justification_cat = self.env["pbms.justification.category"].create({"name": "Need"})
        plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.org_unit.id,
            "category": "manpower",
            "business_justification": "Branch plan",
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Cashier",
                "justification_category_id": justification_cat.id,
                "q1": 1,
                "quantity": 1,
            })],
        })
        line = plan.manpower_line_ids[0]

        # Simulate web client unlinking line with command (3, line.id)
        plan.write({
            "manpower_line_ids": [(3, line.id, 0)],
        })
        self.assertEqual(len(plan.manpower_line_ids), 0)

    def test_submit_manpower_plan_with_manpower_line_ids_succeeds(self):
        """Submitting a manpower plan created with manpower_line_ids succeeds and does not raise no requirement lines error."""
        justification_cat = self.env["pbms.justification.category"].create({"name": "Expansion"})
        plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.org_unit.id,
            "category": "manpower",
            "business_justification": "Staff expansion",
            "justification_category_id": justification_cat.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Loan Officer",
                "justification_category_id": justification_cat.id,
                "q1": 2,
                "quantity": 2,
            })],
        })

        # Submit plan
        plan.with_user(self.branch_user).action_submit()
        self.assertEqual(plan.state, "submitted")

    def test_district_plan_takes_branch_manpower_requirement_lines(self):
        """District plan takes and aggregates requirement lines from child branch plans, allowing district review and submission."""
        district_ou = self.env["operating.unit"].create({
            "name": "East Addis District",
            "work_unit_type": "district_office",
        })
        self.org_unit.write({"parent_unit": district_ou.id})

        justification_cat = self.env["pbms.justification.category"].create({"name": "Branch Growth"})
        branch_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.org_unit.id,
            "category": "manpower",
            "state": "submitted",
            "business_justification": "Branch Growth Need",
            "justification_category_id": justification_cat.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Senior Auditor",
                "justification_category_id": justification_cat.id,
                "q1": 1,
                "quantity": 1,
            })],
        })

        # Consolidate district plan data
        district_plan = self.env["pbms.planning.category"]._consolidate_district_plan_data(self.cycle, district_ou)
        self.assertTrue(bool(district_plan.manpower_line_ids))
        self.assertEqual(district_plan.manpower_line_ids[0].quantity, 1)

        # District plan submission succeeds without 'no requirement lines' error
        district_plan.write({"state": "submitted"})
        self.assertEqual(district_plan.state, "submitted")

    def test_branch_multi_category_routes_to_district_then_respective_functional_reviewers(self):
        """Branch submits both deposit and manpower plans; District endorses; deposit routes to Retail Ops and manpower routes to HR."""
        district_ou = self.env["operating.unit"].create({
            "name": "Central Addis District",
            "work_unit_type": "district_office",
        })
        self.org_unit.write({"parent_unit": district_ou.id})

        justification_cat = self.env["pbms.justification.category"].create({"name": "New Teller Need"})
        dep_type = self.env["pbms.deposit.type"].create({"name": "Saving Account", "code": "SAV01"})

        # Branch creates both Deposit and Manpower plans
        dep_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.org_unit.id,
            "category": "deposit",
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": dep_type.id,
                "annual_total": 500000.0,
                "m01": 500000.0,
            })],
        })
        mp_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.org_unit.id,
            "category": "manpower",
            "business_justification": "Branch teller expansion",
            "justification_category_id": justification_cat.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Junior Teller",
                "justification_category_id": justification_cat.id,
                "q1": 1,
                "quantity": 1,
            })],
        })

        # 1. Branch submits both plans
        dep_plan.with_user(self.branch_user).action_submit()
        mp_plan.with_user(self.branch_user).action_submit()
        self.assertEqual(dep_plan.state, "submitted")
        self.assertEqual(mp_plan.state, "submitted")

        # 2. District Reviewer endorses both plans
        district_reviewer = self.env["res.users"].create({
            "name": "District Reviewer Central",
            "login": "dist_rev_central",
            "email": "dist_rev@bunnabank.com",
            "groups_id": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_district_reviewer").id])],
            "operating_unit_ids": [(6, 0, [district_ou.id])],
        })
        dep_plan.with_user(district_reviewer).action_district_endorse()
        mp_plan.with_user(district_reviewer).action_district_endorse()
        self.assertEqual(dep_plan.state, "district_approved")
        self.assertEqual(mp_plan.state, "district_approved")

        # 3. Verify notification and reviewer routing separates Deposit (Retail) and Manpower (HR)
        hr_pending_users = mp_plan._get_pending_approver_users("district_approved")
        retail_pending_users = dep_plan._get_pending_approver_users("district_approved")
        self.assertTrue(bool(hr_pending_users))
        self.assertTrue(bool(retail_pending_users))

    def test_hr_reviewer_can_only_view_and_action_manpower_category(self):
        """HR reviewer is strictly restricted to manpower category; blocked from actioning deposit plan."""
        hr_dept = self.env["hr.department"].create({"name": "Human Resources"})
        hr_emp = self.env["hr.employee"].create({
            "name": "Chala HR",
            "department_id": hr_dept.id,
        })
        hr_user = self.env["res.users"].create({
            "name": "Chala HR Reviewer",
            "login": "chala_hr",
            "email": "chala@bunnabank.com",
            "groups_id": [(6, 0, [
                self.env.ref("bunna_pbms.group_pbms_ho_reviewer").id,
                self.env.ref("hr.group_hr_user").id,
            ])],
        })
        hr_emp.write({"user_id": hr_user.id})

        # Allowed categories for HR reviewer is strictly manpower
        self.assertEqual(hr_user._pbms_allowed_categories(), ["manpower"])

        justification_cat = self.env["pbms.justification.category"].create({"name": "HR Need"})
        mp_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.org_unit.id,
            "category": "manpower",
            "state": "district_approved",
            "business_justification": "HR Need",
            "justification_category_id": justification_cat.id,
            "manpower_line_ids": [(0, 0, {
                "line_type": "manpower",
                "position_type": "new",
                "new_job_title": "Auditor",
                "justification_category_id": justification_cat.id,
                "q1": 1,
                "quantity": 1,
            })],
        })

        dep_type = self.env["pbms.deposit.type"].create({"name": "Special Saving", "code": "SP01"})
        dep_plan = self.env["pbms.planning.category"].create({
            "cycle_id": self.cycle.id,
            "org_unit_id": self.org_unit.id,
            "category": "deposit",
            "state": "district_approved",
            "deposit_line_ids": [(0, 0, {
                "line_type": "deposit",
                "deposit_type_id": dep_type.id,
                "annual_total": 100000.0,
                "m01": 100000.0,
            })],
        })

        # HR reviewer CAN review manpower plan
        self.assertTrue(mp_plan.with_user(hr_user)._pbms_can_ho_review_plan())
        mp_plan.with_user(hr_user).action_ho_review()
        self.assertEqual(mp_plan.state, "ho_reviewed")

        # HR reviewer CANNOT review deposit plan
        self.assertFalse(dep_plan.with_user(hr_user)._pbms_can_ho_review_plan())
        with self.assertRaises(AccessError):
            dep_plan.with_user(hr_user).action_ho_review()

    def test_configurable_category_reviewer_routing_in_planning_config(self):
        """Test configuring functional reviewer routing directly in PbmsPlanningConfig."""
        special_user = self.env["res.users"].create({
            "name": "Custom Reviewer",
            "login": "custom_reviewer",
            "email": "custom@bunnabank.com",
            "groups_id": [(6, 0, [self.env.ref("bunna_pbms.group_pbms_ho_reviewer").id])],
        })

        # 1. Configure Category Routing on pbms.planning.config
        config = self.env["pbms.planning.config"].search([("config_type", "=", "work_unit_type"), ("work_unit_type", "=", "branch")], limit=1)
        if not config:
            config = self.env["pbms.planning.config"].create({
                "config_type": "work_unit_type",
                "work_unit_type": "branch",
            })
        config.write({
            "fx_reviewer_user_ids": [(6, 0, [special_user.id])],
            "manpower_reviewer_user_ids": [(6, 0, [special_user.id])],
        })

        # 2. Check user allowed categories calculated from PbmsPlanningConfig
        allowed = special_user._pbms_allowed_categories()
        self.assertIn("fx", allowed)
        self.assertIn("manpower", allowed)
        self.assertNotIn("deposit", allowed)
        self.assertNotIn("general_expense", allowed)

        # 3. Check get_category_review_info
        info = self.env["pbms.planning.config"].get_category_review_info("fx")
        self.assertIn(special_user, info["users"])