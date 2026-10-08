# -*- coding: utf-8 -*-
import re
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrEmployeeGrade(models.Model):
    _name = 'hr.employee.grade'
    _description = 'Employee Grade'

    name = fields.Char(string='Grade Name', required=True)
    code = fields.Char(string='Grade Code', required=True)
    active = fields.Boolean(string='Active', default=True)  # ← add this

    @api.constrains('code')
    def _check_unique_code(self):
        for rec in self:
            existing = self.search([
                ('id', '!=', rec.id),
                ('code', '=ilike', rec.code)
            ], limit=1)
            if existing:
                raise ValidationError(
                    f"The Grade Code '{rec.code}' already exists."
                )

    @api.constrains('name')
    def _check_name_is_alphabetic(self):
        for record in self:
            if record.name and not re.search(r'[a-zA-Z]', record.name):
                raise ValidationError(
                    "Grade Name must contain letters. Pure numbers are not allowed."
                )

    @api.constrains('name', 'code')
    def _check_grade_values(self):
        for record in self:
            if len(record.code) < 2:
                raise ValidationError(
                    "Grade Code must be at least 2 characters long."
                )

    def action_save_grade(self):
        """Called by the Save button — saves and returns success toast."""
        # Trigger write so constraints fire
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Saved Successfully',
                'message': f"Employee Grade '{self.name}' has been saved.",
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    # ── HrEmployeeGrade ──────────────────────────────────────────
    def action_delete_grade(self):
        name = self.name
        self.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Deleted',
                'message': f"Employee Grade '{name}' has been deleted successfully.",
                'type': 'warning',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': 'Employee Grades',
                    'res_model': 'hr.employee.grade',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'current',
                },
            }
        }


class HrEmployeeLevel(models.Model):
    _name = 'hr.employee.level'
    _description = 'Employee Level'

    name = fields.Char(string='Level Name', required=True)
    code = fields.Char(string='Level Code', required=True)
    active = fields.Boolean(string='Active', default=True)  # ← add this

    _sql_constraints = [
        ('unique_level_code', 'unique(code)',
         'The Level Code must be unique!')
    ]

    @api.constrains('name', 'code')
    def _check_level_values(self):
        for record in self:
            if len(record.code) < 2:
                raise ValidationError(
                    "Level Code must be at least 2 characters long."
                )

    def action_save_level(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Saved Successfully',
                'message': f"Employee Level '{self.name}' has been saved.",
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    # ── HrEmployeeLevel ──────────────────────────────────────────
    def action_delete_level(self):
        name = self.name
        self.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Deleted',
                'message': f"Employee Level '{name}' has been deleted successfully.",
                'type': 'warning',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': 'Employee Levels',
                    'res_model': 'hr.employee.level',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'current',
                },
            }
        }




class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def _has_field_access(self, field, operation):
        if not field.groups or self.env.su:
            return True
        if operation == 'read':
            user = self.env.user
            if user and len(user) == 1 and (
                user._has_group('base.group_user')
                or user._has_group('hr_employee_custom.group_hr_employee_user')
            ):
                return True
        return super()._has_field_access(field, operation)



    grade_id = fields.Many2one('hr.employee.grade', string='Employee Grade', required=True)
    level_id = fields.Many2one('hr.employee.level', string='Employee Level', required=True)
    disability_details = fields.Char(string='Disability Details')

    former_spouse_name = fields.Char(string='Former Spouse Name')
    is_previously_married = fields.Boolean(
        string='Was Previously Married',
        compute='_compute_is_previously_married',
        store=True,
        readonly=False
    )

    @api.depends('marital', 'former_spouse_name')
    def _compute_is_previously_married(self):
        for rec in self:
            if rec.marital in ('divorced', 'widower') or rec.former_spouse_name:
                rec.is_previously_married = True
            elif not rec.is_previously_married:
                rec.is_previously_married = False

    work_permit_status = fields.Selection([
        ('none', 'Not Applicable'),
        ('valid', 'Valid'),
        ('expiring_soon', 'Expiring Soon'),
        ('expired', 'Expired'),
    ], string='Work Permit Status', compute='_compute_work_permit_status', store=True)

    @api.depends('work_permit_expiration_date')
    def _compute_work_permit_status(self):
        today = fields.Date.today()
        for rec in self:
            if not rec.work_permit_expiration_date:
                rec.work_permit_status = 'none'
            elif rec.work_permit_expiration_date < today:
                rec.work_permit_status = 'expired'
            elif (rec.work_permit_expiration_date - today).days <= 30:
                rec.work_permit_status = 'expiring_soon'
            else:
                rec.work_permit_status = 'valid'

    @api.constrains('grade_id', 'level_id')
    def _check_employee_assignments(self):
        for employee in self:
            if not employee.grade_id or not employee.level_id:
                raise ValidationError(
                    "Both Employee Grade and Level must be assigned."
                )

    def action_save_employee(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Saved Successfully',
                'message': f"Employee '{self.name}' has been saved successfully.",
                'type': 'success',
                'sticky': False,
            }
        }

    # ── HrEmployee ───────────────────────────────────────────────
    def action_delete_employee(self):
        name = self.name
        self.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Deleted',
                'message': f"Employee '{name}' has been deleted successfully.",
                'type': 'warning',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': 'Employees',
                    'res_model': 'hr.employee',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'current',
                },
            }
        }

    # ── Experience Letter Helper Methods ─────────────────────────
    def get_experience_letter_salutation(self):
        """Determine employee salutation based on gender."""
        self.ensure_one()
        gender = (self.gender or '').strip().lower()
        if gender == 'male':
            return 'Ato'
        elif gender == 'female':
            return 'W/y'
        return 'Ato/W/y'

    def get_experience_letter_pronouns(self):
        """Returns pronouns dictionary based on employee gender."""
        self.ensure_one()
        gender = (self.gender or '').strip().lower()
        if gender == 'male':
            return {
                'subj': 'He',
                'subj_lower': 'he',
                'obj': 'him',
                'poss': 'his',
                'poss_cap': 'His',
            }
        elif gender == 'female':
            return {
                'subj': 'She',
                'subj_lower': 'she',
                'obj': 'her',
                'poss': 'her',
                'poss_cap': 'Her',
            }
        return {
            'subj': 'He/She',
            'subj_lower': 'he/she',
            'obj': 'him/her',
            'poss': 'his/her',
            'poss_cap': 'His/Her',
        }

    def get_experience_letter_ref_no(self):
        """Returns official formatted reference number for experience letter."""
        self.ensure_one()
        seq = self.env['ir.sequence'].next_by_code('employee.experience.letter')
        if seq:
            return seq
        digits = ''.join(filter(str.isdigit, str(self.identification_id or self.barcode or self.id))) or str(self.id)
        year_suffix = fields.Date.context_today(self).strftime('%y')
        return f"BB/POMD-PSR/{digits}/0{year_suffix}"

    def get_sorted_job_history(self):
        """Returns employee's job history records sorted in ascending chronological order."""
        self.ensure_one()
        if hasattr(self, 'job_history_ids') and self.job_history_ids:
            return self.job_history_ids.sorted(
                key=lambda h: (h.job_history_start_date or fields.Date.min, h.id or 0)
            )
        return []

    def get_experience_letter_start_date(self):
        """Returns the earliest start date formatted as YYYY-MM-DD."""
        self.ensure_one()
        if hasattr(self, 'first_contract_date') and self.first_contract_date:
            return self.first_contract_date.strftime('%Y-%m-%d')
        histories = self.get_sorted_job_history()
        if histories and histories[0].job_history_start_date:
            return histories[0].job_history_start_date.strftime('%Y-%m-%d')
        if hasattr(self, 'contract_id') and self.contract_id and self.contract_id.date_start:
            return self.contract_id.date_start.strftime('%Y-%m-%d')
        if self.create_date:
            return self.create_date.strftime('%Y-%m-%d')
        return fields.Date.context_today(self).strftime('%Y-%m-%d')

    def _amount_to_words_title_en(self, amt):
        """Convert a numerical amount to English words in Title Case."""
        ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
                'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
                'Seventeen', 'Eighteen', 'Nineteen']
        tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

        def helper(num):
            if num < 20:
                return ones[num]
            elif num < 100:
                rem = num % 10
                return tens[num // 10] + ('-' + ones[rem] if rem else '')
            elif num < 1000:
                rem = num % 100
                return ones[num // 100] + ' Hundred' + (' ' + helper(rem) if rem else '')
            elif num < 1000000:
                thousands = num // 1000
                rem = num % 1000
                return helper(thousands) + ' Thousand' + (' ' + helper(rem) if rem else '')
            elif num < 1000000000:
                millions = num // 1000000
                rem = num % 1000000
                return helper(millions) + ' Million' + (' ' + helper(rem) if rem else '')
            else:
                billions = num // 1000000000
                rem = num % 1000000000
                return helper(billions) + ' Billion' + (' ' + helper(rem) if rem else '')

        amt = round(float(amt), 2)
        int_part = int(amt)
        cents = int(round((amt - int_part) * 100))
        res = helper(int_part).strip() if int_part > 0 else 'Zero'
        if cents > 0:
            res += f' and {cents:02d}/100'
        return res

    def get_experience_letter_salary_info(self):
        """Fetches employee's monthly gross wage from contract, grade, or history,
        returning both formatted numeric string and Title Case words."""
        self.ensure_one()
        wage = 0.0

        # 1. From hr.version contract
        if 'hr.version' in self.env:
            contracts = self.env['hr.version'].search([
                ('employee_id', '=', self.id),
                ('state', 'in', ['open', 'probation', 'draft'])
            ], order='id desc', limit=1)
            if contracts:
                if getattr(contracts, 'wage', 0.0):
                    wage = contracts.wage
                elif getattr(contracts, 'base_salary', 0.0):
                    wage = contracts.base_salary

        # 2. From standard hr.contract
        if not wage and hasattr(self, 'contract_id') and self.contract_id and getattr(self.contract_id, 'wage', 0.0):
            wage = self.contract_id.wage

        # 3. From job grade structure
        if not wage:
            grade = getattr(self, 'job_grade', False) or getattr(self, 'grade_id', False)
            if grade:
                if hasattr(self, '_calculate_grade_step_salary'):
                    wage = self._calculate_grade_step_salary(grade, 0.0)
                elif getattr(grade, 'base_salary', False):
                    wage = grade.base_salary

        # 4. From latest job history row
        if not wage and hasattr(self, 'job_history_ids') and self.job_history_ids:
            latest = self.job_history_ids.sorted(
                key=lambda h: (h.job_history_start_date or fields.Date.min, h.id or 0),
                reverse=True
            )[:1]
            if latest and latest.new_wage:
                wage = latest.new_wage

        fig_str = f"{wage:,.2f}" if wage else "0.00"
        words_str = self._amount_to_words_title_en(wage) if wage else "Zero"
        return {
            'amount': wage,
            'figure': fig_str,
            'words': words_str,
        }

    def get_experience_letter_signatory_name(self):
        """Returns signatory name from system parameters or defaults to Melesse Leykun."""
        return self.env['ir.config_parameter'].sudo().get_param(
            'hr_experience_letter_signatory', 'Melesse Leykun'
        )