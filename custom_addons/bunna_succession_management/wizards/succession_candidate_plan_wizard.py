# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SuccessionCandidatePlanWizard(models.TransientModel):
    """
    Dynamic Assessment Plan Setup Wizard for Succession Candidates.
    Configures Succession Competency Assessment evaluators (Manager, Self, SPMC)
    and allows entering/adjusting weights and exemptions for all synced assessment components.
    """
    _name = 'succession.candidate.plan.wizard'
    _description = 'Configure Succession Assessment Plan & Evaluators'

    candidate_id = fields.Many2one('succession.candidate', string='Succession Candidate', required=True, readonly=True, index=True)
    employee_id = fields.Many2one(related='candidate_id.employee_id', string='Candidate (Employee)', readonly=True, index=True)
    critical_position_id = fields.Many2one(
        related='candidate_id.critical_position_id', string='Target Critical Position', readonly=True, index=True)

    def name_get(self):
        result = []
        for rec in self:
            emp_name = rec.employee_id.name or _('Candidate')
            result.append((rec.id, _('Configure Assessment Plan & Evaluators: %s') % emp_name))
        return result

    # =========================================================================
    # PART 1: Succession Competency Assessment (Evaluators)
    # =========================================================================
    assessment_scope = fields.Selection([
        ('manager_only', 'Manager Evaluation Only'),
        ('manager_spmc', 'Manager + SPMC Committee Evaluation'),
        ('custom', 'Custom Evaluator Selection'),
    ], string='Competency Evaluation Scope', default='manager_only')

    plan_include_manager = fields.Boolean(
        string='Manager Evaluation', default=True,
        help='Include direct manager evaluation on role competencies.')
    plan_include_self = fields.Boolean(
        string='Candidate Self-Assessment', default=False,
        help='Self-assessment is disabled.')
    plan_include_spmc = fields.Boolean(
        string='SPMC Committee Evaluation', default=False,
        help='Include executive committee deliberation and rating.')
    spmc_assessor_ids = fields.Many2many(
        'res.users',
        'succession_cand_plan_wiz_spmc_user_rel',
        'wizard_id',
        'user_id',
        string='Assigned SPMC Assessors',
        domain=lambda self: self._domain_spmc_users(),
        help='Designated SPMC Committee Members who will evaluate this candidate separately.')

    def _domain_spmc_users(self):
        group = self.env.ref('bunna_succession_management.group_succession_spmc', raise_if_not_found=False)
        return [('all_group_ids', 'in', [group.id])] if group else []

    competency_formula_notice = fields.Char(
        string='Calculation Method', compute='_compute_formula_notice')

    # =========================================================================
    # PART 2: Dynamic Assessment Components & Weights
    # =========================================================================
    line_ids = fields.One2many(
        'succession.candidate.plan.wizard.line', 'wizard_id',
        string='Assessment Components & Weights')

    plan_total_weight = fields.Float(
        string='Total Configured Weight (%)', compute='_compute_plan_total_weight')

    @api.depends('line_ids.weight', 'line_ids.waived')
    def _compute_plan_total_weight(self):
        for rec in self:
            active_lines = rec.line_ids.filtered(lambda l: not l.waived)
            rec.plan_total_weight = round(sum(active_lines.mapped('weight')), 2)

    @api.depends('plan_include_manager', 'plan_include_spmc', 'spmc_assessor_ids')
    def _compute_formula_notice(self):
        for rec in self:
            evaluators = []
            if rec.plan_include_manager:
                evaluators.append('Manager')
            if rec.plan_include_spmc:
                if rec.spmc_assessor_ids:
                    evaluators.append(f'SPMC Committee ({len(rec.spmc_assessor_ids)} Assessors - separate submissions)')
                else:
                    evaluators.append('SPMC Committee')

            if not evaluators:
                rec.competency_formula_notice = "Warning: Select at least one evaluator."
            elif len(evaluators) == 1:
                rec.competency_formula_notice = f"Evaluation Method: 100% {evaluators[0]} Score"
            else:
                pct = round(100.0 / len(evaluators), 1)
                rec.competency_formula_notice = f"Evaluation Method: Equal Average across {', '.join(evaluators)} ({pct}% each)"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        cand_id = self.env.context.get('default_candidate_id') or self.env.context.get('active_id')
        if cand_id:
            cand = self.env['succession.candidate'].browse(cand_id)
            if cand.state == 'draft':
                raise UserError(_(
                    'Candidate nomination must be completed first! Please click "Nominate Candidate" '
                    'before configuring the assessment plan.'
                ))
            cand._ensure_assessment_results()
            cand.invalidate_recordset(['assessment_result_ids'])
            res['candidate_id'] = cand.id
            res['assessment_scope'] = cand.assessment_scope or 'manager_only'
            res['plan_include_manager'] = cand.plan_include_manager
            res['plan_include_self'] = False  # Self-assessment disabled
            res['plan_include_spmc'] = cand.plan_include_spmc
            res['spmc_assessor_ids'] = [(6, 0, cand.spmc_assessor_ids.ids)]

            eval_map = dict(self.env['succession.assessment.component']._fields.get('evaluation_type', self.env['succession.assessment.component']._fields['source']).selection or [])
            lines_data = []
            for r in cand.assessment_result_ids:
                etype = getattr(r.component_id, 'evaluation_type', r.component_id.source)
                lines_data.append((0, 0, {
                    'result_id': r.id,
                    'component_id': r.component_id.id,
                    'component_name': r.component_id.name,
                    'component_source': r.component_id.source,
                    'source_display': eval_map.get(etype, r.component_id.name),
                    'weight': 0.0 if r.waived else (r.weight or r.component_id.weight or 0.0),
                    'max_score': r.max_score or r.component_id.max_score or 100.0,
                    'waived': r.waived,
                    'waiver_reason': r.waiver_reason or '',
                    'waivable': r.component_id.waivable,
                }))
            res['line_ids'] = lines_data
        return res

    @api.onchange('assessment_scope')
    def _onchange_assessment_scope(self):
        scope = self.assessment_scope
        if not scope or scope == 'custom':
            return
        if scope == 'manager_only':
            self.plan_include_manager = True
            self.plan_include_self = False
            self.plan_include_spmc = False
        elif scope == 'manager_spmc':
            self.plan_include_manager = True
            self.plan_include_self = False
            self.plan_include_spmc = True

    @api.onchange('plan_include_manager', 'plan_include_spmc')
    def _onchange_competency_pillars(self):
        if self.plan_include_manager and not self.plan_include_spmc:
            new_scope = 'manager_only'
        elif self.plan_include_manager and self.plan_include_spmc:
            new_scope = 'manager_spmc'
        else:
            new_scope = 'custom'
        if self.assessment_scope != new_scope:
            self.assessment_scope = new_scope

    def action_auto_balance_weights(self):
        """
        Auto-balance weights: waived components = 0%, 
        remaining active components redistribute to sum to 100%.
        Competency Assessment gets the residual weight.
        """
        self.ensure_one()
        # Step 1: Zero out all waived lines
        for line in self.line_ids:
            if line.waived:
                line.weight = 0.0

        # Step 2: Get active (non-waived) non-competency lines
        comp_lines = self.line_ids.filtered(
            lambda l: l.component_source == 'competency_eval' and not l.waived)
        other_active = self.line_ids.filtered(
            lambda l: l.component_source != 'competency_eval' and not l.waived)

        # Step 3: Sum weights of other active lines
        other_w = round(sum(other_active.mapped('weight')), 2)

        if other_w > 100.0:
            raise UserError(_(
                "Other active components already sum to %.2f%%, which exceeds 100%%.\n"
                "Please reduce weights of other active components first."
            ) % other_w)

        # Step 4: Assign residual to competency assessment
        if comp_lines:
            residual = max(round(100.0 - other_w, 2), 0.0)
            comp_lines[0].weight = residual

        return {
            'type': 'ir.actions.act_window',
            'name': _('Configure Assessment Plan & Evaluators: %s') % (self.employee_id.name or ''),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_apply_plan(self):
        self.ensure_one()
        cand = self.candidate_id
        if cand.state == 'draft':
            raise UserError(_(
                'Candidate nomination must be completed first! Please click "Nominate Candidate" '
                'before configuring the assessment plan.'
            ))
        if cand.assessment_plan_locked:
            raise UserError(_("The assessment plan is locked and cannot be modified."))

        # Enforce validations
        if not (self.plan_include_manager or self.plan_include_spmc):
            raise UserError(_("At least one evaluator (Manager or SPMC Committee) must be selected for Succession Competency Assessment."))

        if self.plan_include_spmc and not self.spmc_assessor_ids:
            raise UserError(_(
                "SPMC Committee Evaluation is enabled, but no Designated SPMC Committee Assessors have been assigned.\n\n"
                "Please assign at least one SPMC Committee Member under 'Designated SPMC Committee Assessors'."
            ))

        # Check waiver reasons if required
        cfg = self.env['succession.assessment.config'].get_config()
        for line in self.line_ids:
            if line.waived and cfg.waiver_reason_required and not (line.waiver_reason or '').strip():
                raise UserError(_(
                    "%s is marked as Not Applicable (Exempt). A mandatory justification is required."
                ) % line.component_name)

        # Validate total weight of active components = 100%
        active_weight = round(sum(
            l.weight for l in self.line_ids if not l.waived
        ), 2)
        if active_weight != 100.0:
            raise UserError(_(
                "Total weight of active (non-N/A) components is %.2f%%. "
                "It must equal exactly 100%%. "
                "Click Auto-Balance to 100%% or adjust weights manually."
            ) % active_weight)

        # Write updates to candidate result lines
        for line in self.line_ids:
            if line.result_id:
                vals = {
                    'weight': line.weight if not line.waived else 0.0,
                    'max_score': line.max_score,
                    'waived': line.waived,
                    'waiver_reason': line.waiver_reason if line.waived else False,
                }
                if line.waived:
                    vals['score'] = 0.0
                    vals['score_entered'] = False
                line.result_id.write(vals)

        # Sync legacy compatibility fields on candidate
        pms_line = self.line_ids.filtered(lambda l: l.component_source == 'pms')
        exam_line = self.line_ids.filtered(lambda l: 'exam' in (l.component_name or '').lower())
        cand_vals = {
            'assessment_scope': self.assessment_scope,
            'plan_include_manager': self.plan_include_manager,
            'plan_include_self': False,  # Self-assessment disabled
            'plan_include_spmc': self.plan_include_spmc,
            'spmc_assessor_ids': [(6, 0, self.spmc_assessor_ids.ids)],
            'spmc_assigned_user_id': self.spmc_assessor_ids[0].id if self.spmc_assessor_ids else False,
            'assessment_plan_defined_by_id': self.env.user.id,
            'assessment_plan_defined_date': fields.Datetime.now(),
        }
        if pms_line:
            cand_vals['plan_include_pms'] = not pms_line[0].waived
            cand_vals['weight_pms'] = pms_line[0].weight if not pms_line[0].waived else 0.0
            cand_vals['pms_exemption_reason'] = pms_line[0].waiver_reason if pms_line[0].waived else False
        if exam_line:
            cand_vals['plan_include_exam'] = not exam_line[0].waived
            cand_vals['weight_exam'] = exam_line[0].weight if not exam_line[0].waived else 0.0
            cand_vals['exam_exemption_reason'] = exam_line[0].waiver_reason if exam_line[0].waived else False

        cand.with_context(skip_apply_scope=True).write(cand_vals)
        cand._refresh_assessment_scores()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Plan Configured'),
                'message': _('Assessment plan and evaluators successfully updated for %s.') % (cand.employee_id.name or cand.display_name),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }


class SuccessionCandidatePlanWizardLine(models.TransientModel):
    _name = 'succession.candidate.plan.wizard.line'
    _description = 'Plan Wizard Component Line'

    wizard_id = fields.Many2one('succession.candidate.plan.wizard', required=True, ondelete='cascade', index=True)
    result_id = fields.Many2one('succession.candidate.assessment.result', string='Candidate Result', index=True)
    component_id = fields.Many2one('succession.assessment.component', string='Component', index=True)
    component_name = fields.Char(
        string='Assessment Component',
        compute='_compute_component_info', store=True, readonly=True)
    component_source = fields.Selection([
        ('manual', 'Assessment Test / Examination'),
        ('pms', 'Annual PMS Appraisal'),
        ('competency_eval', 'Role Competencies Assessment (Multi-Rater)'),
    ], string='Source', compute='_compute_component_info', store=True, readonly=True)
    source_display = fields.Char(
        string='Evaluation Method',
        compute='_compute_component_info', store=True, readonly=True)
    waivable = fields.Boolean(string='Waivable', default=True)
    waived = fields.Boolean(string='Not Applicable (Exempt)')
    waiver_reason = fields.Char(string='Exemption Justification')
    weight = fields.Float(string='Weight (%)', default=0.0)
    max_score = fields.Float(string='Max Score', default=100.0)

    @api.depends('component_id', 'result_id', 'result_id.component_id')
    def _compute_component_info(self):
        source_labels = {
            'manual': 'Assessment Test / Examination',
            'pms': 'Annual PMS Appraisal',
            'competency_eval': 'Role Competencies Assessment (Multi-Rater)',
        }
        for line in self:
            comp = line.component_id or (line.result_id.component_id if line.result_id else False)
            if comp:
                line.component_name = comp.name
                line.component_source = comp.source
                line.source_display = source_labels.get(comp.source, 'Manual Entry')
            else:
                line.component_name = line.component_name or ''
                line.component_source = line.component_source or 'manual'
                line.source_display = line.source_display or 'Manual Entry'

    @api.onchange('waived')
    def _onchange_waived(self):
        for line in self:
            if line.waived:
                # When marked N/A: zero out weight immediately
                line.weight = 0.0
            else:
                # When N/A removed: clear reason
                line.waiver_reason = False

    @api.constrains('waived', 'waiver_reason')
    def _check_waiver_reason_required(self):
        cfg = self.env['succession.assessment.config'].sudo().get_config()
        if not cfg.waiver_reason_required:
            return
        for line in self:
            if line.waived and not (line.waiver_reason or '').strip():
                raise ValidationError(_(
                    '"%s" is marked as Not Applicable (N/A). '
                    'A mandatory exemption justification is required.'
                ) % (line.component_name or 'Component'))
