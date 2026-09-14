# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestPeerSubordinateRules(TransactionCase):
    """Automated test suite verifying 360° Peer & Subordinate evaluation rules and Director Peer Config."""

    def setUp(self):
        super().setUp()
        self.Employee = self.env['hr.employee']
        self.Department = self.env['hr.department']
        self.Job = self.env['hr.job']
        self.Grade = self.env['employee.grade']
        self.OU = self.env['operating.unit']
        self.Assessment = self.env['competency.assessment']
        self.DirectorConfig = self.env['competency.director.peer.config']

        # Operating Units
        existing_ous = self.OU.search([])
        if len(existing_ous) >= 2:
            self.ou_main = existing_ous[0]
            self.ou_district_b = existing_ous[1]
        else:
            self.ou_main = self.OU.create({'name': 'Head Office OU', 'sol_id': 8881, 'work_unit_type': 'branch'})
            self.ou_district_b = self.OU.create({'name': 'District B OU', 'sol_id': 8882, 'work_unit_type': 'branch'})


        # Departments
        self.dept_ho = self.Department.create({'name': 'HR Department', 'operating_unit_id': self.ou_main.id})
        self.dept_district = self.Department.create({'name': 'District B Dept', 'operating_unit_id': self.ou_district_b.id})

        # Job Grades
        self.grade_10 = self.Grade.create({'name': 'Grade 10', 'level': 10})
        self.grade_12 = self.Grade.create({'name': 'Grade 12', 'level': 12})

        # Job Positions
        self.job_officer = self.Job.create({'name': 'HR Officer', 'grade_id': self.grade_10.id})
        self.job_analyst = self.Job.create({'name': 'HR Analyst', 'grade_id': self.grade_10.id})
        self.job_dm = self.Job.create({'name': 'District Manager', 'grade_id': self.grade_12.id})
        self.job_director = self.Job.create({'name': 'Human Resource Director', 'grade_id': self.grade_12.id})

        # Coach / Executive Manager
        self.coach_exec = self.Employee.create({
            'name': 'Executive VP Coach',
            'department_id': self.dept_ho.id,
            'default_operating_unit_id': self.ou_main.id,
        })

        # Employees for HO Manager / Non-Manager tests
        self.emp_officer_a = self.Employee.create({
            'name': 'HO Officer A',
            'department_id': self.dept_ho.id,
            'job_id': self.job_officer.id,
            'parent_id': self.coach_exec.id,
            'default_operating_unit_id': self.ou_main.id,
        })
        self.emp_officer_b = self.Employee.create({
            'name': 'HO Officer B',
            'department_id': self.dept_ho.id,
            'job_id': self.job_officer.id,
            'parent_id': self.coach_exec.id,
            'default_operating_unit_id': self.ou_main.id,
        })

        # Officer C: Same coach & position, but different OU
        self.emp_officer_c_diff_ou = self.Employee.create({
            'name': 'Officer C (Diff OU)',
            'department_id': self.dept_district.id,
            'job_id': self.job_officer.id,
            'parent_id': self.coach_exec.id,
            'default_operating_unit_id': self.ou_district_b.id,
        })

        # Analyst A: Same coach & OU, but different Job Position
        self.emp_analyst_a = self.Employee.create({
            'name': 'HO Analyst A',
            'department_id': self.dept_ho.id,
            'job_id': self.job_analyst.id,
            'parent_id': self.coach_exec.id,
            'default_operating_unit_id': self.ou_main.id,
        })

        # District Managers (across OUs)
        self.dm_main = self.Employee.create({
            'name': 'District Manager HO',
            'department_id': self.dept_ho.id,
            'job_id': self.job_dm.id,
            'parent_id': self.coach_exec.id,
            'default_operating_unit_id': self.ou_main.id,
        })
        self.dm_dist_b = self.Employee.create({
            'name': 'District Manager District B',
            'department_id': self.dept_district.id,
            'job_id': self.job_dm.id,
            'parent_id': self.coach_exec.id,
            'default_operating_unit_id': self.ou_district_b.id,
        })

        # Director
        self.emp_director = self.Employee.create({
            'name': 'HR Director Main',
            'department_id': self.dept_ho.id,
            'job_id': self.job_director.id,
            'parent_id': self.coach_exec.id,
            'default_operating_unit_id': self.ou_main.id,
        })

    def test_01_subordinate_rules(self):
        """Verify Subordinate domain rules:
        1. Employee assessing Coach -> categorized under Subordinate
        2. Same coach + same OU + different job position -> categorized under Subordinate
        3. Coach assessing direct report -> categorized under Team (NOT Subordinate)
        """
        subs = self.Assessment._get_eligible_subordinates_for_emp(self.emp_officer_a)
        
        # Must include coach (evaluating coach = subordinate type)
        self.assertIn(self.coach_exec, subs, "Officer's coach must be an eligible subordinate evaluatee")
        
        # Must include Analyst A (same coach, same OU, different position)
        self.assertIn(self.emp_analyst_a, subs, "Colleague with same coach & same OU but different position must be eligible subordinate")

        # Coach assessing direct report: Officer A should NOT be in coach's subordinate list (assessing direct report = team)
        coach_subs = self.Assessment._get_eligible_subordinates_for_emp(self.coach_exec)
        self.assertNotIn(self.emp_officer_a, coach_subs, "Coach assessing direct report is type 'team', not 'subordinate'")


    def test_02_non_manager_peer_rules(self):
        """Verify Scenario 1 Peer rules (Non-Manager & HO Manager):
        Requires: Same Coach + Same OU + Same Job Position + Same Job Grade.
        """
        peers = self.Assessment._get_eligible_peers_for_emp(self.emp_officer_a)
        
        # Officer B has same coach, same OU, same position & grade
        self.assertIn(self.emp_officer_b, peers, "Officer B must be eligible peer for Officer A")
        
        # Officer C (diff OU) should NOT be in peers for Scenario 1
        self.assertNotIn(self.emp_officer_c_diff_ou, peers, "Officer C in different OU must be excluded for Non-Manager peers")

    def test_03_district_manager_peer_rules(self):
        """Verify Scenario 2 Peer rules (District Manager):
        Allows peer eligibility across different Operating Units (Same Coach + Same Job Position + Same Grade).
        """
        peers_dm = self.Assessment._get_eligible_peers_for_emp(self.dm_main)
        
        # District Manager in District B should be eligible peer even though in different OU
        self.assertIn(self.dm_dist_b, peers_dm, "District Manager in different OU must be eligible peer for District Manager HO")

    def test_04_director_peer_config_generation_and_resolution(self):
        """Verify Scenario 3 (Director Exception):
        1. action_generate_director_records populates Director Peer Config for HR Director
        2. Assign custom peers in config
        3. _get_eligible_peers_for_emp resolves custom assigned peers for Director
        """
        # Step 1: Auto-generate director config records
        res = self.DirectorConfig.action_generate_director_records()
        self.assertEqual(res.get('type'), 'ir.actions.client')

        config = self.DirectorConfig.search([('director_id', '=', self.emp_director.id)], limit=1)
        self.assertTrue(config, "Director Peer Config record must be auto-generated for HR Director")

        # Step 2: Assign peers
        config.write({'peer_ids': [(6, 0, [self.dm_main.id])]})

        # Step 3: Verify peer resolution for Director
        peers_director = self.Assessment._get_eligible_peers_for_emp(self.emp_director)
        self.assertIn(self.dm_main, peers_director, "Assigned peer must be resolved for Director")
