# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class PmInitiative(models.Model):
    _name = 'pm.initiative'
    _description = 'Strategic Issue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Strategic Issue Title', required=True, tracking=True)
    code = fields.Char(string='ID / Ref', readonly=True, copy=False, default=lambda self: _('New'), tracking=True)
    owner_id = fields.Many2one('res.users', string='Strategic Owner / Sponsor', default=lambda self: self.env.user, tracking=True)
    date_start = fields.Date(string='Start Date', tracking=True)
    date_end = fields.Date(string='Target End Date', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft / Proposed'),
        ('in_progress', 'Active / In Progress'),
        ('achieved', 'Achieved'),
        ('cancelled', 'Cancelled')
    ], string='Status', compute='_compute_initiative_state', store=True, readonly=False, default='draft', tracking=True)
    
    description = fields.Html(string='Description', help='Context and scope regarding this strategic issue.')
    strategic_source_id = fields.Many2one('pm.strategic.source', string='Strategic Source', tracking=True)
    strategic_objective_id = fields.Many2one('pm.strategic.objective', string='Strategic Objective', tracking=True)
    
    # Boss feedback additions
    lead_office_id = fields.Many2one('pm.lead.office', string='Project Lead Office', tracking=True, help='Organizational Directorate or Office acronym.')
    owner_unit = fields.Char(string='Strategic Issues Owner', tracking=True, help='Responsible organizational work unit or department.')
    sponsor_unit = fields.Char(string='Strategic Issues Sponsor', tracking=True, help='Executive sponsor office or division.')

    project_ids = fields.One2many('pm.project', 'initiative_id', string='Projects')
    project_count = fields.Integer(string='Total Projects', compute='_compute_project_stats', store=True)
    progress_rate = fields.Float(string='Progress (%)', compute='_compute_project_stats', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pm.initiative') or _('New')
        return super().create(vals_list)

    @api.constrains('date_start', 'date_end')
    def _check_initiative_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_(
                    "Strategic Issue '%s': End Date (%s) cannot be earlier than Start Date (%s)!"
                ) % (rec.name, rec.date_end, rec.date_start))

    @api.depends('project_ids', 'project_ids.status', 'project_ids.progress_rate')
    def _compute_project_stats(self):
        for rec in self:
            rec.project_count = len(rec.project_ids)
            active_projects = rec.project_ids.filtered(
                lambda p: p.status not in ('cancelled',)
            )
            if active_projects:
                rec.progress_rate = (
                    sum(p.progress_rate for p in active_projects) / len(active_projects)
                )
            else:
                rec.progress_rate = 0.0

    @api.depends('project_ids', 'project_ids.status', 'project_ids.progress_rate', 'progress_rate')
    def _compute_initiative_state(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            active_projects = rec.project_ids.filtered(lambda p: p.status not in ('cancelled',))
            if active_projects and all(p.status == 'completed' for p in active_projects) and rec.progress_rate >= 100.0:
                rec.state = 'achieved'
            elif rec.progress_rate > 0.0 or any(p.status == 'active' or p.progress_rate > 0.0 for p in active_projects):
                rec.state = 'in_progress'
            elif rec.state not in ('in_progress', 'achieved'):
                rec.state = 'draft'

