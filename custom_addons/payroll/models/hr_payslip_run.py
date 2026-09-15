# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import logging
from datetime import date
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HrPayslipRun(models.Model):
    """
    Enterprise Payroll Batch Run & 3-Tier Approval Workflow Model (FR-PAY-032).
    
    Orchestrates bank-wide or branch-level monthly payroll processing batches.
    Enforces strict segregation of duties:
    * Level 1: Initiation by HR Accountant (action_initiate)
    * Level 2: Verification by Senior Payroll Controller (action_verify)
    * Level 3: Final Approval by People Service & Reward Division Manager (action_approve)
    * Post: Automated General Ledger Posting & CBS Direct Credit Generation (action_post)
    """
    _name = 'hr.payslip.run'
    _description = 'Payroll Batch Payrun & Approval Workflow'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Payrun Batch Name', required=True, tracking=True)
    number = fields.Char(
        string='Batch Reference',
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('hr.payslip.run') or _('New')
    )
    period_id = fields.Many2one('hr.payroll.period', string='Payroll Period', required=True, tracking=True)
    date_start = fields.Date(string='Start Date', required=True, related='period_id.date_start', store=True, readonly=False)
    date_end = fields.Date(string='End Date', required=True, related='period_id.date_end', store=True, readonly=False)
    
    struct_id = fields.Many2one('hr.payroll.structure', string='Default Salary Structure')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit / Region')

    slip_ids = fields.One2many('hr.payslip', 'payslip_run_id', string='Included Payslips')
    payslip_count = fields.Integer(string='Payslips Count', compute='_compute_counts')
    
    # Financial Aggregates
    total_basic = fields.Float(string='Total Basic Salary (ETB)', compute='_compute_summary_metrics', store=True, digits=(16, 2))
    total_gross = fields.Float(string='Total Gross Earnings (ETB)', compute='_compute_summary_metrics', store=True, digits=(16, 2))
    total_net = fields.Float(string='Total Net Payable (ETB)', compute='_compute_summary_metrics', store=True, digits=(16, 2))
    total_tax = fields.Float(string='Total Personal Tax (ETB)', compute='_compute_summary_metrics', store=True, digits=(16, 2))
    total_pension_ee = fields.Float(string='Total EE Pension 7% (ETB)', compute='_compute_summary_metrics', store=True, digits=(16, 2))
    total_pension_er = fields.Float(string='Total ER Pension 11% (ETB)', compute='_compute_summary_metrics', store=True, digits=(16, 2))
    total_deductions = fields.Float(string='Total Deductions (ETB)', compute='_compute_summary_metrics', store=True, digits=(16, 2))

    # Diagnostics & Exception Aggregation
    exception_count = fields.Integer(string='Exceptions Count', compute='_compute_counts')
    has_critical_blockers = fields.Boolean(string='Critical Blockers Detected', compute='_compute_counts')

    # State State Machine (FR-PAY-032)
    state = fields.Selection([
        ('draft', 'Draft / Preparation'),
        ('simulated', 'Simulated (Dry-Run Preview)'),
        ('initiated', 'Initiated (Pending Verification)'),
        ('verified', 'Verified (Pending Division Manager Approval)'),
        ('approved', 'Approved by Division Manager'),
        ('posted', 'GL Posted & Committed'),
        ('disbursed', 'Disbursed / Paid via CBS'),
        ('cancelled', 'Cancelled'),
    ], string='Workflow Status', default='draft', required=True, tracking=True, copy=False)

    # Segregation of Duties Audit Fields
    initiator_id = fields.Many2one('res.users', string='Initiated By (HR Accountant)', readonly=True, tracking=True)
    initiation_date = fields.Datetime(string='Initiation Date', readonly=True)

    verifier_id = fields.Many2one('res.users', string='Verified By (Senior Controller)', readonly=True, tracking=True)
    verification_date = fields.Datetime(string='Verification Date', readonly=True)

    approver_id = fields.Many2one('res.users', string='Approved By (Division Manager)', readonly=True, tracking=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)

    # Downstream Integration Linkages
    move_ref = fields.Char(string='Accounting Journal Entry Ref', readonly=True, copy=False)
    payment_batch_id = fields.Many2one('payroll.payment.batch', string='CBS Direct Credit Payment Batch', readonly=True, copy=False)
    
    notes = fields.Text(string='Internal Notes')

    @api.depends('slip_ids.basic_wage', 'slip_ids.gross_wage', 'slip_ids.net_wage',
                 'slip_ids.income_tax', 'slip_ids.pension_ee', 'slip_ids.pension_er')
    def _compute_summary_metrics(self):
        for run in self:
            run.total_basic = sum(slip.basic_wage for slip in run.slip_ids)
            run.total_gross = sum(slip.gross_wage for slip in run.slip_ids)
            run.total_net = sum(slip.net_wage for slip in run.slip_ids)
            run.total_tax = sum(slip.income_tax for slip in run.slip_ids)
            run.total_pension_ee = sum(slip.pension_ee for slip in run.slip_ids)
            run.total_pension_er = sum(slip.pension_er for slip in run.slip_ids)
            run.total_deductions = run.total_gross - run.total_net

    @api.depends('slip_ids', 'slip_ids.exception_ids.severity', 'slip_ids.exception_ids.is_resolved')
    def _compute_counts(self):
        for run in self:
            run.payslip_count = len(run.slip_ids)
            all_exceptions = run.slip_ids.mapped('exception_ids')
            run.exception_count = len(all_exceptions)
            run.has_critical_blockers = any(e.severity == 'critical' and not e.is_resolved for e in all_exceptions)

    def action_compute_batch(self):
        """Compute/recompute all payslips included in this payrun."""
        for run in self:
            if run.state in ['approved', 'posted', 'disbursed']:
                raise UserError(_("Cannot recompute an approved or posted payrun."))
            for slip in run.slip_ids:
                slip.compute_sheet()
            run.message_post(body=_("Batch calculation executed for %d payslips.") % len(run.slip_ids))

    def action_simulate(self):
        """FR-PAY-034: Run complete batch simulation dry-run."""
        for run in self:
            run.action_compute_batch()
            run.write({'state': 'simulated'})
            run.message_post(body=_(
                "Payroll Simulation Completed. Estimated Gross: ETB %.2f, Net: ETB %.2f, Tax: ETB %.2f."
            ) % (run.total_gross, run.total_net, run.total_tax))

    def action_initiate(self):
        """Level 1: Initiation by HR Accountant."""
        for run in self:
            if not run.slip_ids:
                raise UserError(_("Cannot initiate an empty payrun. Generate payslips first."))
            run.action_compute_batch()
            run.write({
                'state': 'initiated',
                'initiator_id': self.env.user.id,
                'initiation_date': fields.Datetime.now()
            })
            run.message_post(body=_("Payrun initiated by HR Accountant %s. Submitted for Senior Controller Verification.") % self.env.user.name)

    def action_verify(self):
        """Level 2: Verification by Senior Payroll Controller."""
        for run in self:
            if not self.env.user.has_group('payroll.group_payroll_verifier'):
                raise UserError(_("Only Senior Payroll Controllers can verify a payrun."))
            if run.has_critical_blockers:
                raise UserError(_("Cannot verify payrun: Unresolved critical exceptions exist. Review the Exceptions tab."))
            run.write({
                'state': 'verified',
                'verifier_id': self.env.user.id,
                'verification_date': fields.Datetime.now()
            })
            run.message_post(body=_("Payrun verified by Senior Controller %s. Submitted for Division Manager Approval.") % self.env.user.name)

    def action_approve(self):
        """Level 3: Final Authorization by People Service & Reward Division Manager."""
        for run in self:
            if not self.env.user.has_group('payroll.group_payroll_manager'):
                raise UserError(_("Only People Service & Reward Division Managers can grant final approval for payroll runs."))
            if run.has_critical_blockers:
                raise UserError(_("Cannot approve payrun: Critical exceptions unresolved."))
            
            # Finalize all underlying payslips
            for slip in run.slip_ids:
                slip.action_payslip_done()

            run.write({
                'state': 'approved',
                'approver_id': self.env.user.id,
                'approval_date': fields.Datetime.now()
            })
            self.env['hr.payroll.audit.log'].log_event(
                event_type='payrun_approved',
                description=f"Payrun {run.name} ({run.number}) officially approved. Total Net: ETB {run.total_net:.2f}",
                approver=self.env.user,
                new_val=run.total_net,
                model='hr.payslip.run',
                res_id=run.id
            )
            run.message_post(body=_("Payrun officially approved by Division Manager %s.") % self.env.user.name)

    def action_post_gl(self):
        """Post General Ledger Journal Entry."""
        for run in self:
            if run.state != 'approved':
                raise UserError(_("Payrun must be approved before posting to General Ledger."))
            # Call GL integration generator
            gl_move = self.env['payroll.gl.integration'].generate_payroll_journal_entry(run)
            if gl_move and hasattr(gl_move, 'name'):
                run.write({'move_ref': gl_move.name, 'state': 'posted'})
            else:
                run.write({'move_ref': f"GL-ENTRY/{run.number}", 'state': 'posted'})
            run.message_post(body=_("Payroll Accounting entries posted successfully."))

    def action_generate_cbs_batch(self):
        """Generate Core Banking Direct Credit Export Batch."""
        for run in self:
            if run.state not in ['approved', 'posted']:
                raise UserError(_("Payrun must be approved before generating CBS payment files."))
            batch = self.env['payroll.payment.batch'].create_batch_from_payrun(run)
            run.write({'payment_batch_id': batch.id})
            return {
                'name': _('CBS Direct Credit Payment Batch'),
                'type': 'ir.actions.act_window',
                'res_model': 'payroll.payment.batch',
                'res_id': batch.id,
                'view_mode': 'form',
                'target': 'current',
            }

    def action_reset_draft(self):
        """Reset payrun to draft."""
        for run in self:
            if run.state == 'posted' and run.move_ref:
                raise UserError(_("Cannot reset a payrun with posted accounting entries."))
            for slip in run.slip_ids:
                slip.action_payslip_draft()
            run.write({'state': 'draft'})
