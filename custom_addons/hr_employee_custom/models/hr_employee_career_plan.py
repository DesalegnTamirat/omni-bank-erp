# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class HrEmployeeCareerPlan(models.Model):
    """
    Employee Career Plan (EDP).
    Connects an employee to a Career Path and tracks their progression.
    """
    _name = 'hr.employee.career.plan'
    _description = 'Employee Career Development Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    career_path_id = fields.Many2one('hr.career.path', string='Career Path', required=True, tracking=True, domain="[('state', '=', 'approved')]")
    
    current_job_id = fields.Many2one('hr.job', string='Current Position', related='employee_id.job_id', store=True)
    
    current_step_id = fields.Many2one('hr.career.path.node', string='Current Career Step', 
                                      domain="[('career_path_id', '=', career_path_id)]",
                                      help="The step in the career path the employee is currently at. If empty, they might be at the anchor role.")
    
    target_step_id = fields.Many2one('hr.career.path.node', string='Next Target Step',
                                     domain="[('career_path_id', '=', career_path_id)]", tracking=True,
                                     help="The next step the employee is aiming for.")
                                     
    target_job_id = fields.Many2one('hr.job', string='Target Job', related='target_step_id.target_job_id')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active (In Progress)'),
        ('ready', 'Ready for Promotion'),
        ('promoted', 'Promoted'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    
    # Gap Analysis & Readiness
    readiness_score = fields.Float(string='Readiness Score (%)', compute='_compute_readiness_score', store=True)
    gap_analysis = fields.Html(string='Gap Analysis', compute='_compute_readiness_score', store=True)
    
    @api.depends('employee_id', 'target_step_id', 'target_step_id.min_tenure_years', 'target_step_id.min_pms_score')
    def _compute_readiness_score(self):
        for plan in self:
            if not plan.employee_id or not plan.target_step_id:
                plan.readiness_score = 0.0
                plan.gap_analysis = "<p>Please select an employee and target step.</p>"
                continue
            
            score = 0.0
            total_weight = 100.0
            gaps = []
            
            # Simplified mock computation for Readiness Score
            # 1. Tenure (Weight: 40%)
            # We would normally calculate the exact tenure from contracts. For now, mock calculation.
            tenure_weight = 40.0
            actual_tenure = 2.0 # Mock data. Real data requires contract/employee history logic.
            min_tenure = plan.target_step_id.min_tenure_years or 1.0
            tenure_score = min(actual_tenure / min_tenure, 1.0) * tenure_weight
            score += tenure_score
            if actual_tenure < min_tenure:
                gaps.append(f"<li><b>Experience:</b> Needs {min_tenure} years, currently has {actual_tenure} years.</li>")
            else:
                gaps.append(f"<li><b>Experience:</b> Meets requirements ({actual_tenure} years).</li>")
                
            # 2. PMS (Weight: 60%)
            pms_weight = 60.0
            # Mock data. Real data would pull from hr_employee_custom PMS fields or evaluation module
            actual_pms = 4.0 
            min_pms = plan.target_step_id.min_pms_score or 3.0
            pms_score = min(actual_pms / min_pms, 1.0) * pms_weight
            score += pms_score
            if actual_pms < min_pms:
                gaps.append(f"<li><b>Performance:</b> Needs {min_pms} score, currently has {actual_pms}.</li>")
            else:
                gaps.append(f"<li><b>Performance:</b> Meets requirements ({actual_pms} score).</li>")
                
            # Compile results
            plan.readiness_score = score
            if gaps:
                plan.gap_analysis = "<ul>" + "".join(gaps) + "</ul>"
            else:
                plan.gap_analysis = "<p>Ready for promotion.</p>"
                
    def action_activate(self):
        self.write({'state': 'active'})
        
    def action_mark_ready(self):
        self.write({'state': 'ready'})
        
    def action_promote(self):
        self.write({'state': 'promoted'})
        
    def action_cancel(self):
        self.write({'state': 'cancelled'})
