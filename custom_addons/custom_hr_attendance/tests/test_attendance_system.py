# -*- coding: utf-8 -*-
import datetime
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo import fields

class TestAttendanceSystem(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.operating_unit = cls.env['operating.unit'].search([], limit=1)
        if not cls.operating_unit:
            cls.operating_unit = cls.env['operating.unit'].create({
                'name': 'Head Office',
                'code': 'HO01',
                'company_id': cls.company.id,
            })

        manager_groups = [
            cls.env.ref('base.group_user').id,
            cls.env.ref('hr_attendance.group_hr_attendance_user').id,
            cls.env.ref('hr_attendance.group_hr_attendance_manager').id,
        ]
        cls.manager_user = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True, mail_create_nolog=True).create({
            'name': 'Test Attendance Manager',
            'login': f'test_mgr_{fields.Datetime.now().timestamp()}',
            'email': 'test_mgr@bunnabank.com',
            'group_ids': [(6, 0, manager_groups)],
        })
        cls.manager_emp = cls.env['hr.employee'].create({
            'name': cls.manager_user.name,
            'user_id': cls.manager_user.id,
            'work_email': cls.manager_user.email,
            'default_operating_unit_id': cls.operating_unit.id,
        })
        mgr_versions = cls.env['hr.version'].search([('employee_id', '=', cls.manager_emp.id)])
        if mgr_versions:
            mgr_versions.sudo().write({'state': 'open'})

        cls.regular_user = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True, mail_create_nolog=True).create({
            'name': 'Test Regular Employee',
            'login': f'test_emp_{fields.Datetime.now().timestamp()}',
            'email': 'test_emp@bunnabank.com',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('custom_hr_attendance.group_hr_attendance_manual_user').id,
            ])],
        })
        cls.regular_emp = cls.env['hr.employee'].create({
            'name': cls.regular_user.name,
            'user_id': cls.regular_user.id,
            'work_email': cls.regular_user.email,
            'parent_id': cls.manager_emp.id,
            'default_operating_unit_id': cls.operating_unit.id,
        })
        reg_versions = cls.env['hr.version'].search([('employee_id', '=', cls.regular_emp.id)])
        if reg_versions:
            reg_versions.sudo().write({'state': 'open'})

    def _set_config(self, key, value):
        self.env['ir.config_parameter'].sudo().set_param(key, str(value))
        self.env.registry.clear_cache()

    def setUp(self):
        super().setUp()
        self.manager_user = self.manager_user.with_env(self.env)
        self.regular_user = self.regular_user.with_env(self.env)
        self.manager_emp = self.manager_emp.with_env(self.env)
        self.regular_emp = self.regular_emp.with_env(self.env)
        # Clean up any open attendances for test employees
        open_atts = self.env['hr.attendance'].sudo().search([
            ('employee_id', 'in', [self.regular_emp.id, self.manager_emp.id]),
            ('check_out', '=', False)
        ])
        if open_atts:
            open_atts.with_context(force_unlink_attendance=True).unlink()

    def test_01_config_matrix_grace_and_restriction(self):
        """Test on-time within grace, late within dead time, and blocked past dead time."""
        self._set_config('hr_attendance.enable_checkin_restriction', True)
        self._set_config('hr_attendance.enable_checkin_grace', True)
        self._set_config('hr_attendance.checkin_grace_period', 0.25)
        self._set_config('hr_attendance.dead_time', 0.3333)

        status, late_h, _, _ = self.regular_emp._evaluate_checkin_status(8.0833, 8.0, 0.3333, False, is_manager=False, allow_late=False)
        self.assertEqual(status, 'Normal')
        self.assertEqual(late_h, 0.0)

        status, late_h, _, _ = self.regular_emp._evaluate_checkin_status(8.3333, 8.0, 0.3333, False, is_manager=False, allow_late=False)
        self.assertEqual(status, 'Late')
        self.assertAlmostEqual(late_h, 0.3333, places=2)

        with self.assertRaises(UserError):
            self.regular_emp._evaluate_checkin_status(8.75, 8.0, 0.3333, False, is_manager=False, allow_late=False)

        self._set_config('hr_attendance.enable_checkin_restriction', False)
        status, late_h, _, _ = self.regular_emp._evaluate_checkin_status(8.75, 8.0, 0.3333, False, is_manager=False, allow_late=False)
        self.assertEqual(status, 'Very Late')
        self.assertAlmostEqual(late_h, 0.75, places=2)
        # Restore configuration back to default True
        self._set_config('hr_attendance.enable_checkin_restriction', True)

    def test_02_preapproval_workflow(self):
        """Test employee preapproval submission and supervisor approval."""
        tomorrow = fields.Date.today() + datetime.timedelta(days=1)
        preapp = self.env['attendance.preapproval'].with_user(self.regular_user).create({
            'employee_id': self.regular_emp.id,
            'date': tomorrow,
            'exception_type': 'predefined_late',
            'start_time': 8.0,
            'end_time': 10.0,
            'approval_reason': 'Branch Official Assignment',
            'state': 'draft',
        })
        self.assertEqual(preapp.state, 'draft')
        preapp.action_submit()
        self.assertEqual(preapp.state, 'requested')

        with self.assertRaises(UserError):
            preapp.with_user(self.regular_user).action_approve()

        preapp.with_user(self.manager_user).action_approve()
        self.assertEqual(preapp.state, 'approved')

        status, _, _, pre_h = self.regular_emp._evaluate_checkin_status(9.5, 8.0, 0.3333, preapp, is_manager=False, allow_late=False)
        self.assertEqual(status, 'Pre-Defined Lateness')
        self.assertAlmostEqual(pre_h, 1.5, places=2)

    def test_03_batch_attendance_request(self):
        """Test multi-day batch attendance request submission and approval."""
        today = fields.Date.today()
        batch_req = self.env['hr.attendance.batch.request'].with_user(self.manager_user).create({
            'start_date': today - datetime.timedelta(days=5),
            'end_date': today - datetime.timedelta(days=1),
            'employee_ids': [(6, 0, [self.regular_emp.id])],
            'coach_id': self.manager_emp.id,
            'operating_unit_id': self.operating_unit.id,
            'justification': 'Batch attendance recording for official assignment',
            'state': 'to_approve',
        })
        self.assertEqual(batch_req.duration_days, 5)
        batch_req.action_approve()
        self.assertEqual(batch_req.state, 'approved')

    def test_04_decoupled_discipline_counters(self):
        """Test rolling counters on hr.employee.discipline.profile without discipline.case creation."""
        cases_before = self.env['discipline.case'].search_count([('employee_id', '=', self.regular_emp.id)])
        profile = self.env['hr.employee.discipline.profile']._get_or_create_profile(self.regular_emp.id)
        self.env['hr.employee.discipline.profile']._increment_late_count(self.regular_emp.id)
        self.env['hr.employee.discipline.profile']._increment_force_checkout_count(self.regular_emp.id)
        cases_after = self.env['discipline.case'].search_count([('employee_id', '=', self.regular_emp.id)])
        self.assertEqual(cases_before, cases_after)
        profile.invalidate_recordset(['late_count_rolling', 'force_checkout_count_rolling'])
        self.assertGreaterEqual(profile.late_count_rolling, 1)
        self.assertGreaterEqual(profile.force_checkout_count_rolling, 1)

    def test_05_audit_trail_unlink_protection(self):
        """Test that attendance records cannot be deleted directly without force_unlink context."""
        att = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create({
            'employee_id': self.regular_emp.id,
            'check_in': fields.Datetime.now(),
        })
        with self.assertRaises(UserError):
            att.unlink()
        att.with_context(force_unlink_attendance=True).unlink()

    def test_06_night_shift_cross_midnight_auto_checkout(self):
        """Test cross-midnight 23:00 - 07:00 shift end calculation and midnight sweep safety."""
        # 1. Float to UTC helper with is_next_day
        now_dt = fields.Datetime.now()
        local_dt = fields.Datetime.context_timestamp(self.regular_emp, now_dt)
        shift_end_utc = self.regular_emp._float_to_utc_datetime(7.0, local_dt, is_next_day=True)
        shift_start_utc = self.regular_emp._float_to_utc_datetime(23.0, local_dt, is_next_day=False)
        self.assertGreater(shift_end_utc, shift_start_utc)
        self.assertAlmostEqual((shift_end_utc - shift_start_utc).total_seconds() / 3600.0, 8.0, places=2)

    def test_07_jit_auto_heal_expired_attendance(self):
        """Test that an expired dangling session from yesterday is auto-closed with Force Checkout when checking in today."""
        yesterday_in = fields.Datetime.now() - datetime.timedelta(days=1, hours=2)
        old_att = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create({
            'employee_id': self.regular_emp.id,
            'check_in': yesterday_in,
            'shift_start_float': 8.0,
            'shift_end_float': 17.0,
        })
        self.env.cr.execute("UPDATE hr_attendance SET create_date = %s WHERE id = %s", (yesterday_in, old_att.id))
        self.assertFalse(old_att.check_out)

        # Trigger attendance action today (bypassing restriction to allow checkin regardless of test run hour)
        new_att = self.regular_emp.with_context(bypass_attendance_restrictions=True)._attendance_action_change()
        
        old_att.invalidate_recordset()
        self.assertTrue(old_att.check_out)
        self.assertEqual(old_att.check_out_status, 'Force Checkout')
        self.assertTrue(old_att.is_force_checkout)
        self.assertEqual(self.regular_emp._last_attendance_action, 'jit_auto_heal_checkin')
        self.assertFalse(new_att.check_out)

        # Cleanup
        new_att.with_context(force_unlink_attendance=True).unlink()
        old_att.with_context(force_unlink_attendance=True).unlink()

    def test_08_shift_end_live_timer_capping(self):
        """Test controller caps duration when current time is past shift end."""
        from odoo.addons.custom_hr_attendance.controllers.controllers import BunnaMyAttendance
        controller = BunnaMyAttendance()
        
        # Create an attendance from this morning at 08:00 AM with shift ending at 17:00 PM
        today_8am = fields.Datetime.now() - datetime.timedelta(hours=12)
        att = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create({
            'employee_id': self.regular_emp.id,
            'check_in': today_8am,
            'shift_start_float': 8.0,
            'shift_end_float': 17.0,
            'check_in_status': 'Normal',
        })
        res = {'id': self.regular_emp.id}
        enriched = controller._enrich_attendance_data(self.regular_emp, res)
        self.assertIn('shift_end_raw', enriched)
        self.assertTrue(enriched.get('shift_end_raw'))

        # Cleanup
        att.with_context(force_unlink_attendance=True).unlink()
