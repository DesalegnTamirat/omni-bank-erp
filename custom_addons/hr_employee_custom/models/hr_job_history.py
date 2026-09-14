# -*- coding: utf-8 -*-
from odoo import api, models, fields


class HrJobHistory(models.Model):
    _name = 'hr.job.history'
    _description = 'Employee Job History'
    _order = 'job_history_start_date desc, id desc'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee Name', required=True,
        ondelete='cascade', index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    old_wage = fields.Monetary(string='Old Wage', currency_field='currency_id')
    new_wage = fields.Monetary(string='New Wage', currency_field='currency_id')

    from_operating_unit_id = fields.Many2one('operating.unit', string='From Operating Unit')
    to_operating_unit_id = fields.Many2one('operating.unit', string='To Operating Unit')
    operating_unit_id = fields.Many2one(
        'operating.unit', string='Operating Unit',
        related='to_operating_unit_id', store=True, readonly=False,
    )

    from_department_id = fields.Many2one('hr.department', string='From Department')
    to_department_id = fields.Many2one('hr.department', string='To Department')
    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='to_department_id', store=True, readonly=False,
    )

    from_grade_id = fields.Many2one('employee.grade', string='From Grade')
    to_grade_id = fields.Many2one('employee.grade', string='To Grade')
    grade_id = fields.Many2one(
        'employee.grade', string='Grade',
        related='to_grade_id', store=True, readonly=False,
    )

    from_job_id = fields.Many2one('hr.job', string='From Position')
    to_job_id = fields.Many2one('hr.job', string='To Position')
    job_id = fields.Many2one(
        'hr.job', string='Job Name',
        related='to_job_id', store=True, readonly=False,
    )

    position = fields.Char(string='Position')
    job_history_start_date = fields.Date(string='Job History Start Date')
    job_history_end_date = fields.Date(string='Job History End Date')
    reason_for_change = fields.Selection([
        ('promotion', 'Promotion'),
        ('transfer', 'Transfer'),
        ('demotion', 'Demotion'),
        ('acting_role', 'Acting Role'),
        ('recruitment', 'Recruitment / New Hire'),
        ('resignation', 'Resignation'),
        ('termination', 'Termination'),
        ('other', 'Other'),
    ], string='Reason for Change', default='other')
    is_current = fields.Boolean(
        string='Current Position', compute='_compute_is_current', store=True,
        help="True when this row has no end date, i.e. it is the employee's active position.",
    )

    @api.depends('job_history_end_date')
    def _compute_is_current(self):
        for rec in self:
            rec.is_current = not rec.job_history_end_date


class HrEmployeeJobHistory(models.Model):
    """Automatically maintains hr.job.history whenever an employee's
    position, grade, department, or operating unit changes — regardless
    of which flow triggers the change (promotion, demotion, transfer,
    acting role, recruitment, or a direct edit on the employee form).
    """
    _inherit = 'hr.employee'

    job_history_ids = fields.One2many(
        'hr.job.history', 'employee_id',
        string='Job History',
        help="Chronological list of job positions — used by the Experience Letter report.",
    )

    _JOB_HISTORY_TRACKED_FIELDS = (
        'job_position',
        'job_id',
        'job_grade',
        'default_operating_unit_id',
        'department_id',
    )

    def _get_job_id(self, emp, vals=None):
        """Extracts job position ID from employee record or incoming write vals."""
        if vals:
            if 'job_id' in vals and vals['job_id']:
                return vals['job_id']
            if 'job_position' in vals and vals['job_position']:
                return vals['job_position']
        if hasattr(emp, 'job_id') and emp.job_id:
            return emp.job_id.id
        if hasattr(emp, 'job_position') and emp.job_position:
            return emp.job_position.id
        return False

    def _get_employee_current_wage(self, emp):
        """Finds the current wage of the employee from contract (hr.version) or grade structure."""
        contracts = self.env['hr.version'].search([
            ('employee_id', '=', emp.id),
            ('state', 'in', ['open', 'probation', 'draft'])
        ], order='id desc', limit=1)

        if not contracts and hasattr(emp, 'contract_id') and emp.contract_id:
            contracts = emp.contract_id

        if contracts:
            if getattr(contracts, 'wage', 0.0):
                return contracts.wage
            if getattr(contracts, 'base_salary', 0.0):
                return contracts.base_salary

        if emp.job_grade:
            return self._calculate_grade_step_salary(emp.job_grade, 0.0)

        return 0.0

    def write(self, vals):
        if self.env.context.get('in_job_history_logging'):
            return super().write(vals)
        tracked_fields = [f for f in self._JOB_HISTORY_TRACKED_FIELDS if f in vals]

        before = {}
        if tracked_fields:
            for emp in self:
                old_wage = self._get_employee_current_wage(emp)
                old_job_id = emp.job_id.id if emp.job_id else (emp.job_position.id if emp.job_position else False)
                before[emp.id] = {
                    'job_position': old_job_id,
                    'job_grade': emp.job_grade.id if emp.job_grade else False,
                    'default_operating_unit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                    'department_id': emp.department_id.id if emp.department_id else False,
                    'wage': old_wage,
                }

        res = super().write(vals)

        if tracked_fields:
            self.with_context(in_job_history_logging=True)._log_job_history_changes(before)

        return res

    def _calculate_grade_step_salary(self, new_grade, old_wage):
        """Determines the appropriate salary step for a new grade based on the
        salary structure (base_salary and increment steps amount_1..10).

        Mandatory Rule: The new salary MUST exceed the old salary by at least 1,000.
        If current salary >= base salary of new grade, it finds the next step in new_grade
        where step_salary >= old_wage + 1000.
        """
        if not new_grade:
            return old_wage or 0.0

        steps = []
        if getattr(new_grade, 'base_salary', False) and new_grade.base_salary > 0:
            steps.append(new_grade.base_salary)

        inc = getattr(new_grade, 'increment_id', False)
        if inc:
            inc_rec = inc[0] if len(inc) > 0 else inc
            for i in range(1, 11):
                amt = getattr(inc_rec, f'amount_{i}', 0.0)
                if amt and amt > 0:
                    steps.append(amt)

        if not steps:
            return old_wage or 0.0

        steps = sorted(list(set(steps)))

        if not old_wage or old_wage <= 0:
            return steps[0]

        # Mandatory minimum salary increase threshold (+1,000)
        target_min_wage = old_wage + 1000.0

        for step_val in steps:
            if step_val >= target_min_wage:
                return step_val

        # If old_wage + 1000 exceeds all steps in the new grade, use max step available
        return steps[-1]

    def _log_job_history_changes(self, before):
        JobHistory = self.env['hr.job.history']
        today = fields.Date.context_today(self)
        reason = self.env.context.get('job_history_reason', 'other')

        for emp in self:
            old = before.get(emp.id)
            if old is None:
                continue

            new_job_id = emp.job_id.id if emp.job_id else (emp.job_position.id if emp.job_position else False)
            new_grade_id = emp.job_grade.id if emp.job_grade else False
            new_ou_id = emp.default_operating_unit_id.id if emp.default_operating_unit_id else False
            new_dept_id = emp.department_id.id if emp.department_id else False

            new = {
                'job_position': new_job_id,
                'job_grade': new_grade_id,
                'default_operating_unit_id': new_ou_id,
                'department_id': new_dept_id,
            }

            if (old['job_position'] == new['job_position'] and
                old['job_grade'] == new['job_grade'] and
                old['default_operating_unit_id'] == new['default_operating_unit_id'] and
                old['department_id'] == new['department_id']):
                continue

            job_obj = self.env['hr.job'].browse(new_job_id) if new_job_id else False
            position_name = job_obj.name if job_obj else False

            # Synchronize job_position, job_id, and job_name on hr.employee
            emp_vals = {}
            if new_job_id:
                if 'job_position' in emp._fields and (not emp.job_position or emp.job_position.id != new_job_id):
                    emp_vals['job_position'] = new_job_id
                if 'job_id' in emp._fields and (not emp.job_id or emp.job_id.id != new_job_id):
                    emp_vals['job_id'] = new_job_id
                if 'job_name' in emp._fields and position_name and emp.job_name != position_name:
                    emp_vals['job_name'] = position_name
            if emp_vals:
                emp.with_context(in_job_history_logging=True).write(emp_vals)

            old_wage = old.get('wage', 0.0)
            new_grade = emp.job_grade
            grade_changed = (old['job_grade'] != new_grade_id)

            if grade_changed and new_grade:
                new_wage = self._calculate_grade_step_salary(new_grade, old_wage)
            else:
                new_wage = old_wage

            contracts = self.env['hr.version'].search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['open', 'probation', 'draft'])
            ])
            if not contracts and hasattr(emp, 'contract_id') and emp.contract_id:
                contracts = emp.contract_id

            if contracts:
                contract_vals = {}
                version_fields = self.env['hr.version']._fields
                if new_wage and 'wage' in version_fields:
                    contract_vals['wage'] = new_wage
                if new_grade_id and 'job_grade' in version_fields:
                    contract_vals['job_grade'] = new_grade_id
                if new_job_id and 'job_id' in version_fields:
                    contract_vals['job_id'] = new_job_id
                if new_job_id and 'job_position' in version_fields:
                    contract_vals['job_position'] = new_job_id
                if new_ou_id and 'operating_unit_id' in version_fields:
                    contract_vals['operating_unit_id'] = new_ou_id
                if new_dept_id and 'department_id' in version_fields:
                    contract_vals['department_id'] = new_dept_id

                if contract_vals:
                    contracts.write(contract_vals)

            # CONDITION: If Grade CHANGED -> log under hr.job.history
            # If Grade DID NOT CHANGE -> log under hr.employee.transfer.history
            if grade_changed:
                open_history = JobHistory.search([
                    ('employee_id', '=', emp.id),
                    ('job_history_end_date', '=', False),
                ], order='job_history_start_date desc', limit=1)

                if open_history:
                    open_history.job_history_end_date = today

                JobHistory.create({
                    'employee_id': emp.id,
                    'from_job_id': old['job_position'],
                    'to_job_id': new_job_id,
                    'from_grade_id': old['job_grade'],
                    'to_grade_id': new_grade_id,
                    'from_operating_unit_id': old['default_operating_unit_id'],
                    'to_operating_unit_id': new_ou_id,
                    'from_department_id': old['department_id'],
                    'to_department_id': new_dept_id,
                    'old_wage': old_wage,
                    'new_wage': new_wage,
                    'position': position_name,
                    'job_history_start_date': today,
                    'reason_for_change': reason if reason != 'other' else 'promotion',
                })
            else:
                # Grade did NOT change -> log under hr.employee.transfer.history
                open_transfer = self.env['hr.employee.transfer.history'].search([
                    ('employee_id', '=', emp.id),
                    ('end_date', '=', False),
                ], order='start_date desc, id desc', limit=1)

                if open_transfer:
                    open_transfer.end_date = today

                self.env['hr.employee.transfer.history'].create({
                    'employee_id': emp.id,
                    'date': today,
                    'start_date': today,
                    'transfer_reason': reason if reason != 'other' else 'Transfer',
                    'from_operating_unit_id': old['default_operating_unit_id'],
                    'from_department_id': old['department_id'],
                    'from_job_id': old['job_position'],
                    'from_grade_id': old['job_grade'],
                    'to_operating_unit_id': new_ou_id,
                    'to_department_id': new_dept_id,
                    'to_job_id': new_job_id,
                    'to_grade_id': new_grade_id,
                })

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        for emp in employees:
            job_id = self._get_job_id(emp)
            if job_id or emp.job_grade:
                initial_wage = self._get_employee_current_wage(emp)
                new_wage = self._calculate_grade_step_salary(emp.job_grade, initial_wage) if emp.job_grade else initial_wage

                contracts = self.env['hr.version'].search([
                    ('employee_id', '=', emp.id),
                    ('state', 'in', ['open', 'probation', 'draft'])
                ])
                if not contracts and hasattr(emp, 'contract_id') and emp.contract_id:
                    contracts = emp.contract_id

                if contracts and new_wage:
                    version_fields = self.env['hr.version']._fields
                    contract_vals = {}
                    if 'wage' in version_fields:
                        contract_vals['wage'] = new_wage
                    if emp.job_grade and 'job_grade' in version_fields:
                        contract_vals['job_grade'] = emp.job_grade.id
                    if job_id and 'job_id' in version_fields:
                        contract_vals['job_id'] = job_id
                    if emp.default_operating_unit_id and 'operating_unit_id' in version_fields:
                        contract_vals['operating_unit_id'] = emp.default_operating_unit_id.id
                    if emp.department_id and 'department_id' in version_fields:
                        contract_vals['department_id'] = emp.department_id.id
                    if contract_vals:
                        contracts.write(contract_vals)

                job_obj = self.env['hr.job'].browse(job_id) if job_id else False
                position_name = job_obj.name if job_obj else False

                self.env['hr.job.history'].create({
                    'employee_id': emp.id,
                    'to_job_id': job_id,
                    'to_grade_id': emp.job_grade.id if emp.job_grade else False,
                    'to_operating_unit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                    'to_department_id': emp.department_id.id if emp.department_id else False,
                    'old_wage': initial_wage,
                    'new_wage': new_wage,
                    'position': position_name,
                    'job_history_start_date': fields.Date.context_today(self),
                    'reason_for_change': 'recruitment',
                })
        return employees

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