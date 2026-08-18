# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

class PanelMemberResponseWizard(models.TransientModel):
    _name = 'panel.member.response.wizard'
    _description = 'Panel Member Interview Response Wizard'

    panel_member_id = fields.Many2one('new.internal.recruitment.panel', string='Internal Panel Member Line')
    ext_panel_member_id = fields.Many2one('external.recruitment.panel', string='External Panel Member Line')
    
    internal_selected_id = fields.Many2one('new.internal.recruitment.selected', string='Internal Process', related='panel_member_id.new_int_panel', readonly=True)
    external_selected_id = fields.Many2one('external.recruitment.selected', string='External Process', related='ext_panel_member_id.ext_panel', readonly=True)

    response_type = fields.Selection([
        ('accept', 'Accept Schedule'),
        ('unavailable', 'Declare Unavailability'),
        ('reschedule', 'Request Change of Date / Time'),
        ('delegate', 'Delegate Responsibility to Alternate Member'),
    ], string='Response Choice', required=True, default='accept')

    reason = fields.Text(string='Reason / Notes')
    proposed_datetime = fields.Datetime(string='Proposed Alternate Date & Time')
    delegate_employee_id = fields.Many2one(
        'hr.employee', string='Substitute Panel Member',
        domain="[('active', '=', True)]",
        help="Select alternate panel member to delegate responsibility to."
    )

    @api.onchange('panel_member_id', 'ext_panel_member_id')
    def _onchange_panel_member_coach_domain(self):
        member = self.panel_member_id or self.ext_panel_member_id
        if member and member.emp_name:
            emp = member.emp_name
            domain = [('id', '!=', emp.id), ('active', '=', True)]
            if emp.coach_id:
                domain.append(('coach_id', '=', emp.coach_id.id))
            elif emp.parent_id:
                domain.append(('parent_id', '=', emp.parent_id.id))
            elif emp.department_id:
                domain.append(('department_id', '=', emp.department_id.id))
            return {'domain': {'delegate_employee_id': domain}}
        return {'domain': {'delegate_employee_id': [('active', '=', True)]}}

    def action_submit_response(self):
        self.ensure_one()
        member = self.panel_member_id or self.ext_panel_member_id
        if not member:
            raise UserError(_("No panel member record specified."))

        rec = getattr(member, 'new_int_panel', False) or getattr(member, 'ext_panel', False)
        name_str = member.emp_name.name if member.emp_name else _("Panel Member")

        if self.response_type == 'accept':
            member.write({
                'response_status': 'accepted',
                'accepted': True,
                'response_reason': self.reason or _("Schedule accepted."),
            })
            if rec:
                rec.message_post(body=_("Interview panel member <b>%s</b> accepted the interview schedule.") % name_str)

        elif self.response_type == 'unavailable':
            if not self.reason:
                raise UserError(_("Please provide a reason for unavailability."))
            member.write({
                'response_status': 'unavailable',
                'accepted': False,
                'response_reason': self.reason,
            })
            if rec:
                rec.message_post(body=_(
                    "Interview panel member <b>%s</b> declared unavailability. Reason: %s"
                ) % (name_str, self.reason))

        elif self.response_type == 'reschedule':
            if not self.reason or not self.proposed_datetime:
                raise UserError(_("Please provide both proposed date/time and reason for rescheduling."))
            member.write({
                'response_status': 'reschedule_requested',
                'accepted': False,
                'response_reason': self.reason,
                'proposed_interview_date': self.proposed_datetime,
            })
            if rec:
                rec.message_post(body=_(
                    "Interview panel member <b>%s</b> requested rescheduling to <b>%s</b>. Reason: %s"
                ) % (name_str, self.proposed_datetime, self.reason))

        elif self.response_type == 'delegate':
            if not self.delegate_employee_id or not self.reason:
                raise UserError(_("Please specify the substitute panel member and provide a reason."))
            member.write({
                'response_status': 'delegation_requested',
                'accepted': False,
                'response_reason': self.reason,
                'delegate_employee_id': self.delegate_employee_id.id,
                'delegation_state': 'pending_hr',
            })
            if rec:
                rec.message_post(body=_(
                    "Interview panel member <b>%s</b> requested delegation to <b>%s</b> (Pending HR Approval). Reason: %s"
                ) % (name_str, self.delegate_employee_id.name, self.reason))

        return {'type': 'ir.actions.act_window_close'}
