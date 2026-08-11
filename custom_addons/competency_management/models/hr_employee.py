# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrEmployeeCompetency(models.Model):
    """hr.employee extension: competency profile smart buttons (/006)."""
    _inherit = 'hr.employee'

    competency_assessment_ids = fields.One2many(
        'competency.assessment', 'employee_id', string='Competency Assessments')
    competency_assessment_count = fields.Integer(
        string='Competency Assessments', compute='_compute_competency_assessment_count')
    competency_idp_ids = fields.One2many(
        'competency.idp', 'employee_id', string='Development Plans (IDP)')
    competency_idp_count = fields.Integer(
        string='Development Plans', compute='_compute_competency_idp_count')

    @api.depends('competency_assessment_ids')
    def _compute_competency_assessment_count(self):
        for rec in self:
            rec.competency_assessment_count = len(rec.competency_assessment_ids)

    @api.depends('competency_idp_ids')
    def _compute_competency_idp_count(self):
        for rec in self:
            rec.competency_idp_count = len(rec.competency_idp_ids)

    def action_view_competency_assessments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Competency Assessments',
            'res_model': 'competency.assessment',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }

    def action_view_competency_idps(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Development Plans (IDP)',
            'res_model': 'competency.idp',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }
