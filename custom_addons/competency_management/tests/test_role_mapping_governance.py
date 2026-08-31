# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestRoleMappingGovernance(TransactionCase):
    """Unit tests for Role-Competency Mapping uniqueness, versioning, supersession, and Demo/Test separation."""

    def setUp(self):
        super().setUp()
        self.Job = self.env['hr.job']
        self.Competency = self.env['competency.competency']
        self.Mapping = self.env['competency.role.mapping']
        
        # Create fresh entities for each test
        self.job_test = self.Job.create({
            'name': 'Test Financial Analyst %s' % self.id,
        })
        
        self.job_demo = self.Job.create({
            'name': 'DEMO Quality Analyst %s' % self.id,
        })
        
        self.competency = self.Competency.search([], limit=1)
        if not self.competency:
            self.competency = self.Competency.create({
                'name': 'Financial Risk Assessment Test',
                'code': 'TEST_FIN_RISK_001',
                'pillar': 'technical',
            })

    def test_01_duplicate_job_version_rejection(self):
        """1. Enforce one active mapping per Job Position + Version."""
        map1 = self.Mapping.create({
            'job_position_id': self.job_test.id,
            'version': 'v1.0',
            'record_type': 'production',
        })
        self.assertTrue(map1.id, "First mapping should be created successfully.")

        with self.assertRaises(ValidationError) as cm:
            self.Mapping.create({
                'job_position_id': self.job_test.id,
                'version': 'v1.0',
                'record_type': 'production',
            })
        self.assertIn("A mapping for this Job Position at this version already exists", str(cm.exception))

    def test_02_version_increment_on_edit(self):
        """2. Enforce proper versioning instead of duplicate same-version records."""
        map_v1 = self.Mapping.create({
            'job_position_id': self.job_test.id,
            'version': 'v1.0',
            'record_type': 'production',
            'line_ids': [(0, 0, {
                'competency_id': self.competency.id,
                'required_proficiency': '3',
                'weight': 1.0,
            })]
        })
        map_v1.action_submit_for_approval()
        map_v1.action_approve()
        self.assertEqual(map_v1.state, 'approved')

        res = map_v1.action_create_new_version()
        new_map_id = res.get('res_id')
        map_v2 = self.Mapping.browse(new_map_id)
        
        self.assertEqual(map_v2.version, 'v1.1')
        self.assertEqual(map_v2.state, 'draft')
        self.assertEqual(map_v2.job_position_id, self.job_test)
        self.assertEqual(len(map_v2.line_ids), 1)

    def test_03_automatic_version_supersession(self):
        """3. Automatic supersession of prior version on new approval."""
        map_v1 = self.Mapping.create({
            'job_position_id': self.job_test.id,
            'version': 'v1.0',
            'record_type': 'production',
            'line_ids': [(0, 0, {
                'competency_id': self.competency.id,
                'required_proficiency': '2',
                'weight': 1.0,
            })]
        })
        map_v1.action_submit_for_approval()
        map_v1.action_approve()
        self.assertEqual(map_v1.state, 'approved')

        map_v2 = self.Mapping.create({
            'job_position_id': self.job_test.id,
            'version': 'v1.1',
            'record_type': 'production',
            'line_ids': [(0, 0, {
                'competency_id': self.competency.id,
                'required_proficiency': '3',
                'weight': 1.0,
            })]
        })
        map_v2.action_submit_for_approval()
        map_v2.action_approve()
        
        self.assertEqual(map_v2.state, 'approved')
        self.assertEqual(map_v1.state, 'archived', "Prior version v1.0 must be automatically archived/superseded!")

    def test_04_rejection_of_demo_test_approval(self):
        """4. Separate test/demo data from production data."""
        demo_map = self.Mapping.create({
            'job_position_id': self.job_demo.id,
            'version': 'v1.0',
            'record_type': 'demo',
            'line_ids': [(0, 0, {
                'competency_id': self.competency.id,
                'required_proficiency': '1',
                'weight': 1.0,
            })]
        })
        
        with self.assertRaises(ValidationError) as cm:
            demo_map.action_submit_for_approval()
        self.assertIn("Demo or Test mapping records cannot be submitted or approved", str(cm.exception))

    def test_05_successful_valid_unique_mapping_save(self):
        """5. Successful save and approval of a valid unique mapping."""
        valid_map = self.Mapping.create({
            'job_position_id': self.job_test.id,
            'version': 'v1.0',
            'record_type': 'production',
            'line_ids': [(0, 0, {
                'competency_id': self.competency.id,
                'required_proficiency': '3',
                'weight': 1.5,
            })]
        })
        self.assertEqual(valid_map.state, 'draft')
        valid_map.action_submit_for_approval()
        self.assertEqual(valid_map.state, 'under_approval')
        valid_map.action_approve()
        self.assertEqual(valid_map.state, 'approved')

    def test_06_assessment_self_approval_rejection(self):
        """6. Segregation of duties: Assessment self-approval rejection (FR-COM-055)."""
        Employee = self.env['hr.employee']
        Cycle = self.env['competency.assessment.cycle']
        Assessment = self.env['competency.assessment']

        emp = Employee.create({'name': 'Self Rater Employee', 'user_id': self.env.user.id})
        cycle = Cycle.create({'name': 'Cycle Self Approval Test'})

        asm = Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': emp.id,
            'assessor_id': self.env.user.id,
            'assessment_type': 'self',
            'line_ids': [(0, 0, {
                'competency_id': self.competency.id,
                'current_level': '2',
                'required_level': '3',
            })]
        })
        asm.action_submit()
        asm.action_supervisor_review()
        asm.action_hr_verify()

        with self.assertRaises(ValidationError) as cm:
            asm.action_approve()
        self.assertIn("You cannot approve your own assessment/IDP", str(cm.exception))
