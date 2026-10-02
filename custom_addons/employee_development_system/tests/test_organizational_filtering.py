# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds', 'organizational_filtering')
class TestEdsOrganizationalFiltering(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 1. Setup Operating Units
        cls.ou_hq = cls.env['operating.unit'].search([('work_unit_type', '=', 'head_office')], limit=1)
        if not cls.ou_hq:
            cls.ou_hq = cls.env['operating.unit'].create({
                'name': 'Head Office OU Test',
                'sol_id': 9991,
                'work_unit_type': 'head_office',
            })
        cls.ou_branch = cls.env['operating.unit'].search([('id', '!=', cls.ou_hq.id)], limit=1)
        if not cls.ou_branch:
            cls.ou_branch = cls.env['operating.unit'].create({
                'name': 'Bole Branch OU Test',
                'sol_id': 9992,
                'work_unit_type': 'branch',
            })

        # 2. Setup Departments
        cls.dept_it = cls.env['hr.department'].create({
            'name': 'Information Technology Dept Test',
            'operating_unit_id': cls.ou_hq.id,
        })
        cls.dept_retail = cls.env['hr.department'].create({
            'name': 'Retail Banking Dept Test',
            'operating_unit_id': cls.ou_branch.id,
        })

        # 3. Setup Job Positions
        cls.job_developer = cls.env['hr.job'].create({
            'name': 'Software Developer Test',
            'department_id': cls.dept_it.id,
        })
        cls.job_teller = cls.env['hr.job'].create({
            'name': 'Bank Teller Test',
            'department_id': cls.dept_retail.id,
        })
        cls.job_general = cls.env['hr.job'].create({
            'name': 'General Officer Test',
            'department_id': False,
        })

        # 4. Setup Employees
        cls.emp_dev = cls.env['hr.employee'].create({
            'name': 'Abebe Developer Test',
            'department_id': cls.dept_it.id,
            'job_id': cls.job_developer.id,
            'job_position': cls.job_developer.id,
            'default_operating_unit_id': cls.ou_hq.id,
        })
        cls.emp_teller = cls.env['hr.employee'].create({
            'name': 'Almaz Teller Test',
            'department_id': cls.dept_retail.id,
            'job_id': cls.job_teller.id,
            'job_position': cls.job_teller.id,
            'default_operating_unit_id': cls.ou_branch.id,
        })

        # 5. Setup Cycle
        today = date.today()
        cls.cycle = cls.env['eds.tna.cycle'].create({
            'name': 'FY2026/27 Org Filter TNA Cycle',
            'year': '2026/2027',
            'start_date': today,
            'state': 'collecting',
        })

    def test_01_compat_domain_helpers(self):
        "Test eds.hr.compat domain generation for departments, OUs, jobs, and employees."
        compat = self.env['eds.hr.compat']

        # Operating Unit domain from Department (Top -> Next)
        ou_domain = compat.get_operating_unit_domain(departments=self.dept_it)
        self.assertTrue(ou_domain, "OU domain should not be empty for dept_it")
        self.assertTrue(compat.is_operating_unit_in_departments(self.ou_hq, self.dept_it))
        self.assertFalse(compat.is_operating_unit_in_departments(self.ou_branch, self.dept_it))

        # Empty department allows all operating units
        empty_ou_domain = compat.get_operating_unit_domain(departments=False)
        self.assertEqual(empty_ou_domain, [])

        # Department domain from OU
        dept_domain = compat.get_department_domain(self.ou_hq)
        self.assertIn(('operating_unit_id', 'in', [self.ou_hq.id]), dept_domain)

        # Job domain
        job_domain_dept = compat.get_job_domain(departments=self.dept_it)
        self.assertIn(('department_id', 'in', [self.dept_it.id]), job_domain_dept)

        job_domain_ou = compat.get_job_domain(operating_units=self.ou_hq)
        self.assertIn(('department_id', 'in', [self.dept_it.id]), job_domain_ou)

        # Employee domain
        emp_domain = compat.get_employee_domain(
            department=self.dept_it, operating_unit=self.ou_hq, job=self.job_developer
        )
        self.assertTrue(any(item == ('department_id', 'in', [self.dept_it.id]) for item in emp_domain))
        self.assertTrue(any(isinstance(item, tuple) and item[0] in ('job_id', 'job_position') for item in emp_domain))

    def test_02_course_target_scope_cascading(self):
        "Test eds.course hierarchy: Department -> Operating Unit -> Job Position."
        course = self.env['eds.course'].new({
            'name': 'Core Banking Architecture',
            'department_ids': [(6, 0, [self.dept_it.id])],
            'operating_unit_ids': [(6, 0, [self.ou_branch.id])],  # Mismatched OU
        })
        res = course._onchange_department_ids()
        # Invalid OU pruned
        self.assertNotIn(self.ou_branch.id, course.operating_unit_ids.ids)
        # OU domain restricts to dept_it's operating units
        self.assertIn('operating_unit_ids', res['domain'])
        self.assertTrue(res['domain']['operating_unit_ids'])

        # Clearing department allows all operating units
        course.department_ids = False
        res_empty = course._onchange_department_ids()
        self.assertEqual(res_empty['domain']['operating_unit_ids'], [])

    def test_03_tna_entry_cascading(self):
        "Test eds.tna.entry hierarchy: Department -> Operating Unit -> Job Position."
        entry = self.env['eds.tna.entry'].new({
            'cycle_id': self.cycle.id,
            'department_id': self.dept_it,
            'work_unit_id': self.ou_branch,  # Mismatched OU
        })
        res = entry._onchange_department_id()
        # Mismatched work_unit cleared
        self.assertFalse(entry.work_unit_id)
        self.assertIn('work_unit_id', res['domain'])
        self.assertTrue(res['domain']['work_unit_id'])

        # Selecting employee auto-populates all three
        entry.work_unit_id = False
        entry.department_id = False
        entry.job_position_id = False
        entry.employee_id = self.emp_dev
        entry._onchange_employee_id()
        self.assertEqual(entry.department_id, self.dept_it)
        self.assertEqual(entry.work_unit_id, self.ou_hq)
        self.assertEqual(entry.job_position_id, self.job_developer)

    def test_04_unscheduled_request_cascading(self):
        "Test eds.unscheduled.request hierarchy: Department -> Operating Unit."
        req = self.env['eds.unscheduled.request'].new({
            'department_id': self.dept_retail,
            'work_unit_id': self.ou_hq,  # Mismatched OU
        })
        res = req._onchange_department_id()
        self.assertFalse(req.work_unit_id)
        self.assertIn('work_unit_id', res['domain'])

        # Selecting employee auto-fills organization
        req.employee_id = self.emp_teller
        req._onchange_employee_id()
        self.assertEqual(req.department_id, self.dept_retail)
        self.assertEqual(req.work_unit_id, self.ou_branch)
        self.assertEqual(req.job_position_id, self.job_teller)

    def test_05_nomination_wizard_filtering(self):
        "Test eds.nomination.wizard organization filtering for employees."
        course = self.env['eds.course'].create({
            'name': 'Branch Operations Specialist',
            'department_ids': [(6, 0, [self.dept_retail.id])],
            'operating_unit_ids': [(6, 0, [self.ou_branch.id])],
        })
        today = date.today()
        session = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': today + timedelta(days=10),
            'date_end': today + timedelta(days=12),
        })

        wiz = self.env['eds.nomination.wizard'].new({
            'session_id': session.id,
            'department_id': self.dept_retail.id,
            'work_unit_id': self.ou_branch.id,
        })
        res = wiz._onchange_department_id()
        self.assertIn('work_unit_id', res['domain'])
        self.assertIn('employee_ids', res['domain'])
        emp_domain = res['domain']['employee_ids']
        self.assertTrue(any(item == ('department_id', 'in', [self.dept_retail.id]) for item in emp_domain))

    def test_06_consolidation_and_wizard_filtering(self):
        "Test consolidation and consolidation wizard department and work unit filtering."
        # Create an entry
        self.env['eds.tna.entry'].create({
            'cycle_id': self.cycle.id,
            'employee_id': self.emp_dev.id,
            'department_id': self.dept_it.id,
            'work_unit_id': self.ou_hq.id,
            'proposed_program': 'Enterprise Architecture',
            'justification': 'Required for cloud migration',
            'state': 'submitted',
        })

        # Wizard cascading
        wiz = self.env['eds.tna.consolidation.wizard'].new({
            'cycle_id': self.cycle.id,
            'department_id': self.dept_it.id,
        })
        res = wiz._onchange_department_id()
        self.assertIn('work_unit_id', res['domain'])

        # Consolidation record
        consolidation = self.env['eds.tna.consolidation'].create({
            'cycle_id': self.cycle.id,
            'department_id': self.dept_it.id,
            'work_unit_id': self.ou_hq.id,
        })
        consolidation.action_consolidate()
        self.assertEqual(consolidation.entry_count, 1)

    def test_07_internship_cascading(self):
        "Test internship application supervisor and department cascading."
        intern = self.env['eds.internship.application'].new({
            'applicant_name': 'Intern Candidate Test',
            'department_id': self.dept_it.id,
        })
        res = intern._onchange_department_id()
        self.assertIn('work_unit_id', res['domain'])
        self.assertIn('supervisor_id', res['domain'])

        # Selecting supervisor auto-fills department and work unit
        intern.supervisor_id = self.emp_dev
        intern._onchange_supervisor_id()
        self.assertEqual(intern.department_id, self.dept_it)
        self.assertEqual(intern.work_unit_id, self.ou_hq)
