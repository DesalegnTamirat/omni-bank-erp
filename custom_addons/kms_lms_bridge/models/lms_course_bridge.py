# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class LmsCourse(models.Model):
    _inherit = 'lms.course'

    library_resource_ids = fields.Many2many(
        'kms.digital.library',
        'kms_lms_course_library_rel',
        'course_id',
        'library_id',
        string='Reference Library Materials',
        help='Curated digital library reading materials, regulatory manuals, and e-books linked from KMS.'
    )
    lesson_learned_ids = fields.Many2many(
        'kms.lesson.learned',
        'kms_lms_course_lesson_rel',
        'course_id',
        'lesson_id',
        string='Relevant Lessons Learned',
        help='Operational incident reviews and validated institutional case studies linked from KMS.'
    )
    library_resource_count = fields.Integer(
        string='Library Materials Count',
        compute='_compute_bridge_counts'
    )
    lesson_learned_count = fields.Integer(
        string='Lessons Learned Count',
        compute='_compute_bridge_counts'
    )

    @api.depends('library_resource_ids', 'lesson_learned_ids')
    def _compute_bridge_counts(self):
        for rec in self:
            rec.library_resource_count = len(rec.library_resource_ids)
            rec.lesson_learned_count = len(rec.lesson_learned_ids)

    def action_view_library_resources(self):
        self.ensure_one()
        return {
            'name': _('Linked Library Materials - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'kms.digital.library',
            'view_mode': 'kanban,list,form',
            'domain': [('id', 'in', self.library_resource_ids.ids)],
        }

    def action_view_lessons_learned(self):
        self.ensure_one()
        return {
            'name': _('Linked Lessons Learned - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'kms.lesson.learned',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.lesson_learned_ids.ids)],
        }
