# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrEmployee(models.Model):
    """
    Extends hr.employee to add Career Path smart button and related fields
    so employees can access their Career Path directly from their Employee Master.
    """
    _inherit = 'hr.employee'

    career_aspiration_ids = fields.One2many(
        'hr.career.aspiration', 'employee_id', string='Career Aspirations')
    career_aspiration_count = fields.Integer(
        string='Career Aspirations', compute='_compute_career_aspiration_count')
    active_aspiration_count = fields.Integer(
        string='Active Aspirations', compute='_compute_career_aspiration_count')
    has_career_path = fields.Boolean(
        string='Has Active Career Path', compute='_compute_career_aspiration_count', store=False)

    @api.depends('career_aspiration_ids', 'career_aspiration_ids.state')
    def _compute_career_aspiration_count(self):
        for emp in self:
            all_aspirations = emp.career_aspiration_ids
            emp.career_aspiration_count = len(all_aspirations)
            active = all_aspirations.filtered(
                lambda a: a.state in ('submitted', 'manager_review', 'approved'))
            emp.active_aspiration_count = len(active)
            emp.has_career_path = bool(active)

    def action_view_career_path(self):
        """
        Smart button action: Opens the employee's Career Map (Visualizer)
        passing the specific employee's ID via context.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'career_path_visualizer',
            'name': _('Career Map — %s') % self.name,
            'context': {
                'active_employee_id': self.id,
            }
        }

    def action_new_career_aspiration(self):
        """
        Opens a new Career Aspiration form, pre-populated with this employee.
        Accessible from the Employee Master 'Career Path' smart button.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Career Aspiration'),
            'res_model': 'hr.career.aspiration',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_employee_id': self.id,
            },
        }

    @api.model
    def get_career_path_graph(self, employee_id):
        """
        Returns JSON data for the Career Path Visualizer component.
        """
        if not employee_id:
            # Fall back to current user's employee when opened from the 'My Career Map' menu
            employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        else:
            employee = self.browse(employee_id)
            
        if not employee or not employee.exists():
            return {'error': 'Employee not found.'}
            
        plan = self.env['hr.employee.career.plan'].search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ['active', 'ready'])
        ], limit=1)
        
        # Calculate current tenure safely
        curr_tenure = 0.0
        if hasattr(employee, 'service_duration_years') and hasattr(employee, 'service_duration_months'):
            curr_tenure = employee.service_duration_years + (employee.service_duration_months / 12.0)
            
        # Helper to fetch competencies for a given job position
        def get_job_competencies(job):
            comps = []
            if not job:
                return comps
                
            # 1. Try to fetch from competency.role.mapping
            if 'competency.role.mapping' in self.env:
                mapping = self.env['competency.role.mapping'].search([('job_position_id', '=', job.id)], limit=1)
                if mapping:
                    for line in mapping.line_ids:
                        req = float(line.required_level) if hasattr(line, 'required_level') and line.required_level else 0.0
                        pillar = line.pillar_id.name if hasattr(line, 'pillar_id') and line.pillar_id else 'Core Competencies'
                        name = line.competency_id.name if hasattr(line, 'competency_id') and line.competency_id else 'Unknown'
                        comps.append({
                            'name': name,
                            'pillar': pillar,
                            'required': req,
                            'current': 0.0,
                            'gap': -req,
                            'status': 'Missing'
                        })
                    return comps
            
            # 2. Fallback to the default job.competencies_id
            if hasattr(job, 'competencies_id') and job.competencies_id:
                for c in job.competencies_id:
                    # Depending on exact structure of hr_competencies_info_job
                    req = float(c.requirement) if hasattr(c, 'requirement') and c.requirement else 0.0
                    try:
                        name = c.competencies.name if hasattr(c, 'competencies') and c.competencies else 'Unknown'
                    except:
                        name = 'Unknown'
                    comps.append({
                        'name': name,
                        'pillar': 'General Requirements',
                        'required': req,
                        'current': 0.0,
                        'gap': -req,
                        'status': 'Missing'
                    })
            return comps
            
        # Whether they have a plan or not, return a valid base structure to prevent UI crashes
        base_data = {
            'employee_name': employee.name,
            'current_job': employee.job_id.name if employee.job_id else 'No Position',
            'nodes': [{
                'id': 0,
                'is_current': True,
                'job_name': employee.job_id.name if employee.job_id else 'No Position',
                'movement_type': 'vertical',
                'requirements': {
                    'current_tenure': curr_tenure,
                    'meets_tenure': True,
                    'competencies': get_job_competencies(employee.job_id)
                }
            }]
        }
        
        if not plan:
            # Dynamically find a career path if no explicit plan exists
            if employee.job_id:
                career_path = self.env['hr.career.path'].search([
                    ('anchor_job_id', '=', employee.job_id.id),
                    ('state', '=', 'approved')
                ], limit=1)
                
                if not career_path:
                    # Maybe they are halfway through a path?
                    node = self.env['hr.career.path.node'].search([
                        ('target_job_id', '=', employee.job_id.id),
                        ('career_path_id.state', '=', 'approved')
                    ], limit=1)
                    if node:
                        career_path = node.career_path_id
        else:
            career_path = plan.career_path_id
            
        if not career_path:
            return base_data
            
        # Determine the current sequence so we only show FUTURE steps
        current_seq = 0
        current_node_rec = career_path.node_ids.filtered(lambda n: n.target_job_id.id == employee.job_id.id)
        if current_node_rec:
            current_seq = current_node_rec[0].sequence
            
        # Append all future target nodes defined in the path
        for node in career_path.node_ids:
            if node.sequence <= current_seq:
                continue
                
            base_data['nodes'].append({
                'id': node.id,
                'is_current': False,
                'job_name': node.target_job_id.name,
                'movement_type': node.movement_type,
                'requirements': {
                    'current_tenure': curr_tenure,
                    'meets_tenure': True,
                    'competencies': get_job_competencies(node.target_job_id)
                }
            })
            
        return base_data

class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'
    
    def action_view_career_path(self):
        """
        Smart button action for the public employee profile.
        """
        self.ensure_one()
        # Find the real employee record
        employee = self.env['hr.employee'].search([('id', '=', self.id)], limit=1)
        if employee:
            return employee.action_view_career_path()
        return {}
