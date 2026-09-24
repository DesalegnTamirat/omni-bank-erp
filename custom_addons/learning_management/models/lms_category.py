# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class LmsCategory(models.Model):
    """LMS Course Taxonomy Category."""
    _name = 'lms.category'
    _description = 'LMS Course Category'
    _order = 'complete_name'
    _parent_store = True

    name = fields.Char(string='Category Name', required=True, translate=True)
    complete_name = fields.Char(string='Complete Name', compute='_compute_complete_name', recursive=True, store=True)
    code = fields.Char(string='Code', required=True)
    parent_id = fields.Many2one('lms.category', string='Parent Category', index=True, ondelete='cascade')
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('lms.category', 'parent_id', string='Subcategories')
    description = fields.Text(string='Description')
    color = fields.Integer(string='Color Index', default=0)
    course_count = fields.Integer(string='Courses', compute='_compute_course_count')
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'Course category code must be unique!'
    )

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for rec in self:
            if rec.parent_id:
                rec.complete_name = f"{rec.parent_id.complete_name} / {rec.name}"
            else:
                rec.complete_name = rec.name

    def _compute_course_count(self):
        for rec in self:
            rec.course_count = self.env['lms.course'].search_count([('category_id', '=', rec.id)])
