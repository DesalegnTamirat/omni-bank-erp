# -*- coding: utf-8 -*-

from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError, ValidationError

class RecruitmentPanelInvitation(models.Model):
    _name = 'recruitment.panel.invitation'
    _description = 'Panel Interview Invitation'
    _auto = False
    _order = 'interview_date desc, id desc'

    panel_type = fields.Selection([
        ('internal', 'Internal'),
        ('external', 'External'),
    ], string="Vacancy Type", readonly=True)
    res_id = fields.Integer(string="Resource ID", readonly=True)
    emp_name = fields.Many2one('hr.employee', string="Panel Member", readonly=True)
    user_id = fields.Many2one('res.users', string="User", readonly=True)
    vacancy_reference = fields.Char(string="Vacancy Reference", readonly=True)
    job_position_id = fields.Many2one('hr.job', string="Job Position", readonly=True)
    selection_criteria = fields.Selection([
        ('Exam', 'Exam'),
        ('Interview', 'Interview'),
    ], string="Assessment Type", readonly=True)
    interview_date = fields.Datetime(string="Scheduled Date & Time", readonly=True)
    interview_location = fields.Text(string="Interview Location", readonly=True)
    response_status = fields.Selection([
        ('pending', 'Pending Response'),
        ('accepted', 'Accepted'),
        ('unavailable', 'Unavailable'),
        ('reschedule_requested', 'Reschedule Requested'),
        ('delegation_requested', 'Delegation Requested'),
    ], string="Response Status", readonly=True)
    accepted = fields.Boolean(string="Accepted", readonly=True)
    delegate_employee_id = fields.Many2one('hr.employee', string="Proposed Alternate Member", readonly=True)
    delegate_user_id = fields.Many2one('res.users', string="Delegate User", readonly=True)
    delegation_state = fields.Selection([
        ('draft', 'Draft'),
        ('pending_hr', 'Pending HR Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string="Delegation Status", readonly=True)
    response_reason = fields.Text(string="Response Reason / Notes", readonly=True)
    proposed_interview_date = fields.Datetime(string="Proposed Date & Time", readonly=True)
    active = fields.Boolean(string="Active", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT 
                    (p.id * 10 + 1)::integer AS id,
                    'internal'::varchar AS panel_type,
                    p.id::integer AS res_id,
                    p.emp_name::integer AS emp_name,
                    e.user_id::integer AS user_id,
                    s.vacancy_reference::varchar AS vacancy_reference,
                    s.job_position::integer AS job_position_id,
                    p.selection_criteria::varchar AS selection_criteria,
                    s.interview_date::timestamp AS interview_date,
                    s.interview_location::text AS interview_location,
                    COALESCE(p.response_status, 'pending')::varchar AS response_status,
                    COALESCE(p.accepted, FALSE)::boolean AS accepted,
                    p.delegate_employee_id::integer AS delegate_employee_id,
                    de.user_id::integer AS delegate_user_id,
                    COALESCE(p.delegation_state, 'draft')::varchar AS delegation_state,
                    p.response_reason::text AS response_reason,
                    p.proposed_interview_date::timestamp AS proposed_interview_date,
                    COALESCE(p.active, TRUE)::boolean AS active
                FROM new_internal_recruitment_panel p
                LEFT JOIN new_internal_recruitment_selected s ON p.new_int_panel = s.id
                LEFT JOIN hr_employee e ON p.emp_name = e.id
                LEFT JOIN hr_employee de ON p.delegate_employee_id = de.id
                WHERE p.active IS NOT FALSE
                
                UNION ALL
                
                SELECT 
                    (p.id * 10 + 2)::integer AS id,
                    'external'::varchar AS panel_type,
                    p.id::integer AS res_id,
                    p.emp_name::integer AS emp_name,
                    e.user_id::integer AS user_id,
                    s.vacancy_reference::varchar AS vacancy_reference,
                    s.job_position::integer AS job_position_id,
                    p.selection_criteria::varchar AS selection_criteria,
                    s.interview_date::timestamp AS interview_date,
                    COALESCE(p.interview_location, s.interview_location)::text AS interview_location,
                    COALESCE(p.response_status, 'pending')::varchar AS response_status,
                    COALESCE(p.accepted, FALSE)::boolean AS accepted,
                    p.delegate_employee_id::integer AS delegate_employee_id,
                    de.user_id::integer AS delegate_user_id,
                    COALESCE(p.delegation_state, 'draft')::varchar AS delegation_state,
                    p.response_reason::text AS response_reason,
                    p.proposed_interview_date::timestamp AS proposed_interview_date,
                    COALESCE(p.active, TRUE)::boolean AS active
                FROM external_recruitment_panel p
                LEFT JOIN external_recruitment_selected s ON p.ext_panel = s.id
                LEFT JOIN hr_employee e ON p.emp_name = e.id
                LEFT JOIN hr_employee de ON p.delegate_employee_id = de.id
                WHERE p.active IS NOT FALSE
            )
        """ % self._table)

    def _check_current_user_is_panel_member(self):
        """Ensure that only the assigned employee (or approved delegate or administrator) can respond."""
        if self.env.su or self.env.user.has_group('base.group_system') or self.env.user._is_admin():
            return
        current_user = self.env.user
        current_emp = current_user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', current_user.id)], limit=1)
        for rec in self:
            assigned_emp = rec.emp_name
            if not assigned_emp:
                continue
            is_assigned = (
                (rec.user_id and rec.user_id == current_user) or
                (assigned_emp.user_id and assigned_emp.user_id == current_user) or
                (current_emp and current_emp == assigned_emp) or
                (hasattr(current_user, 'employee_ids') and assigned_emp in current_user.employee_ids)
            )
            delegate_emp = rec.delegate_employee_id
            if not is_assigned and delegate_emp:
                is_assigned = (
                    (rec.delegate_user_id and rec.delegate_user_id == current_user) or
                    (delegate_emp.user_id and delegate_emp.user_id == current_user) or
                    (current_emp and current_emp == delegate_emp) or
                    (hasattr(current_user, 'employee_ids') and delegate_emp in current_user.employee_ids)
                )
            if not is_assigned:
                emp_name_str = assigned_emp.name if hasattr(assigned_emp, 'name') else str(assigned_emp)
                raise ValidationError(_(
                    "Validation Error: You cannot accept or respond to this interview invitation on behalf of employee '%s'. "
                    "Only '%s' is authorized to respond to this assignment."
                ) % (emp_name_str, emp_name_str))

    def _get_target_panel_record(self):
        self.ensure_one()
        if self.panel_type == 'internal':
            return self.env['new.internal.recruitment.panel'].sudo().browse(self.res_id)
        else:
            return self.env['external.recruitment.panel'].sudo().browse(self.res_id)

    def action_accept_assignment(self):
        for rec in self:
            rec._check_current_user_is_panel_member()
            target = rec._get_target_panel_record()
            if target.exists():
                target.sudo().with_context(bypass_panel_check=True).action_accept_assignment()
        return True

    def action_reject_assignment(self):
        for rec in self:
            rec._check_current_user_is_panel_member()
            target = rec._get_target_panel_record()
            if target.exists():
                target.sudo().with_context(bypass_panel_check=True).action_reject_assignment()
        return True

    def action_open_response_wizard(self):
        self.ensure_one()
        self._check_current_user_is_panel_member()
        target = self._get_target_panel_record()
        if target.exists():
            return target.sudo().with_context(bypass_panel_check=True).action_open_response_wizard()
