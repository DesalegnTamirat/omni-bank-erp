# -*- coding: utf-8 -*-

from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class HrPayrollPeriod(models.Model):
    """Payroll Period configuration model for Bunna Bank Payroll.
    Defines monthly/custom payroll periods with start date, end date, payment date, and status.
    """
    _name = 'hr.payroll.period'
    _description = 'Payroll Period'
    _order = 'date_from desc, id desc'

    name = fields.Char(
        string='Name',
        required=True,
        index=True,
        help='Period name (e.g. "April 2026", "2026/04", "Period 10 - Meskerem")'
    )
    code = fields.Char(string='Code', index=True, help='Short reference code (e.g. 2026-04)')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', index=True, required=True, copy=False)

    fiscal_year = fields.Char(
        string='Fiscal Year',
        required=True,
        default=lambda self: str(fields.Date.today().year),
        help='Fiscal year reference (e.g. 2025/2026, 2018 E.C.)'
    )
    date_from = fields.Date(
        string='Start Date',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
        help='Start date of this payroll period'
    )
    date_to = fields.Date(
        string='End Date',
        required=True,
        default=lambda self: (fields.Date.today() + relativedelta(months=1, day=1, days=-1)),
        help='End date of this payroll period'
    )
    payment_date = fields.Date(
        string='Date of Payment',
        required=True,
        default=lambda self: (fields.Date.today() + relativedelta(months=1, day=1, days=-1)),
        help='Date when salary payment is processed or disbursed'
    )
    schedule_pay = fields.Selection([
        ('monthly', 'Monthly (12)'),
        ('quarterly', 'Quarterly (4)'),
        ('semi-annually', 'Semi-annually (2)'),
        ('annually', 'Annually (1)'),
        ('weekly', 'Weekly (52)'),
        ('bi-weekly', 'Bi-weekly (26)'),
    ], string='Scheduled Pay', default='monthly', required=True)
    period_type = fields.Selection([
        ('hr_period', 'HR Period'),
        ('bonus_period', 'Bonus Period'),
        ('other', 'Other'),
    ], string='Type', default='hr_period', required=True)
    number = fields.Integer(
        string='Number',
        default=1,
        help='Sequence number of this period within the fiscal year (e.g. 1 to 12)'
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    note = fields.Text(string='Description / Notes')

    payslip_ids = fields.One2many(
        'hr.payslip',
        'period_id',
        string='Payslips',
        readonly=True
    )
    payslip_count = fields.Integer(
        string='Payslips Count',
        compute='_compute_payslip_count'
    )
    run_ids = fields.One2many(
        'hr.payslip.run',
        'period_id',
        string='Payslip Batches',
        readonly=True
    )
    run_count = fields.Integer(
        string='Batches Count',
        compute='_compute_run_count'
    )

    @api.depends('payslip_ids')
    def _compute_payslip_count(self):
        for rec in self:
            rec.payslip_count = len(rec.payslip_ids)

    @api.depends('run_ids')
    def _compute_run_count(self):
        for rec in self:
            rec.run_count = len(rec.run_ids)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_("Start Date cannot be later than End Date."))

    @api.constrains('state', 'company_id')
    def _check_single_open_period(self):
        for rec in self:
            if rec.state == 'open':
                # Check within the current recordset batch
                other_in_batch = self.filtered(
                    lambda r: r.id != rec.id and r.state == 'open' and (
                        not rec.company_id or not r.company_id or r.company_id == rec.company_id
                    )
                )
                if other_in_batch:
                    company_name = rec.company_id.name if rec.company_id else "the company"
                    raise ValidationError(_(
                        "Only one payroll period is allowed to be open at a time for %(company)s.\n"
                        "Cannot open multiple periods simultaneously: %(periods)s."
                    ) % {
                        'company': company_name,
                        'periods': ", ".join(self.filtered(lambda r: r.state == 'open').mapped('name')),
                    })
                # Check in database
                domain = [
                    ('id', '!=', rec.id),
                    ('state', '=', 'open'),
                ]
                if rec.company_id:
                    domain.append(('company_id', '=', rec.company_id.id))
                open_periods = self.search(domain)
                if open_periods:
                    other_names = ", ".join(open_periods.mapped('name'))
                    company_name = rec.company_id.name if rec.company_id else "the company"
                    raise ValidationError(_(
                        "Only one payroll period is allowed to be open at a time for %(company)s.\n"
                        "Period '%(periods)s' is currently open. Please close it before opening another period."
                    ) % {
                        'company': company_name,
                        'periods': other_names,
                    })

    def action_open_period(self):
        for rec in self:
            domain = [
                ('id', '!=', rec.id),
                ('state', '=', 'open'),
            ]
            if rec.company_id:
                domain.append(('company_id', '=', rec.company_id.id))
            open_periods = self.search(domain)
            if open_periods:
                other_names = ", ".join(open_periods.mapped('name'))
                company_name = rec.company_id.name if rec.company_id else "the company"
                raise UserError(_(
                    "Only one payroll period is allowed to be open at a time for %(company)s.\n"
                    "Period '%(periods)s' is currently open. Please close it before opening another period."
                ) % {
                    'company': company_name,
                    'periods': other_names,
                })
            rec.write({'state': 'open'})

    def action_close_period(self):
        for rec in self:
            rec.write({'state': 'closed'})

    def action_set_draft(self):
        for rec in self:
            rec.write({'state': 'draft'})

    def action_view_payslips(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('bunna_hr_payroll.action_view_hr_payslip_form')
        action['domain'] = [('period_id', '=', self.id)]
        action['context'] = {'default_period_id': self.id}
        return action

    def action_view_batches(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('bunna_hr_payroll.action_hr_payslip_run_tree')
        action['domain'] = [('period_id', '=', self.id)]
        action['context'] = {'default_period_id': self.id, 'search_default_period_id': self.id}
        return action
