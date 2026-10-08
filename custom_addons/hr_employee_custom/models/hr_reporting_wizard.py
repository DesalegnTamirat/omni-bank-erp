# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrReportingWizard(models.Model):
    """
    EM-088: Configurable HR Reporting & Analytics Wizard.
    Launches interactive list, pivot, and graph views for 18 HR report types.
    """
    _name = 'hr.reporting.wizard'
    _description = 'HR Reporting & Analytics Wizard'

    report_type = fields.Selection([
        ('profile', '1. Employee Profile Report'),
        ('headcount', '2. Headcount Report'),
        ('headcount_dept', '3. Headcount by Department'),
        ('headcount_branch', '4. Headcount by Branch (Operating Unit)'),
        ('headcount_grade', '5. Headcount by Grade'),
        ('headcount_position', '6. Headcount by Position'),
        ('demographic', '7. Employee Demographic Report'),
        ('gender', '8. Gender Report'),
        ('age_profile', '9. Age Profile Report'),
        ('length_of_service', '10. Length of Service Report'),
        ('movement', '11. Employee Movement Report'),
        ('promotion', '12. Promotion Report'),
        ('transfer', '13. Transfer Report'),
        ('recruitment', '14. Recruitment Report'),
        ('separation', '15. Separation Report'),
        ('work_permit_expiry', '16. Work Permit Expiry Report'),
        ('document', '17. Employee Document Report'),
        ('status', '18. Employee Status Report'),
    ], string='Report Type', required=True, default='profile')

    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')
    department_id = fields.Many2one('hr.department', string='Department')
    operating_unit_id = fields.Many2one('operating.unit', string='Branch / Operating Unit')
    job_id = fields.Many2one('hr.job', string='Job Position')
    grade_id = fields.Many2one('employee.grade', string='Employee Grade')
    gender = fields.Selection([
        ('all', 'All Genders'),
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ], string='Gender', default='all')
    work_permit_status = fields.Selection([
        ('all', 'All Statuses'),
        ('none', 'Not Applicable'),
        ('valid', 'Valid'),
        ('expiring_soon', 'Expiring Soon'),
        ('expired', 'Expired'),
    ], string='Work Permit Status', default='all')

    def action_generate_report(self):
        self.ensure_one()
        rtype = self.report_type

        # Base Domain
        domain = []

        # Filter by Department
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))

        # Filter by Branch / Operating Unit
        if self.operating_unit_id:
            domain.append(('operating_unit_id', '=', self.operating_unit_id.id))

        # Filter by Job Position
        if self.job_id:
            domain.append(('job_id', '=', self.job_id.id))

        # Filter by Grade
        if self.grade_id:
            domain.append(('grade_id', '=', self.grade_id.id))

        # Filter by Gender
        if self.gender and self.gender != 'all':
            domain.append(('gender', '=', self.gender))

        # Filter by Work Permit Status
        if self.work_permit_status and self.work_permit_status != 'all':
            domain.append(('work_permit_status', '=', self.work_permit_status))

        # Route to appropriate model / action
        if rtype in ('profile', 'headcount', 'headcount_dept', 'headcount_branch', 'headcount_grade', 'headcount_position', 'demographic', 'gender', 'age_profile', 'length_of_service', 'work_permit_expiry', 'status'):
            res_model = 'hr.employee'
            view_mode = 'list,pivot,graph'
            ctx = dict(self.env.context)

            # Specific group_by contexts
            if rtype == 'headcount_dept':
                ctx['search_default_group_department'] = 1
                ctx['group_by'] = ['department_id']
            elif rtype == 'headcount_branch':
                ctx['search_default_group_operating_unit'] = 1
                ctx['group_by'] = ['operating_unit_id']
            elif rtype == 'headcount_grade':
                ctx['search_default_group_grade'] = 1
                ctx['group_by'] = ['grade_id']
            elif rtype == 'headcount_position':
                ctx['search_default_group_job'] = 1
                ctx['group_by'] = ['job_id']
            elif rtype == 'gender':
                ctx['search_default_group_gender'] = 1
                ctx['group_by'] = ['gender']
            elif rtype == 'age_profile':
                ctx['group_by'] = ['age_group']
            elif rtype == 'length_of_service':
                ctx['group_by'] = ['tenure_group']
            elif rtype == 'work_permit_expiry':
                domain.append(('work_permit_status', 'in', ['expiring_soon', 'expired', 'valid']))
                ctx['group_by'] = ['work_permit_status']
            elif rtype == 'status':
                ctx['group_by'] = ['validation_state']

            return {
                'name': _("HR Report: %s") % dict(self._fields['report_type'].selection).get(rtype, rtype),
                'type': 'ir.actions.act_window',
                'res_model': res_model,
                'view_mode': view_mode,
                'domain': domain,
                'context': ctx,
                'target': 'current',
            }

        elif rtype in ('movement', 'promotion', 'transfer'):
            res_model = 'hr.employee.change.history'
            history_domain = []
            if self.date_from:
                history_domain.append(('applied_date', '>=', self.date_from))
            if self.date_to:
                history_domain.append(('applied_date', '<=', self.date_to))
            if self.department_id:
                history_domain.append(('employee_id.department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                history_domain.append(('employee_id.operating_unit_id', '=', self.operating_unit_id.id))

            if rtype == 'promotion':
                history_domain.append(('change_type', '=', 'job_org'))
            elif rtype == 'transfer':
                history_domain.append(('change_type', '=', 'job_org'))

            return {
                'name': _("HR Report: %s") % dict(self._fields['report_type'].selection).get(rtype, rtype),
                'type': 'ir.actions.act_window',
                'res_model': res_model,
                'view_mode': 'list,pivot',
                'domain': history_domain,
                'context': {'group_by': ['change_type', 'employee_id']},
                'target': 'current',
            }

        elif rtype == 'document':
            res_model = 'hr.employee.document'
            doc_domain = []
            if self.department_id:
                doc_domain.append(('employee_id.department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                doc_domain.append(('employee_id.operating_unit_id', '=', self.operating_unit_id.id))

            return {
                'name': _("Employee Document Report"),
                'type': 'ir.actions.act_window',
                'res_model': res_model,
                'view_mode': 'list,pivot',
                'domain': doc_domain,
                'context': {'group_by': ['document_type_id', 'employee_id']},
                'target': 'current',
            }

        else:
            return {
                'name': _("Employee Master Profile"),
                'type': 'ir.actions.act_window',
                'res_model': 'hr.employee',
                'view_mode': 'list,form',
                'domain': domain,
                'target': 'current',
            }
