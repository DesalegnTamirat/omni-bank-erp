# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import MagicMock, patch
import requests

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.addons.bunna_helpdesk.models.cbs_service import (
    get_cbs_credentials,
    parse_cbs_response_customer,
    query_cbs_api,
)


class TestBunnaHelpdeskEnhancements(TransactionCase):
    """
    Automated test suite verifying:
    1. Automatic ticket title generation without manual name input.
    2. 3-tier Product & Service Catalogue dependency and validation.
    3. Customer Profile CBS enrichment (Age, District, Branch, Customer Type).
    4. CBS real HTTP API integration, credential resolution from cbs_integration, and timeout/error handling.
    5. SLA-based automatic hierarchical escalation through employee hierarchy up to CEO.
    6. Circular reporting protection, duplicate escalation prevention, and audit history.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # Users and Employees for Hierarchical Escalation Test
        # Chain: Agent -> Manager -> Director -> CEO
        cls.user_ceo = cls.env["res.users"].create({
            "name": "Bunna CEO",
            "login": "bunna_ceo_test",
            "email": "ceo@bunnabanksc.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.emp_ceo = cls.env["hr.employee"].create({
            "name": "Bunna CEO Employee",
            "user_id": cls.user_ceo.id,
        })

        cls.user_director = cls.env["res.users"].create({
            "name": "Bunna Director",
            "login": "bunna_director_test",
            "email": "director@bunnabanksc.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.emp_director = cls.env["hr.employee"].create({
            "name": "Bunna Director Employee",
            "user_id": cls.user_director.id,
            "parent_id": cls.emp_ceo.id,
        })

        cls.user_manager = cls.env["res.users"].create({
            "name": "Branch Operations Manager",
            "login": "branch_mgr_test",
            "email": "mgr@bunnabanksc.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.emp_manager = cls.env["hr.employee"].create({
            "name": "Branch Manager Employee",
            "user_id": cls.user_manager.id,
            "parent_id": cls.emp_director.id,
        })

        cls.user_agent = cls.env["res.users"].create({
            "name": "Frontline Support Agent",
            "login": "support_agent_test",
            "email": "agent@bunnabanksc.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.emp_agent = cls.env["hr.employee"].create({
            "name": "Support Agent Employee",
            "user_id": cls.user_agent.id,
            "parent_id": cls.emp_manager.id,
        })

        # Set CEO in configuration parameter
        cls.env["ir.config_parameter"].sudo().set_param("bunna_helpdesk.ceo_user_id", str(cls.user_ceo.id))

        # Helpdesk Team and Stages
        cls.stage_new = cls.env["helpdesk.ticket.stage"].create({
            "name": "New Registered",
            "sequence": 1,
            "closed": False,
        })
        cls.stage_resolved = cls.env["helpdesk.ticket.stage"].create({
            "name": "Resolved / Closed",
            "sequence": 10,
            "closed": True,
        })

        cls.team = cls.env["helpdesk.ticket.team"].create({
            "name": "Customer Care Contact Center",
            "user_id": cls.user_manager.id,
            "user_ids": [(6, 0, [cls.user_agent.id, cls.user_manager.id])],
            "stage_ids": [(6, 0, [cls.stage_new.id, cls.stage_resolved.id])],
        })

        # SLA Policy: 2 hours to reach stage_resolved for high priority
        cls.sla_policy = cls.env["helpdesk.sla"].create({
            "name": "Urgent Resolution SLA",
            "team_id": cls.team.id,
            "stage_id": cls.stage_resolved.id,
            "priority": "0",
            "time_days": 0,
            "time_hours": 2,
        })

        # Service Catalogue
        cls.service_family = cls.env["helpdesk.service.family"].create({
            "name": "Digital Banking & Payments",
            "code": "DIGITAL_PAY",
        })
        cls.service = cls.env["helpdesk.service"].create({
            "name": "ATM & POS Operations",
            "code": "ATM_POS",
            "family_id": cls.service_family.id,
            "default_sdt_hours": 4.0,
        })
        cls.sub_category = cls.env["helpdesk.service.sub.category"].create({
            "name": "ATM Cash Retract / Card Trapped",
            "code": "ATM_RETRACT",
            "service_id": cls.service.id,
            "default_priority": "2",
        })

        # Secondary Catalogue for Cascade Tests
        cls.family_cbs = cls.env["helpdesk.service.family"].create({
            "name": "Core Banking Services",
            "code": "CBS_FAM",
        })
        cls.service_cbs = cls.env["helpdesk.service"].create({
            "name": "Account Maintenance",
            "code": "ACCT_MAINT",
            "family_id": cls.family_cbs.id,
        })

        # Customer Partner
        cls.partner = cls.env["res.partner"].create({
            "name": "Abebe Bikila",
            "account_number": "10000235467",
            "cif_number": "CIF00235467",
            "fayda_number": "FAN-2024-883921",
            "phone": "+251911456789",
            "email": "abebe@example.com",
            "age": 36,
            "district_name": "East Addis Ababa District",
            "branch_name": "Bole Medhanialem Branch",
            "customer_type": "Individual Retail",
        })

    # ── Test 1 & 2: Automatic Ticket Title Generation ─────────────────────────
    def test_ticket_creation_auto_title(self):
        """Test creating a ticket without providing 'name', verifying autogeneration."""
        ticket = self.env["helpdesk.ticket"].create({
            "team_id": self.team.id,
            "partner_id": self.partner.id,
            "service_family_id": self.service_family.id,
            "service_id": self.service.id,
            "service_sub_category_id": self.sub_category.id,
            "description": "<p>Customer card trapped in ATM.</p>",
        })
        self.assertTrue(ticket.name, "Ticket name must be populated automatically")
        self.assertNotIn(ticket.name, ["/", "New", "New Ticket"], "Ticket title should not remain default slash or placeholder")
        self.assertIn("ATM Cash Retract / Card Trapped", ticket.name)
        self.assertIn("Abebe Bikila", ticket.name)

    # ── Test 3 & 4: Catalogue Hierarchy & Cascade Clearing ────────────────────
    def test_service_catalogue_cascade_clearing(self):
        """Test that changing parent catalogue selection clears invalid child selections."""
        ticket = self.env["helpdesk.ticket"].new({
            "service_family_id": self.service_family.id,
            "service_id": self.service.id,
            "service_sub_category_id": self.sub_category.id,
        })

        # Changing family to CBS should clear ATM service and sub-category
        ticket.service_family_id = self.family_cbs.id
        ticket._onchange_service_family_id()
        self.assertFalse(ticket.service_id, "Incompatible service must be cleared when family changes")
        self.assertFalse(ticket.service_sub_category_id, "Sub-category must be cleared when family changes")

        # Selecting service under new family
        ticket.service_id = self.service_cbs.id
        ticket._onchange_service_id()
        self.assertEqual(ticket.service_family_id, self.family_cbs, "Service family should align with service")

    # ── Test 5: Customer Profile CBS Enrichment Fields ───────────────────────
    def test_customer_profile_cbs_fields(self):
        """Test that res.partner and helpdesk.ticket store and display CBS profile fields."""
        ticket = self.env["helpdesk.ticket"].create({
            "team_id": self.team.id,
            "partner_id": self.partner.id,
            "description": "<p>General banking inquiry</p>",
        })
        ticket._apply_customer_profile(self.partner)
        self.assertEqual(ticket.customer_age, 36)
        self.assertEqual(ticket.customer_district, "East Addis Ababa District")
        self.assertEqual(ticket.account_branch_name, "Bole Medhanialem Branch")
        self.assertEqual(ticket.customer_type_name, "Individual Retail")
        self.assertEqual(ticket.account_number, "10000235467")
        self.assertEqual(ticket.cbs_lookup_status, "verified")

    # ── Test 6: CBS Credentials Resolution from cbs_integration Table ────────
    def test_cbs_credentials_retrieval(self):
        """Test secure credential retrieval from cbs_integration table or system parameters."""
        config = get_cbs_credentials(self.env)
        self.assertIsInstance(config, dict, "Config must be returned as a dictionary")
        self.assertIn("username", config)
        self.assertIn("password", config)
        self.assertIn("endpoint", config)
        self.assertIn("environment", config)
        self.assertIn("status", config)

    # ── Test 7: CBS API Real Response Parser and Error Handling ───────────────
    def test_cbs_response_parser(self):
        """Test parsing real Finacle CBS production response payload."""
        real_cbs_payload = {
            "ACCOUNT_NUMBER": "1019501012030",
            "CIF_NUMBER": "100271122",
            "FAYDA_NUMBER": "6/440/3/1",
            "PHONE": "0912211913",
            "NAME": "YONAS GOSA DIBARGACHEW",
            "EMAIL": None,
            "ACCOUNT_TYPE": "Saving Account",
            "ACCOUNT_STATUS": "I",
            "CUSTOMER_SEGMENT": "Retail",
            "PREFERRED_LANGUAGE": "AMH",
            "SOL_ID": "101",
            "BRANCH_NAME": "BIB MAIN BRANCH",
            "DISTRICT_NAME": "South Addis Ababa",
            "ACCT_OPN_DATE": "2017-07-20T00:00:00",
            "MODE_OF_OPER_CODE": "SINGL",
            "AGE": 56,
        }
        parsed = parse_cbs_response_customer(real_cbs_payload, "1019501012030", "account")
        self.assertEqual(parsed["name"], "YONAS GOSA DIBARGACHEW")
        self.assertEqual(parsed["account_number"], "1019501012030")
        self.assertEqual(parsed["cif_number"], "100271122")
        self.assertEqual(parsed["fayda_number"], "6/440/3/1")
        self.assertEqual(parsed["phone"], "0912211913")
        self.assertFalse(parsed["email"])
        self.assertEqual(parsed["account_type"], "Saving Account")
        self.assertEqual(parsed["account_status"], "frozen")
        self.assertEqual(parsed["customer_segment"], "retail")
        self.assertEqual(parsed["preferred_language"], "amharic")
        self.assertEqual(parsed["branch_name"], "BIB MAIN BRANCH")
        self.assertEqual(parsed["district_name"], "South Addis Ababa")
        self.assertEqual(parsed["age"], 56)

    def test_cbs_timeout_handling(self):
        """Test handling CBS timeout without uncaught exceptions and reporting timeout cleanly."""
        self.env["ir.config_parameter"].sudo().set_param("bunna_helpdesk.cbs_endpoint", "http://127.0.0.1:9999/customer")
        with patch("requests.get", side_effect=requests.exceptions.Timeout("Connection timed out")):
            success, data, msg = query_cbs_api(self.env, "1019501012030", "account")
            self.assertFalse(success)
            self.assertIsNone(data)
            self.assertIn("timed out", msg.lower())

    def test_cbs_live_query_success(self):
        """Test successful query to live CBS endpoint with mocked HTTP 200 response."""
        self.env["ir.config_parameter"].sudo().set_param("bunna_helpdesk.cbs_endpoint", "http://127.0.0.1:9999/customer")
        real_cbs_payload = {
            "ACCOUNT_NUMBER": "1019501012030",
            "CIF_NUMBER": "100271122",
            "FAYDA_NUMBER": "6/440/3/1",
            "PHONE": "0912211913",
            "NAME": "YONAS GOSA DIBARGACHEW",
            "EMAIL": None,
            "ACCOUNT_TYPE": "Saving Account",
            "ACCOUNT_STATUS": "I",
            "CUSTOMER_SEGMENT": "Retail",
            "PREFERRED_LANGUAGE": "AMH",
            "SOL_ID": "101",
            "BRANCH_NAME": "BIB MAIN BRANCH",
            "DISTRICT_NAME": "South Addis Ababa",
            "ACCT_OPN_DATE": "2017-07-20T00:00:00",
            "MODE_OF_OPER_CODE": "SINGL",
            "AGE": 56,
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = real_cbs_payload

        with patch("requests.get", return_value=mock_resp):
            success, data, msg = query_cbs_api(self.env, "1019501012030", "account")
            self.assertTrue(success)
            self.assertEqual(data["name"], "YONAS GOSA DIBARGACHEW")
            self.assertEqual(data["account_number"], "1019501012030")
            self.assertEqual(data["cif_number"], "100271122")
            self.assertEqual(data["age"], 56)

    # ── Test 8 & 9: SLA Deadline Calculation and Escalation to Manager ─────────
    def test_sla_breach_and_manager_escalation(self):
        """Test that an unresolved ticket past its SLA deadline escalates to the user's manager."""
        ticket = self.env["helpdesk.ticket"].create({
            "team_id": self.team.id,
            "user_id": self.user_agent.id,
            "stage_id": self.stage_new.id,
            "priority": "1",
            "description": "<p>SLA escalation test</p>",
        })
        self.assertTrue(ticket.sla_deadline, "SLA deadline should be calculated on create")

        # Simulate SLA breach by setting deadline in the past
        past_time = fields.Datetime.now() - timedelta(hours=1)
        ticket.write({"sla_deadline": past_time, "sla_status": "failed"})

        # Run hierarchical escalation
        escaped = ticket._escalate_ticket_sla(reason="SLA Breached in Test")
        self.assertTrue(escaped)
        self.assertEqual(ticket.user_id, self.user_manager, "Ticket must escalate to Support Agent's manager")
        self.assertEqual(ticket.escalation_level, 1)
        self.assertEqual(ticket.sla_status, "in_progress", "SLA status must reset to in_progress with new deadline")
        self.assertGreater(ticket.sla_deadline, fields.Datetime.now(), "Next target deadline must be set in the future")

        # Verify audit history
        self.assertEqual(len(ticket.escalation_history_ids), 1)
        history = ticket.escalation_history_ids[0]
        self.assertEqual(history.previous_user_id, self.user_agent)
        self.assertEqual(history.new_user_id, self.user_manager)
        self.assertEqual(history.escalation_level, 1)
        self.assertFalse(history.is_ceo_level)

    # ── Test 10, 11 & 12: Multi-Level Escalation up to CEO and Resolution Stop ──
    def test_hierarchical_escalation_to_ceo(self):
        """Test cascading escalation up through Director to CEO, then stopping at CEO."""
        ticket = self.env["helpdesk.ticket"].create({
            "team_id": self.team.id,
            "user_id": self.user_manager.id,
            "stage_id": self.stage_new.id,
            "description": "<p>Multi-tier escalation test</p>",
        })

        # Step 1: Manager -> Director
        ticket.write({"sla_deadline": fields.Datetime.now() - timedelta(minutes=10)})
        ticket._escalate_ticket_sla()
        self.assertEqual(ticket.user_id, self.user_director)
        self.assertEqual(ticket.escalation_level, 1)
        self.assertFalse(ticket.is_ceo_escalated)

        # Step 2: Director -> CEO
        ticket.write({"sla_deadline": fields.Datetime.now() - timedelta(minutes=10)})
        ticket._escalate_ticket_sla()
        self.assertEqual(ticket.user_id, self.user_ceo, "Ticket should escalate to the CEO")
        self.assertEqual(ticket.escalation_level, 2)
        self.assertTrue(ticket.is_ceo_escalated, "Flag is_ceo_escalated must be True at CEO level")

        # Step 3: Attempting further escalation when already at CEO level
        ticket.write({"sla_deadline": fields.Datetime.now() - timedelta(minutes=10)})
        result = ticket._escalate_ticket_sla()
        self.assertFalse(result, "Escalation must stop at CEO level")
        self.assertEqual(ticket.user_id, self.user_ceo, "Assignee should remain CEO")

    def test_escalation_stopped_on_resolved_ticket(self):
        """Test that resolved tickets do not get escalated."""
        ticket = self.env["helpdesk.ticket"].create({
            "team_id": self.team.id,
            "user_id": self.user_agent.id,
            "stage_id": self.stage_resolved.id,  # Closed stage
            "description": "<p>Resolved ticket test</p>",
        })
        ticket.write({"sla_deadline": fields.Datetime.now() - timedelta(hours=5)})
        result = ticket._escalate_ticket_sla()
        self.assertFalse(result, "Resolved ticket must never be escalated")
        self.assertEqual(ticket.user_id, self.user_agent)

    # ── Test 13: Circular Reporting and Missing Manager Handling ─────────────
    def test_circular_reporting_loop_prevention(self):
        """Test that circular employee hierarchies do not cause infinite recursion."""
        emp_a = self.env["hr.employee"].create({"name": "Employee A"})
        emp_b = self.env["hr.employee"].create({"name": "Employee B", "parent_id": emp_a.id})
        emp_a.parent_id = emp_b.id  # Circular link

        user_cycle = self.env["res.users"].create({
            "name": "Cycle User",
            "login": "cycle_test_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        emp_a.user_id = user_cycle.id

        ticket = self.env["helpdesk.ticket"].create({
            "team_id": self.team.id,
            "user_id": user_cycle.id,
            "stage_id": self.stage_new.id,
            "description": "<p>Cycle test</p>",
        })

        # Next manager lookup should terminate safely and fallback to CEO
        next_mgr, is_ceo = ticket._get_next_escalation_manager()
        self.assertEqual(next_mgr, self.user_ceo, "Should break circular loop and fallback safely to CEO")
        self.assertTrue(is_ceo)

    # ── Test 14: Cron Job Batch Escalation ────────────────────────────────────
    def test_cron_sla_escalation(self):
        """Test scheduled action evaluation across multiple tickets."""
        ticket = self.env["helpdesk.ticket"].create({
            "team_id": self.team.id,
            "user_id": self.user_agent.id,
            "stage_id": self.stage_new.id,
            "description": "<p>Cron batch test</p>",
        })
        ticket.write({"sla_deadline": fields.Datetime.now() - timedelta(hours=1)})

        count = self.env["helpdesk.ticket"]._cron_evaluate_sla_escalation()
        self.assertGreaterEqual(count, 1, "Cron should have processed at least 1 breached ticket")
        ticket.invalidate_recordset()

    # ── Test 15: 3rd Level Executive & Vendor Escalation ─────────────────────
    def test_3rd_level_escalation(self):
        """Test escalation to 3rd Level Executive / External Vendor Unit."""
        team_l3 = self.env["helpdesk.ticket.team"].search([("team_tier", "=", "level_3_executive")], limit=1)
        if not team_l3:
            team_l3 = self.env["helpdesk.ticket.team"].create({
                "name": "Level 3 Executive Taskforce",
                "team_tier": "level_3_executive",
            })

        ticket = self.env["helpdesk.ticket"].create({
            "team_id": self.team.id,
            "user_id": self.user_agent.id,
            "stage_id": self.stage_new.id,
            "description": "<p>3rd Level escalation test</p>",
        })

        ticket.action_escalate_to_level_3(
            target_team_id=team_l3,
            reason="Unresolved critical transaction error requiring Executive Taskforce resolution",
        )

        self.assertTrue(ticket.is_level_3_escalated, "is_level_3_escalated must be True")
        self.assertEqual(ticket.escalation_level, 3, "Escalation level must be set to 3")
        self.assertEqual(ticket.team_id, team_l3, "Ticket team must be transferred to 3rd level team")
        self.assertEqual(ticket.priority, "3", "Priority should escalate to Critical (3)")

    # ── Test 16: Knowledge Base Pull & Publish from Contact Center Assistant Notes ─
    def test_kb_load_and_publish_from_notes(self):
        """Test pulling Knowledge Base SOP into notes and publishing notes as a new KB article."""
        article = self.env["helpdesk.knowledge.article"].create({
            "name": "On-Us ATM Cash Retraction SOP",
            "service_id": self.service.id,
            "content": "<p>1. Audit physical cash tray.<br/>2. Reconcile Electronic Journal (EJ) log.<br/>3. Credit customer account.</p>",
            "state": "published",
        })

        ticket = self.env["helpdesk.ticket"].create({
            "team_id": self.team.id,
            "service_id": self.service.id,
            "inquiry_summary": "ATM Cash Retraction Issue",
            "customer_request_details": "Customer attempted 5000 ETB withdrawal at Bole ATM. Debited without cash.",
            "kb_article_id": article.id,
        })

        # Step 1: Pull KB SOP into notes
        ticket.action_load_kb_sop_to_notes()
        self.assertIn("Audit physical cash tray", ticket.agent_action_taken)

        # Step 2: Publish updated notes to a new KB article
        action = ticket.action_publish_notes_to_kb()
        new_article_id = action.get("res_id")
        self.assertTrue(new_article_id, "New Knowledge Base Article ID should be returned")

        new_article = self.env["helpdesk.knowledge.article"].browse(new_article_id)
        self.assertEqual(new_article.name, "ATM Cash Retraction Issue")
        self.assertIn("Customer attempted 5000 ETB", new_article.content)
