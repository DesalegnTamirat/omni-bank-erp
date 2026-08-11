# -*- coding: utf-8 -*-
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EdsTnaPriorityRule(models.Model):
    """Configurable weighting for the TNA priority engine ().

    Each active rule contributes `weight` % to the weighted average score of a
    training need. Scores per criterion are 0-100 (see eds.tna.entry criterion
    fields). Weights need not sum to 100 - the engine normalizes by the total.
    """
    _name = 'eds.tna.priority.rule'
    _description = 'TNA Priority Rule'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Rule Name', required=True)
    criteria = fields.Selection([
        ('strategic_alignment', 'Strategic Alignment'),
        ('tom_impact', 'TOM Impact'),
        ('gap_severity', 'Gap Severity'),
        ('risk_level', 'Risk Level'),
        ('regulatory', 'Regulatory Requirement'),
        ('future_capability', 'Future Capability'),
    ], string='Criteria', required=True)
    weight = fields.Float(string='Weight (%)', required=True, default=0.0)
    active = fields.Boolean(string='Active', default=True)
    description = fields.Text(string='Description')

    _sql_constraints = [
        ('criteria_uniq', 'unique(criteria)',
         'A priority rule for this criteria already exists!'),
    ]

    def write(self, vals):
        """Re-score all consolidated entries when weights/rules change ()."""
        res = super().write(vals)
        if 'weight' in vals or 'active' in vals:
            entries = self.env['eds.tna.entry'].search(
                [('consolidation_id', '!=', False), ('state', 'not in', ('excluded',))])
            # The global rule config re-scores entries even if one consolidation is locked;
            # the score write itself is engine-internal, so bypass the locked-edit guard.
            for entry in entries:
                entry.with_context(eds_allow_locked_edit=True).priority_score = entry._get_weighted_priority_score()
        return res


class EdsApprovalHistory(models.Model):
    """Immutable approval trail, generic across EDS approval workflows.

    Used by TNA consolidation now; will be shared with curriculum and annual
    plan approvals (Task 3/5) via the same model + `model`/`record_id` pair.
    """
    _name = 'eds.approval.history'
    _description = 'EDS Approval History'
    _order = 'create_date desc'

    model = fields.Char(string='Model', required=True, readonly=True)
    record_id = fields.Integer(string='Record ID', required=True, readonly=True)
    # Convenience links for the current consumers (filters on `model` above)
    consolidation_id = fields.Many2one(
        'eds.tna.consolidation', string='Consolidation', ondelete='cascade', readonly=True)
    curriculum_id = fields.Many2one(
        'eds.curriculum', string='Curriculum', ondelete='cascade', readonly=True)
    annual_plan_id = fields.Many2one(
        'eds.annual.plan', string='Annual Plan', ondelete='cascade', readonly=True)
    state_from = fields.Char(string='From State', readonly=True)
    state_to = fields.Char(string='To State', readonly=True)
    user_id = fields.Many2one(
        'res.users', string='User', default=lambda self: self.env.user, readonly=True)
    comment = fields.Text(string='Comment', readonly=True)
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('record_id'):
                if vals.get('consolidation_id'):
                    vals.update({
                        'model': 'eds.tna.consolidation',
                        'record_id': vals['consolidation_id'],
                    })
                elif vals.get('curriculum_id'):
                    vals.update({
                        'model': 'eds.curriculum',
                        'record_id': vals['curriculum_id'],
                    })
                elif vals.get('annual_plan_id'):
                    vals.update({
                        'model': 'eds.annual.plan',
                        'record_id': vals['annual_plan_id'],
                    })
        return super().create(vals_list)

    def unlink(self):
        # Immutability: approval history is non-editable and non-deletable (audit trail).
        # The consolidation unlink flow passes a context flag so cascade deletes of draft
        # consolidations do not get blocked by this guard.
        if not self.env.context.get('eds_bypass_history_guard'):
            raise ValidationError(_('Approval history entries cannot be deleted (immutable audit trail).'))
        return super().unlink()


class EdsTnaConsolidation(models.Model):
    """Bank-wide TNA consolidation register (-010).

    Gathers submitted/validated needs (optionally per work unit), auto-flags
    duplicates and non-training items (), computes weighted priority
    (), then routes through the four-step approval chain
    PPDD Validation -> Director PPDD -> CPCO Endorsement -> SMC Approval with
    segregation of duties (). Locks after SMC approval ().
    """
    _name = 'eds.tna.consolidation'
    _description = 'TNA Consolidation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    cycle_id = fields.Many2one(
        'eds.tna.cycle', string='TNA Cycle', required=True, ondelete='cascade', tracking=True)
    work_unit_id = fields.Many2one(
        'operating.unit', string='Work Unit',
        help='Leave empty to consolidate the whole cycle bank-wide.', tracking=True)
    entry_ids = fields.One2many(
        'eds.tna.entry', 'consolidation_id', string='Training Needs')
    entry_count = fields.Integer(string='Needs', compute='_compute_counts')
    duplicate_count = fields.Integer(string='Duplicates', compute='_compute_counts')
    non_training_count = fields.Integer(string='Non-Training Items', compute='_compute_counts')
    excluded_count = fields.Integer(string='Excluded', compute='_compute_counts')
    # Review sub-tabs (): computed subsets of entry_ids for the form pages
    duplicate_entry_ids = fields.One2many(
        'eds.tna.entry', 'consolidation_id', string='Duplicate Needs',
        compute='_compute_review_subsets')
    non_training_entry_ids = fields.One2many(
        'eds.tna.entry', 'consolidation_id', string='Non-Training Items',
        compute='_compute_review_subsets')
    excluded_entry_ids = fields.One2many(
        'eds.tna.entry', 'consolidation_id', string='Excluded Needs',
        compute='_compute_review_subsets')
    priority_score = fields.Float(
        string='Weighted Priority Score', compute='_compute_priority_score', store=True)
    approval_deadline = fields.Date(
        string='Approval Deadline', related='cycle_id.approval_deadline', store=True)
    days_to_deadline = fields.Integer(string='Days to Deadline', compute='_compute_days_to_deadline', store=True)
    deadline_breached = fields.Boolean(
        string='Deadline Breached', compute='_compute_days_to_deadline', store=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('ppdd_validation', 'PPDD Validation'),
        ('director_review', 'Director PPDD Review'),
        ('cpco_endorsement', 'CPCO Endorsement'),
        ('smc_approval', 'SMC Approval'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Segregation of duties (): validator != reviewer != endorser != approver
    validator_id = fields.Many2one('res.users', string='Validator (PPDD)', tracking=True)
    reviewer_id = fields.Many2one('res.users', string='Reviewer (Director PPDD)', tracking=True)
    endorser_id = fields.Many2one('res.users', string='Endorser (CPCO)', tracking=True)
    approver_id = fields.Many2one('res.users', string='Approver (SMC)', tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    approval_history_ids = fields.One2many(
        'eds.approval.history', 'consolidation_id', string='Approval History',
        domain=[('model', '=', 'eds.tna.consolidation')])
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('entry_ids')
    def _compute_counts(self):
        for rec in self:
            rec.entry_count = len(rec.entry_ids)
            rec.duplicate_count = len(rec.entry_ids.filtered('is_duplicate'))
            rec.non_training_count = len(rec.entry_ids.filtered('exclusion_type'))
            rec.excluded_count = len(rec.entry_ids.filtered(lambda e: e.state == 'excluded'))

    @api.depends('entry_ids')
    def _compute_review_subsets(self):
        for rec in self:
            rec.duplicate_entry_ids = rec.entry_ids.filtered('is_duplicate')
            rec.non_training_entry_ids = rec.entry_ids.filtered('exclusion_type')
            rec.excluded_entry_ids = rec.entry_ids.filtered(lambda e: e.state == 'excluded')

    @api.depends('entry_ids.priority_score')
    def _compute_priority_score(self):
        for rec in self:
            scored = rec.entry_ids.filtered(lambda e: e.state != 'excluded' and e.priority_score)
            rec.priority_score = round(
                sum(scored.mapped('priority_score')) / len(scored), 2) if scored else 0.0

    @api.depends('approval_deadline')
    def _compute_days_to_deadline(self):
        today = date.today()
        for rec in self:
            if rec.approval_deadline:
                rec.days_to_deadline = (rec.approval_deadline - today).days
                rec.deadline_breached = rec.days_to_deadline < 0 and rec.state not in ('approved', 'locked')
            else:
                rec.days_to_deadline = 0
                rec.deadline_breached = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.tna.consolidation') or _('New')
        return super().create(vals_list)

    def unlink(self):
        for rec in self:
            if rec.state in ('approved', 'locked'):
                raise UserError(_('Approved/locked TNA consolidations cannot be deleted ().'))
            # Allow deleting draft consolidations: drop their immutable history first
            # (bypasses the history unlink guard) so the cascade does not raise.
            if rec.approval_history_ids:
                rec.approval_history_ids.with_context(eds_bypass_history_guard=True).unlink()
        return super().unlink()

    # ── Consolidation & Prioritization (/007) ────────────────────────
    def action_consolidate(self):
        """Gather submitted/validated needs (per work unit when set) into the register,
        auto-flag duplicates and non-training items for review & exclusion ()."""
        self.ensure_one()
        domain = [('cycle_id', '=', self.cycle_id.id),
                  ('state', 'in', ('submitted', 'validated'))]
        if self.work_unit_id:
            domain.append(('work_unit_id', '=', self.work_unit_id.id))
        entries = self.env['eds.tna.entry'].search(domain)
        # Detach entries that no longer match (cycle/work unit changed) but stay on this record
        self.entry_ids.filtered(lambda e: e not in entries).write({'consolidation_id': False})
        entries.write({'consolidation_id': self.id})
        self._flag_duplicates()
        self._flag_non_training()
        self.message_post(body=_('Consolidation %s gathered %d training needs ().')
                          % (self.name, len(entries)))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.tna.consolidation',
            'res_id': self.id,
            'view_mode': 'form',
        }

    def _flag_duplicates(self):
        """Same employee + competency need appearing from multiple sources/modes ().

        The entry-level guard already blocks exact (employee, competency, delivery mode)
        triples within a cycle, so a consolidation duplicate here means the same
        employee+competency surfaced again via a different delivery mode or source.
        Flags are reset first so re-running consolidation re-evaluates from scratch.
        """
        candidates = self.entry_ids.filtered(lambda e: e.state in ('submitted', 'validated'))
        candidates.write({'is_duplicate': False, 'duplicate_of_id': False})
        seen = {}
        for entry in candidates:
            if not entry.employee_id or not entry.competency_id:
                continue
            key = (entry.employee_id.id, entry.competency_id.id)
            if key in seen:
                entry.write({
                    'is_duplicate': True,
                    'duplicate_of_id': seen[key].id,
                })
            else:
                seen[key] = entry

    def _flag_non_training(self):
        """Auto-suggest exclusion_type for needs that look like process/system/structural
        items (no employee, no competency, no proposed program)."""
        for entry in self.entry_ids.filtered(lambda e: e.state in ('submitted', 'validated')):
            if not entry.exclusion_type and not entry.employee_id and not entry.proposed_program:
                entry.write({'exclusion_type': 'process'})

    def action_compute_priority(self):
        """Re-run the weighted scoring engine over all needs ()."""
        self.ensure_one()
        for entry in self.entry_ids.filtered(lambda e: e.state != 'excluded'):
            entry.priority_score = entry._get_weighted_priority_score()
        self.message_post(body=_('Priority scores recomputed for consolidation %s ().')
                          % self.name)

    # ── Approval chain with segregation of duties () ────────────────
    def _check_segregation(self):
        """Validator != Reviewer != Endorser != Approver ()."""
        self.ensure_one()
        users = [self.validator_id.id, self.reviewer_id.id, self.endorser_id.id, self.approver_id.id]
        present = [u for u in users if u]
        if len(present) != len(set(present)):
            raise ValidationError(_(
                'Segregation of Duties Violation (): Validator, Reviewer, Endorser and '
                'Approver must all be different individuals.'))

    def _log_approval_step(self, state_from, state_to, comment=''):
        self.env['eds.approval.history'].create({
            'consolidation_id': self.id,
            'state_from': state_from,
            'state_to': state_to,
            'comment': comment or _('Moved %s -> %s') % (state_from, state_to),
        })

    def _require_manager(self):
        """Higher approval steps require at least the L&D Manager authority ()."""
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This approval step requires L&D Manager authority ().'))

    def action_submit_ppdd(self):
        """Draft -> PPDD Validation (starts the approval chain, )."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft consolidations can be submitted to PPDD validation.'))
            if not rec.entry_ids:
                raise UserError(_('Consolidate the training needs before submitting for approval.'))
            rec.validator_id = rec.validator_id or self.env.user.id
            rec._check_segregation()
            rec.state = 'ppdd_validation'
            rec._log_approval_step('draft', 'ppdd_validation')
            rec.message_post(body=_('Consolidation %s submitted to PPDD Validation.') % rec.name)

    def action_validate_ppdd(self):
        """PPDD Validation -> Director PPDD Review."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'ppdd_validation':
                raise UserError(_('Only consolidations under PPDD validation can move to Director review.'))
            rec.validator_id = rec.validator_id or self.env.user.id
            rec.reviewer_id = rec.reviewer_id or self.env.user.id
            rec._check_segregation()
            rec.state = 'director_review'
            rec._log_approval_step('ppdd_validation', 'director_review')
            rec.message_post(body=_('Consolidation %s validated by PPDD, sent to Director PPDD review.')
                             % rec.name)

    def action_director_review(self):
        """Director PPDD Review -> CPCO Endorsement."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'director_review':
                raise UserError(_('Only consolidations under Director review can be endorsed by CPCO.'))
            rec.reviewer_id = rec.reviewer_id or self.env.user.id
            rec.endorser_id = rec.endorser_id or self.env.user.id
            rec._check_segregation()
            rec.state = 'cpco_endorsement'
            rec._log_approval_step('director_review', 'cpco_endorsement')
            rec.message_post(body=_('Consolidation %s reviewed by Director PPDD, sent to CPCO endorsement.')
                             % rec.name)

    def action_cpco_endorsement(self):
        """CPCO Endorsement -> SMC Approval."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'cpco_endorsement':
                raise UserError(_('Only CPCO-endorsed consolidations can move to SMC approval.'))
            rec.endorser_id = rec.endorser_id or self.env.user.id
            rec.approver_id = rec.approver_id or self.env.user.id
            rec._check_segregation()
            rec.state = 'smc_approval'
            rec._log_approval_step('cpco_endorsement', 'smc_approval')
            rec.message_post(body=_('Consolidation %s endorsed by CPCO, submitted to SMC for final approval.')
                             % rec.name)

    def action_smc_approve(self):
        """SMC Approval -> Approved (/010)."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'smc_approval':
                raise UserError(_('Only consolidations under SMC approval can be approved.'))
            rec.approver_id = rec.approver_id or self.env.user.id
            rec._check_segregation()
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            for entry in rec.entry_ids.filtered(lambda e: e.state in ('submitted', 'validated') and not e.is_duplicate):
                entry.write({'state': 'approved'})
            rec._log_approval_step('smc_approval', 'approved', _('Final approval by SMC'))
            rec.message_post(body=_('Consolidation %s approved by SMC. Needs are locked for curriculum planning.')
                             % rec.name)
            self._maybe_approve_cycle(rec)

    def _maybe_approve_cycle(self, consolidation):
        """When all consolidations of a cycle are SMC-approved, approve the cycle too."""
        cycle = consolidation.cycle_id
        if cycle.state == 'under_approval' and cycle.consolidation_ids:
            if all(c.state == 'approved' for c in cycle.consolidation_ids):
                cycle.action_approve()

    def action_lock(self):
        """Approved -> Locked (): register is final; edits need a change request."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'approved':
                raise UserError(_('Only approved consolidations can be locked.'))
            rec.state = 'locked'
            rec._log_approval_step('approved', 'locked', _('Register locked'))
            rec.message_post(body=_('Consolidation %s locked. Further changes require a documented change request.')
                             % rec.name)

    def action_unlock(self):
        """Locked -> Approved (admin only, documented change request)."""
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('Only EDS Administrators can unlock a locked consolidation ().'))
        self.state = 'approved'
        self._log_approval_step('locked', 'approved', _('Unlocked with documented change request'))
        self.message_post(body=_('Consolidation %s unlocked with a documented change request.') % self.name)
