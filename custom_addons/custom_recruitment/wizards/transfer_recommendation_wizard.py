# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup


class TransferRecommendationWizard(models.TransientModel):
    _name = 'transfer.recommendation.wizard'
    _description = 'Transfer Request Supervisor Recommendation Wizard'

    transfer_request_id = fields.Many2one(
        'employee.transfer.request',
        string='Transfer Request',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee Name',
        readonly=True,
    )
    current_position = fields.Char(string='Current Position', readonly=True)
    current_grade = fields.Char(string='Current Grade', readonly=True)
    current_work_unit = fields.Char(string='Current Location', readonly=True)
    current_department = fields.Char(string='Current Department', readonly=True)
    service_in_current_position = fields.Float(string='Current Position Experience (Years)', readonly=True)
    service_in_current_location = fields.Float(string='Current Location Experience (Years)', readonly=True)
    service_in_company = fields.Float(string='Company Experience (Years)', readonly=True)
    total_experience = fields.Float(string='Total Experience (Years)', readonly=True)
    pms_score = fields.Float(string='PMS Score (%)', readonly=True)

    requested_operating_unit = fields.Char(string='Requested Operating Unit', readonly=True)
    alternate_location = fields.Char(string='Alternate Location Preference', readonly=True)
    reason_for_transfer = fields.Text(string='Reason for Transfer', readonly=True)

    supervisor_id = fields.Many2one('hr.employee', string='Supervisor / Coach', readonly=True)
    evaluator_user_id = fields.Many2one('res.users', string='Evaluated By', default=lambda self: self.env.user, readonly=True)
    evaluation_date = fields.Date(string='Evaluation Date', default=fields.Date.context_today, readonly=True)

    recommendation_score = fields.Float(
        string='Supervisor Recommendation Score (0 - 100%)',
        required=True,
        default=0.0,
        help="Enter the supervisor recommendation score between 0 and 100% (weighted in final ranking).",
    )
    recommendation_remarks = fields.Text(
        string='Supervisor Comments / Justification',
        help="Provide detailed feedback on the subordinate's transfer suitability, performance, and justification.",
    )

    def read(self, fields=None, load='_classic_read'):
        return super(TransferRecommendationWizard, self.sudo()).read(fields=fields, load=load)

    def web_read(self, specification=None, **kwargs):
        return super(TransferRecommendationWizard, self.sudo()).web_read(specification, **kwargs)

    def write(self, vals):
        return super(TransferRecommendationWizard, self.sudo()).write(vals)

    @api.constrains('recommendation_score')
    def _check_recommendation_score(self):
        for rec in self:
            if rec.recommendation_score < 0.0 or rec.recommendation_score > 100.0:
                raise ValidationError(_("Supervisor Recommendation Score must be between 0% and 100%."))

    def action_submit_recommendation(self):
        self.ensure_one()
        wiz_sudo = self.sudo()
        req = wiz_sudo.transfer_request_id
        if not req or not req.exists():
            raise UserError(_("Transfer request record could not be found."))

        if req.state != 'under_review':
            raise ValidationError(_("Cannot submit recommendation: Transfer request %s is currently in '%s' state (must be 'Under Review').") % (req.name, req.state))

        if wiz_sudo.recommendation_score < 0.0 or wiz_sudo.recommendation_score > 100.0:
            raise ValidationError(_("Supervisor Recommendation Score must be between 0% and 100%."))

        # Update transfer request record
        req.sudo().write({
            'supervisor_recommendation_score': wiz_sudo.recommendation_score,
            'supervisor_remarks': wiz_sudo.recommendation_remarks or False,
        })

        emp_name = wiz_sudo.employee_id.name if wiz_sudo.employee_id else req.employee_id.name
        sup_name = wiz_sudo.supervisor_id.name if wiz_sudo.supervisor_id else self.env.user.name

        # Post official audit log to transfer request chatter
        req.message_post(
            body=Markup(
                _("<b>Supervisor Recommendation Submitted:</b><br/>"
                  "• Candidate: <b>%s</b><br/>"
                  "• Evaluated By: <b>%s</b> (%s)<br/>"
                  "• Score: <b>%.2f%%</b><br/>"
                  "• Justification/Comments: %s<br/>"
                  "• Date: %s") % (
                      emp_name,
                      self.env.user.name,
                      sup_name,
                      wiz_sudo.recommendation_score,
                      wiz_sudo.recommendation_remarks or _('No remarks provided.'),
                      wiz_sudo.evaluation_date
                  )
            )
        )

        # Mark pending activity as Done
        activities = req.activity_ids.filtered(
            lambda a: 'Supervisor Recommendation' in (a.summary or '')
        )
        if activities:
            try:
                activities.action_feedback(
                    feedback=_("Supervisor recommendation score (%.2f%%) submitted by %s.") % (wiz_sudo.recommendation_score, self.env.user.name)
                )
            except Exception:
                pass

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recommendation Submitted'),
                'message': _('Supervisor recommendation score (%.2f%%) submitted successfully for %s.') % (
                    wiz_sudo.recommendation_score, emp_name
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
