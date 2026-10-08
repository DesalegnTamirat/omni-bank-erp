# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class SuccessionAutoMatchWizard(models.TransientModel):
    _name = 'succession.auto.match.wizard'
    _description = 'Succession Auto-Match Candidates Wizard'

    critical_position_id = fields.Many2one('succession.critical.position', string='Critical Position', readonly=True)
    job_id = fields.Many2one('hr.job', related='critical_position_id.job_id', string='Job Position', readonly=True)
    match_line_ids = fields.One2many('succession.auto.match.line', 'wizard_id', string='Matched Candidates')

class SuccessionAutoMatchLine(models.TransientModel):
    _name = 'succession.auto.match.line'
    _description = 'Succession Auto-Match Candidate Line'
    _order = 'match_percent desc, employee_id'

    wizard_id = fields.Many2one('succession.auto.match.wizard', string='Wizard', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department')
    job_id = fields.Many2one('hr.job', related='employee_id.job_id', string='Current Job')
    
    match_percent = fields.Float(string='Competency Match (%)')
    matched_competency_count = fields.Integer(string='Matched Competencies')
    required_competency_count = fields.Integer(string='Required Competencies')
    
    def action_nominate(self):
        self.ensure_one()
        critical_pos = self.wizard_id.critical_position_id
        
        # Check if already a candidate
        existing = self.env['succession.candidate'].search([
            ('critical_position_id', '=', critical_pos.id),
            ('employee_id', '=', self.employee_id.id)
        ])
        if existing:
            raise ValidationError(_('%s is already nominated for this position.') % self.employee_id.name)
            
        candidate = self.env['succession.candidate'].create({
            'critical_position_id': critical_pos.id,
            'employee_id': self.employee_id.id,
            'nominated_by_id': self.env.user.id,
            'manager_justification': _('Auto-Nominated based on %s%% competency match.') % self.match_percent,
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Successor Candidate'),
            'res_model': 'succession.candidate',
            'res_id': candidate.id,
            'view_mode': 'form',
            'target': 'current',
        }
