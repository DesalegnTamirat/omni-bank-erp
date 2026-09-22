# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RecognitionPoint(models.Model):
    """
    Unified Recognition & Gamification Points Ledger (FR-REC-001, FR-REC-003, FR-REC-004).
    Consolidates gamification points earned across KMS (knowledge contribution)
    and LMS (learning achievements).
    """
    _name = 'recognition.point'
    _description = 'Unified Gamification Points Ledger'
    _order = 'create_date desc'

    user_id = fields.Many2one('res.users', string='User', required=True, index=True)
    employee_id = fields.Many2one(
        'hr.employee',
        string='Staff Member',
        compute='_compute_employee_id',
        store=True,
        index=True
    )
    department_id = fields.Many2one(
        'hr.department',
        related='employee_id.department_id',
        string='Department',
        store=True,
        readonly=True
    )
    points = fields.Integer(string='Points Earned', required=True)
    source_module = fields.Selection([
        ('kms', 'Knowledge Management (KMS)'),
        ('lms', 'Learning Management (LMS)'),
    ], string='Source Module', required=True, index=True)
    source_action = fields.Char(string='Action Code', required=True, index=True)
    source_model = fields.Char(string='Source Model')
    source_res_id = fields.Integer(string='Source Record ID')
    description = fields.Char(string='Activity Description')
    date_earned = fields.Date(string='Date Earned', default=fields.Date.context_today, index=True)

    @api.depends('user_id')
    def _compute_employee_id(self):
        for rec in self:
            rec.employee_id = rec.user_id.employee_id.id if rec.user_id and rec.user_id.employee_id else False

    @api.model
    def award_points(self, user, points, source_module, source_action,
                     source_model=None, source_res_id=None, description=None):
        """Helper to create unified point ledger entries safely."""
        if not user or not points:
            return False
        return self.sudo().create({
            'user_id': user.id,
            'points': points,
            'source_module': source_module,
            'source_action': source_action,
            'source_model': source_model or '',
            'source_res_id': source_res_id or 0,
            'description': description or '',
            'date_earned': fields.Date.context_today(self),
        })
