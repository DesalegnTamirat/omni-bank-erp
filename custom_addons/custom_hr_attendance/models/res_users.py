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
