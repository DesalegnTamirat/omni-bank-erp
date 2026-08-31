# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestStateBasedLocking(TransactionCase):
    """Unit tests for state-based locking across all Competency Management models."""

    def setUp(self):
        super().setUp()
        self.Job = self.env['hr.job']
        self.Competency = self.env['competency.competency']
        self.Mapping = self.env['competency.role.mapping']
        self.Cycle = self.env['competency.assessment.cycle']
        self.Assessment = self.env['competency.assessment']
        self.IDP = env_idp = self.env['competency.idp']
        
        self.user_admin = self.env.ref('base.user_admin')
        self.user_test = self.env['res.users'].create({
            'name': 'Test Locking User',
            'login': 'test_locking_user',
            'email': 'test_locking_user@bunnabank.com',
        })
        admin_group = self.env.ref('competency_management.group_competency_admin')
        admin_group.sudo().write({'user_ids': [(4, self.user_test.id)]})
        
        self.job = self.Job.create({'name': 'Test Locking Job'})
        self.competency = self.Competency.create({
            'name': 'Locking Test Competency',
            'code': 'LOCK_TEST_001',
            'pillar': 'technical',
        })

    def test_01_retired_competency_locking(self):
        """1. Lock retired competency dictionary entry."""
        self.competency.write({'status': 'retired'})
        with self.assertRaises(ValidationError):
            self.competency.with_user(self.user_test).write({'name': 'New Name Attempt'})
        with self.assertRaises(ValidationError):
            self.env['competency.proficiency.level'].with_user(self.user_test).create({
                'competency_id': self.competency.id,
                'level': '1',
                'behavioral_indicators': 'Test Indicators',
            })



    def test_03_approved_role_mapping_locking_and_versioning(self):
        """3. Lock approved role mapping fields and lines; allow versioning."""
        mapping = self.Mapping.create({
            'job_position_id': self.job.id,
            'version': 'v1.0',
            'record_type': 'production',
            'line_ids': [(0, 0, {'competency_id': self.competency.id, 'required_proficiency': '2'})]
        })
        mapping.action_submit_for_approval()
        mapping.action_approve()
        
        with self.assertRaises(ValidationError):
            mapping.with_user(self.user_test).write({'version': 'v2.0'})
            
        res = mapping.action_create_new_version()
        new_map = self.Mapping.browse(res['res_id'])
        self.assertEqual(new_map.state, 'draft')
        self.assertEqual(new_map.version, 'v1.1')

    def test_04_closed_assessment_cycle_locking(self):
        """4. Lock closed assessment cycle dates."""
        cycle = self.Cycle.create({'name': 'Locking Cycle Test'})
        cycle.action_start()
        cycle.action_close()
        
        with self.assertRaises(ValidationError):
            cycle.with_user(self.user_test).write({'name': 'Renamed Closed Cycle'})

    def test_05_locked_assessment_and_admin_unlock_override(self):
        """5. Lock finalized assessment; allow Admin justified unlock."""
        emp = self.env['hr.employee'].create({'name': 'Locking Test Employee'})
        cycle = self.Cycle.create({'name': 'Cycle Test 5'})
        asm = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': emp.id,
            'line_ids': [(0, 0, {'competency_id': self.competency.id, 'current_level': '1', 'required_level': '2'})]
        })
        asm.action_submit()
        asm.action_supervisor_review()
        asm.action_hr_verify()
        asm.with_context(force_write=True).action_approve()
        asm.action_lock()
        
        with self.assertRaises(ValidationError):
            asm.with_user(self.user_test).write({'notes': 'Direct edit attempt'})
            
        # Admin unlock with justification succeeds
        asm.write({'notes': 'Unlocking for re-evaluation as requested by HR Director'})
        asm.with_user(self.user_test).action_unlock()
        self.assertEqual(asm.state, 'approved')

    def test_06_completed_idp_locking(self):
        """6. Lock completed IDP goals and checkpoints."""
        emp = self.env['hr.employee'].create({'name': 'IDP Locking Employee'})
        idp = self.IDP.create({
            'employee_id': emp.id,
            'goal_ids': [(0, 0, {'goal': 'Complete Risk Certification', 'activity_type': 'training'})]
        })
        idp.action_submit()
        idp.with_context(force_write=True).action_approve()
        idp.action_start()
        idp.action_complete()
        
        with self.assertRaises(ValidationError):
            idp.with_user(self.user_test).write({'notes': 'Modifying completed IDP'})
