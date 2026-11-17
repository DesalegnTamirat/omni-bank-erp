# -*- coding: utf-8 -*-
from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
from datetime import date
import logging

_logger = logging.getLogger(__name__)


class EmployeeDemotion(models.Model):
    _name = "employee.demotion"
    _description = "Employee Demotion"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = "ref_num"
    _order = "id desc"

    ref_num = fields.Char(string='Reference Number', default=lambda self: _('New'), copy=False, required=True, tracking=True)
    employee_name = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    current_work_unit = fields.Char(string="Current Work Unit", compute='_compute_current_assignment_info', store=True, readonly=True)
    current_work_unit_id = fields.Many2one('operating.unit', string="Current Work Unit (ID)", compute='_compute_current_assignment_info', store=True, readonly=True)
    job_name = fields.Many2one('employee.job', string='Job Name')
    job_grade = fields.Char(string="Current Grade", compute='_compute_current_assignment_info', store=True, readonly=True)
    current_job_grade_id = fields.Many2one('employee.grade', string="Current Grade (ID)", compute='_compute_current_assignment_info', store=True, readonly=True)
    job_position = fields.Char(string="Current Job Position", compute='_compute_current_assignment_info', store=True, readonly=True)
    current_job_position_id = fields.Many2one('hr.job', string="Current Position (ID)", compute='_compute_current_assignment_info', store=True, readonly=True)
    current_wage = fields.Float(string="Current Basic Salary", readonly=True)

    demotion_type = fields.Selection([
        ('all', 'Grade, Position & Location'),
        ('grade_position', 'Grade & Position'),
        ('grade_only', 'Grade Only'),
        ('position_only', 'Position Only'),
        ('location_only', 'Location Only (Branch Demotion)'),
        ('other', 'Other'),
    ], string="Demotion Scope", default='all', required=True, tracking=True)
    other_demotion_scope = fields.Char(string="Other Demotion Scope", tracking=True)

    new_job_title = fields.Many2one('hr.job', string='New Position', tracking=True)
    new_job_grade = fields.Many2one(
        'employee.grade', string='New Grade',
        compute='_compute_new_job_grade', store=True, readonly=False, precompute=True, tracking=True
    )
    new_work_unit = fields.Many2one('operating.unit', string='New Work Unit / Location', tracking=True)
    new_wage = fields.Float(string='New Basic Salary', tracking=True)

    change_date = fields.Date(string='Demotion Effective Date', default=fields.Date.context_today, required=True, tracking=True)
    job_history_start_date = fields.Date(string='Job History Start Date')
    job_history_end_date = fields.Date(string='Job History End Date')
    debarment_months = fields.Integer(
        string='Ineligibility / Debarment Period (Months)', default=12,
        help="Number of months the employee remains debarred from internal promotion or voluntary transfer."
    )
    demoted_until = fields.Date(string='Debarred Until Date', compute='_compute_demoted_until', store=True, tracking=True)

    reason = fields.Selection([
        ('performance', 'Performance'),
        ('health', 'Health'),
        ('discipline', 'Discipline'),
    ], string='Reason for Demotion', required=True, tracking=True)
    status = fields.Char(string='Status')
    disciplinary_case_ref = fields.Char(string='Disciplinary Case / Resolution Ref', tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('approve', 'Approved'),
        ('cancel', 'Cancelled'),
    ], string="State", default='draft', tracking=True)

    salary_det_demotion = fields.One2many("salary.detail.demotion", 'emp_demotion_id', string="Demotion Employee Salary Details")

    @api.model
    def _get_fiscal_year_demotion_prefix(self):
        """Computes current fiscal-year prefix BB/DEM/YY-YY/ (e.g. BB/DEM/26-27/)."""
        FISCAL_START_MONTH = 7
        FISCAL_START_DAY = 1
        today = fields.Date.context_today(self)
        start_year = today.year if (today.month, today.day) >= (FISCAL_START_MONTH, FISCAL_START_DAY) else today.year - 1
        end_year = start_year + 1
        return f"BB/DEM/{str(start_year)[-2:]}-{str(end_year)[-2:]}/"

    @api.model
    def _get_next_demotion_reference(self):
        """Auto-generates unique Demotion reference number (e.g. BB/DEM/26-27/00001)."""
        prefix = self._get_fiscal_year_demotion_prefix()
        self.env.cr.execute("""
            SELECT ref_num FROM employee_demotion
            WHERE ref_num IS NOT NULL 
              AND ref_num != 'New'
              AND ref_num LIKE %s
            ORDER BY id DESC LIMIT 1
        """, (prefix + '%',))
        res = self.env.cr.fetchone()
        if res and res[0]:
            try:
                seq_num = int(res[0].replace(prefix, '')) + 1
            except ValueError:
                seq_num = 1
        else:
            seq_num = 1
        return f"{prefix}{seq_num:05d}"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('ref_num') or vals.get('ref_num') in (_('New'), 'New') or str(vals.get('ref_num', '')).startswith('DEM-'):
                vals['ref_num'] = self._get_next_demotion_reference()
        return super().create(vals_list)

    def read(self, fields=None, load="_classic_read"):
        res = super().read(fields=fields, load=load)
        for r in res:
            if "ref_num" in r and (not r["ref_num"] or r["ref_num"] in ("New", _("New")) or str(r["ref_num"]).startswith("DEM-")):
                new_ref = self._get_next_demotion_reference()
                self.browse(r["id"]).sudo().write({"ref_num": new_ref})
                r["ref_num"] = new_ref
        return res

    @api.depends('new_job_title')
    def _compute_new_job_grade(self):
        for rec in self:
            if rec.new_job_title and getattr(rec.new_job_title, 'grade', False):
                rec.new_job_grade = rec.new_job_title.grade
            elif not rec.new_job_grade:
                rec.new_job_grade = False

    @api.onchange('new_job_title')
    def _onchange_new_job_title(self):
        if self.new_job_title and getattr(self.new_job_title, 'grade', False):
            self.new_job_grade = self.new_job_title.grade

    @api.depends('change_date', 'debarment_months')
    def _compute_demoted_until(self):
        for rec in self:
            if rec.change_date and rec.debarment_months:
                rec.demoted_until = rec.change_date + relativedelta(months=rec.debarment_months)
            elif rec.change_date:
                rec.demoted_until = rec.change_date
            else:
                rec.demoted_until = False

    @api.depends('employee_name')
    def _compute_current_assignment_info(self):
        for rec in self:
            if rec.employee_name:
                emp = rec.employee_name
                # 1. Position resolution
                pos = emp.job_position or emp.job_id or (getattr(emp, 'contract_id', False) and emp.contract_id.job_id)
                pos_name = pos.name if pos else ''
                pos_id = pos.id if pos else False
                rec.job_position = pos_name
                rec.current_job_position_id = pos_id

                # 2. Grade resolution
                grade = emp.job_grade or (pos and getattr(pos, 'grade', False)) or (getattr(emp, 'contract_id', False) and getattr(emp.contract_id, 'job_grade', False))
                grade_name = grade.grade_name if (grade and hasattr(grade, 'grade_name') and grade.grade_name) else (grade.display_name if grade else '')
                grade_id = grade.id if grade else False
                rec.job_grade = grade_name
                rec.current_job_grade_id = grade_id

                # 3. Work Unit / Location resolution
                ou = (
                    emp.default_operating_unit_id or
                    emp.operating_unit_id or
                    (getattr(emp, 'contract_id', False) and getattr(emp.contract_id, 'operating_unit_id', False)) or
                    (getattr(emp, 'department_id', False) and getattr(emp.department_id, 'operating_unit_id', False))
                )
                rec.current_work_unit = ou.name if ou else (emp.department_id.name if emp.department_id else '')
                rec.current_work_unit_id = ou.id if ou else False
            else:
                rec.job_position = False
                rec.current_job_position_id = False
                rec.job_grade = False
                rec.current_job_grade_id = False
                rec.current_work_unit = False
                rec.current_work_unit_id = False

    @api.onchange('employee_name')
    def _onchange_employee_name_info(self):
        self._compute_current_assignment_info()

    def approve(self):
        """Applies the demotion to the employee profile and logs histories without altering salary."""
        today = fields.Date.today()
        for rec in self:
            if not rec.employee_name:
                raise UserError(_("Please select an employee to demote."))

            if not rec.new_job_title and not rec.new_job_grade and not rec.new_work_unit:
                raise UserError(_("Please specify at least one new assignment: New Position, New Grade, or New Work Unit."))

            eff_date = rec.change_date or today
            debar_until = rec.demoted_until or (eff_date + relativedelta(months=rec.debarment_months or 12))

            emp = rec.employee_name
            emp_vals = {
                'is_demoted': True,
                'demotion_date': eff_date,
                'demoted_until': debar_until,
            }

            # 1. New Position
            if rec.new_job_title:
                emp_vals['job_position'] = rec.new_job_title.id
                emp_vals['job_id'] = rec.new_job_title.id

            # 2. New Grade
            if rec.new_job_grade:
                emp_vals['job_grade'] = rec.new_job_grade.id

            # 3. New Work Unit / Location
            loc_changed = False
            old_ou = emp.default_operating_unit_id
            if rec.new_work_unit and rec.new_work_unit != old_ou:
                loc_changed = True
                emp_vals['default_operating_unit_id'] = rec.new_work_unit.id
                if 'operating_unit_id' in emp._fields:
                    emp_vals['operating_unit_id'] = rec.new_work_unit.id
                if getattr(rec.new_work_unit, 'manager_id', False):
                    emp_vals['parent_id'] = rec.new_work_unit.manager_id.id

            # Apply to employee with context job_history_reason='demotion' (salary remains unchanged)
            ctx = dict(self.env.context, job_history_reason='demotion')
            emp.with_context(ctx).write(emp_vals)

            # 4. Synchronize grade on active contract / hr.version if grade changed (wage is untouched)
            if rec.new_job_grade and 'hr.version' in self.env:
                contracts = self.env['hr.version'].search([
                    ('employee_id', '=', emp.id),
                    ('state', 'in', ['open', 'draft'])
                ], order='id desc')
                for c in contracts:
                    c.write({'job_grade': rec.new_job_grade.id})

            # 5. Only log to transfer history if same position and same grade in a different location.
            # Demotions (grade changes) are tracked in Job History.
            is_same_pos_and_grade = (
                rec.current_job_position_id == rec.new_job_title
                and rec.current_job_grade_id == rec.new_job_grade
            )
            if loc_changed and is_same_pos_and_grade and 'hr.employee.transfer.history' in self.env:
                self.env['hr.employee.transfer.history'].create({
                    'employee_id': emp.id,
                    'date': eff_date,
                    'start_date': eff_date,
                    'from_operating_unit_id': old_ou.id if old_ou else False,
                    'to_operating_unit_id': rec.new_work_unit.id,
                    'from_job_id': rec.current_job_position_id.id if rec.current_job_position_id else False,
                    'to_job_id': rec.new_job_title.id if rec.new_job_title else False,
                    'from_grade_id': rec.current_job_grade_id.id if rec.current_job_grade_id else False,
                    'to_grade_id': rec.new_job_grade.id if rec.new_job_grade else False,
                    'transfer_reason': 'Transfer',
                    'reason_for_movement': 'transfer',
                    'is_current': True,
                })

            rec.state = 'approve'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancel'

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'approve':
                raise UserError(_("Approved demotions cannot be reset to draft directly."))
            rec.state = 'draft'


class EmployeeDemotionSalary(models.Model):
    _name = "salary.detail.demotion"
    _description = "Employee Demotion Salary Detail"

    name = fields.Char(string="Salary Component", default="Basic Salary")
    value = fields.Float(string="Current Value")
    end_date = fields.Date(string="End Date")
    revised_value = fields.Float(string="Revised Value")
    start_date = fields.Date(string="Start Date")
    total_value = fields.Float(string="Payroll Value")
    payroll_period_id = fields.Integer(string="Payroll Period Id")
    employee_id = fields.Integer(string="Employee Id")
    emp_demotion_id = fields.Many2one('employee.demotion', string="Demotion Reference", ondelete='cascade')


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    is_demoted = fields.Boolean(string="Is Demoted", default=False, tracking=True)
    demotion_date = fields.Date(string="Demotion Effective Date", tracking=True)
    demoted_until = fields.Date(string="Ineligible for Promotion/Transfer Until", tracking=True)
    demotion_ids = fields.One2many('employee.demotion', 'employee_name', string="Demotions")
    demotion_count = fields.Integer(string="Demotion Count", compute="_compute_demotion_count")

    def _compute_demotion_count(self):
        for emp in self:
            emp.demotion_count = len(emp.demotion_ids)
