# -*- coding: utf-8 -*-
from odoo import api, fields, models

class PmProjectRisk(models.Model):
    _name = 'pm.project.risk'
    _description = 'Project Risk'
    _order = 'severity desc, id desc'

    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade')
    name = fields.Char(string='Risk Description', required=True)
    category = fields.Selection([
        ('technical', 'Technical / Architecture'),
        ('resource', 'Resource / Staffing'),
        ('schedule', 'Schedule / Timeline'),
        ('budget', 'Budget / Cost'),
        ('external', 'External / Vendor'),
        ('compliance', 'Regulatory & Compliance')
    ], string='Risk Category', default='technical')
    
    probability = fields.Selection([
        ('1', 'Low (1)'),
        ('2', 'Medium (2)'),
        ('3', 'High (3)'),
        ('4', 'Critical (4)')
    ], string='Probability', default='2', required=True)
    
    impact = fields.Selection([
        ('1', 'Low (1)'),
        ('2', 'Medium (2)'),
        ('3', 'High (3)'),
        ('4', 'Critical (4)')
    ], string='Impact', default='2', required=True)
    
    severity = fields.Integer(string='Severity Score', compute='_compute_severity', store=True)
    mitigation = fields.Text(string='Mitigation Strategy')
    owner_id = fields.Many2one('res.users', string='Risk Owner')
    status = fields.Selection([
        ('open', 'Identified / Open'),
        ('mitigated', 'Mitigated / Under Control'),
        ('closed', 'Resolved / Closed')
    ], string='Status', default='open')

    @api.depends('probability', 'impact')
    def _compute_severity(self):
        for rec in self:
            p = int(rec.probability or 1)
            i = int(rec.impact or 1)
            rec.severity = p * i


class PmProjectDependency(models.Model):
    _name = 'pm.project.dependency'
    _description = 'Project Dependency'
    _order = 'id desc'

    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade')
    name = fields.Char(string='Dependency Description', required=True)
    dependency_type = fields.Selection([
        ('upstream', 'Upstream (Prerequisite Project/System)'),
        ('downstream', 'Downstream (Dependent on this Project)'),
        ('external', 'External Third Party / Regulatory')
    ], string='Dependency Type', default='upstream', required=True)
    
    dependent_project_id = fields.Many2one('pm.project', string='Related Project')
    owner_id = fields.Many2one('res.users', string='Owner / Liaison')
    impact_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('critical', 'Critical Blocker')
    ], string='Impact', default='medium')
    status = fields.Selection([
        ('pending', 'Pending / Blocked'),
        ('in_progress', 'Being Addressed'),
        ('satisfied', 'Satisfied / Delivered')
    ], string='Status', default='pending')


class PmProjectCustomTab(models.Model):
    _name = 'pm.project.custom.tab'
    _description = 'Custom Configurable Project Section'
    _order = 'sequence, id'

    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Section / Tab Name', required=True)
    content = fields.Html(string='Section Content & Notes')


class PmProjectAssumption(models.Model):
    _name = 'pm.project.assumption'
    _description = 'Project Assumption'
    _order = 'id asc'

    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='Assumption', required=True)
    category = fields.Selection([
        ('business', 'Business'),
        ('technical', 'Technical / Architecture'),
        ('resource', 'Resource / Staffing'),
        ('governance', 'Governance / Regulatory'),
        ('external', 'External / Vendor'),
        ('other', 'Other')
    ], string='Category', default='business')
    impact = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical')
    ], string='Potential Impact', default='medium')
    status = fields.Selection([
        ('valid', 'Valid / Confirmed'),
        ('invalid', 'Invalid / Disproven'),
        ('under_review', 'Under Review')
    ], string='Status', default='under_review')
    notes = fields.Char(string='Notes / Mitigation')


class PmProjectSkill(models.Model):
    _name = 'pm.project.skill'
    _description = 'Project Required Skill'
    _order = 'id asc'

    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='Skill / Competency', required=True)
    skill_level = fields.Selection([
        ('basic', 'Basic / Beginner'),
        ('intermediate', 'Intermediate / Competent'),
        ('advanced', 'Advanced / Senior'),
        ('expert', 'Expert / Specialist')
    ], string='Proficiency Level', default='intermediate')
    headcount = fields.Integer(string='Headcount Required', default=1)
    assigned_count = fields.Integer(string='Headcount Assigned', default=0)
    notes = fields.Char(string='Role / Notes')

