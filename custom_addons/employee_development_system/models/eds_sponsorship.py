# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta

from .eds_action_notification import clear_action_activities, notify_action, role_users
from .eds_employee_projection import safe_employee_web_read

class EdsSponsorship(models.Model):
    _name = 'eds.sponsorship'
    _description = 'EDS Certification Sponsorship & Bond Management'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _approved_states = frozenset({'approved', 'active', 'completed', 'breached'})
    _approved_terms = frozenset({
        'name', 'employee_id', 'sponsorship_type', 'program_name',
        'currency_id', 'approved_amount', 'bond_start_date', 'bond_end_date',
        'bond_duration_months', 'recovery_policy', 'application_date',
        'institution_name', 'field_of_study', 'admission_letter_attached',
        'tenure_score', 'performance_score', 'pms_score_available',
        'pms_source_label', 'pms_fetched_score', 'pms_fetch_attempted',
        'pms_override', 'pms_override_justification',
        'strategic_alignment_score', 'total_matrix_score',
        'committee_decision', 'committee_chair_name', 'ppdd_director_name',
    })

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

    name = fields.Char(string='Sponsorship Ref', required=True, copy=False, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    program_name = fields.Char(string='Sponsored Program / Certification', required=True, tracking=True)
    sponsorship_type = fields.Selection([
        ('certification', 'Professional Certification'),
        ('education', 'Bonded Higher Education'),
    ], string='Sponsorship Type', required=True, default='certification')
    service_months = fields.Integer(
        string='Continuous Service (Months)', compute='_compute_eligibility',
        help='Full calendar months from the earliest non-cancelled HR contract start '
             'to today. If no contract start exists, other HR service dates are used. '
             'Employment gaps are not subtracted.')
    eligible = fields.Boolean(string='Meets Service Eligibility', compute='_compute_eligibility')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    approved_amount = fields.Monetary(string='Sponsored Amount', currency_field='currency_id', required=True, tracking=True)
    bond_agreement = fields.Binary(string='Signed Service Bond Agreement', attachment=True)
    bond_filename = fields.Char(string='Bond File Name')
    bond_start_date = fields.Date(string='Bond Start Date', tracking=True)
    bond_end_date = fields.Date(string='Bond End Date', tracking=True)
    bond_duration_months = fields.Integer(
        string='Bond Period (Months)', default=24,
        help='When an end date is entered, partial calendar months are rounded up. '
             'The entered end date is preserved.')
    outstanding_obligation = fields.Monetary(string='Outstanding Bond Obligation', compute='_compute_obligation', currency_field='currency_id')
    repayment_line_ids = fields.One2many('eds.sponsorship.repayment.line', 'sponsorship_id', string='Repayment Lines')
    breach_reason = fields.Selection([
        ('resignation', 'Resignation'),
        ('breach', 'Contract Breach'),
        ('withdrawal', 'Course / Study Withdrawal'),
        ('non_completion', 'Non-Completion / Academic Failure'),
    ], string='Breach Reason', default='breach', tracking=True)
    recovery_policy = fields.Selection([
        ('pro_rata', 'Pro-Rata Unamortised Balance (Default)'),
        ('full', 'Full Amount (Documented Policy Clause)'),
    ], string='Recovery Policy', default='pro_rata', tracking=True)
    recovery_amount = fields.Monetary(
        string='Calculated Breach Recovery Amount',
        currency_field='currency_id',
        readonly=True, tracking=True)

    # Sponsorship Application & Scoring Matrix
    application_date = fields.Date(string='Application Date', default=fields.Date.context_today)
    institution_name = fields.Char(string='University / Educational Institution')
    field_of_study = fields.Char(string='Field of Study / Degree Title')
    admission_letter_attached = fields.Boolean(string='Official Admission Letter Attached', default=True)
    tenure_score = fields.Float(string='Service Tenure Score (Max 30 pts)', default=25.0)
    performance_score = fields.Float(
        string='PMS Score / 40', copy=False,
        help='Use Fetch PMS Score to load the latest confirmed appraisal. Check Override '
             'PMS Score and provide a justification to enter a different score.')
    pms_fetched_score = fields.Float(
        string='Fetched PMS Score / 40', copy=False, readonly=True,
        help='The last score fetched from a confirmed employee PMS appraisal.')
    pms_fetch_attempted = fields.Boolean(copy=False, readonly=True)
    pms_score_available = fields.Boolean(
        string='Confirmed PMS Appraisal Found', copy=False, readonly=True)
    pms_source_label = fields.Char(
        string='PMS Score Source', copy=False, readonly=True,
        help='Internal reference to the appraisal last fetched for this application.')
    pms_override = fields.Boolean(string='Override PMS Score', copy=False)
    pms_override_justification = fields.Text(
        string='Override Justification', copy=False,
        help='Explain why the PMS score was changed or entered without an appraisal.')
    strategic_alignment_score = fields.Float(string='Strategic Need Score (Max 30 pts)', default=25.0)
    total_matrix_score = fields.Float(string='Total Matrix Score', compute='_compute_total_matrix_score', store=True)
    committee_decision = fields.Selection([
        ('recommended', 'Recommended for Full Sponsorship'),
        ('waitlisted', 'Waitlisted for Next Cohort'),
        ('rejected', 'Rejected'),
    ], string='Committee Recommendation', default='recommended')
    committee_chair_name = fields.Char(string='Committee Chairperson')
    ppdd_director_name = fields.Char(string='Director, PPDD Approval')

    @api.model
    def _pms_snapshot_for(self, employee_id, application_date):
        """Read one final appraisal as a fetchable 40-point baseline."""
        cutoff = fields.Date.to_date(application_date) or fields.Date.context_today(self)
        if not employee_id:
            return {
                'pms_fetched_score': 0.0,
                'pms_fetch_attempted': True,
                'pms_score_available': False,
                'pms_source_label': _('Select an employee to load a PMS score.'),
            }
        appraisal = self.env['t3.appraisal'].sudo().search([
            ('employee_id', '=', employee_id),
            ('state', '=', 'confirmed'),
            ('end_date', '<=', cutoff),
        ], order='end_date desc, appraisal_date desc, id desc', limit=1)
        if not appraisal:
            return {
                'pms_fetched_score': 0.0,
                'pms_fetch_attempted': True,
                'pms_score_available': False,
                'pms_source_label': _(
                    'No confirmed PMS appraisal ending on or before %s.') % cutoff,
            }
        pms_percent = max(0.0, min(100.0, appraisal.employee_score or 0.0))
        return {
            'pms_fetched_score': round(pms_percent * 0.4, 2),
            'pms_fetch_attempted': True,
            'pms_score_available': True,
            'pms_source_label': _('%s (PMS ID %s; period ended %s; score %.2f%%)') % (
                appraisal.name, appraisal.id, appraisal.end_date, pms_percent),
        }

    @api.onchange('employee_id', 'application_date')
    def _onchange_pms_source(self):
        for rec in self:
            rec.update({
                'performance_score': 0.0,
                'pms_fetched_score': 0.0,
                'pms_fetch_attempted': False,
                'pms_score_available': False,
                'pms_source_label': False,
                'pms_override': False,
                'pms_override_justification': False,
            })

    @api.onchange('pms_override')
    def _onchange_pms_override(self):
        for rec in self:
            if rec.pms_override and not rec.pms_fetch_attempted:
                rec.pms_fetched_score = rec.performance_score
            elif not rec.pms_override:
                rec.performance_score = rec.pms_fetched_score
                rec.pms_override_justification = False

    @api.model
    def _bond_months_covering_dates(self, start, end):
        """Return whole calendar months covering the entered bond dates."""
        start = fields.Date.to_date(start)
        end = fields.Date.to_date(end)
        if not start or not end or end <= start:
            return 0
        months = (end.year - start.year) * 12 + end.month - start.month
        if start + relativedelta(months=months) < end:
            months += 1
        return max(1, months)

    @api.onchange('bond_start_date', 'bond_duration_months')
    def _onchange_bond_start_or_duration(self):
        for rec in self:
            if rec.bond_start_date and rec.bond_duration_months > 0:
                rec.bond_end_date = rec.bond_start_date + relativedelta(
                    months=rec.bond_duration_months)

    @api.onchange('bond_end_date')
    def _onchange_bond_end_date(self):
        for rec in self:
            if rec.bond_start_date and rec.bond_end_date and rec.bond_end_date > rec.bond_start_date:
                rec.bond_duration_months = rec._bond_months_covering_dates(
                    rec.bond_start_date, rec.bond_end_date)

    @api.model
    def _synchronize_bond_terms(self, values, current=None):
        """Honor an explicit end date; otherwise calculate it from start/months."""
        if not {'bond_start_date', 'bond_end_date', 'bond_duration_months'} & values.keys():
            return values
        values = values.copy()
        start = fields.Date.to_date(values.get(
            'bond_start_date', current.bond_start_date if current else False))
        end = fields.Date.to_date(values.get(
            'bond_end_date', current.bond_end_date if current else False))
        months = values.get(
            'bond_duration_months', current.bond_duration_months if current else 24)
        if 'bond_end_date' in values:
            if start and end and end > start:
                values['bond_duration_months'] = self._bond_months_covering_dates(start, end)
        elif ('bond_start_date' in values or 'bond_duration_months' in values) and start and months and months > 0:
            values['bond_end_date'] = start + relativedelta(months=months)
        return values

    @api.depends('tenure_score', 'performance_score', 'strategic_alignment_score')
    def _compute_total_matrix_score(self):
        for rec in self:
            rec.total_matrix_score = (rec.tenure_score or 0.0) + (rec.performance_score or 0.0) + (rec.strategic_alignment_score or 0.0)

    @api.constrains('approved_amount', 'bond_duration_months', 'bond_start_date', 'bond_end_date',
                    'tenure_score', 'performance_score', 'strategic_alignment_score',
                    'pms_override', 'pms_override_justification')
    def _check_sponsorship_values(self):
        for rec in self:
            if rec.approved_amount <= 0:
                raise ValidationError(_('The sponsored amount must be positive.'))
            if rec.bond_duration_months <= 0:
                raise ValidationError(_('The bond duration must be positive.'))
            if rec.bond_start_date and rec.bond_end_date and rec.bond_end_date <= rec.bond_start_date:
                raise ValidationError(_('The bond end date must be after its start date.'))
            for score, maximum, label in (
                    (rec.tenure_score, 30, _('Service tenure')),
                    (rec.performance_score, 40, _('PMS performance')),
                    (rec.strategic_alignment_score, 30, _('Strategic need'))):
                if score < 0 or score > maximum:
                    raise ValidationError(_('%s score must be between 0 and %s.') % (label, maximum))
            if rec.pms_override and not (rec.pms_override_justification or '').strip():
                raise ValidationError(_('Enter a justification for the PMS score override.'))

    def action_print_application_form(self):
        """Prints official Form Staff Sponsorship Application & Scoring Matrix PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_sponsorship_application').report_action(self)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('eligibility_check', 'Eligibility Verified'),
        ('approved', 'Approved'),
        ('active', 'Active Bond'),
        ('completed', 'Bond Obligation Fulfilled'),
        ('breached', 'Bond Breached'),
    ], string='Status', default='draft', required=True, tracking=True)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    @api.model_create_multi
    def create(self, vals_list):
        internal_pms_fields = {
            'pms_fetched_score', 'pms_fetch_attempted',
            'pms_score_available', 'pms_source_label',
        }
        vals_list = [self._synchronize_bond_terms(vals) for vals in vals_list]
        for vals in vals_list:
            if any(vals.get(field) for field in internal_pms_fields):
                raise UserError(_('Use Fetch PMS Score to load the PMS result.'))
            for field in internal_pms_fields:
                vals.pop(field, None)
            if vals.get('pms_override'):
                if not (vals.get('pms_override_justification') or '').strip():
                    raise ValidationError(_('Enter a justification for the PMS score override.'))
            elif vals.get('performance_score'):
                raise UserError(_('Use Fetch PMS Score or a justified override to set the PMS score.'))
            else:
                vals['performance_score'] = 0.0
                vals['pms_override_justification'] = False
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.sponsorship') or _('New')
        return super(EdsSponsorship, self).create(vals_list)

    def write(self, vals):
        requested = set(vals)
        target_state = vals.get('state')
        locked_terms = requested & self._approved_terms
        for rec in self:
            if (rec.state in ('completed', 'breached') and target_state
                    and target_state != rec.state):
                raise UserError(_('A completed or breached bond cannot change status.'))
            if rec.state in self._approved_states and target_state in ('draft', 'eligibility_check'):
                raise UserError(_('An approved sponsorship cannot be returned to draft or eligibility review.'))
            if (rec.state in ('active', 'completed', 'breached')
                    and target_state == 'approved'):
                raise UserError(_('An activated or closed bond cannot return to approval.'))
            if locked_terms and (rec.state in self._approved_states
                                 or target_state in self._approved_states):
                raise UserError(_(
                    'The employee, sponsorship terms, bond dates, and application matrix '
                    'cannot be changed after approval.'))
            if target_state == 'approved' and (not rec.bond_start_date or not rec.bond_end_date):
                raise ValidationError(_(
                    'Set the bond start date and end date before approving the sponsorship.'))
            if target_state == 'active' and rec.state != 'active' and (
                    not rec.bond_start_date or not rec.bond_end_date or not rec.bond_agreement):
                raise ValidationError(_(
                    'Set both bond dates and attach the signed agreement before activating the bond.'))
            if (requested & {'bond_agreement', 'bond_filename'}
                    and (rec.state in ('active', 'completed', 'breached')
                         or target_state in ('active', 'completed', 'breached'))):
                raise UserError(_('The signed bond document cannot be replaced after activation.'))
            if (requested & {'breach_reason', 'recovery_amount'}
                    and (rec.state == 'breached' or target_state == 'breached')):
                raise UserError(_('The recorded breach reason and recovery amount cannot be changed.'))
        internal_pms_fields = {
            'pms_fetched_score', 'pms_fetch_attempted',
            'pms_score_available', 'pms_source_label',
        }
        if requested & internal_pms_fields:
            if not requested & {'employee_id', 'application_date', 'pms_override'}:
                raise UserError(_('Use Fetch PMS Score to update the PMS result.'))
            # The form may send readonly onchange values with an employee,
            # application date, or override change. Never trust those values.
            vals = vals.copy()
            for field in internal_pms_fields:
                vals.pop(field, None)
            requested = set(vals)
        pms_inputs_changed = bool({'employee_id', 'application_date'} & vals.keys())
        bond_inputs_changed = bool(
            {'bond_start_date', 'bond_end_date', 'bond_duration_months'} & vals.keys())
        pms_inputs_changed = pms_inputs_changed or bool(
            {'pms_override', 'pms_override_justification', 'performance_score'} & requested)
        if not pms_inputs_changed and not bond_inputs_changed:
            return super().write(vals)
        for rec in self:
            record_vals = vals.copy()
            if {'employee_id', 'application_date'} & requested:
                if rec.state not in ('draft', 'eligibility_check'):
                    raise UserError(_(
                        'The employee and application date cannot change after sponsorship approval.'))
                if (rec.state == 'eligibility_check' and 'employee_id' in record_vals
                        and record_vals['employee_id'] != rec.employee_id.id):
                    raise UserError(_(
                        'Change the employee while the sponsorship is still a draft; '
                        'service eligibility must be verified for that employee.'))
                record_vals.update({
                    'performance_score': 0.0,
                    'pms_fetched_score': 0.0,
                    'pms_fetch_attempted': False,
                    'pms_score_available': False,
                    'pms_source_label': False,
                    'pms_override': False,
                    'pms_override_justification': False,
                })
            elif pms_inputs_changed:
                override = record_vals.get('pms_override', rec.pms_override)
                if override:
                    # Preserve the prior score of a legacy record as the
                    # baseline before its first justified override.
                    if not rec.pms_override and not rec.pms_fetch_attempted:
                        record_vals['pms_fetched_score'] = rec.performance_score
                    justification = record_vals.get(
                        'pms_override_justification', rec.pms_override_justification)
                    if not (justification or '').strip():
                        raise ValidationError(_(
                            'Enter a justification for the PMS score override.'))
                else:
                    if rec.pms_override:
                        record_vals['performance_score'] = rec.pms_fetched_score
                        record_vals['pms_override_justification'] = False
                    elif ('performance_score' in record_vals
                          and record_vals['performance_score'] != rec.performance_score):
                        raise UserError(_(
                            'Use Fetch PMS Score or a justified override to change the PMS score.'))
                    if record_vals.get('pms_override_justification'):
                        raise ValidationError(_(
                            'Enable Override PMS Score before entering a justification.'))
            if bond_inputs_changed:
                record_vals = rec._synchronize_bond_terms(record_vals, rec)
            super(EdsSponsorship, rec).write(record_vals)
        return True

    def action_refresh_pms_score(self):
        """Fetch the latest final PMS result for this application."""
        notices = []
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state not in ('draft', 'eligibility_check'):
                raise UserError(_(
                    'The PMS score of an approved sponsorship is a historical snapshot.'))
            if not rec.employee_id:
                raise ValidationError(_('Select an employee before fetching the PMS score.'))
            snapshot = rec._pms_snapshot_for(rec.employee_id.id, rec.application_date)
            if not rec.pms_override:
                snapshot['performance_score'] = snapshot['pms_fetched_score']
            super(EdsSponsorship, rec).write(snapshot)
            notices.append(bool(snapshot['pms_score_available']))
        if len(self) == 1:
            found = notices[0]
            if found:
                message = _('PMS score fetched: %.2f / 40.') % snapshot['pms_fetched_score']
            elif self.pms_override:
                message = _(
                    'No confirmed PMS appraisal was found for this employee and '
                    'application date. The justified override was retained.')
            else:
                message = _(
                    'No confirmed PMS appraisal was found for this employee and '
                    'application date. Enter a justified override if needed.')
            if len(self) == 1:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'bunna_refresh_form',
                    'params': {
                        'res_model': self._name,
                        'res_id': self.id,
                        'title': _('PMS Score'),
                        'message': message,
                        'type': 'success' if found else 'warning',
                    },
                }
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('PMS Score'),
                    'message': message,
                    'type': 'success' if found else 'warning',
                    'sticky': False,
                },
            }
        return True

    @api.depends('employee_id', 'employee_id.service_start_date',
                 'employee_id.service_hire_date', 'employee_id.first_contract_date')
    def _compute_eligibility(self):
        configured = self.env['ir.config_parameter'].sudo().get_param(
            'eds.sponsorship_min_service_months', '12')
        try:
            minimum_months = max(0, int(configured))
        except (TypeError, ValueError):
            minimum_months = 12
        for rec in self:
            start = self.env['eds.hr.compat'].get_employee_service_start(rec.employee_id)
            if start:
                today = fields.Date.context_today(self)
                service = relativedelta(today, fields.Date.to_date(start))
                rec.service_months = max(0, service.years * 12 + service.months)
                rec.eligible = rec.service_months >= minimum_months
            else:
                rec.service_months = 0
                rec.eligible = False

    @api.depends('approved_amount', 'bond_start_date', 'bond_end_date', 'state', 'recovery_amount')
    def _compute_obligation(self):
        for rec in self:
            if rec.state == 'active' and rec.bond_start_date and rec.bond_end_date:
                today = fields.Date.context_today(self)
                if today >= rec.bond_end_date:
                    rec.outstanding_obligation = 0.0
                else:
                    total_days = (rec.bond_end_date - rec.bond_start_date).days or 1
                    elapsed_days = (today - rec.bond_start_date).days
                    remaining_ratio = min(1.0, max(0.0, (total_days - elapsed_days) / float(total_days)))
                    rec.outstanding_obligation = rec.approved_amount * remaining_ratio
            elif rec.state == 'breached':
                rec.outstanding_obligation = rec.recovery_amount
            elif rec.state == 'completed':
                rec.outstanding_obligation = 0.0
            else:
                rec.outstanding_obligation = 0.0

    def action_verify_eligibility(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'draft':
                raise UserError(_("Only draft sponsorships can have eligibility verified."))
            rec._compute_eligibility()
            if not rec.eligible:
                minimum = self.env['ir.config_parameter'].sudo().get_param(
                    'eds.sponsorship_min_service_months', '12')
                raise ValidationError(_(
                    'Employee does not meet the minimum %s months continuous service requirement '
                    '(current: %s months). Verify the employment start date in HR.')
                    % (minimum, rec.service_months))
            rec.state = 'eligibility_check'
            notify_action(rec, role_users(rec, 'group_eds_manager'),
                          _('Approve sponsorship'),
                          _('Sponsorship %s for %s is eligible and awaits approval.')
                          % (rec.name, rec.employee_id.sudo().name))

    def action_approve(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'eligibility_check':
                raise UserError(_("Only sponsorships with verified eligibility can be approved."))
            if not rec.bond_start_date or not rec.bond_end_date:
                raise ValidationError(_(
                    'Set the bond start date and end date before approving the sponsorship. '
                    'These dates cannot be changed after approval.'))
            if rec.bond_end_date <= rec.bond_start_date:
                raise ValidationError(_('The bond end date must be after its start date.'))
            rec.state = 'approved'
            clear_action_activities(rec)
            notify_action(rec, role_users(rec, 'group_eds_officer'),
                          _('Activate approved sponsorship'),
                          _('Sponsorship %s is approved. Attach the signed bond and activate it.')
                          % rec.name)
            notify_action(rec, rec.employee_id.sudo().user_id,
                          _('Sponsorship approved'),
                          _('Your sponsorship for %s has been approved.') % rec.program_name,
                          action_required=False)

    def action_activate_bond(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'approved':
                raise UserError(_("Only approved sponsorships can have their bond activated."))
            if not rec.bond_agreement:
                raise ValidationError(_("Please attach the signed bond agreement document before activating."))
            # Older approved records may lack dates. Set only the missing values
            # once here; normal approvals require both dates before approval.
            start = rec.bond_start_date
            if not start and rec.bond_end_date:
                start = rec.bond_end_date - relativedelta(months=rec.bond_duration_months)
            start = start or fields.Date.context_today(self)
            end = rec.bond_end_date or (start + relativedelta(months=rec.bond_duration_months))
            if end <= start:
                raise ValidationError(_('The bond end date must be after its start date.'))
            if not rec.bond_start_date or not rec.bond_end_date:
                legacy_values = {'state': 'active'}
                if not rec.bond_start_date:
                    legacy_values['bond_start_date'] = start
                if not rec.bond_end_date:
                    legacy_values['bond_end_date'] = end
                # This internal write is limited to first-time completion of
                # missing dates on a legacy record; the public write guard
                # never permits changing approved bond terms.
                super(EdsSponsorship, rec).write(legacy_values)
                rec.message_post(body=_('Missing legacy bond dates were initialized on activation.'))
            else:
                rec.state = 'active'
            clear_action_activities(rec)
            notify_action(rec, rec.employee_id.sudo().user_id,
                          _('Sponsorship bond active'),
                          _('Your sponsorship bond for %s is active through %s.')
                          % (rec.program_name, rec.bond_end_date or _('the agreed date')),
                          action_required=False)

    def action_complete_bond(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'active':
                raise UserError(_('Only active bonds can be completed.'))
            if not rec.bond_end_date or fields.Date.context_today(self) < rec.bond_end_date:
                raise ValidationError(_('The agreed bond period has not ended.'))
            rec.state = 'completed'
            clear_action_activities(rec)
            rec.message_post(body=_('Service bond fulfilled after the agreed period ended.'))
            notify_action(rec, rec.employee_id.sudo().user_id,
                          _('Sponsorship bond fulfilled'),
                          _('Your service obligation for %s has been fulfilled.') % rec.program_name,
                          action_required=False)

    def action_mark_breached(self, breach_reason=None):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'active':
                raise UserError(_("Only active bonds can be marked as breached."))
            if breach_reason:
                rec.breach_reason = breach_reason

            # Compute recovery amount BEFORE state change
            today = fields.Date.context_today(self)
            if rec.recovery_policy == 'full':
                recovery_amt = rec.approved_amount
            else:  # pro_rata by default
                if rec.bond_end_date and today >= rec.bond_end_date:
                    recovery_amt = 0.0
                elif rec.bond_start_date and rec.bond_end_date:
                    total_days = (rec.bond_end_date - rec.bond_start_date).days or 1
                    elapsed_days = max(0, (today - rec.bond_start_date).days)
                    remaining_ratio = max(0.0, (total_days - elapsed_days) / float(total_days))
                    recovery_amt = round(rec.approved_amount * remaining_ratio, 2)
                else:
                    recovery_amt = rec.approved_amount

            rec.recovery_amount = recovery_amt
            rec.state = 'breached'

            # Create repayment line and payroll payload
            line = self.env['eds.sponsorship.repayment.line'].create({
                'sponsorship_id': rec.id,
                'date': today,
                'amount': recovery_amt,
                'schedule_type': 'salary_deduction',
            })
            payload = self.env['eds.payroll.payload'].create({
                'payload_type': 'sponsorship_recovery',
                'employee_id': rec.employee_id.id,
                'amount': recovery_amt,
                'effective_date': today,
                'source_ref': f"Sponsorship Breach ({rec.breach_reason}): {rec.name}",
            })
            line.payload_id = payload.id
            rec.message_post(body=_("Bond marked as breached (Reason: %s, Policy: %s). Calculated recovery: %s. Payroll payload %s generated.") % (
                rec.breach_reason, rec.recovery_policy, recovery_amt, payload.name
            ))
            notify_action(rec, rec.employee_id.sudo().user_id,
                          _('Sponsorship bond status changed'),
                          _('Your sponsorship bond for %s was marked breached. Recorded recovery: %s %s. Contact L&D for details.')
                          % (rec.program_name, rec.currency_id.name, recovery_amt),
                          action_required=False)

class EdsSponsorshipRepaymentLine(models.Model):
    _name = 'eds.sponsorship.repayment.line'
    _description = 'EDS Sponsorship Repayment / Recovery Line'
    _order = 'create_date desc, id desc'

    sponsorship_id = fields.Many2one('eds.sponsorship', string='Sponsorship', ondelete='cascade', required=True)
    date = fields.Date(string='Recovery Date', default=fields.Date.context_today, required=True)
    currency_id = fields.Many2one('res.currency', related='sponsorship_id.currency_id')
    amount = fields.Monetary(string='Repayment Amount', currency_field='currency_id', required=True)
    schedule_type = fields.Selection([
        ('salary_deduction', 'Payroll Salary Deduction'),
        ('terminal_benefits', 'Terminal Benefits Deduction'),
        ('waiver', 'CEO Waiver Approved'),
    ], string='Recovery Method', default='salary_deduction', required=True)
    waiver_authority = fields.Text(string='Waiver Justification / Authority')
    payload_id = fields.Many2one('eds.payroll.payload', string='Payroll Payload Ref')
