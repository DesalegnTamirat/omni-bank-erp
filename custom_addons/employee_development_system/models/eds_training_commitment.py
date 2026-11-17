# -*- coding: utf-8 -*-
"""Link the existing HR training commitment ledger to completed EDS enrollments."""

from odoo import api, fields, models, _

from .eds_action_notification import notify_action


class TrainingCommitmentEds(models.Model):
    _inherit = 'training.commitment'

    terms = fields.Text(string='Commitment Terms')
    state = fields.Selection([
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='active', required=True)
    signed_commitment_file = fields.Binary(
        string='Signed Commitment Document', attachment=True)
    signed_commitment_filename = fields.Char(string='Document Filename')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        linked = records.filtered('eds_enrollment_id')
        if not linked:
            return records
        action = self.env.ref('employee_development_system.action_eds_enrollment_my')
        form = self.env.ref('employee_development_system.view_eds_enrollment_form')
        for commitment in linked:
            enrollment = commitment.eds_enrollment_id.sudo()
            user = enrollment.employee_id.sudo().user_id
            if not user or not user.active or user.share:
                continue
            session = enrollment.session_id
            message = _(
                'Your training commitment for %s (%s) has been recorded. '
                'Service period: %s to %s. Terms: %s') % (
                    session.course_id.name or session.program_name or session.name,
                    session.name, commitment.start_date, commitment.end_date,
                    commitment.terms or '')
            notify_action(
                enrollment, user, 'Training commitment recorded', message,
                action_id=action.id,
                form_view_id=form.id, action_label=_('View commitment'))
        return records

    eds_session_id = fields.Many2one(
        'eds.session', string='EDS Training Session', index=True,
        ondelete='restrict', copy=False)
    eds_enrollment_id = fields.Many2one(
        'eds.enrollment', string='EDS Participant', index=True,
        ondelete='restrict', copy=False)
    eds_accepted_at = fields.Datetime(
        string='Employee Accepted At', readonly=True, copy=False)

    _eds_enrollment_commitment_unique = models.Constraint(
        'UNIQUE(eds_enrollment_id)',
        'A training commitment already exists for this EDS participant.')
