# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup


class SupervisorRecommendationWizard(models.TransientModel):
    _name = 'supervisor.recommendation.wizard'
    _description = 'Supervisor Recommendation Evaluation Wizard'

    vacancy_id = fields.Many2one('job.vacancy', string='Job Vacancy', readonly=True)
    selected_recruitment_id = fields.Many2one('new.internal.recruitment.selected', string='Selected Pipeline', readonly=True)
    candidate_id = fields.Many2one('new.internal.recruitment.selected.candidates', string='Candidate Line', readonly=True)
    
    employee_id = fields.Many2one('hr.employee', string='Employee Name', readonly=True)
    job_position = fields.Char(string='Target Position', readonly=True)
    current_work_unit = fields.Char(string='Current Location', readonly=True)
    current_department = fields.Char(string='Current Department', readonly=True)
    current_position = fields.Char(string='Current Position', readonly=True)
    current_grade = fields.Char(string='Current Grade', readonly=True)
    service_in_company = fields.Float(string='Service in Company (Years)', readonly=True)
    pms_score = fields.Float(string='PMS Score', readonly=True)

    supervisor_id = fields.Many2one('hr.employee', string='Supervisor / Manager', readonly=True)
    evaluator_user_id = fields.Many2one('res.users', string='Evaluated By', default=lambda self: self.env.user, readonly=True)
    evaluation_date = fields.Date(string='Evaluation Date', default=fields.Date.context_today, readonly=True)

    recommendation_score = fields.Float(
        string='Supervisor Recommendation Score (0 - 100%)',
        required=True,
        default=100.0,
        help="Enter the evaluation recommendation mark between 0 and 100%."
    )
    recommendation_remarks = fields.Text(
        string='Supervisor Comments / Justification',
        help="Provide detailed feedback on the candidate's performance, suitability, and recommendation."
    )

    is_batch = fields.Boolean(string='Is Batch Evaluation', default=False)
    line_ids = fields.One2many('supervisor.recommendation.line', 'wizard_id', string='Candidate Lines')

    def read(self, fields=None, load='_classic_read'):
        return super(SupervisorRecommendationWizard, self.sudo()).read(fields=fields, load=load)

    def web_read(self, specification=None, **kwargs):
        return super(SupervisorRecommendationWizard, self.sudo()).web_read(specification, **kwargs)

    def write(self, vals):
        return super(SupervisorRecommendationWizard, self.sudo()).write(vals)

    @api.constrains('recommendation_score')
    def _check_recommendation_score(self):
        for rec in self:
            if not rec.is_batch:
                if rec.recommendation_score < 0.0 or rec.recommendation_score > 100.0:
                    raise ValidationError(_("Recommendation score must be between 0% and 100%."))

    def action_submit_recommendation(self):
        rec_sudo = self.sudo()
        rec_sudo.ensure_one()
        log_target = rec_sudo.selected_recruitment_id
        if not log_target and rec_sudo.vacancy_id and hasattr(rec_sudo.vacancy_id, '_get_selected_recruitment_record'):
            log_target = rec_sudo.vacancy_id._get_selected_recruitment_record()

        if rec_sudo.is_batch:
            for line in rec_sudo.line_ids:
                if line.recommendation_score < 0.0 or line.recommendation_score > 100.0:
                    cand_title = line.employee_id.name if line.employee_id else _('Candidate')
                    raise ValidationError(_("Recommendation score for %s must be between 0%% and 100%%.") % cand_title)
                line.candidate_id.sudo().write({
                    'supervisor_recommendation_score': line.recommendation_score,
                    'supervisor_remarks': line.recommendation_remarks or False,
                })
            
            if log_target and hasattr(log_target, 'message_post'):
                try:
                    log_target.message_post(
                        body=Markup(_("<b>Supervisor Recommendations Submitted:</b> Evaluated %d candidate(s) by %s.") % (len(rec_sudo.line_ids), self.env.user.name))
                    )
                except Exception:
                    pass

            if log_target:
                try:
                    activities = self.env['mail.activity'].sudo().search([
                        ('res_model', '=', 'new.internal.recruitment.selected'),
                        ('res_id', '=', log_target.id),
                        ('user_id', '=', self.env.user.id),
                    ])
                    activities.action_feedback(feedback=_("Supervisor recommendation submitted."))
                except Exception:
                    pass

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Recommendations Submitted'),
                    'message': _('Supervisor recommendations updated successfully for %d candidate(s).') % len(rec_sudo.line_ids),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        else:
            if not rec_sudo.candidate_id:
                raise UserError(_("No candidate line selected for evaluation."))
            
            if rec_sudo.recommendation_score < 0.0 or rec_sudo.recommendation_score > 100.0:
                raise ValidationError(_("Recommendation score must be between 0% and 100%."))

            rec_sudo.candidate_id.sudo().write({
                'supervisor_recommendation_score': rec_sudo.recommendation_score,
                'supervisor_remarks': rec_sudo.recommendation_remarks or False,
            })

            emp_name = rec_sudo.employee_id.name if rec_sudo.employee_id else _('Candidate')
            if log_target and hasattr(log_target, 'message_post'):
                try:
                    log_target.message_post(
                        body=Markup(
                            _("<b>Supervisor Recommendation Submitted:</b><br/>"
                              "• Candidate: <b>%s</b><br/>"
                              "• Score: <b>%.2f%%</b><br/>"
                              "• Comments: %s<br/>"
                              "• Evaluated By: %s on %s") % (
                                  emp_name,
                                  rec_sudo.recommendation_score,
                                  rec_sudo.recommendation_remarks or _('No remarks provided.'),
                                  self.env.user.name,
                                  rec_sudo.evaluation_date
                              )
                        )
                    )
                except Exception:
                    pass

            if log_target:
                try:
                    activities = self.env['mail.activity'].sudo().search([
                        ('res_model', '=', 'new.internal.recruitment.selected'),
                        ('res_id', '=', log_target.id),
                        ('user_id', '=', self.env.user.id),
                    ])
                    activities.action_feedback(feedback=_("Supervisor recommendation submitted for %s.") % emp_name)
                except Exception:
                    pass

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Recommendation Submitted'),
                    'message': _('Supervisor recommendation score (%.2f%%) recorded for %s.') % (rec_sudo.recommendation_score, emp_name),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }

    def action_send_supervisor_requests(self):
        """Sends chat/system notification to all direct supervisors of shortlisted candidates requesting evaluation."""
        self.ensure_one()
        if self.vacancy_id and hasattr(self.vacancy_id, 'action_request_supervisor_recommendation'):
            return self.vacancy_id.action_request_supervisor_recommendation()
        elif self.selected_recruitment_id and hasattr(self.selected_recruitment_id, 'action_request_supervisor_recommendation'):
            return self.selected_recruitment_id.action_request_supervisor_recommendation()
        raise UserError(_("No vacancy or recruitment process found to request supervisor recommendation."))


class SupervisorRecommendationLine(models.TransientModel):
    _name = 'supervisor.recommendation.line'
    _description = 'Supervisor Recommendation Evaluation Line'

    wizard_id = fields.Many2one('supervisor.recommendation.wizard', string='Wizard', ondelete='cascade')
    candidate_id = fields.Many2one('new.internal.recruitment.selected.candidates', string='Candidate Line', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Candidate Name', readonly=True)
    current_position = fields.Char(string='Current Position', readonly=True)
    current_work_unit = fields.Char(string='Work Unit', readonly=True)
    pms_score = fields.Float(string='PMS Score', readonly=True)
    service_in_company = fields.Float(string='Service (Yrs)', readonly=True)
    recommendation_score = fields.Float(string='Rec. Score (0 - 100%)', default=100.0, required=True)
    recommendation_remarks = fields.Char(string='Supervisor Remarks')

    def read(self, fields=None, load='_classic_read'):
        return super(SupervisorRecommendationLine, self.sudo()).read(fields=fields, load=load)

    def web_read(self, specification=None, **kwargs):
        return super(SupervisorRecommendationLine, self.sudo()).web_read(specification, **kwargs)

    def write(self, vals):
        return super(SupervisorRecommendationLine, self.sudo()).write(vals)
