# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import logging
from datetime import date
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HrPayrollPeriod(models.Model):
    """
    Payroll Period Definition & Cut-Off Governance Model.
    
    Enforces the organization's monthly payroll calculation boundaries and cut-off date.
    All employee lifecycle changes, attendance hours, and disciplinary penalties are evaluated
    against the active period's start, end, and cut-off dates (FR-PAY-001, FR-PAY-030).
    """
    _name = 'hr.payroll.period'
    _description = 'Payroll Accounting Period & Cut-Off Governance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(
        string='Period Name',
        required=True,
        tracking=True,
        help="Display label for the pay period, e.g. 'September 2026 Payroll Cycle'."
    )
    code = fields.Char(
        string='Period Code',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('hr.payroll.period') or _('New'),
        help="Unique reference code for the pay period."
    )
    date_start = fields.Date(
        string='Period Start Date',
        required=True,
        tracking=True,
        help="Start date of the active payroll computation cycle."
    )
    date_end = fields.Date(
        string='Period End Date',
        required=True,
        tracking=True,
        help="End date of the active payroll computation cycle."
    )
    cutoff_date = fields.Date(
        string='Cut-Off Date',
        required=True,
        tracking=True,
        help="Hard boundary date after which no HR actions may affect this payroll without formal override (FR-PAY-030)."
    )
    cutoff_locked = fields.Boolean(
        string='Cut-Off Locked',
        default=False,
        tracking=True,
        help="When checked, the system rejects any standard HR modification attempts without an approved override workflow."
    )
    state = fields.Selection([
        ('draft', 'Draft Planning'),
        ('open', 'Open for Data Ingestion'),
        ('cutoff_locked', 'Cut-Off Locked'),
        ('closed', 'Closed & Finalized'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )
    payslip_count = fields.Integer(
        string='Total Payslips',
        compute='_compute_payslip_count'
    )
    notes = fields.Text(string='Internal Notes')

    @api.constrains('date_start', 'date_end', 'cutoff_date')
    def _check_dates(self):
        """Validate logical sequence of pay period dates."""
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError(_("Period Start Date (%s) cannot be after Period End Date (%s).") % (rec.date_start, rec.date_end))
            if rec.cutoff_date and rec.date_start and rec.date_end:
                if rec.cutoff_date < rec.date_start or rec.cutoff_date > rec.date_end:
                    raise ValidationError(_("Cut-Off Date (%s) must fall within the Period Start (%s) and End (%s) range.") % (
                        rec.cutoff_date, rec.date_start, rec.date_end
                    ))

    def _compute_payslip_count(self):
        """Compute the total count of payslips generated within this period."""
        Payslip = self.env['hr.payslip']
        for rec in self:
            rec.payslip_count = Payslip.search_count([
                ('date_from', '>=', rec.date_start),
                ('date_to', '<=', rec.date_end),
                ('company_id', '=', rec.company_id.id)
            ])

    def action_open(self):
        """Transition period from Draft to Open for active data ingestion."""
        for rec in self:
            rec.write({'state': 'open'})
            rec.message_post(body=_("Payroll period opened for active HR data ingestion."))

    def action_lock_cutoff(self):
        """Enforce cut-off lock on the period (FR-PAY-030)."""
        for rec in self:
            rec.write({
                'cutoff_locked': True,
                'state': 'cutoff_locked'
            })
            rec.message_post(body=_("Payroll cut-off has been enforced. All subsequent HR changes require formal audited override approval."))

    def action_unlock_cutoff(self):
        """Managerial authorization to release cut-off lock."""
        self.check_access('write')
        for rec in self:
            if not self.env.user.has_group('payroll.group_payroll_manager'):
                raise UserError(_("Only People Service & Reward Division Managers can unlock an enforced cut-off."))
            rec.write({
                'cutoff_locked': False,
                'state': 'open'
            })
            rec.message_post(body=_("Payroll cut-off lock released by Division Manager: %s.") % self.env.user.name)

    def action_close(self):
        """Finalize and permanently close the payroll period."""
        for rec in self:
            rec.write({'state': 'closed', 'cutoff_locked': True})
            rec.message_post(body=_("Payroll period finalized and permanently closed."))

    @api.model
    def _cron_enforce_cutoff_locks(self):
        """
        Automated daily background job: identifies open payroll periods where current date
        exceeds cutoff_date and transitions them to cutoff_locked state.
        """
        today = fields.Date.context_today(self)
        periods_to_lock = self.search([
            ('state', '=', 'open'),
            ('cutoff_date', '<=', today),
            ('cutoff_locked', '=', False)
        ])
        for period in periods_to_lock:
            _logger.info("Automatically enforcing cut-off lock for period: %s", period.name)
            period.action_lock_cutoff()

    def name_get(self):
        """Custom display name with status indicator."""
        result = []
        for rec in self:
            label = f"{rec.name} ({rec.date_start} ~ {rec.date_end})"
            result.append((rec.id, label))
        return result
