# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools.translate import _


class ResUsers(models.Model):
    _inherit = "res.users"

    # Records come from user_ids field of helpdesk.ticket.team.
    helpdesk_team_ids = fields.Many2many(
        comodel_name="helpdesk.ticket.team",
        relation="helpdesk_ticket_team_res_users_rel",
        column1="res_users_id",
        column2="helpdesk_ticket_team_id",
        string="Helpdesk Teams",
    )
    agent_manual_duty_status = fields.Selection(
        selection=[
            ("available", "Available / On Duty"),
            ("busy", "Busy / Handling Call"),
            ("on_break", "On Break"),
            ("offline", "Offline / Absent"),
        ],
        string="Agent Manual Preference",
        default="available",
        help="Manual status preference set by agent or supervisor while checked in.",
    )
    agent_duty_status = fields.Selection(
        selection=[
            ("available", "Available / On Duty"),
            ("busy", "Busy / Handling Call"),
            ("on_break", "On Break"),
            ("offline", "Offline / Absent"),
        ],
        string="Agent Duty Status",
        compute="_compute_agent_duty_status",
        inverse="_inverse_agent_duty_status",
        search="_search_agent_duty_status",
        help="Dynamically checked against Time Off (hr.leave) and Attendance (hr.attendance).",
    )
    agent_duty_status_reason = fields.Char(
        string="Duty Status Reason",
        compute="_compute_agent_duty_status",
        help="Explanation of current duty status derived from Time Off and Attendance.",
    )
    cc_phone_extension = fields.Char(string="CC Phone / Extension")

    @api.depends("agent_manual_duty_status")
    def _compute_agent_duty_status(self):
        now = fields.Datetime.now()
        leave_model = self.env.get("hr.leave")
        for user in self:
            # Safely resolve employee record added dynamically by hr module
            employee_id = getattr(user, "employee_id", None)
            employee_ids = getattr(user, "employee_ids", None)
            emp = employee_id or (employee_ids[0] if employee_ids else None)
            if not emp:
                user.agent_duty_status = user.agent_manual_duty_status or "available"
                user.agent_duty_status_reason = _("No employee record linked")
                continue

            # 1. Check Time Off (Leaves)
            emp_id = getattr(emp, "id", None)
            is_absent = getattr(emp, "is_absent", False)
            active_leave = None
            if leave_model and emp_id:
                active_leave = leave_model.sudo().search([
                    ("employee_id", "=", emp_id),
                    ("date_from", "<=", now),
                    ("date_to", ">=", now),
                    ("state", "=", "validate"),
                ], limit=1)

            if is_absent or active_leave:
                holiday_status = getattr(active_leave, "holiday_status_id", None) if active_leave else None
                leave_name = getattr(holiday_status, "name", _("Leave")) if holiday_status else _("Leave")
                leave_date_to = getattr(active_leave, "date_to", None) if active_leave else None
                date_to_str = leave_date_to.strftime("%Y-%m-%d") if leave_date_to else ""
                user.agent_duty_status = "offline"
                user.agent_duty_status_reason = _("On Time Off: %s%s") % (
                    leave_name, f" (until {date_to_str})" if date_to_str else ""
                )
                continue

            # 2. Check Attendance (Check-in / Check-out)
            att_state = getattr(emp, "attendance_state", "checked_out")
            if att_state == "checked_out":
                user.agent_duty_status = "offline"
                user.agent_duty_status_reason = _("Offline (Checked Out in Attendance)")
                continue

            if att_state == "checked_in":
                last_att = getattr(emp, "last_attendance_id", None)
                check_in = getattr(last_att, "check_in", None) if last_att else None
                check_in_str = check_in.strftime("%H:%M") if check_in else ""
                manual = user.agent_manual_duty_status or "available"
                if manual == "busy":
                    user.agent_duty_status = "busy"
                    user.agent_duty_status_reason = _("Busy / Handling Call (Checked In)")
                elif manual == "on_break":
                    user.agent_duty_status = "on_break"
                    user.agent_duty_status_reason = _("On Break (Checked In)")
                elif manual == "offline":
                    user.agent_duty_status = "offline"
                    user.agent_duty_status_reason = _("Manually Offline (Checked In)")
                else:
                    user.agent_duty_status = "available"
                    user.agent_duty_status_reason = _("Available / On Duty%s") % (
                        f" (Checked In at {check_in_str})" if check_in_str else ""
                    )
                continue

            # Fallback if employee has no attendance tracking configured
            user.agent_duty_status = user.agent_manual_duty_status or "available"
            user.agent_duty_status_reason = _("Active Duty")

    def _inverse_agent_duty_status(self):
        for user in self:
            user.agent_manual_duty_status = user.agent_duty_status

    def _search_agent_duty_status(self, operator, value):
        users = self.search([("share", "=", False)])
        if operator in ("=", "=="):
            matched = users.filtered(lambda u: u.agent_duty_status == value)
        elif operator in ("!=", "<>"):
            matched = users.filtered(lambda u: u.agent_duty_status != value)
        elif operator == "in":
            matched = users.filtered(lambda u: u.agent_duty_status in value)
        elif operator == "not in":
            matched = users.filtered(lambda u: u.agent_duty_status not in value)
        else:
            matched = users.filtered(lambda u: u.agent_duty_status == value)
        return [("id", "in", matched.ids)]
