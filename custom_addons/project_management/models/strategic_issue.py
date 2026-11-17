# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class PmStrategicIssue(models.Model):
    _name = 'pm.strategic.issue'
    _description = 'Strategic Issue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Strategic Issue Title', required=True, tracking=True)
    code = fields.Char(string='ID / Ref', readonly=True, copy=False, default=lambda self: _('New'), tracking=True)
    date_start = fields.Date(string='Start Date', tracking=True)
    date_end = fields.Date(string='Target End Date', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft / Proposed'),
        ('in_progress', 'Active / In Progress'),
        ('achieved', 'Achieved'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)

    description = fields.Html(string='Description', help='Context, background, and alignment regarding this strategic issue.')
    strategic_source_ids = fields.Many2many('pm.strategic.source', string='Strategic Sources', tracking=True)
    active = fields.Boolean(string='Active', default=True)

    # Replaced Aligned Projects with Aligned Objectives (Feedback Line 33 & 88)
    objective_ids = fields.One2many('pm.strategic.objective', 'strategic_issue_id', string='Aligned Strategic Objectives')
    objective_count = fields.Integer(string='Total Objectives', compute='_compute_objective_stats', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pm.strategic.issue') or _('New')
        return super().create(vals_list)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_("Strategic Issue '%s': End Date (%s) cannot be earlier than Start Date (%s)!") % (
                    rec.name, rec.date_end, rec.date_start
                ))

    @api.depends('objective_ids')
    def _compute_objective_stats(self):
        for rec in self:
            rec.objective_count = len(rec.objective_ids)

    def unlink(self):
        """Soft delete: archive strategic issue instead of permanent deletion."""
        return self.write({'active': False})

