# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

NON_MANAGERIAL_DURATION = 60
MANAGERIAL_DURATION = 75
NOTIFICATION_DAYS_BEFORE_END = 5


class HrEmployeeProbation(models.Model):
    _name = "hr.employee.probation"
    _inherit = ["mail.thread"]
    _description = "Employee Probation"
    _rec_name = "name"
    active = fields.Boolean(default=True)
    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    _order = "probation_end_date"

    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))

    employee_id = fields.Many2one("hr.employee", string="Employee", required=True, tracking=True)
    job_position_id = fields.Many2one(
        "hr.job", string="Job Position", compute="_compute_from_employee", store=True, readonly=True
    )
    operating_unit_id = fields.Many2one(
        "operating.unit", string="Work Unit", compute="_compute_from_employee", store=True, readonly=True
    )
    supervisor_id = fields.Many2one("hr.employee", string="Supervisor", tracking=True)

    source_recruitment = fields.Selection(
        [("internal", "Internal Recruitment"), ("external", "External Recruitment")],
        string="Recruitment Source", default="external",
    )
    recruitment_reference = fields.Char(string="Recruitment Reference")

    #  ---------------------------------
    employee_category = fields.Selection(
        [("Managerial", "Managerial"), ("Non Managerial", "Non Managerial")],
        string="Employee Category", required=True, default="Non Managerial", tracking=True,
        help="Drives the statutory probation duration: 60 days for Non-Managerial, "
             "75 days for Managerial.",
    )
    probation_start_date = fields.Date(string="Probation Start Date", required=True, default=fields.Date.context_today)
    duration_days = fields.Integer(
        string="Probation Duration (Days)", compute="_compute_duration_days", store=True, readonly=True,
    )
    probation_end_date = fields.Date(
        string="Probation End Date", compute="_compute_probation_end_date", store=True, readonly=True,
    )

    #  ---------------------------------
    notification_sent = fields.Boolean(string="Supervisor Notified", default=False, readonly=True, copy=False)
    notification_date = fields.Datetime(string="Notification Sent On", readonly=True, copy=False)

    #  ---------------------------------
    outcome = fields.Selection(
        [
            ("pending", "Pending"),
            ("satisfactory", "Satisfactory (Confirmation)"),
            ("unsatisfactory", "Unsatisfactory (Termination)"),
            ("discipline", "Discipline Issue"),
        ],
        string="Outcome", default="pending", required=True, tracking=True,
    )
    outcome_date = fields.Date(string="Outcome Recorded On", readonly=True, copy=False)
    outcome_notes = fields.Text(string="Outcome Notes")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("notified", "Supervisor Notified"),
            ("completed", "Completed"),
        ],
        string="Status", default="draft", tracking=True, copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hr.employee.probation") or _("New")
        return super().create(vals_list)

    @api.depends("employee_id")
    def _compute_from_employee(self):
        for rec in self:
            rec.job_position_id = rec.employee_id.job_position if rec.employee_id else False
            rec.operating_unit_id = rec.employee_id.default_operating_unit_id if rec.employee_id else False

    @api.depends("employee_category")
    def _compute_duration_days(self):
        for rec in self:
            rec.duration_days = (
                MANAGERIAL_DURATION if rec.employee_category == "Managerial" else NON_MANAGERIAL_DURATION
            )

    @api.depends("probation_start_date", "duration_days")
    def _compute_probation_end_date(self):
        for rec in self:
            if rec.probation_start_date and rec.duration_days:
                rec.probation_end_date = rec.probation_start_date + timedelta(days=rec.duration_days)
            else:
                rec.probation_end_date = False

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for rec in self:
            if rec.employee_id and rec.employee_id.job_position and rec.employee_id.job_position.employee_category:
                rec.employee_category = rec.employee_id.job_position.employee_category

    def action_start(self):
        for rec in self:
            if not rec.probation_start_date:
                raise ValidationError(_("Please set the Probation Start Date before starting probation."))
            rec.state = "in_progress"
            rec.message_post(body=_("Probation started for %s.") % rec.employee_id.name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Probation Started'),
                'message': _('Probation started for %s.') % self[:1].employee_id.name,
                'type': 'success',
                'sticky': False,
            },
        }

    def _notify_supervisor(self, body):
        """Send a Discuss notification to the supervisor, consistent with the
        notification pattern used elsewhere in this module."""
        self.ensure_one()
        if not self.supervisor_id or not self.supervisor_id.user_id or not self.supervisor_id.user_id.partner_id:
            return
        partner = self.supervisor_id.user_id.partner_id
        channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[partner.id])
        channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")

    def action_notify_supervisor(self):
        """: proactive notification to the Supervisor.
        Can be triggered manually or by the scheduled action below."""
        for rec in self:
            if rec.notification_sent:
                continue
            body = _(
                "Dear %(supervisor)s,<br/><br/>"
                "This is a reminder that the probation period of <b>%(employee)s</b> "
                "(%(position)s) is due to end on <b>%(end_date)s</b>.<br/>"
                "Please submit the probation outcome (Satisfactory / Unsatisfactory / "
                "Discipline Issue) before that date.<br/><br/>Thank you."
            ) % {
                "supervisor": rec.supervisor_id.name or _("Supervisor"),
                "employee": rec.employee_id.name,
                "position": rec.job_position_id.name or "",
                "end_date": rec.probation_end_date,
            }
            rec._notify_supervisor(body)
            rec.message_post(body=_("Supervisor notified of upcoming probation end date."))
            rec.write({
                "notification_sent": True,
                "notification_date": fields.Datetime.now(),
                "state": "notified",
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Supervisor Notified'),
                'message': _('Supervisor notified.'),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def _cron_notify_upcoming_probation_end(self):
        """Scheduled action : notify supervisors 5 days before the
        probation end date for probations still pending an outcome."""
        target_date = fields.Date.context_today(self) + timedelta(days=NOTIFICATION_DAYS_BEFORE_END)
        records = self.search([
            ("state", "in", ["draft", "in_progress"]),
            ("notification_sent", "=", False),
            ("outcome", "=", "pending"),
            ("probation_end_date", "<=", target_date),
        ])
        records.action_notify_supervisor

    def action_record_outcome(self):
        """: record the probation outcome."""
        for rec in self:
            if rec.outcome == "pending":
                raise UserError(_("Please select an Outcome (Satisfactory, Unsatisfactory, or Discipline Issue) "
                                   "before completing the probation."))
            rec.write({
                "state": "completed",
                "outcome_date": fields.Date.context_today(self),
            })
            outcome_label = dict(rec._fields["outcome"].selection).get(rec.outcome)
            rec.message_post(body=_("Probation outcome recorded: %s") % outcome_label)
        outcome_label = dict(self[:1]._fields["outcome"].selection).get(self[:1].outcome, self[:1].outcome)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Outcome Recorded'),
                'message': _('Outcome recorded: %s.') % outcome_label,
                'type': 'success',
                'sticky': False,
            },
        }
