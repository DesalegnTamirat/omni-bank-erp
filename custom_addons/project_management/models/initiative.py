# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class PmInitiative(models.Model):
    _name = 'pm.initiative'
    _description = 'Strategic Initiative'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    # Feedback Line 35: Initiative name
    name = fields.Char(string='Initiative Name', required=True, tracking=True)
    code = fields.Char(string='ID / Ref', readonly=True, copy=False, default=lambda self: _('New'), tracking=True)
    
    # Feedback Line 36: Strategic issues
    strategic_issue_id = fields.Many2one('pm.strategic.issue', string='Strategic Issues', tracking=True, index=True)

    # Feedback Line 37: Strategic objectives: list
    strategic_objective_ids = fields.Many2many(
        'pm.strategic.objective',
        'pm_strategic_objective_initiative_rel',
        'initiative_id',
        'objective_id',
        string='Strategic Objectives',
        tracking=True
    )

    # Feedback Line 38: Strategic sources :list
    strategic_source_ids = fields.Many2many(
        'pm.strategic.source',
        'pm_initiative_source_rel',
        'initiative_id',
        'source_id',
        string='Strategic Sources',
        tracking=True
    )

    # Feedback Line 39-40: Start date & End date
    date_start = fields.Date(string='Start Date', tracking=True)
    date_end = fields.Date(string='Target End Date', tracking=True)

    # Feedback Line 41: Description
    description = fields.Html(string='Description', help='Context, scope, and objectives of this initiative.')
    active = fields.Boolean(string='Active', default=True)

    # Feedback Line 46: Make editable: status, health in each menu
    state = fields.Selection([
        ('draft', 'Draft / Proposed'),
        ('in_progress', 'Active / In Progress'),
        ('achieved', 'Achieved'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)

    health_state = fields.Selection([
        ('on_track', 'On Track'),
        ('at_risk', 'At Risk'),
        ('off_track', 'Off Track'),
        ('on_hold', 'On Hold'),
        ('done', 'Done')
    ], string='Health', default='on_track', tracking=True)

    # Feedback Line 42: Aligned Projects – list of projects – as is
    project_ids = fields.One2many('pm.project', 'initiative_id', string='Aligned Projects')
    project_count = fields.Integer(string='Total Projects', compute='_compute_project_stats', store=True)
    progress_rate = fields.Float(string='Progress (%)', compute='_compute_project_stats', store=True)
    owner_id = fields.Many2one('res.users', string='Initiative Lead', default=lambda self: self.env.user, tracking=True)
    kpi_ids = fields.One2many('pm.initiative.kpi', 'initiative_id', string='KPIs')

    @api.onchange('strategic_issue_id')
    def _onchange_strategic_issue_id(self):
        if self.strategic_issue_id:
            objs = self.env['pm.strategic.objective'].search([('strategic_issue_id', '=', self.strategic_issue_id.id)])
            if objs and not self.strategic_objective_ids:
                self.strategic_objective_ids = objs

    @api.onchange('strategic_objective_ids')
    def _onchange_strategic_objective_ids(self):
        if self.strategic_objective_ids:
            # Auto-infer strategic sources linked to the selected objectives
            sources = self.strategic_objective_ids.mapped('strategic_source_ids')
            if sources:
                self.strategic_source_ids = self.strategic_source_ids | sources
            # Auto-infer strategic issue if not set
            if not self.strategic_issue_id:
                issues = self.strategic_objective_ids.mapped('strategic_issue_id')
                if issues:
                    self.strategic_issue_id = issues[0]

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
                    "Initiative '%s': End Date (%s) cannot be earlier than Start Date (%s)!"
                ) % (rec.name, rec.date_end, rec.date_start))

    @api.depends('project_ids', 'project_ids.status', 'project_ids.progress_rate')
    def _compute_project_stats(self):
        for rec in self:
            rec.project_count = len(rec.project_ids)
            active_projects = rec.project_ids.filtered(lambda p: p.status not in ('cancelled',))
            if active_projects:
                rec.progress_rate = sum(p.progress_rate for p in active_projects) / len(active_projects)
            else:
                rec.progress_rate = 0.0

    def unlink(self):
        """Soft delete: archive instead of permanent deletion."""
        return self.write({'active': False})


class PmInitiativeKpi(models.Model):
    _name = 'pm.initiative.kpi'
    _description = 'Initiative KPI'
    _order = 'sequence, id asc'

    initiative_id = fields.Many2one('pm.initiative', string='Initiative', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='KPI Name', required=True)
    target = fields.Char(string='Target')
    remark = fields.Text(string='Remark')

