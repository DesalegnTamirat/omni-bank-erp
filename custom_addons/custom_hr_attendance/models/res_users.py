from odoo import models, api
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.constrains('groups_id')
    def _check_attendance_role_rules(self):
        job_position = self.env.ref(
            'custom_hr_attendance.group_hr_attendance_job_position_Officer',
            raise_if_not_found=False
        )
        it_driver = self.env.ref(
            'custom_hr_attendance.group_hr_attendance_it_driver_Officer',
            raise_if_not_found=False
        )
        attendance_officer = self.env.ref(
            'hr_attendance.group_hr_attendance_officer',
            raise_if_not_found=False
        )

        # SAFETY GUARD
        if not job_position or not it_driver or not attendance_officer:
            return

        for user in self:
            groups = user.groups_id

            # Mutually exclusive roles
            if job_position in groups and it_driver in groups:
                raise ValidationError(
                    "A user cannot have both "
                    "Job Position Officer and "
                    "IT and Driver Officer roles at the same time."
                )

            # Job Position Officer requires Attendance Officer
            if job_position in groups and attendance_officer not in groups:
                raise ValidationError(
                    "Job Position Officer role requires "
                    "Attendance Officer role."
                )

            #  IT & Driver Officer requires Attendance Officer
            if it_driver in groups and attendance_officer not in groups:
                raise ValidationError(
                    "IT and Driver Officer role requires "
                    "Attendance Officer role."
                )

    def _get_default_home_action(self):
        """
        When ERP Access Gate is enabled, force non-checked-in employees to
        open the Check In / Check Out Attendance Dashboard upon login.
        """
        self.ensure_one()
        param = self.env['ir.config_parameter'].sudo().get_param('hr_attendance.enable_checkin_gate', 'False')
        gate_enabled = param.lower() in ('true', '1')

        if gate_enabled and not self.has_group('base.group_system') and self.employee_id:
            if self.employee_id.attendance_state != 'checked_in':
                my_att_action = self.env.ref('custom_hr_attendance.action_my_attendance', raise_if_not_found=False)
                if my_att_action:
                    return my_att_action

        return super()._get_default_home_action()

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._sync_attendance_manager_groups()
        return users

    def write(self, vals):
        res = super().write(vals)
        if 'employee_id' in vals or 'employee_ids' in vals:
            self._sync_attendance_manager_groups()
        return res

    def _sync_attendance_manager_groups(self):
        """
        Synchronizes attendance security groups based on employee hierarchy:
        - Non-managers (no direct report employees): Manual Attendance (default via base.group_user)
        - Managers (has direct report employees): Manager: Manage all attendances
        Preserves higher administrative/specialized manager roles if explicitly assigned.
        """
        group_manager = self.env.ref('hr_attendance.group_hr_attendance_user', raise_if_not_found=False)
        group_job_pos = self.env.ref('custom_hr_attendance.group_hr_attendance_job_position_user', raise_if_not_found=False)
        group_it_driver = self.env.ref('custom_hr_attendance.group_hr_attendance_it_driver_user', raise_if_not_found=False)
        group_admin = self.env.ref('hr_attendance.group_hr_attendance_manager', raise_if_not_found=False)

        if not group_manager:
            return

        higher_groups = [g for g in [group_job_pos, group_it_driver, group_admin] if g]

        for user in self:
            if not user.has_group('base.group_user'):
                continue

            emp = user.employee_id or (user.employee_ids[0] if user.employee_ids else False)
            if not emp:
                continue

            has_subordinates = bool(emp.child_ids)
            has_higher_role = any(g in user.groups_id for g in higher_groups)

            if has_subordinates:
                if group_manager not in user.groups_id and not has_higher_role:
                    user.sudo().write({'groups_id': [(4, group_manager.id)]})
            else:
                if group_manager in user.groups_id and not has_higher_role:
                    user.sudo().write({'groups_id': [(3, group_manager.id)]})

    def _get_allowed_job_shift_ids(self, target_employee=None, target_operating_unit=None):
        """
        Returns list of job.shift IDs allowed for the target employee or target operating unit,
        considering both target employee/OU and the assigning coach/manager's OU and department.
        """
        self.ensure_one()
        user_sudo = self.sudo()
        shifts = self.env['job.shift'].sudo().search([('active', '=', True)])

        assigner_emp = user_sudo.employee_id or (user_sudo.employee_ids[0] if user_sudo.employee_ids else False)
        assigner_ou = assigner_emp.default_operating_unit_id if assigner_emp else False
        assigner_dept = assigner_emp.department_id if assigner_emp else False

        target_emp = target_employee or assigner_emp
        target_ou = target_operating_unit or (target_emp.default_operating_unit_id if target_emp else False)
        target_dept = target_emp.department_id if target_emp else False

        allowed = shifts.filtered(lambda s: s.is_applicable_for(
            operating_unit=target_ou,
            department=target_dept,
            assigner_operating_unit=assigner_ou,
            assigner_department=assigner_dept
        ))
        return allowed.ids


