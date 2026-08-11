# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrResignation(models.Model):
    _name = 'hr.resignation'
    _description = 'HR Resignation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'employee_id'

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False)

    initiated_by = fields.Selection([
        ('employee', 'Employee'),
        ('organization', 'Organization'),
    ], default='employee', required=True, tracking=True)

    employee_id = fields.Many2one('hr.employee', required=True, tracking=True)
    contract_id = fields.Many2one('hr.version', readonly=True)

    department_id = fields.Many2one('hr.department')
    job_id = fields.Many2one('hr.job')
    job_grade = fields.Char(string='Job Grade')
    manager_id = fields.Many2one('hr.employee', string='Manager')
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit')

    job_category = fields.Selection([
        ('managerial', 'Managerial'),
        ('non_managerial', 'Non Managerial'),
    ])

    employee_contract = fields.Char(
        compute="_compute_contract",
        store=True,
        readonly=False
    )

    notice_period_applicable = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No')
    ], string="Notice Period Applicable", default='yes', required=True, tracking=True)

    notice_period = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No'),
    ], string="Notice Period",
        compute="_compute_notice_period",
        store=True,
        readonly=False,
        tracking=True)

    joined_date = fields.Date(
        related='employee_id.start_date',
        store=True,
        string='Join Date',
        readonly=False
    )

    reason = fields.Text(required=True)

    resignation_applied_date = fields.Date(
        string='Resignation Applied Date',
        default=fields.Date.context_today,
        tracking=True,
        required=True
    )

    expected_revealing_date = fields.Date(
        string="Last Day of Employee",
        required=True
    )

    resign_confirm_date = fields.Datetime()

    resignation_type = fields.Selection([
        ('normal', 'Normal Resignation'),
        ('fired', 'Fired by the Company'),
        ('retirement', 'Retirement'),
        ('voluntary_retirement', 'Voluntary Retirement'),
        ('medical', 'Medical Grounds'),
        ('death', 'Death'),
    ], default='normal', required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirm'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', tracking=True)

    # ------------------------------------------------------------------
    # SECURITY & INTEGRITY RESTRAINTS (READONLY PROTECTIONS)
    # ------------------------------------------------------------------

    def write(self, vals):
        """Strictly prohibit editing any record details once it has been approved."""
        for rec in self:
            if rec.state == 'approved':
                # Ignore system/chatter modifications (tracking, messages, activities)
                ignored_fields = {
                    'message_ids', 'message_follower_ids', 'activity_ids',
                    'message_main_attachment_id', 'website_message_ids'
                }
                actual_modifications = set(vals.keys()) - ignored_fields
                if actual_modifications:
                    raise UserError(
                        _("Modification Rejected: This resignation request has already been approved and locked."))

        vals = self._sanitize_selection_vals(dict(vals))
        return super(HrResignation, self).write(vals)

    def unlink(self):
        """Strictly prohibit deleting approved resignation documents."""
        for rec in self:
            if rec.state == 'approved':
                raise UserError(_("Deletion Rejected: You cannot delete an approved resignation record."))
        return super(HrResignation, self).unlink()

    # ------------------------------------------------------------------
    # AUTOMATED DATABASE INITIALIZATION & CLEANUP
    # ------------------------------------------------------------------

    def init(self):
        """Automated SQL cleanup execution. Runs on module upgrade to scrub
        corrupt/legacy selection values straight from the DB tables before
        the web client can fetch them and crash.
        """
        super(HrResignation, self).init()

        # Check if table exists to prevent installation order issues
        self.env.cr.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'hr_resignation'
            );
        """)
        if self.env.cr.fetchone()[0]:
            # 1. Clean up notice_period (Replaces old integers/strings with 'no')
            self.env.cr.execute("""
                UPDATE hr_resignation 
                SET notice_period = 'no' 
                WHERE notice_period NOT IN ('yes', 'no') AND notice_period IS NOT NULL;
            """)
            # 2. Clean up job_category
            self.env.cr.execute("""
                UPDATE hr_resignation 
                SET job_category = NULL 
                WHERE job_category NOT IN ('managerial', 'non_managerial') AND job_category IS NOT NULL;
            """)
            # 3. Clean up resignation_type
            self.env.cr.execute("""
                UPDATE hr_resignation 
                SET resignation_type = 'normal' 
                WHERE resignation_type NOT IN ('normal', 'fired', 'retirement', 'voluntary_retirement', 'medical', 'death') AND resignation_type IS NOT NULL;
            """)
            # 4. Clean up initiated_by
            self.env.cr.execute("""
                UPDATE hr_resignation 
                SET initiated_by = 'employee' 
                WHERE initiated_by NOT IN ('employee', 'organization') AND initiated_by IS NOT NULL;
            """)
            # 5. Clean up state
            self.env.cr.execute("""
                UPDATE hr_resignation 
                SET state = 'draft' 
                WHERE state NOT IN ('draft', 'confirm', 'approved', 'rejected') AND state IS NOT NULL;
            """)

    # ------------------------------------------------------------------
    # ON-THE-FLY SELECTION FIELD GUARDS
    # ------------------------------------------------------------------

    def _get_selection_field_names(self):
        """Return the names of all non-related Selection fields on this model."""
        return [
            fname
            for fname, field in self._fields.items()
            if field.type == 'selection' and not field.related
        ]

    @api.model
    def _sanitize_selection_vals(self, vals):
        """Drop any Selection value in vals that isn't a valid key for that field."""
        for fname in self._get_selection_field_names():
            if fname not in vals:
                continue
            value = vals[fname]
            if not value:
                continue
            field = self._fields[fname]
            selection = field.selection
            if callable(selection):
                try:
                    selection = selection(self)
                except Exception:
                    selection = []
            allowed_keys = dict(selection or [])
            if value not in allowed_keys:
                vals[fname] = False
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._sanitize_selection_vals(dict(vals)) for vals in vals_list]
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.resignation') or 'New'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # BUSINESS LOGIC & COMPUTES
    # ------------------------------------------------------------------

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for rec in self:
            if not rec.employee_id:
                rec.department_id = False
                rec.job_id = False
                rec.contract_id = False
                rec.manager_id = False
                rec.operating_unit_id = False
                rec.employee_contract = False
                rec.job_category = False
                rec.job_grade = False
                continue

            emp = rec.employee_id
            rec.department_id = emp.department_id
            rec.job_id = emp.job_id
            rec.job_grade = getattr(emp, 'job_grade', False)
            rec.manager_id = emp.parent_id if 'parent_id' in emp._fields else False

            contract = self.env['hr.contract'].search([
                ('employee_id', '=', emp.id),
                ('state', '=', 'open'),
            ], limit=1, order="date_start desc")

            rec.contract_id = contract

            if contract:
                rec.employee_contract = contract.display_name
                allowed_job_categories = dict(rec._fields['job_category'].selection)
                contract_job_category = getattr(contract, 'job_category', False)
                rec.job_category = (
                    contract_job_category
                    if contract_job_category in allowed_job_categories
                    else False
                )
                rec.operating_unit_id = contract.operating_unit_id
            else:
                rec.employee_contract = False
                rec.job_category = False
                rec.operating_unit_id = False

    @api.depends('contract_id')
    def _compute_contract(self):
        for rec in self:
            if rec.contract_id:
                rec.employee_contract = rec.contract_id.display_name
            else:
                rec.employee_contract = False

    @api.depends('notice_period_applicable', 'contract_id.notice_period')
    def _compute_notice_period(self):
        for rec in self:
            if rec.notice_period_applicable == 'no':
                rec.notice_period = 'no'
            elif rec.contract_id and rec.contract_id.notice_period:
                rec.notice_period = 'yes'
            else:
                rec.notice_period = 'no'

    # ------------------------------------------------------------------
    # WORKFLOW ACTIONS
    # ------------------------------------------------------------------

    def action_confirm_resignation(self):
        for rec in self:
            rec.state = 'confirm'
            rec.resign_confirm_date = fields.Datetime.now()

    def action_approve_resignation(self):
        for rec in self:
            rec.state = 'approved'
            rec.employee_id.active = False

    def action_reject(self):
        for rec in self:
            rec.state = 'rejected'

    def action_save_notify(self):
        """Save button handler for resignation request."""
        now = fields.Datetime.now()
        for rec in self:
            just_written = bool(
                rec.write_date and (now - rec.write_date).total_seconds() < 3
            )
            if just_written:
                title = _('Saved')
                message = _('Resignation request has been saved successfully.')
                notif_type = 'success'
            else:
                title = _('Nothing to Save')
                message = _('No changes to save.')
                notif_type = 'info'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': False,
            }
        }