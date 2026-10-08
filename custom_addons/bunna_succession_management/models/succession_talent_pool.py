# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SuccessionTalentPool(models.Model):
    """
    Talent Pool (FR-TAL-002, FR-TAL-003).
    A named group of employees identified as potential successors
    for a specific Critical Position. Each pool is managed by PPDD.
    """
    _name = 'succession.talent.pool'
    _description = 'Succession: Talent Pool'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'critical_position_id, name'
    _rec_name = 'name'

    name = fields.Char(string='Pool Name', required=True, tracking=True)
    critical_position_id = fields.Many2one(
        'succession.critical.position', string='Critical Position',
        required=True, ondelete='cascade', tracking=True,
        domain="[('state', '=', 'approved')]")
    description = fields.Text(string='Pool Purpose / Notes')
    state = fields.Selection([
        ('active', 'Active'),
        ('closed', 'Closed'),
    ], string='Status', default='active', tracking=True)
    candidate_ids = fields.One2many(
        'succession.candidate', 'talent_pool_id',
        string='Candidates in Pool')
    candidate_count = fields.Integer(
        string='Candidates', compute='_compute_candidate_count')
    ready_now_count = fields.Integer(
        string='Ready Now', compute='_compute_candidate_count')

    @api.depends('candidate_ids', 'candidate_ids.readiness_level', 'candidate_ids.state')
    def _compute_candidate_count(self):
        for rec in self:
            approved = rec.candidate_ids.filtered(lambda c: c.state in ('assessed', 'approved'))
            rec.candidate_count = len(approved)
            rec.ready_now_count = len(approved.filtered(lambda c: c.readiness_level == 'ready_now'))

    def action_close(self):
        self.with_context(force_write=True).write({'state': 'closed'})

    def action_reopen(self):
        self.with_context(force_write=True).write({'state': 'active'})
