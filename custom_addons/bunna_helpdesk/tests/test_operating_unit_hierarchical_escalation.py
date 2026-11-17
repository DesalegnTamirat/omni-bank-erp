# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import fields
from odoo.tests import common, tagged


@tagged("post_install", "-at_install", "bunna_helpdesk", "bunna_escalation")
class TestOperatingUnitHierarchicalEscalation(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # 1. Create Operating Unit Hierarchy up to CEO
        cls.ou_ceo_office = cls.env["operating.unit"].sudo().create({
            "name": "Executive Management & CEO Office",
            "sol_id": 8803,
            "work_unit_type": "head_office",
        })
        cls.ou_is_directorate = cls.env["operating.unit"].sudo().create({
            "name": "Information Systems & Digital Banking Directorate",
            "sol_id": 8802,
            "work_unit_type": "head_office",
            "parent_unit": cls.ou_ceo_office.id,
        })
        cls.ou_ead = cls.env["operating.unit"].sudo().create({
            "name": "Enterprise Application Development Division",
            "sol_id": 8801,
            "work_unit_type": "head_office",
            "parent_unit": cls.ou_is_directorate.id,
        })

        # 2. Create Users along the 7-level hierarchy
        cls.user_ceo = cls.env["res.users"].sudo().create({
            "name": "Mulugeta Alemayehu (CEO)",
            "login": "ceo_mulugeta@bunnabank.test",
            "email": "ceo_mulugeta@bunnabank.test",
            "helpdesk_role": "ceo",
        })
        cls.user_cido = cls.env["res.users"].sudo().create({
            "name": "Yeshanew Ayalew (CIDO)",
            "login": "cido_yeshanew@bunnabank.test",
            "email": "cido_yeshanew@bunnabank.test",
            "helpdesk_role": "cido",
        })
        cls.user_deputy_cto = cls.env["res.users"].sudo().create({
            "name": "Tadesse Dabi (Deputy CTO)",
            "login": "deputy_tadesse@bunnabank.test",
            "email": "deputy_tadesse@bunnabank.test",
            "helpdesk_role": "deputy_cto",
        })
        cls.user_director = cls.env["res.users"].sudo().create({
            "name": "Derese Wudu (Director)",
            "login": "director_derese@bunnabank.test",
            "email": "director_derese@bunnabank.test",
            "helpdesk_role": "director",
        })
        cls.user_manager = cls.env["res.users"].sudo().create({
            "name": "Eyob Shewangzaw (Division Manager)",
            "login": "manager_eyob@bunnabank.test",
            "email": "manager_eyob@bunnabank.test",
            "helpdesk_role": "manager",
        })
        cls.user_backend = cls.env["res.users"].sudo().create({
            "name": "Backend Specialist User",
            "login": "backend_dev@bunnabank.test",
            "email": "backend_dev@bunnabank.test",
            "helpdesk_role": "backend",
        })
        cls.user_frontend = cls.env["res.users"].sudo().create({
            "name": "Getaye Aweke (Frontend Officer)",
            "login": "frontend_getaye@bunnabank.test",
            "email": "frontend_getaye@bunnabank.test",
            "helpdesk_role": "frontend",
        })

        # Assign OU to Users
        cls.ou_ead.write({"user_ids": [(4, cls.user_frontend.id), (4, cls.user_backend.id), (4, cls.user_manager.id)]})

        # 3. Create Employee Reporting Hierarchy
        cls.emp_ceo = cls.env["hr.employee"].sudo().create({
            "name": "Mulugeta Alemayehu Awoke",
            "job_title": "Chief Executive Officer (CEO)",
            "user_id": cls.user_ceo.id,
        })
        cls.emp_cido = cls.env["hr.employee"].sudo().create({
            "name": "Yeshanew Ayalew Shibeshi",
            "job_title": "Chief Information and Digital Officer (CIDO)",
            "parent_id": cls.emp_ceo.id,
            "user_id": cls.user_cido.id,
        })
        cls.emp_deputy_cto = cls.env["hr.employee"].sudo().create({
            "name": "Tadesse Dabi Abebe",
            "job_title": "Deputy Chief-Technology Officer",
            "parent_id": cls.emp_cido.id,
            "user_id": cls.user_deputy_cto.id,
        })
        cls.emp_director = cls.env["hr.employee"].sudo().create({
            "name": "Derese Wudu Mekonen",
            "job_title": "Director - Enterprise Application Development Directorate",
            "parent_id": cls.emp_deputy_cto.id,
            "user_id": cls.user_director.id,
        })
        cls.emp_manager = cls.env["hr.employee"].sudo().create({
            "name": "Eyob Shewangzaw Bogale",
            "job_title": "Manager - Enterprise Application Division",
            "parent_id": cls.emp_director.id,
            "user_id": cls.user_manager.id,
            "default_operating_unit_id": cls.ou_ead.id,
        })
        cls.emp_backend = cls.env["hr.employee"].sudo().create({
            "name": "Backend Specialist",
            "job_title": "Enterprise Application Senior Backend Developer",
            "parent_id": cls.emp_manager.id,
            "user_id": cls.user_backend.id,
            "default_operating_unit_id": cls.ou_ead.id,
        })
        cls.emp_frontend = cls.env["hr.employee"].sudo().create({
            "name": "Getaye Aweke Bantihun",
            "job_title": "Enterprise Application Officer / Frontend Developer",
            "parent_id": cls.emp_manager.id,
            "user_id": cls.user_frontend.id,
            "default_operating_unit_id": cls.ou_ead.id,
        })

        # Configure CEO user in parameters
        cls.env["ir.config_parameter"].sudo().set_param("bunna_helpdesk.ceo_user_id", str(cls.user_ceo.id))

        # 4. Create Helpdesk Team with Operating Unit (members are auto-populated)
        cls.team = cls.env["helpdesk.ticket.team"].sudo().create({
            "name": "Enterprise Application Support Team",
            "operating_unit_id": cls.ou_ead.id,
            "user_id": cls.user_manager.id,
        })
        cls.stage_new = cls.env["helpdesk.ticket.stage"].sudo().create({
            "name": "New",
            "sequence": 1,
            "team_ids": [(4, cls.team.id)],
        })
        cls.stage_progress = cls.env["helpdesk.ticket.stage"].sudo().create({
            "name": "In Progress",
            "sequence": 2,
            "team_ids": [(4, cls.team.id)],
        })

        # 5. Create 3-tier Service Catalogue with Operating Unit
        cls.family = cls.env["helpdesk.service.family"].sudo().create({
            "name": "Enterprise Application Systems",
            "code": "EAD_SYS",
            "operating_unit_id": cls.ou_ead.id,
        })
        cls.service = cls.env["helpdesk.service"].sudo().create({
            "name": "DFS Loan Disbursement Service",
            "family_id": cls.family.id,
            "responsible_team_id": cls.team.id,
            "operating_unit_id": cls.ou_ead.id,
            "default_sdt_hours": 12.0,
        })
        cls.sub_service = cls.env["helpdesk.service.sub.category"].sudo().create({
            "name": "DFS Loan Disbursement Case / Failure",
            "service_id": cls.service.id,
            "default_priority": "2",
        })

    def test_01_service_catalogue_operating_unit_inheritance(self):
        """Verify operating unit links and hierarchy chain across service hierarchy."""
        self.assertEqual(self.family.operating_unit_id, self.ou_ead)
        self.assertEqual(self.family.parent_operating_unit_id, self.ou_is_directorate)
        self.assertIn("Enterprise Application Development Division", self.family.operating_unit_hierarchy)
        self.assertIn("Executive Management & CEO Office", self.family.operating_unit_hierarchy)

        self.assertEqual(self.service.operating_unit_id, self.ou_ead)
        self.assertEqual(self.service.parent_operating_unit_id, self.ou_is_directorate)
        self.assertEqual(self.sub_service.operating_unit_id, self.ou_ead)
        self.assertEqual(self.sub_service.parent_operating_unit_id, self.ou_is_directorate)
        self.assertEqual(self.sub_service.responsible_team_id, self.team)

    def test_02_ticket_auto_population_on_sub_service_select(self):
        """Selecting sub-service auto-populates Service, Family, Operating Unit, Parent OU up to CEO, and Team."""
        ticket = self.env["helpdesk.ticket"].new({
            "service_sub_category_id": self.sub_service.id,
        })
        ticket._onchange_service_sub_category_id()

        self.assertEqual(ticket.service_id, self.service)
        self.assertEqual(ticket.service_family_id, self.family)
        self.assertEqual(ticket.operating_unit_id, self.ou_ead)
        self.assertEqual(ticket.district_operating_unit_id, self.ou_ead)
        self.assertEqual(ticket.directorate_operating_unit_id, self.ou_is_directorate)
        self.assertEqual(ticket.executive_operating_unit_id, self.ou_ceo_office)
        self.assertEqual(ticket.parent_operating_unit_id, self.ou_is_directorate)
        self.assertIn(self.ou_is_directorate.id, ticket.parent_operating_unit_ids.ids)
        self.assertIn(self.ou_ceo_office.id, ticket.parent_operating_unit_ids.ids)
        self.assertEqual(
            ticket.operating_unit_hierarchy,
            "Enterprise Application Development Division ➔ Information Systems & Digital Banking Directorate ➔ Executive Management & CEO Office"
        )
        self.assertEqual(ticket.team_id, self.team)
        self.assertEqual(ticket.priority, "2")

        # Also test 4-tier Branch hierarchy (CMC Branch -> South District -> Retail Ops -> CEO)
        ou_retail = self.env["operating.unit"].sudo().create({
            "name": "Retail Operations Directorate",
            "sol_id": 8804,
            "work_unit_type": "head_office",
            "parent_unit": self.ou_ceo_office.id,
        })
        ou_district = self.env["operating.unit"].sudo().create({
            "name": "South District Office",
            "sol_id": 8805,
            "work_unit_type": "district_office",
            "parent_unit": ou_retail.id,
        })
        ou_cmc = self.env["operating.unit"].sudo().create({
            "name": "CMC Branch",
            "sol_id": 8806,
            "work_unit_type": "branch",
            "parent_unit": ou_district.id,
        })
        ticket_cmc = self.env["helpdesk.ticket"].new({
            "operating_unit_id": ou_cmc.id,
        })
        ticket_cmc._onchange_operating_unit_id()
        self.assertEqual(ticket_cmc.branch_operating_unit_id, ou_cmc)
        self.assertEqual(ticket_cmc.district_operating_unit_id, ou_district)
        self.assertEqual(ticket_cmc.directorate_operating_unit_id, ou_retail)
        self.assertEqual(ticket_cmc.executive_operating_unit_id, self.ou_ceo_office)
        self.assertEqual(
            ticket_cmc.operating_unit_hierarchy,
            "CMC Branch ➔ South District Office ➔ Retail Operations Directorate ➔ Executive Management & CEO Office"
        )

    def test_03_operating_unit_user_filtering(self):
        """Ticket operating_unit_user_ids contains only EAD operating unit users."""
        ticket = self.env["helpdesk.ticket"].sudo().create({
            "name": "Test Ticket EAD",
            "description": "<p>EAD Issue</p>",
            "service_sub_category_id": self.sub_service.id,
            "service_id": self.service.id,
            "service_family_id": self.family.id,
            "operating_unit_id": self.ou_ead.id,
            "team_id": self.team.id,
        })
        ticket._compute_operating_unit_user_ids()

        allowed_users = ticket.operating_unit_user_ids
        self.assertIn(self.user_frontend, allowed_users)
        self.assertIn(self.user_backend, allowed_users)
        self.assertIn(self.user_manager, allowed_users)
        # CEO, CIDO, Director not in EAD unit users
        self.assertNotIn(self.user_ceo, allowed_users)

    def test_04_manual_peer_escalation_wizard(self):
        """Frontend officer uses escalation wizard to escalate to Backend Specialist."""
        ticket = self.env["helpdesk.ticket"].sudo().create({
            "name": "DFS Loan Issue HT00048",
            "description": "<p>API response failure</p>",
            "service_sub_category_id": self.sub_service.id,
            "service_id": self.service.id,
            "service_family_id": self.family.id,
            "operating_unit_id": self.ou_ead.id,
            "team_id": self.team.id,
            "user_id": self.user_frontend.id,
        })

        wizard = self.env["helpdesk.ticket.escalate.wizard"].with_context(active_id=ticket.id).sudo().create({
            "ticket_id": ticket.id,
            "escalation_type": "peer_backend",
            "target_user_id": self.user_backend.id,
            "reason": "Frontend API payload correct; backend loan engine returned timeout.",
        })
        wizard.action_escalate()

        # Check Ticket state
        self.assertTrue(ticket.is_escalated)
        self.assertEqual(ticket.user_id, self.user_backend)
        self.assertEqual(ticket.escalation_level, 2)

        # Check Audit History
        history = self.env["helpdesk.ticket.escalation.history"].search([("ticket_id", "=", ticket.id)], limit=1)
        self.assertTrue(history)
        self.assertEqual(history.previous_user_id, self.user_frontend)
        self.assertEqual(history.new_user_id, self.user_backend)
        self.assertEqual(history.escalation_type, "peer_backend")

    def test_05_manual_manager_escalation_wizard(self):
        """Backend specialist escalates to Division Manager (Eyob Shewangzaw)."""
        ticket = self.env["helpdesk.ticket"].sudo().create({
            "name": "DFS Core Timeout HT00049",
            "description": "<p>CBS Finacle connector issue</p>",
            "service_sub_category_id": self.sub_service.id,
            "service_id": self.service.id,
            "service_family_id": self.family.id,
            "operating_unit_id": self.ou_ead.id,
            "team_id": self.team.id,
            "user_id": self.user_backend.id,
        })

        wizard = self.env["helpdesk.ticket.escalate.wizard"].with_context(active_id=ticket.id).sudo().create({
            "ticket_id": ticket.id,
            "escalation_type": "line_manager",
            "target_user_id": self.user_manager.id,
            "reason": "Requires CBS vendor coordination approved by Division Manager.",
        })
        wizard.action_escalate()

        self.assertTrue(ticket.is_escalated)
        self.assertEqual(ticket.user_id, self.user_manager)
        self.assertEqual(ticket.escalation_level, 3)

        history = self.env["helpdesk.ticket.escalation.history"].search([("ticket_id", "=", ticket.id)], limit=1)
        self.assertEqual(history.previous_user_id, self.user_backend)
        self.assertEqual(history.new_user_id, self.user_manager)
        self.assertEqual(history.escalation_type, "line_manager")

    def test_06_full_automatic_sla_escalation_chain(self):
        """
        Verify SLA breach automatic escalation traverses:
        Frontend (L1) -> Backend (L2) -> Manager (L3) -> Director (L4) -> Deputy CTO (L5) -> CIDO (L6) -> CEO (L7)
        """
        ticket = self.env["helpdesk.ticket"].sudo().create({
            "name": "Critical DFS Loan Disbursement Breach",
            "description": "<p>SLA Breach simulation</p>",
            "service_sub_category_id": self.sub_service.id,
            "service_id": self.service.id,
            "service_family_id": self.family.id,
            "operating_unit_id": self.ou_ead.id,
            "team_id": self.team.id,
            "user_id": self.user_frontend.id,
            "sla_deadline": fields.Datetime.now() - timedelta(hours=2),
        })

        # Step 1: SLA breach from Frontend -> Backend Specialist (Peer Escalation)
        ticket._escalate_ticket_sla(reason="SLA Breached at Level 1")
        self.assertEqual(ticket.user_id, self.user_backend)
        self.assertEqual(ticket.escalation_level, 2)

        # Step 2: SLA breach from Backend -> Division Manager (Eyob Shewangzaw)
        ticket.write({"sla_deadline": fields.Datetime.now() - timedelta(hours=1)})
        ticket._escalate_ticket_sla(reason="SLA Breached at Level 2")
        self.assertEqual(ticket.user_id, self.user_manager)
        self.assertEqual(ticket.escalation_level, 3)

        # Step 3: SLA breach from Manager -> Directorate Director (Derese Wudu)
        ticket.write({"sla_deadline": fields.Datetime.now() - timedelta(hours=1)})
        ticket._escalate_ticket_sla(reason="SLA Breached at Level 3")
        self.assertEqual(ticket.user_id, self.user_director)
        self.assertEqual(ticket.escalation_level, 4)

        # Step 4: SLA breach from Director -> Deputy CTO (Tadesse Dabi)
        ticket.write({"sla_deadline": fields.Datetime.now() - timedelta(hours=1)})
        ticket._escalate_ticket_sla(reason="SLA Breached at Level 4")
        self.assertEqual(ticket.user_id, self.user_deputy_cto)
        self.assertEqual(ticket.escalation_level, 5)

        # Step 5: SLA breach from Deputy CTO -> CIDO (Yeshanew Ayalew)
        ticket.write({"sla_deadline": fields.Datetime.now() - timedelta(hours=1)})
        ticket._escalate_ticket_sla(reason="SLA Breached at Level 5")
        self.assertEqual(ticket.user_id, self.user_cido)
        self.assertEqual(ticket.escalation_level, 6)

        # Step 6: SLA breach from CIDO -> CEO (Mulugeta Alemayehu)
        ticket.write({"sla_deadline": fields.Datetime.now() - timedelta(hours=1)})
        ticket._escalate_ticket_sla(reason="SLA Breached at Level 6")
        self.assertEqual(ticket.user_id, self.user_ceo)
        self.assertEqual(ticket.escalation_level, 7)
        self.assertTrue(ticket.is_ceo_escalated)

        # Verify audit histories count
        histories = self.env["helpdesk.ticket.escalation.history"].search([("ticket_id", "=", ticket.id)])
        self.assertEqual(len(histories), 6)

    def test_07_team_auto_members_from_operating_unit(self):
        """Verify team.user_ids automatically includes all employees in its operating unit without manual addition."""
        # Check that the team automatically populated user_ids from ou_ead
        self.assertIn(self.user_frontend, self.team.user_ids)
        self.assertIn(self.user_backend, self.team.user_ids)
        self.assertIn(self.user_manager, self.team.user_ids)
        self.assertNotIn(self.user_ceo, self.team.user_ids)

        # Create a new employee in this operating unit and verify team.user_ids auto updates
        new_user = self.env["res.users"].sudo().create({
            "name": "Abebe QA Specialist",
            "login": "abebe_qa@bunnabank.test",
            "email": "abebe_qa@bunnabank.test",
            "helpdesk_role": "qa",
        })
        self.env["hr.employee"].sudo().create({
            "name": "Abebe QA Specialist",
            "job_title": "Enterprise Application QA Engineer",
            "parent_id": self.emp_manager.id,
            "user_id": new_user.id,
            "default_operating_unit_id": self.ou_ead.id,
        })
        self.team._compute_user_ids()
        self.assertIn(new_user, self.team.user_ids)

    def test_08_journey_map_primary_track_wizard(self):
        """Test explicit Journey Map primary track stages via wizard."""
        ticket = self.env["helpdesk.ticket"].sudo().create({
            "name": "Journey Map Test HT00050",
            "description": "<p>Journey test description</p>",
            "service_sub_category_id": self.sub_service.id,
            "service_id": self.service.id,
            "operating_unit_id": self.ou_ead.id,
            "team_id": self.team.id,
            "user_id": self.user_frontend.id,
        })

        # Step 1: Front line -> Back line
        wiz1 = self.env["helpdesk.ticket.escalate.wizard"].with_context(active_id=ticket.id).sudo().create({
            "ticket_id": ticket.id,
            "escalation_journey": "primary_journey",
            "escalation_type": "back_line",
            "target_user_id": self.user_backend.id,
            "reason": "Backend analysis needed",
        })
        wiz1.action_escalate()
        self.assertEqual(ticket.user_id, self.user_backend)
        self.assertEqual(ticket.escalation_level, 2)

        # Step 2: Back line -> Team Leader
        wiz2 = self.env["helpdesk.ticket.escalate.wizard"].with_context(active_id=ticket.id).sudo().create({
            "ticket_id": ticket.id,
            "escalation_journey": "primary_journey",
            "escalation_type": "team_leader",
            "target_user_id": self.user_manager.id,
            "reason": "Team Leader authorization needed",
        })
        wiz2.action_escalate()
        self.assertEqual(ticket.user_id, self.user_manager)
        self.assertEqual(ticket.escalation_level, 3)

        # Step 3: Team Leader -> Directorate
        wiz3 = self.env["helpdesk.ticket.escalate.wizard"].with_context(active_id=ticket.id).sudo().create({
            "ticket_id": ticket.id,
            "escalation_journey": "primary_journey",
            "escalation_type": "directorate",
            "target_user_id": self.user_director.id,
            "reason": "Director decision needed",
        })
        wiz3.action_escalate()
        self.assertEqual(ticket.user_id, self.user_director)
        self.assertEqual(ticket.escalation_level, 4)

        # Step 4: Directorate -> Deputy Chief
        wiz4 = self.env["helpdesk.ticket.escalate.wizard"].with_context(active_id=ticket.id).sudo().create({
            "ticket_id": ticket.id,
            "escalation_journey": "primary_journey",
            "escalation_type": "deputy_chief",
            "target_user_id": self.user_deputy_cto.id,
            "reason": "Executive Deputy Chief decision needed",
        })
        wiz4.action_escalate()
        self.assertEqual(ticket.user_id, self.user_deputy_cto)
        self.assertEqual(ticket.escalation_level, 5)

        # Step 5: Deputy Chief -> Chief
        wiz5 = self.env["helpdesk.ticket.escalate.wizard"].with_context(active_id=ticket.id).sudo().create({
            "ticket_id": ticket.id,
            "escalation_journey": "primary_journey",
            "escalation_type": "chief",
            "target_user_id": self.user_cido.id,
            "reason": "C-Level decision needed",
        })
        wiz5.action_escalate()
        self.assertEqual(ticket.user_id, self.user_cido)
        self.assertEqual(ticket.escalation_level, 6)

        # Step 6: Chief -> CEO
        wiz6 = self.env["helpdesk.ticket.escalate.wizard"].with_context(active_id=ticket.id).sudo().create({
            "ticket_id": ticket.id,
            "escalation_journey": "primary_journey",
            "escalation_type": "ceo",
            "target_user_id": self.user_ceo.id,
            "reason": "Final CEO approval needed",
        })
        wiz6.action_escalate()
        self.assertEqual(ticket.user_id, self.user_ceo)
        self.assertEqual(ticket.escalation_level, 7)
        self.assertTrue(ticket.is_ceo_escalated)

    def test_09_journey_map_direct_bypass_to_deputy_chief(self):
        """Test direct bypass escalation arrow from Team Leader directly to Deputy Chief."""
        ticket = self.env["helpdesk.ticket"].sudo().create({
            "name": "Bypass Test HT00051",
            "description": "<p>Bypass test description</p>",
            "service_sub_category_id": self.sub_service.id,
            "service_id": self.service.id,
            "operating_unit_id": self.ou_ead.id,
            "team_id": self.team.id,
            "user_id": self.user_manager.id,
        })
        wiz = self.env["helpdesk.ticket.escalate.wizard"].with_context(active_id=ticket.id).sudo().create({
            "ticket_id": ticket.id,
            "escalation_journey": "primary_journey",
            "escalation_type": "team_leader_to_deputy_chief",
            "target_user_id": self.user_deputy_cto.id,
            "reason": "Critical outage: direct bypass to Deputy Chief",
        })
        wiz.action_escalate()
        self.assertEqual(ticket.user_id, self.user_deputy_cto)
        self.assertEqual(ticket.escalation_level, 5)

    def test_10_journey_map_cross_workunit_track(self):
        """Test cross-workunit transfer ('Other Work') and escalation within target unit."""
        ou_cards = self.env["operating.unit"].sudo().create({
            "name": "Electronic Payment & Cards Division",
            "sol_id": 8807,
            "work_unit_type": "head_office",
        })
        user_card_officer = self.env["res.users"].sudo().create({
            "name": "Card Officer User",
            "login": "card_officer@bunnabank.test",
            "email": "card_officer@bunnabank.test",
            "helpdesk_role": "officer",
        })
        ou_cards.write({"user_ids": [(4, user_card_officer.id)]})

        ticket = self.env["helpdesk.ticket"].sudo().create({
            "name": "Cross-unit Test HT00052",
            "description": "<p>Cross-unit test description</p>",
            "service_sub_category_id": self.sub_service.id,
            "service_id": self.service.id,
            "operating_unit_id": self.ou_ead.id,
            "team_id": self.team.id,
            "user_id": self.user_backend.id,
        })

        # Transfer to Other Workunit -> Card Officer
        wiz = self.env["helpdesk.ticket.escalate.wizard"].with_context(active_id=ticket.id).sudo().create({
            "ticket_id": ticket.id,
            "escalation_journey": "other_work_journey",
            "escalation_type": "other_officer",
            "target_operating_unit_id": ou_cards.id,
            "target_user_id": user_card_officer.id,
            "reason": "Transferring to Cards unit for switch settlement dispute",
        })
        wiz.action_escalate()

        self.assertEqual(ticket.operating_unit_id, ou_cards)
        self.assertEqual(ticket.user_id, user_card_officer)
        self.assertEqual(ticket.escalation_level, 2)

    def test_11_role_based_creation_and_hierarchical_escalation(self):
        """Verify Front line / Specialist can create tickets and escalate to Back line, and upwards through each tier."""
        group_front_line = self.env.ref("bunna_helpdesk.group_helpdesk_front_line")
        group_back_line = self.env.ref("bunna_helpdesk.group_helpdesk_back_line")
        group_contact_center = self.env.ref("bunna_helpdesk.group_helpdesk_contact_center")

        # Assign groups
        self.user_frontend.write({"group_ids": [(4, group_front_line.id)]})
        self.user_backend.write({"group_ids": [(4, group_back_line.id)]})

        # Create CC agent
        user_cc = self.env["res.users"].sudo().create({
            "name": "Contact Center Agent 1",
            "login": "cc_agent1@bunnabank.test",
            "email": "cc_agent1@bunnabank.test",
            "helpdesk_role": "contact_center",
            "group_ids": [(4, group_contact_center.id)],
        })
        self.ou_ead.write({"user_ids": [(4, user_cc.id)]})

        # 1. Contact Center creates ticket
        ticket_cc = self.env["helpdesk.ticket"].with_user(user_cc).create({
            "name": "CC Customer Dispute",
            "description": "<p>Customer called regarding ATM debit without cash</p>",
            "customer_status": "existing",
            "customer_type": "external",
            "operating_unit_id": self.ou_ead.id,
            "team_id": self.team.id,
        })
        self.assertTrue(ticket_cc.id)

        # Contact Center escalates to Front line
        wiz_cc = self.env["helpdesk.ticket.escalate.wizard"].with_user(user_cc).with_context(active_id=ticket_cc.id).create({
            "ticket_id": ticket_cc.id,
            "reason": "Escalating call center dispute to frontline specialist",
        })
        self.assertEqual(wiz_cc.escalation_type, "front_line")
        wiz_cc.target_user_id = self.user_frontend.id
        wiz_cc.action_escalate()
        self.assertEqual(ticket_cc.user_id, self.user_frontend)

        # 2. Front line creates ticket directly
        ticket_fl = self.env["helpdesk.ticket"].with_user(self.user_frontend).create({
            "name": "Front line Ticket Direct Creation",
            "description": "<p>Front line branch walkin issue</p>",
            "customer_status": "existing",
            "customer_type": "internal",
            "operating_unit_id": self.ou_ead.id,
            "team_id": self.team.id,
            "user_id": self.user_frontend.id,
        })
        self.assertTrue(ticket_fl.id)

        # Front line wizard auto-selects Back line
        wiz_fl = self.env["helpdesk.ticket.escalate.wizard"].with_user(self.user_frontend).with_context(active_id=ticket_fl.id).create({
            "ticket_id": ticket_fl.id,
            "reason": "Escalating to Back line specialist for DB error investigation",
        })
        self.assertEqual(wiz_fl.escalation_type, "back_line")
        wiz_fl.target_user_id = self.user_backend.id
        wiz_fl.action_escalate()
        self.assertEqual(ticket_fl.user_id, self.user_backend)
        self.assertEqual(ticket_fl.escalation_level, 2)


