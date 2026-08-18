# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

class RescheduleInterviewWizard(models.TransientModel):
    _name = 'reschedule.interview.wizard'
    _description = 'HR Interview Rescheduling Wizard'

    internal_selected_id = fields.Many2one('new.internal.recruitment.selected', string='Internal Recruitment Process')
    external_selected_id = fields.Many2one('external.recruitment.selected', string='External Recruitment Process')
    
    new_interview_date = fields.Datetime(string='New Interview Date & Time', required=True, default=fields.Datetime.now)
    new_interview_location = fields.Char(string='New Interview Location')
    
    reschedule_reason = fields.Text(string='Reason for Rescheduling', required=True)
    re_notify_panel = fields.Boolean(string='Notify Panel Members', default=True)
    re_notify_candidates = fields.Boolean(string='Notify Candidates', default=True)

    def action_confirm_reschedule(self):
        self.ensure_one()
        rec = self.internal_selected_id or self.external_selected_id
        if not rec:
            raise UserError(_("No recruitment selection process record specified."))

        rec.write({
            'interview_date': self.new_interview_date,
            'interview_location': self.new_interview_location or rec.interview_location,
        })

        # Reset panel member response statuses
        panel_lines = getattr(rec, 'new_int_rec_panel', False) or getattr(rec, 'ext_rec_panel', False)
        if panel_lines:
            for member in panel_lines:
                member.write({
                    'response_status': 'pending',
                    'response_reason': False,
                    'proposed_interview_date': False,
                })

        # Log audit trail message
        msg = _(
            "<b>Interview Rescheduled by HR Team</b><br/>"
            "• New Date/Time: %s<br/>"
            "• Location: %s<br/>"
            "• Reason: %s"
        ) % (self.new_interview_date, self.new_interview_location or _("Unchanged"), self.reschedule_reason)
        rec.message_post(body=msg)

        if self.re_notify_panel:
            try:
                rec.notify_interview_panel()
            except Exception as e:
                pass

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Interview Rescheduled'),
                'message': _('The interview schedule has been updated and panel members notified.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
