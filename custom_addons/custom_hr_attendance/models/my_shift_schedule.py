# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class MyShiftSchedule(models.TransientModel):
    _name = 'my.shift.schedule'
    _description = 'My Current Shift Schedule'

    employee_id = fields.Many2one('hr.employee', string="Employee Name", readonly=True)
    job_position = fields.Char(string="Job Position", readonly=True)
    department_id = fields.Many2one('hr.department', string="Department", readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string="Operating Unit / Branch", readonly=True)
    
    assignment_source = fields.Selection([
        ('roster', 'Job Position Roster Exception'),
        ('job_position', 'Job Position Exception'),
        ('location', 'Location Based Exception'),
        ('default', 'Default System Shift'),
    ], string="Shift Assignment Source", readonly=True)
    
    schedule_name = fields.Char(string="Schedule Name", readonly=True)
    shift_id = fields.Many2one('job.shift', string="Shift Definition", readonly=True)
    
    start_time = fields.Float(string="Start Time", readonly=True)
    end_time = fields.Float(string="End Time", readonly=True)
    duration = fields.Float(string="Net Worked Duration (Hours)", readonly=True)
    time_range = fields.Char(string="Time Range", readonly=True)
    
    start_date = fields.Date(string="Start Date", readonly=True)
    end_date = fields.Date(string="End Date", readonly=True)

    @api.model
    def action_open_my_shift(self):
        """
        Resolves the logged-in user's active shift hierarchy
        and opens a List View with 1 row (or Form view if clicked).
        """
        user = self.env.user
        employee = user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        today = fields.Date.context_today(self)

        # Priority 1: Job Position Roster Exception (Date-based)
        if employee:
            roster = self.env['job.position.roster.exception'].sudo().search([
                ('employee_id', '=', employee.id),
                ('active', '=', True),
                ('start_date', '<=', today),
                ('end_date', '>=', today)
            ], order='start_date desc, id desc', limit=1)

            if roster:
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('My Shift Schedule (Roster Exception)'),
                    'res_model': 'job.position.roster.exception',
                    'domain': [('id', '=', roster.id)],
                    'view_mode': 'list,form',
                    'target': 'current',
                }

            # Priority 2: Job Position Exception (Static)
            job_ex = self.env['job.position.exception'].sudo().search([
                ('employee_id', '=', employee.id),
                ('active', '=', True),
                ('start_date', '<=', today),
                '|', ('end_date', '=', False), ('end_date', '>=', today)
            ], order='start_date desc, id desc', limit=1)

            if job_ex:
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('My Shift Schedule (Job Position Exception)'),
                    'res_model': 'job.position.exception',
                    'domain': [('id', '=', job_ex.id)],
                    'view_mode': 'list,form',
                    'target': 'current',
                }

            # Priority 3: Location Based Exception (Branch / Operating Unit)
            if employee.default_operating_unit_id:
                loc_ex = self.env['location.based.exception'].sudo().search([
                    '|', ('operating_unit_ids', 'in', [employee.default_operating_unit_id.id]),
                         ('operating_unit', '=', employee.default_operating_unit_id.id),
                    ('active', '=', True),
                    ('start_date', '<=', today),
                    '|', ('end_date', '=', False), ('end_date', '>=', today)
                ], order='start_date desc, id desc', limit=1)

                if loc_ex:
                    return {
                        'type': 'ir.actions.act_window',
                        'name': _('My Shift Schedule (Location Based Exception)'),
                        'res_model': 'location.based.exception',
                        'domain': [('id', '=', loc_ex.id)],
                        'view_mode': 'list,form',
                        'target': 'current',
                    }

        # Priority 4: Default System Shift from Settings (Transient Record)
        self.sudo().search([('create_uid', '=', self.env.uid)]).unlink()

        def _fmt(f_val):
            val = float(f_val or 0.0) % 24.0
            h = int(val)
            m = int(round((val - h) * 60))
            if m >= 60:
                h = (h + 1) % 24
                m = 0
            return f"{h:02d}:{m:02d}"

        ICP = self.env['ir.config_parameter'].sudo()
        m_time = float(ICP.get_param('hr_attendance.morning_time', '8.0'))
        e_time = float(ICP.get_param('hr_attendance.exit_time', '17.0'))
        enable_lunch = ICP.get_param('hr_attendance.enable_lunch_break', 'False').lower() in ('true', '1')
        lunch_dur = float(ICP.get_param('hr_attendance.lunch_duration', '1.0')) if enable_lunch else 0.0

        gross = e_time - m_time
        if gross < 0:
            gross += 24.0
        dur = max(0.0, round(gross - lunch_dur, 2))
        t_range = f"{_fmt(m_time)} - {_fmt(e_time)}"

        rec = self.create({
            'employee_id': employee.id if employee else False,
            'job_position': (employee.job_title or (employee.job_id.name if employee.job_id else '')) if employee else 'System Administrator',
            'department_id': (employee.department_id.id if employee.department_id else False) if employee else False,
            'operating_unit_id': (employee.default_operating_unit_id.id if employee.default_operating_unit_id else False) if employee else False,
            'assignment_source': 'default',
            'schedule_name': _("Default System Shift (%s - %s)") % (_fmt(m_time), _fmt(e_time)),
            'start_time': m_time,
            'end_time': e_time,
            'duration': dur,
            'time_range': t_range,
            'start_date': today,
            'end_date': False,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('My Shift Schedule'),
            'res_model': 'my.shift.schedule',
            'domain': [('id', '=', rec.id)],
            'view_mode': 'list,form',
            'target': 'current',
        }
