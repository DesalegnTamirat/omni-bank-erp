# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    last_attendance_id = fields.Many2one(
        'hr.attendance',
        compute='_compute_last_attendance_id',
        search='_search_last_attendance_id',
        store=False,
        groups="hr_attendance.group_hr_attendance_officer,hr.group_hr_user",
        help="Latest attendance record dynamically resolved without DB table locking."
    )
    last_check_in = fields.Datetime(
        compute='_compute_last_attendance_id',
        store=False,
        groups="hr_attendance.group_hr_attendance_officer,hr.group_hr_user"
    )
    last_check_out = fields.Datetime(
        compute='_compute_last_attendance_id',
        store=False,
        groups="hr_attendance.group_hr_attendance_officer,hr.group_hr_user"
    )
    attendance_state = fields.Selection(
        selection=[('checked_out', "Checked out"), ('checked_in', "Checked in")],
        string="Attendance Status",
        compute='_compute_attendance_state',
        search='_search_attendance_state',
        store=False,
        groups="hr_attendance.group_hr_attendance_officer,hr.group_hr_user"
    )

    def _compute_last_attendance_id(self):
        """
        High-performance batch resolution using PostgreSQL DISTINCT ON (employee_id).
        Zero writes to hr_employee; sub-millisecond in-memory resolution.
        """
        if not self:
            return
        
        self.env.cr.execute("""
            SELECT DISTINCT ON (employee_id) id, employee_id, check_in, check_out
            FROM hr_attendance
            WHERE employee_id IN %s
            ORDER BY employee_id, check_in DESC, id DESC
        """, (tuple(self.ids),))
        rows = self.env.cr.dictfetchall()
        att_map = {r['employee_id']: r for r in rows}

        for emp in self:
            data = att_map.get(emp.id)
            if data:
                emp.last_attendance_id = data['id']
                emp.last_check_in = data['check_in']
                emp.last_check_out = data['check_out']
            else:
                emp.last_attendance_id = False
                emp.last_check_in = False
                emp.last_check_out = False

    def _compute_attendance_state(self):
        """ Dynamically evaluate attendance status based on resolved last attendance. """
        for employee in self:
            att = employee.last_attendance_id
            employee.attendance_state = 'checked_in' if (att and not att.check_out) else 'checked_out'

    def _search_last_attendance_id(self, operator, value):
        """ Allow searching/filtering employees by last_attendance_id. """
        if operator not in ('=', '!=', 'in', 'not in'):
            return []
        self.env.cr.execute("""
            SELECT DISTINCT ON (employee_id) id, employee_id
            FROM hr_attendance
            ORDER BY employee_id, check_in DESC, id DESC
        """)
        rows = self.env.cr.dictfetchall()
        emp_att_map = {r['id']: r['employee_id'] for r in rows}
        
        target_ids = value if isinstance(value, (list, tuple)) else [value]
        matched_emp_ids = [emp_id for att_id, emp_id in emp_att_map.items() if att_id in target_ids]

        if operator in ('=', 'in'):
            return [('id', 'in', matched_emp_ids)]
        else:
            return [('id', 'not in', matched_emp_ids)]

    def _search_attendance_state(self, operator, value):
        """ Allow searching/filtering employees by dynamic attendance state. """
        if operator not in ('=', '!=', 'in', 'not in', 'ilike', 'like'):
            return []
        
        self.env.cr.execute("""
            SELECT DISTINCT ON (employee_id) employee_id, check_out
            FROM hr_attendance
            ORDER BY employee_id, check_in DESC, id DESC
        """)
        rows = self.env.cr.dictfetchall()
        checked_in_ids = [r['employee_id'] for r in rows if not r['check_out']]

        is_checked_in = (
            (operator in ('=', '==', 'ilike', 'like') and value == 'checked_in') or
            (operator == 'in' and 'checked_in' in value) or
            (operator == '!=' and value == 'checked_out')
        )
        if is_checked_in:
            return [('id', 'in', checked_in_ids)]
        else:
            return [('id', 'not in', checked_in_ids)]
