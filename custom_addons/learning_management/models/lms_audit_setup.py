# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError


class LmsCourseAuditSetup(models.Model):
    _inherit = 'lms.course'

    @api.model
    def _configure_lms_audit_rules(self):
        """Idempotently enable the repository's OCA auditlog for LMS records.

        Keep high-frequency video heartbeats out of auditlog; operational logs
        retain those events. Production must still export audit logs to a
        separately controlled retention store for tamper resistance.
        """
        Rule = self.env['auditlog.rule'].sudo()
        IrModel = self.env['ir.model'].sudo()
        tracked_models = (
            'lms.course', 'lms.lesson', 'lms.assessment', 'lms.question',
            'lms.question.answer', 'lms.course.assignment', 'lms.enrollment',
            'lms.exam.session', 'lms.certificate',
        )
        for model_name in tracked_models:
            model = IrModel.search([('model', '=', model_name)], limit=1)
            if not model:
                raise UserError(_('Cannot configure LMS audit: model %s is missing.') % model_name)
            rule = Rule.search([('model_id', '=', model.id)], limit=1)
            if rule:
                rule.write({
                    'log_create': True, 'log_write': True, 'log_unlink': True,
                    'state': 'confirmed',
                })
                continue
            binary_fields = self.env['ir.model.fields'].sudo().search([
                ('model_id', '=', model.id), ('ttype', '=', 'binary'),
            ])
            Rule.create({
                'name': 'LMS: %s' % model.name,
                'model_id': model.id,
                'state': 'confirmed',
                'log_type': 'fast',
                'log_create': True,
                'log_write': True,
                'log_unlink': True,
                'log_read': False,
                'log_export_data': False,
                'fields_to_exclude_ids': [(6, 0, binary_fields.ids)],
            })
