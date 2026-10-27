# -*- coding: utf-8 -*-
"""Private, lasting history of assessment-cycle notifications."""

from odoo import fields, models


class CompetencyNotification(models.Model):
    _name = 'competency.notification'
    _description = 'Competency Notification History'
    _order = 'create_date desc, id desc'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade', readonly=True)
    cycle_id = fields.Many2one('competency.assessment.cycle', index=True, ondelete='set null', readonly=True)
    assessment_id = fields.Many2one('competency.assessment', ondelete='set null', readonly=True)
    name = fields.Char(string='Notification', required=True, readonly=True)
    summary = fields.Char(readonly=True)
    body = fields.Html(readonly=True, sanitize=True)
    mail_message_id = fields.Many2one('mail.message', ondelete='set null', readonly=True)
    event_key = fields.Char(index=True, copy=False, readonly=True)

    _event_key_unique = models.Constraint(
        'UNIQUE(event_key)',
        'This competency notification has already been sent.',
    )
