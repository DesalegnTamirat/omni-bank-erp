# -*- coding: utf-8 -*-
"""
Automated tests for manager-based escalation hierarchy.
Validates both Primary and Other OU journey tracks.
"""
from odoo.tests import common, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install", "bunna_helpdesk", "bunna_manager_escalation")
class TestManagerBasedEscalationHierarchy(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # -- Operating Units --
        cls.ou_branch = cls.env["operating.unit"].sudo().create({
            "name": "Test Branch OU",
            "sol_id": 9901,
            "work_unit_type": "branch",
        })
        cls.ou_division = cls.env["operating.unit"].sudo().create({
            "name": "Test Division OU",
            "parent_unit": cls.ou_branch.id,
            "sol_id": 9902,
            "work_unit_type": "head_office",
        })
        cls.ou_other = cls.env["operating.unit"].sudo().create({
            "name": "Test Other Division OU",
            "sol_id": 9903,
            "work_unit_type": "head_office",
        })

        # -- Users --
        def make_user(name, login, role):
            return cls.env["res.users"].sudo().create({
                "name": name,
                "login": login,
                "email": login,
                "helpdesk_role": role,
            })

        cls.user_frontline = make_user("Test Frontline Agent", "test_frontline@test.local", "front_line")
        cls.user_backline   = make_user("Test Backline Agent",  "test_backline@test.local",  "back_line")
        cls.user_teamlead   = make_user("Test Team Leader",     "test_teamlead@test.local",  "team_leader")
        cls.user_director   = make_user("Test Director",        "test_director@test.local",  "directorate")
        cls.user_chief      = make_user("Test Chief",           "test_chief@test.local",     "chief")
        cls.user_ceo        = make_user("Test CEO",             "test_ceo@test.local",       "ceo")
        cls.user_other_tl   = make_user("Test Other TL",        "test_other_tl@test.local",  "team_leader")
        cls.user_other_dir  = make_user("Test Other Director",  "test_other_dir@test.local", "directorate")
        cls.user_unrelated  = make_user("Test Unrelated",       "test_unrelated@test.local", "front_line")

        # -- Employees with manager hierarchy --
        def make_emp(name, user, parent_emp=None, ou=None):
            vals = {
                "name": name,
                "user_id": user.id,
                "work_email": user.email,
            }
            if parent_emp:
                vals["parent_id"] = parent_emp.id
            if ou:
                vals["default_operating_unit_id"] = ou.id
            return cls.env["hr.employee"].sudo().create(vals)

        cls.emp_ceo_emp   = make_emp("Test CEO Emp",        cls.user_ceo)
        cls.emp_chief     = make_emp("Test Chief Emp",      cls.user_chief,     parent_emp=cls.emp_ceo_emp)
        cls.emp_director  = make_emp("Test Director Emp",   cls.user_director,  parent_emp=cls.emp_chief, ou=cls.ou_division)
        cls.emp_teamlead  = make_emp("Test TL Emp",         cls.user_teamlead,  parent_emp=cls.emp_director, ou=cls.ou_division)
        cls.emp_backline  = make_emp("Test Backline Emp",   cls.user_backline,  parent_emp=cls.emp_teamlead, ou=cls.ou_division)
        cls.emp_frontline = make_emp("Test Frontline Emp",  cls.user_frontline, parent_emp=cls.emp_teamlead, ou=cls.ou_division)
        cls.emp_other_dir = make_emp("Test Other Dir Emp",  cls.user_other_dir, parent_emp=cls.emp_chief, ou=cls.ou_other)
        cls.emp_other_tl  = make_emp("Test Other TL Emp",  cls.user_other_tl,  parent_emp=cls.emp_other_dir, ou=cls.ou_other)

        cls.ou_division.write({"user_ids": [(4, cls.user_frontline.id), (4, cls.user_backline.id), (4, cls.user_teamlead.id), (4, cls.user_director.id), (4, cls.user_chief.id), (4, cls.user_ceo.id)]})
        cls.ou_other.write({"user_ids": [(4, cls.user_other_tl.id), (4, cls.user_other_dir.id)]})

        # -- Ticket --
        cls.team = cls.env["helpdesk.ticket.team"].sudo().search([], limit=1)
        cls.ticket = cls.env["helpdesk.ticket"].with_user(cls.user_frontline).create({
            "name": "Test Manager Escalation Ticket",
            "description": "<p>Test Manager Escalation Ticket</p>",
            "user_id": cls.user_backline.id,
            "operating_unit_id": cls.ou_division.id,
        })

    # ===========================================================================
    # TESTS — Primary Journey
    # ===========================================================================

    def test_01_primary_frontline_to_backline(self):
        """Frontline -> Backline: operating unit validation applies, no manager restriction."""
        t = self.ticket
        t.with_user(self.env.user).action_perform_hierarchical_escalation(
            escalation_type="back_line",
            target_user_id=self.user_backline,
            escalation_journey="primary_journey",
            reason="Backline escalation test",
        )
        self.assertTrue(t.is_escalated)
        self.assertEqual(t.escalation_level, 2)

    def test_02_primary_backline_to_teamlead(self):
        """Backline -> Team Leader: team leader = backline's direct manager."""
        t = self.ticket
        t.user_id = self.user_backline
        t.with_user(self.env.user).action_perform_hierarchical_escalation(
            escalation_type="team_leader",
            target_user_id=self.user_teamlead,
            escalation_journey="primary_journey",
            reason="Team leader escalation test",
        )
        self.assertEqual(t.escalation_level, 3)

    def test_03_primary_teamlead_to_director(self):
        """Team Leader -> Director: must be TL's actual manager (emp_teamlead.parent_id = emp_director)."""
        t = self.ticket
        t.user_id = self.user_teamlead
        t.escalation_level = 3
        t.with_user(self.env.user).action_perform_hierarchical_escalation(
            escalation_type="directorate",
            target_user_id=self.user_director,
            escalation_journey="primary_journey",
            reason="Director escalation test",
        )
        self.assertEqual(t.escalation_level, 4)

    def test_04_primary_director_rejects_unrelated_user(self):
        """Escalating to an unrelated user at Director level must be blocked."""
        t = self.ticket
        t.user_id = self.user_teamlead
        t.escalation_level = 3
        with self.assertRaises(ValidationError):
            t.with_user(self.env.user).action_perform_hierarchical_escalation(
                escalation_type="directorate",
                target_user_id=self.user_unrelated,
                escalation_journey="primary_journey",
                reason="Should fail",
            )

    def test_05_primary_director_to_chief(self):
        """Director -> Chief: must be Director's actual manager."""
        t = self.ticket
        t.user_id = self.user_director
        t.escalation_level = 4
        t.with_user(self.env.user).action_perform_hierarchical_escalation(
            escalation_type="chief",
            target_user_id=self.user_chief,
            escalation_journey="primary_journey",
            reason="Chief escalation test",
        )
        self.assertEqual(t.escalation_level, 6)

    def test_06_primary_self_escalation_blocked(self):
        """Self-escalation must be blocked at any level."""
        t = self.ticket
        t.user_id = self.user_teamlead
        with self.assertRaises(ValidationError):
            t.with_user(self.user_teamlead).action_perform_hierarchical_escalation(
                escalation_type="directorate",
                target_user_id=self.user_teamlead,
                escalation_journey="primary_journey",
                reason="Self-escalation test",
            )

    # ===========================================================================
    # TESTS — Other OU Journey
    # ===========================================================================

    def test_07_other_ou_teamlead_to_director(self):
        """Other OU Journey: Team Leader -> Other Director via manager-based hierarchy."""
        t = self.ticket
        t.write({
            "operating_unit_id": self.ou_other.id,
            "user_id": self.user_other_tl.id,
            "escalation_level": 3,
        })
        t.with_user(self.env.user).action_perform_hierarchical_escalation(
            escalation_type="other_directorate",
            target_user_id=self.user_other_dir,
            escalation_journey="other_work_journey",
            reason="Other OU director escalation test",
        )
        self.assertEqual(t.escalation_level, 4)

    # ===========================================================================
    # TESTS — Escalation History / Audit Trail
    # ===========================================================================

    def test_08_escalation_history_recorded(self):
        """Every escalation must be recorded in the audit history with all required fields."""
        t = self.ticket
        t.user_id = self.user_backline
        t.operating_unit_id = self.ou_division
        t.escalation_level = 0
        t.with_user(self.env.user).action_perform_hierarchical_escalation(
            escalation_type="team_leader",
            target_user_id=self.user_teamlead,
            escalation_journey="primary_journey",
            reason="History audit test",
        )
        hist = t.escalation_history_ids.sorted("escalation_datetime")[-1]
        self.assertEqual(hist.escalation_journey, "primary_journey")
        self.assertEqual(hist.new_user_id, self.user_teamlead)
        self.assertEqual(hist.escalation_status, "escalated")
        self.assertTrue(hist.level_name)
        self.assertTrue(hist.escalation_datetime)

    def test_09_original_operating_unit_preserved(self):
        """original_operating_unit_id must be set on first escalation and never change."""
        t = self.ticket
        t.original_operating_unit_id = False
        t.user_id = self.user_backline
        t.operating_unit_id = self.ou_division
        t.escalation_level = 0
        original_ou = t.operating_unit_id

        t.with_user(self.env.user).action_perform_hierarchical_escalation(
            escalation_type="team_leader",
            target_user_id=self.user_teamlead,
            escalation_journey="primary_journey",
            reason="Original OU preservation test",
        )
        self.assertEqual(t.original_operating_unit_id, original_ou)

        t.user_id = self.user_teamlead
        t.escalation_level = 3
        t.with_user(self.env.user).action_perform_hierarchical_escalation(
            escalation_type="directorate",
            target_user_id=self.user_director,
            escalation_journey="primary_journey",
            reason="Original OU preservation - 2nd escalation",
        )
        self.assertEqual(t.original_operating_unit_id, original_ou, "Original OU must not change on 2nd escalation!")
