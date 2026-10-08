# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class HrCareerIdp(models.Model):
    """
    Individual Career Development Plan (ICDP).
    Automatically generated when a career aspiration is approved (FR-IDP-001).
    """
    _name = 'hr.career.idp'
    _description = 'Individual Career Development Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='IDP Reference', required=True, copy=False, readonly=True, default='New')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True,
        default=lambda self: self.env.user.employee_id)
        
    aspiration_id = fields.Many2one('hr.career.aspiration', string='Source Aspiration', domain="[('employee_id', '=', employee_id)]")
    target_job_id = fields.Many2one('hr.job', string='Target Role', tracking=True, required=True)
    
    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            # Auto-populate with the employee's latest active aspiration
            aspiration = self.env['hr.career.aspiration'].search([
                ('employee_id', '=', self.employee_id.id)
            ], limit=1, order='id desc')
            
            if aspiration:
                self.aspiration_id = aspiration.id
            else:
                self.aspiration_id = False
        else:
            self.aspiration_id = False

    @api.onchange('aspiration_id')
    def _onchange_aspiration_id(self):
        if self.aspiration_id and self.aspiration_id.target_job_id:
            self.target_job_id = self.aspiration_id.target_job_id

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Review'),
        ('active', 'Active / In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    
    start_date = fields.Date(string='Start Date', default=fields.Date.context_today)
    target_completion_date = fields.Date(string='Target Completion Date')
    
    line_ids = fields.One2many('hr.career.idp.line', 'idp_id', string='Development Activities')
    
    manager_id = fields.Many2one('hr.employee', string='Approving Manager', related='employee_id.parent_id', readonly=True)
    notes = fields.Text(string='General Notes')

    # Computed fields to control form access
    is_owner = fields.Boolean(compute='_compute_is_owner', string='Is Owner')
    is_manager_user = fields.Boolean(compute='_compute_is_manager_user', string='Is Manager User')

    @api.depends('employee_id')
    def _compute_is_owner(self):
        for rec in self:
            rec.is_owner = rec.employee_id and rec.employee_id.user_id == self.env.user

    @api.depends('manager_id')
    def _compute_is_manager_user(self):
        for rec in self:
            is_mgr = rec.manager_id and rec.manager_id.user_id == self.env.user
            is_coach = rec.employee_id and rec.employee_id.coach_id and rec.employee_id.coach_id.user_id == self.env.user
            is_hr = self.env.user.has_group('hr_employee_custom.group_career_path_admin')
            rec.is_manager_user = bool(is_mgr or is_coach or is_hr)

    competency_gap_html = fields.Html(string='Competency Gap Analysis', compute='_compute_competency_gap_html')

    @api.depends('target_job_id', 'employee_id')
    def _compute_competency_gap_html(self):
        for rec in self:
            html = '<div class="text-muted p-4 text-center">Please select a Target Role and Employee to generate gap analysis.</div>'
            if rec.target_job_id and rec.employee_id:
                job = rec.target_job_id
                emp = rec.employee_id
                
                # Helper to get current employee score
                def get_emp_score(comp_id):
                    assessment = self.env['competency.assessment'].search([
                        ('employee_id', '=', emp.id),
                        ('state', 'in', ['approved', 'locked']),
                    ], order='id desc', limit=1)
                    if assessment:
                        match = assessment.line_ids.filtered(lambda c: c.competency_id.id == comp_id)
                        if match and match[0].current_level:
                            try:
                                return float(match[0].current_level)
                            except:
                                pass
                    return 0.0
                    
                mapping = self.env['competency.role.mapping'].search([('job_position_id', '=', job.id)], limit=1) if 'competency.role.mapping' in self.env else False
                
                if mapping and mapping.line_ids:
                    # Using standard Odoo list table styling
                    html = '<div class="table-responsive"><table class="table table-sm table-hover" style="margin-bottom: 0;">'
                    html += '<thead><tr style="border-bottom: 2px solid #dee2e6;">'
                    html += '<th>Competency</th>'
                    html += '<th>Pillar</th>'
                    html += '<th class="text-end">Weight</th>'
                    html += '<th class="text-end">Assessment Score</th>'
                    html += '<th class="text-end">Required Score</th>'
                    html += '<th class="text-end">Gap Size</th>'
                    html += '<th class="text-center">Status</th>'
                    html += '</tr></thead><tbody>'
                    
                    for line in mapping.line_ids:
                        req_lvl = float(line.required_proficiency) if hasattr(line, 'required_proficiency') and line.required_proficiency else 0.0
                        comp = line.competency_id
                        if not comp: continue
                        
                        curr_lvl = get_emp_score(comp.id)
                        
                        gap = req_lvl - curr_lvl
                        
                        if curr_lvl >= req_lvl:
                            # Meets or Exceeds (Green)
                            row_class = 'table-success'
                            badge_class = 'text-bg-success'
                            status_text = 'Meets' if curr_lvl == req_lvl else 'Exceeds'
                            gap_display = "0.00" if curr_lvl == req_lvl else f"+{curr_lvl - req_lvl:.2f}"
                        else:
                            # Gap (Red)
                            row_class = 'table-danger'
                            badge_class = 'text-bg-danger'
                            status_text = 'Gap Detected'
                            gap_display = f"{gap:.2f}"
                            
                        # Format scores to 2 decimals like in the screenshot
                        req_str = f"{req_lvl:.2f}"
                        curr_str = f"{curr_lvl:.2f}"
                        weight_str = f"{line.weight:.2f}" if hasattr(line, 'weight') and line.weight else "0.00"
                        pillar_str = dict(comp._fields['pillar'].selection).get(comp.pillar, '') if hasattr(comp, 'pillar') and comp.pillar else ''
                        
                        html += f'<tr class="{row_class}">'
                        html += f'<td><span class="text-primary">{comp.name}</span></td>'
                        html += f'<td>{pillar_str}</td>'
                        html += f'<td class="text-end">{weight_str}</td>'
                        html += f'<td class="text-end">{curr_str}</td>'
                        html += f'<td class="text-end">{req_str}</td>'
                        html += f'<td class="text-end">{gap_display}</td>'
                        html += f'<td class="text-center"><span class="badge rounded-pill {badge_class}">{status_text}</span></td>'
                        html += '</tr>'
                        
                    html += '</tbody></table></div>'
                else:
                    html = '<div class="alert alert-info" role="alert"><i class="fa fa-info-circle me-2"></i>No competency mapping found for the Target Role.</div>'
            rec.competency_gap_html = html

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('hr.career.idp') or 'IDP-New'
        return super().create(vals_list)

    def action_generate_gaps(self):
        """Automatically identify competency gaps and recommend development lines (FR-IDP-002)."""
        for rec in self:
            if not rec.target_job_id or not rec.employee_id:
                raise ValidationError(_("Please ensure both an Employee and Target Role are selected."))
                
            job = rec.target_job_id
            emp = rec.employee_id
            
            # Helper to get current employee score
            def get_emp_score(comp_id):
                assessment = self.env['competency.assessment'].search([
                    ('employee_id', '=', emp.id),
                    ('state', 'in', ['approved', 'locked']),
                ], order='id desc', limit=1)
                if assessment:
                    match = assessment.line_ids.filtered(lambda c: c.competency_id.id == comp_id)
                    if match and match[0].current_level:
                        try:
                            return float(match[0].current_level)
                        except:
                            pass
                return 0.0
                
            new_lines = []
            mapping = self.env['competency.role.mapping'].search([('job_position_id', '=', job.id)], limit=1) if 'competency.role.mapping' in self.env else False
            
            if mapping:
                for line in mapping.line_ids:
                    req_lvl = float(line.required_proficiency) if hasattr(line, 'required_proficiency') and line.required_proficiency else 0.0
                    comp = line.competency_id
                    if not comp: continue
                    
                    curr_lvl = get_emp_score(comp.id)
                    if curr_lvl < req_lvl:
                        new_lines.append((0, 0, {
                            'target_gap': comp.name,
                            'name': f"Improve {comp.name}",
                            'activity_type': 'training_program',
                        }))
                        
            if new_lines:
                rec.line_ids = new_lines
                rec.message_post(body=_("Gap Analysis generated %d recommended development activities.") % len(new_lines))
            else:
                rec.message_post(body=_("No competency gaps found for the Target Role."))

    def action_submit(self):
        self.write({'state': 'submitted'})
        for rec in self:
            rec.message_post(body=_("IDP submitted to Manager for review."))

    def action_activate(self):
        self.write({'state': 'active'})
        for rec in self:
            rec.line_ids.filtered(lambda l: l.status in ('pending', False)).write({'status': 'in_progress'})
            rec.message_post(body=_("IDP Approved and Activated by Manager. All activities are now In Progress."))

    def action_complete(self):
        for rec in self:
            rec.line_ids.filtered(lambda l: l.status != 'completed').write({
                'status': 'completed',
                'completion_date': fields.Date.context_today(self)
            })
            rec.write({'state': 'completed'})
            rec.message_post(body=_("IDP successfully completed. All underlying activities have been marked as Completed."))
        
    def action_cancel(self):
        self.write({'state': 'cancelled'})


class HrCareerIdpLine(models.Model):
    """
    A specific development activity within an IDP to close a competency gap.
    """
    _name = 'hr.career.idp.line'
    _description = 'IDP Activity Line'

    idp_id = fields.Many2one('hr.career.idp', string='IDP Reference', required=True, ondelete='cascade')
    target_gap = fields.Char(string='Target Gap / Competency')
    
    # 1. Goal/Competency
    competency_id = fields.Many2one('recruitment.competency', string='Goal / Competency')
    
    # 2. Development Methods
    activity_type = fields.Selection([
        ('coaching', 'Coaching'),
        ('mentoring', 'Mentoring'),
        ('job_rotation', 'Job Rotation'),
        ('acting_assignment', 'Acting Assignment'),
        ('stretch_assignment', 'Stretch Assignment'),
        ('training_program', 'Formal Training Program'),
        ('certification', 'Certification'),
        ('learning_activity', 'General Learning Activity'),
    ], string='Development Method', required=True, default='training_program')
    
    # 3. Milestone / Activity
    name = fields.Char(string='Milestone / Activity', required=True)
    
    # 4. Target
    target_outcome = fields.Char(string='Target')
    
    # 5. Timeline
    target_date = fields.Date(string='Timeline')
    
    # 6. Resource / Support (Removed)
    
    # 7. Progress / Status
    status = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed')
    ], string='Progress / Status', default='pending')
    
    # 8. Employee Comment
    employee_comment = fields.Text(string='Employee Comment')
    
    # 9. Supervisor Feedback
    supervisor_feedback = fields.Text(string='Supervisor Feedback')
    
    completion_date = fields.Date(string='Completion Date')
    notes = fields.Text(string='Notes/Details')

    idp_state = fields.Selection(related='idp_id.state', string="IDP Status")
    is_manager = fields.Boolean(compute='_compute_is_manager', string="Is Manager")

    @api.depends('idp_id.manager_id', 'idp_id.employee_id')
    def _compute_is_manager(self):
        for rec in self:
            # Check if current user is the manager or an HR admin
            is_hr = self.env.user.has_group('hr.group_hr_user')
            is_mgr = rec.idp_id.manager_id and rec.idp_id.manager_id.user_id == self.env.user
            rec.is_manager = bool(is_mgr or is_hr)
