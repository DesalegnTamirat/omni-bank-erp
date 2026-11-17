# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class SuccessionCandidateEvalLine(models.Model):
    """
    One assessment score line per competency required by the critical position.

    Lines are auto-created from the critical position's approved role-competency
    mapping when the candidate is nominated.  PPDD fills in score + evidence
    directly on the candidate form — no sessions, no separate configuration.
    """
    _name = 'succession.candidate.eval.line'
    _description = 'Candidate Assessment Score'
    _order = 'sequence, id'

    candidate_id = fields.Many2one(
        'succession.candidate', string='Candidate',
        required=True, ondelete='cascade', index=True,
    )

    # --- Competency reference (from the critical position's role mapping) ---
    competency_id = fields.Many2one(
        'competency.competency', string='Competency',
        required=True, ondelete='restrict', readonly=True,
    )
    competency_name = fields.Char(
        related='competency_id.name', string='Competency',
        store=True, readonly=True,
    )
    pillar = fields.Selection(
        related='competency_id.pillar', string='Pillar',
        store=True, readonly=True,
    )
    required_proficiency = fields.Selection([
        ('1', 'Level 1 – Basic'),
        ('2', 'Level 2 – Intermediate'),
        ('3', 'Level 3 – Advanced'),
        ('4', 'Level 4 – Expert'),
    ], string='Required Level', readonly=True,
    )
    weight = fields.Float(string='Weight', readonly=True, default=1.0)
    sequence = fields.Integer(default=10)

    # --- Plan Inclusions (Related from Candidate Plan) ---
    plan_include_manager = fields.Boolean(
        related='candidate_id.plan_include_manager', string='Include Manager', readonly=True)
    plan_include_self = fields.Boolean(
        related='candidate_id.plan_include_self', string='Include Self', readonly=True)
    plan_include_spmc = fields.Boolean(
        related='candidate_id.plan_include_spmc', string='Include SPMC', readonly=True)

    # --- Multi-Rater Evaluations ---
    # 1. Direct Manager Evaluation
    manager_score = fields.Selection([
        ('1', 'Level 1 – Basic'),
        ('2', 'Level 2 – Intermediate'),
        ('3', 'Level 3 – Advanced'),
        ('4', 'Level 4 – Expert'),
    ], string='Manager Rating')
    manager_eval_display = fields.Char(
        string='Manager Level', compute='_compute_eval_displays')
    manager_evidence = fields.Text(
        string='Manager Evidence / Observation',
        help='Manager observation justifying this rating.')

    # 2. Candidate Self-Assessment
    self_score = fields.Selection([
        ('1', 'Level 1 – Basic'),
        ('2', 'Level 2 – Intermediate'),
        ('3', 'Level 3 – Advanced'),
        ('4', 'Level 4 – Expert'),
    ], string='Self Rating')
    self_eval_display = fields.Char(
        string='Self Level', compute='_compute_eval_displays')
    self_evidence = fields.Text(
        string='Self Reflection / Notes',
        help='Candidate self-reflection on demonstrated competencies.')

    # 3. SPMC Executive Committee Evaluation
    spmc_score = fields.Selection([
        ('1', 'Level 1 – Basic'),
        ('2', 'Level 2 – Intermediate'),
        ('3', 'Level 3 – Advanced'),
        ('4', 'Level 4 – Expert'),
    ], string='SPMC Rating')
    spmc_eval_display = fields.Char(
        string='SPMC Level', compute='_compute_eval_displays')
    spmc_evidence = fields.Text(
        string='Note',
        help='Committee deliberation and consensus notes.')
    spmc_evidence_written_by_id = fields.Many2one(
        'res.users', string='Note Written By', readonly=True, copy=False)
    spmc_evidence_written_date = fields.Datetime(
        string='Note Written On', readonly=True, copy=False)

    # Current User Context & Role-Based Permissions
    current_user_role = fields.Char(
        string='Current User Role', compute='_compute_current_user_role')
    current_user_score = fields.Selection([
        ('1', 'Level 1 – Basic'),
        ('2', 'Level 2 – Intermediate'),
        ('3', 'Level 3 – Advanced'),
        ('4', 'Level 4 – Expert'),
    ], string='Current User Rating', compute='_compute_current_user_role')
    can_edit_manager = fields.Boolean(
        string='Can Edit Manager Rating', compute='_compute_current_user_role')
    can_edit_spmc = fields.Boolean(
        string='Can Edit SPMC Rating', compute='_compute_current_user_role')
    can_edit_self = fields.Boolean(
        string='Can Edit Self Rating', compute='_compute_current_user_role')
    can_edit_current_user = fields.Boolean(
        string='Can Edit Current User Rating', compute='_compute_current_user_role')
    is_manager_rater = fields.Boolean(compute='_compute_current_user_role')
    is_spmc_rater = fields.Boolean(compute='_compute_current_user_role')
    is_self_rater = fields.Boolean(compute='_compute_current_user_role')

    @api.depends_context('uid')
    def _compute_current_user_role(self):
        user = self.env.user
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or self.env.is_superuser()
        is_spmc_group = user.has_group('bunna_succession_management.group_succession_spmc')
        is_ppdd = user.has_group('bunna_succession_management.group_succession_ppdd')

        for rec in self:
            cand = rec.candidate_id
            emp = cand.employee_id if cand else False
            is_self = bool(emp and emp.user_id and emp.user_id.id == user.id)
            is_coach_or_mgr = bool(emp and (
                (emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == user.id) or
                (emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == user.id) or
                (cand and cand.parent_id and cand.parent_id.user_id and cand.parent_id.user_id.id == user.id) or
                (cand and cand.coach_id and cand.coach_id.user_id and cand.coach_id.user_id.id == user.id)
            ))
            is_spmc = user.has_group('bunna_succession_management.group_succession_spmc')
            is_assigned_spmc = bool(cand and cand.spmc_assigned_user_id and cand.spmc_assigned_user_id.id == user.id)
            is_spmc = bool(is_spmc_group or is_assigned_spmc)

            rec.can_edit_self = bool(((is_self and not cand.self_evaluation_submitted) or is_admin))
            rec.can_edit_manager = bool(((is_coach_or_mgr and not cand.manager_evaluation_submitted) or is_admin or (is_ppdd and not is_spmc)))
            rec.can_edit_spmc = bool(((is_spmc and not cand.spmc_evaluation_submitted) or is_admin))

            if is_self and rec.plan_include_self:
                rec.current_user_role = 'self'
                rec.current_user_score = rec.self_score
                rec.is_self_rater = True
                rec.is_manager_rater = False
                rec.is_spmc_rater = False
                rec.can_edit_current_user = rec.can_edit_self
            elif is_spmc and rec.plan_include_spmc and not is_coach_or_mgr:
                rec.current_user_role = 'spmc'
                rec.current_user_score = rec.spmc_score
                rec.is_spmc_rater = True
                rec.is_manager_rater = False
                rec.is_self_rater = False
                rec.can_edit_current_user = rec.can_edit_spmc
            elif rec.plan_include_manager and (is_coach_or_mgr or is_ppdd or is_admin):
                rec.current_user_role = 'manager'
                rec.current_user_score = rec.manager_score
                rec.is_manager_rater = True
                rec.is_spmc_rater = False
                rec.is_self_rater = False
                rec.can_edit_current_user = rec.can_edit_manager
            elif rec.plan_include_spmc:
                rec.current_user_role = 'spmc'
                rec.current_user_score = rec.spmc_score
                rec.is_spmc_rater = True
                rec.is_manager_rater = False
                rec.is_self_rater = False
                rec.can_edit_current_user = rec.can_edit_spmc
            else:
                rec.current_user_role = 'general'
                rec.current_user_score = rec.score
                rec.is_manager_rater = False
                rec.is_spmc_rater = False
                rec.is_self_rater = False
                rec.can_edit_current_user = bool(rec.can_edit_manager or rec.can_edit_spmc or rec.can_edit_self)

    # Effective / Consensus Score (Determined from active raters)
    score = fields.Selection([
        ('1', 'Level 1 – Basic'),
        ('2', 'Level 2 – Intermediate'),
        ('3', 'Level 3 – Advanced'),
        ('4', 'Level 4 – Expert'),
    ], string='Evaluated Level', compute='_compute_score_consensus', store=True, readonly=False)
    eval_display = fields.Char(
        string='Evaluated Level', compute='_compute_eval_displays',
    )
    evidence = fields.Text(
        string='Evidence / Observation', compute='_compute_consolidated_evidence', store=True, readonly=False,
        help='Consolidated notes from active evaluators justifying this rating.',
    )

    # --- Behavioral Guidance (Image 2 Indicators) ---
    competency_definition = fields.Text(
        related='competency_id.definition', string='Competency Definition', readonly=True)
    indicator_level_1 = fields.Text(
        string='Level 1 (Basic) Indicator', compute='_compute_level_indicators')
    indicator_level_2 = fields.Text(
        string='Level 2 (Intermediate) Indicator', compute='_compute_level_indicators')
    indicator_level_3 = fields.Text(
        string='Level 3 (Advanced) Indicator', compute='_compute_level_indicators')
    indicator_level_4 = fields.Text(
        string='Level 4 (Expert) Indicator', compute='_compute_level_indicators')

    # --- HR Visibility & Gap Analysis ---
    gap_score = fields.Integer(
        string='Gap Score', compute='_compute_gap_and_status', store=True)
    gap_display = fields.Char(
        string='Variance (+/-)', compute='_compute_gap_and_status', store=True)
    achievement_status = fields.Selection([
        ('exceeds', 'Exceeds'),
        ('meets', 'Meets'),
        ('below', 'Gap / Below Required'),
    ], string='Status', compute='_compute_gap_and_status', store=True)

    # --- Computed helpers ---
    meets_requirement = fields.Boolean(
        string='Meets Requirement',
        compute='_compute_meets_requirement', store=True,
        help='True when score >= required proficiency level.',
    )
    is_scored = fields.Boolean(
        compute='_compute_is_scored',
        help='True when a score has been selected.',
    )

    @api.depends('competency_id')
    def _compute_level_indicators(self):
        matrix_config = self.env['competency.matrix.config'].sudo().get_active_config()
        for rec in self:
            if rec.competency_id:
                levels = self.env['competency.proficiency.level'].search([
                    ('competency_id', '=', rec.competency_id.id)
                ])
                l_map = {l.level: l.behavioral_indicators for l in levels if l.behavioral_indicators}
                rec.indicator_level_1 = l_map.get('1') or (getattr(matrix_config, 'tech_indicator_level_1', False) if rec.competency_id.pillar == 'technical' else 'Level 1 (Basic) behavioral indicators.')
                rec.indicator_level_2 = l_map.get('2') or (getattr(matrix_config, 'tech_indicator_level_2', False) if rec.competency_id.pillar == 'technical' else 'Level 2 (Intermediate) behavioral indicators.')
                rec.indicator_level_3 = l_map.get('3') or (getattr(matrix_config, 'tech_indicator_level_3', False) if rec.competency_id.pillar == 'technical' else 'Level 3 (Advanced) behavioral indicators.')
                rec.indicator_level_4 = l_map.get('4') or (getattr(matrix_config, 'tech_indicator_level_4', False) if rec.competency_id.pillar == 'technical' else 'Level 4 (Expert) behavioral indicators.')
            else:
                rec.indicator_level_1 = False
                rec.indicator_level_2 = False
                rec.indicator_level_3 = False
                rec.indicator_level_4 = False

    @api.depends('score', 'required_proficiency')
    def _compute_gap_and_status(self):
        for rec in self:
            if rec.score and rec.required_proficiency:
                try:
                    gap = int(rec.score) - int(rec.required_proficiency)
                    rec.gap_score = gap
                    if gap > 0:
                        rec.gap_display = f"+{gap}"
                        rec.achievement_status = 'exceeds'
                    elif gap == 0:
                        rec.gap_display = "0 (Match)"
                        rec.achievement_status = 'meets'
                    else:
                        rec.gap_display = f"{gap}"
                        rec.achievement_status = 'below'
                except (ValueError, TypeError):
                    rec.gap_score = 0
                    rec.gap_display = "—"
                    rec.achievement_status = False
            else:
                rec.gap_score = 0
                rec.gap_display = "—"
                rec.achievement_status = False

    @api.depends('score', 'required_proficiency')
    def _compute_meets_requirement(self):
        for rec in self:
            if rec.score and rec.required_proficiency:
                rec.meets_requirement = int(rec.score) >= int(rec.required_proficiency)
            else:
                rec.meets_requirement = False

    @api.depends('manager_score', 'self_score', 'spmc_score',
                 'candidate_id.plan_include_manager',
                 'candidate_id.plan_include_self',
                 'candidate_id.plan_include_spmc')
    def _compute_score_consensus(self):
        for rec in self:
            cand = rec.candidate_id
            active_scores = []
            if cand.plan_include_manager and rec.manager_score:
                active_scores.append(int(rec.manager_score))
            if cand.plan_include_self and rec.self_score:
                active_scores.append(int(rec.self_score))
            if cand.plan_include_spmc and rec.spmc_score:
                active_scores.append(int(rec.spmc_score))

            if active_scores:
                avg_val = round(sum(active_scores) / len(active_scores))
                avg_val = max(1, min(4, int(avg_val)))
                rec.score = str(avg_val)
            elif not rec.score:
                rec.score = False

    @api.depends('manager_score', 'self_score', 'spmc_score', 'score')
    def _compute_eval_displays(self):
        label_map = dict(self._fields['score'].selection)
        for rec in self:
            rec.manager_eval_display = label_map.get(rec.manager_score) or _('Pending')
            rec.self_eval_display = label_map.get(rec.self_score) or _('Pending')
            rec.spmc_eval_display = label_map.get(rec.spmc_score) or _('Pending')
            rec.eval_display = label_map.get(rec.score) or _('Pending Evaluation (Click to Rate)')

    @api.depends('manager_evidence', 'self_evidence', 'spmc_evidence',
                 'candidate_id.plan_include_manager',
                 'candidate_id.plan_include_self',
                 'candidate_id.plan_include_spmc')
    def _compute_consolidated_evidence(self):
        for rec in self:
            cand = rec.candidate_id
            notes = []
            if cand.plan_include_manager and rec.manager_evidence:
                notes.append(f"Manager: {rec.manager_evidence.strip()}")
            if cand.plan_include_self and rec.self_evidence:
                notes.append(f"Self: {rec.self_evidence.strip()}")
            if cand.plan_include_spmc and rec.spmc_evidence:
                notes.append(f"SPMC: {rec.spmc_evidence.strip()}")
            if notes:
                rec.evidence = "\n".join(notes)
            elif not rec.evidence:
                rec.evidence = False

    score_points_display = fields.Char(
        string='Points Earned', compute='_compute_score_points_display',
        help='Points and percentage contribution towards the Succession Competency Assessment.')

    @api.depends('score', 'required_proficiency')
    def _compute_score_points_display(self):
        for rec in self:
            if not rec.score:
                rec.score_points_display = _("Pending")
            elif not rec.required_proficiency:
                rec.score_points_display = "—"
            else:
                try:
                    score_val = int(rec.score)
                    req_val = int(rec.required_proficiency)
                    if score_val >= req_val:
                        if score_val > req_val:
                            rec.score_points_display = _("100% (Exceeds Required)")
                        else:
                            rec.score_points_display = _("100% (Meets Required)")
                    else:
                        rec.score_points_display = _("0% (Below Required / Gap)")
                except (ValueError, TypeError):
                    rec.score_points_display = "—"

    @api.depends('score')
    def _compute_is_scored(self):
        for rec in self:
            rec.is_scored = bool(rec.score)

    candidate_assessment_done = fields.Boolean(
        related='candidate_id.assessment_done',
        string='Assessment Done',
        readonly=True,
    )
    is_last_competency = fields.Boolean(
        string='Is Final Competency',
        compute='_compute_is_last_competency',
    )
    is_first_competency = fields.Boolean(
        string='Is First Competency',
        compute='_compute_is_last_competency',
    )
    competency_progress_label = fields.Char(
        string='Progress Label',
        compute='_compute_is_last_competency',
    )

    def _compute_is_last_competency(self):
        for rec in self:
            rec_id = rec._origin.id if rec._origin else rec.id
            cand = rec.candidate_id or (rec._origin.candidate_id if rec._origin else False)
            if cand and cand.eval_line_ids:
                lines = cand.eval_line_ids.sorted(lambda l: (l.sequence, l.id or 0))
                line_ids = [l._origin.id if l._origin else l.id for l in lines]
                if rec_id in line_ids:
                    idx = line_ids.index(rec_id)
                    rec.is_last_competency = (idx == len(line_ids) - 1)
                    rec.is_first_competency = (idx == 0)
                    rec.competency_progress_label = _("Competency %s of %s") % (idx + 1, len(line_ids))
                    continue
            rec.is_last_competency = True
            rec.is_first_competency = True
            rec.competency_progress_label = ""

    def action_open_eval_modal(self):
        """Opens the interactive behavioral indicator rating dialog for this competency."""
        self.ensure_one()
        title = _('Rate Competency: %s') % (self.competency_id.name if self.competency_id else '')
        if self.candidate_id and self.candidate_id.eval_line_ids:
            lines = self.candidate_id.eval_line_ids.sorted(lambda l: (l.sequence, l.id))
            if self.id in lines.ids:
                idx = lines.ids.index(self.id) + 1
                title = _('Rate Competency (%s of %s): %s') % (
                    idx, len(lines), self.competency_id.name if self.competency_id else ''
                )
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'succession.candidate.eval.line',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('bunna_succession_management.view_succession_candidate_eval_line_modal_form').id, 'form')],
            'target': 'new',
            'context': self.env.context,
        }

    def _action_select_level(self, level):
        self.ensure_one()
        cand = self.candidate_id
        user = self.env.user
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or self.env.is_superuser()
        is_spmc = user.has_group('bunna_succession_management.group_succession_spmc')
        emp = cand.employee_id if cand else False
        is_self = bool(emp and emp.user_id and emp.user_id.id == user.id)
        is_coach_or_mgr = bool(emp and (
            (emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == user.id) or
            (emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == user.id) or
            (cand and cand.parent_id and cand.parent_id.user_id and cand.parent_id.user_id.id == user.id) or
            (cand and cand.coach_id and cand.coach_id.user_id and cand.coach_id.user_id.id == user.id)
        ))
        is_spmc = user.has_group('bunna_succession_management.group_succession_spmc')
        is_assigned_spmc = bool(cand and cand.spmc_assigned_user_id and cand.spmc_assigned_user_id.id == user.id)
        is_authorized_spmc = bool(is_spmc or is_assigned_spmc)

        vals = {}
        if is_self and self.plan_include_self:
            if cand and cand.self_evaluation_submitted and not is_admin:
                raise UserError(_("You have already submitted your self-assessment. It cannot be modified."))
            vals['self_score'] = str(level)
        elif is_authorized_spmc and self.plan_include_spmc and not is_coach_or_mgr:
            if cand and cand.spmc_evaluation_submitted and not is_admin:
                raise UserError(_("You have already submitted your SPMC evaluation. It cannot be modified."))
            vals['spmc_score'] = str(level)
            if cand and is_spmc and not cand.spmc_assigned_user_id:
                cand.sudo().write({'spmc_assigned_user_id': user.id})
        elif self.plan_include_manager and (is_coach_or_mgr or not is_authorized_spmc or is_admin):
            if cand and cand.manager_evaluation_submitted and not is_admin:
                raise UserError(_("You have already submitted your manager evaluation. It cannot be modified."))
            vals['manager_score'] = str(level)
        elif self.plan_include_spmc:
            if cand and cand.spmc_evaluation_submitted and not is_admin:
                raise UserError(_("You have already submitted your SPMC evaluation. It cannot be modified."))
            vals['spmc_score'] = str(level)
        else:
            vals['score'] = str(level)

        self.sudo().write(vals)

        if cand:
            cand.sudo()._compute_competency_eval_score()
            cand.sudo()._compute_self_assessment_score()
            cand.sudo()._compute_spmc_score()
            cand.sudo()._compute_succession_competency_score()
            cand.sudo()._refresh_assessment_scores()
        return self.action_open_eval_modal()

    def action_select_level_1(self):
        return self._action_select_level(1)

    def action_select_level_2(self):
        return self._action_select_level(2)

    def action_select_level_3(self):
        return self._action_select_level(3)

    def action_select_level_4(self):
        return self._action_select_level(4)

    def action_save_and_close(self):
        self.ensure_one()
        cand = self.candidate_id
        if cand:
            cand.sudo()._compute_competency_eval_score()
            cand.sudo()._compute_self_assessment_score()
            cand.sudo()._compute_spmc_score()
            cand.sudo()._compute_succession_competency_score()
            cand.sudo()._refresh_assessment_scores()
        return {'type': 'ir.actions.act_window_close'}

    def action_save_and_prev(self):
        """Navigate to the previous competency without requiring a score."""
        self.ensure_one()
        cand = self.candidate_id
        if cand:
            cand.sudo()._refresh_assessment_scores()
            lines = cand.eval_line_ids.sorted(lambda l: (l.sequence, l.id))
            line_ids = lines.ids
            if self.id in line_ids:
                idx = line_ids.index(self.id)
                if idx > 0:
                    prev_line = lines[idx - 1]
                    return prev_line.action_open_eval_modal()
        return {'type': 'ir.actions.act_window_close'}

    def action_save_and_next(self):
        self.ensure_one()
        cand = self.candidate_id
        user = self.env.user
        emp = cand.employee_id if cand else False
        is_self = bool(emp and emp.user_id and emp.user_id.id == user.id)
        is_coach_or_mgr = bool(emp and (
            (emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == user.id) or
            (emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == user.id) or
            (cand and cand.parent_id and cand.parent_id.user_id and cand.parent_id.user_id.id == user.id) or
            (cand and cand.coach_id and cand.coach_id.user_id and cand.coach_id.user_id.id == user.id)
        ))
        is_spmc = user.has_group('bunna_succession_management.group_succession_spmc')
        is_assigned_spmc = bool(cand and cand.spmc_assigned_user_id and cand.spmc_assigned_user_id.id == user.id)
        is_authorized_spmc = bool(is_spmc or is_assigned_spmc)

        has_score = False
        if is_self and self.plan_include_self:
            has_score = bool(self.self_score)
        elif is_authorized_spmc and self.plan_include_spmc and not is_coach_or_mgr:
            has_score = bool(self.spmc_score)
        elif self.plan_include_manager and (is_coach_or_mgr or not is_authorized_spmc):
            has_score = bool(self.manager_score)
        else:
            has_score = bool(self.score or self.manager_score or self.spmc_score or self.self_score)

        if not has_score:
            raise UserError(_('Please select a rating level for "%s" before moving to the next competency.') % (self.competency_id.name or ''))

        if cand:
            cand.sudo()._compute_competency_eval_score()
            cand.sudo()._compute_self_assessment_score()
            cand.sudo()._compute_spmc_score()
            cand.sudo()._compute_succession_competency_score()
            cand.sudo()._refresh_assessment_scores()
            lines = cand.eval_line_ids.sorted(lambda l: (l.sequence, l.id))
            line_ids = lines.ids
            if self.id in line_ids:
                idx = line_ids.index(self.id)
                if idx + 1 < len(line_ids):
                    next_line = lines[idx + 1]
                    return next_line.action_open_eval_modal()
        return {'type': 'ir.actions.act_window_close'}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'score_entered' not in vals and vals.get('score'):
                vals['score_entered'] = True
                vals['entered_by_id'] = self.env.user.id
                vals['entered_date'] = fields.Datetime.now()
        return super().create(vals_list)

    def write(self, vals):
        user = self.env.user
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or self.env.is_superuser()
        is_ppdd = user.has_group('bunna_succession_management.group_succession_ppdd')
        if not (is_admin or is_ppdd or self.env.context.get('force_write')):
            if any(f in vals for f in ('self_score', 'self_evidence')):
                for rec in self:
                    cand = rec.candidate_id
                    emp = cand.employee_id if cand else False
                    is_cand = bool(emp and emp.user_id and emp.user_id.id == user.id)
                    if not is_cand:
                        raise AccessError(_("You can only modify self-assessment scores for your own candidate record."))
                    if cand and cand.self_evaluation_submitted:
                        raise UserError(_("Self-assessment has already been submitted and cannot be modified."))
            if any(f in vals for f in ('manager_score', 'manager_evidence')):
                for rec in self:
                    cand = rec.candidate_id
                    emp = cand.employee_id if cand else False
                    is_mgr = bool(emp and (
                        (emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == user.id) or
                        (emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == user.id) or
                        (cand and cand.parent_id and cand.parent_id.user_id and cand.parent_id.user_id.id == user.id) or
                        (cand and cand.coach_id and cand.coach_id.user_id and cand.coach_id.user_id.id == user.id)
                    ))
                    if not is_mgr:
                        raise AccessError(_("Only the direct manager or coach can modify manager ratings."))
                    if cand and cand.manager_evaluation_submitted:
                        raise UserError(_("Manager evaluation has already been submitted and cannot be modified."))
            if any(f in vals for f in ('spmc_score', 'spmc_evidence')):
                is_spmc = user.has_group('bunna_succession_management.group_succession_spmc')
                for rec in self:
                    cand = rec.candidate_id
                    is_assigned = bool(cand and cand.spmc_assigned_user_id and cand.spmc_assigned_user_id.id == user.id)
                    if not (is_spmc or is_assigned):
                        raise AccessError(_("Only SPMC committee members can modify committee scores."))
                    if cand and cand.spmc_evaluation_submitted:
                        raise UserError(_("SPMC evaluation has already been submitted and cannot be modified."))
        res = super().write(vals)
        if 'spmc_evidence' in vals and vals.get('spmc_evidence'):
            now = fields.Datetime.now()
            for rec in self:
                self.env.cr.execute(
                    "UPDATE succession_candidate_eval_line SET spmc_evidence_written_by_id = %s, spmc_evidence_written_date = %s WHERE id = %s",
                    (self.env.uid, now, rec.id)
                )
        score_fields = {'score', 'evidence', 'manager_score', 'manager_evidence',
                        'self_score', 'self_evidence', 'spmc_score', 'spmc_evidence'}
        if any(f in vals for f in score_fields):
            for cand in self.mapped('candidate_id'):
                cand.sudo()._compute_competency_eval_score()
                cand.sudo()._compute_self_assessment_score()
                cand.sudo()._compute_spmc_score()
                cand.sudo()._refresh_assessment_scores()
                try:
                    cand.sudo().action_compute_gap_analysis()
                except Exception:
                    pass
        return res

    def unlink(self):
        cands = self.mapped('candidate_id')
        res = super().unlink()
        for cand in cands:
            cand.sudo()._compute_competency_eval_score()
            cand.sudo()._compute_self_assessment_score()
            cand.sudo()._compute_spmc_score()
            cand.sudo()._refresh_assessment_scores()
            try:
                cand.sudo().action_compute_gap_analysis()
            except Exception:
                pass
        return res

    _candidate_competency_uniq = models.Constraint(
        'unique(candidate_id, competency_id)',
        'A score line for this competency already exists on this candidate.',
    )


class SuccessionAssessmentCriterion(models.Model):
    """
    Assessment Criterion Library (FR-CBIS-003, Module 3).
    Configurable behavioral and competency criteria with behavioral anchors
    used for standardized interview and candidate evaluations.
    """
    _name = 'succession.assessment.criterion'
    _description = 'Succession Assessment Criterion'
    _order = 'sequence, id'

    name = fields.Char(string='Criterion Name', required=True)
    criterion_type = fields.Selection([
        ('leadership', 'Leadership Competency'),
        ('decision', 'Decision Making & Problem Solving'),
        ('communication', 'Communication & Influence'),
        ('behavioral', 'Behavioral & Governance'),
        ('collaboration', 'Collaboration & Teamwork'),
        ('technical', 'Technical & Banking Expertise'),
    ], string='Criterion Type', default='leadership')
    sequence = fields.Integer(default=10)
    weight = fields.Float(string='Weight (%)', default=10.0)
    max_score = fields.Float(string='Max Score', default=5.0)
    description = fields.Text(string='Behavioral Anchors / Description')
    active = fields.Boolean(default=True)


# ==============================================================================
# CONFIGURABLE ASSESSMENT PROCESS (FR-SEL-002, FR-SEL-004, FR-TAR-003, FR-TAR-004)
# ==============================================================================

class SuccessionAssessmentConfig(models.Model):
    """
    Global assessment configuration (single record, like the Governance Policy).
    Defines which components make up the final assessment score (e.g. written
    exam, interview, PMS), their weights, the pass mark and the waiver rules.
    """
    _name = 'succession.assessment.config'
    _description = 'Succession Assessment Configuration'
    _inherit = ['mail.thread']

    name = fields.Char(default='Global Assessment Configuration', required=True)
    scoring_method = fields.Selection([
        ('average', 'Simple Average of Active Components'),
        ('weighted', 'Weighted Distribution (%)'),
    ], string='Scoring Method', default='average', required=True, tracking=True,
        help='Determines whether the final assessment score is computed as an equal average of active components or by custom configured weights.')
    pass_mark = fields.Float(
        string='Pass Mark (%)', default=65.0, tracking=True,
        help='Minimum final assessment score (0-100) for a candidate to pass.')
    enforce_pass_mark = fields.Boolean(
        string='Block Approval Below Pass Mark', default=True, tracking=True,
        help='When enabled, a candidate whose final score is below the pass mark '
             'cannot be approved as a successor.')
    enable_self_assessment = fields.Boolean(
        string='Enable Candidate Self-Assessment', default=True, tracking=True,
        help='When enabled, nominated candidates are required to perform a self-assessment on target role competencies.')
    waiver_mode = fields.Selection([
        ('redistribute', 'Redistribute weight to remaining components (Fair evaluation)'),
        ('zero', 'Count Not Applicable component as zero (No weight redistribution)'),
    ], string='When a Component is Not Applicable (N/A)', default='redistribute',
        required=True, tracking=True,
        help='Determines how the final score is calculated when a component does not apply (N/A) to a candidate.')
    waiver_reason_required = fields.Boolean(
        string='Require Justification for Not Applicable (N/A)', default=True, tracking=True,
        help='Enforce entering an approved justification when marking a component as Not Applicable (N/A).')
    component_ids = fields.One2many(
        'succession.assessment.component', 'config_id', string='Assessment Components')
    total_weight = fields.Float(
        string='Total Weight of Active Components (%)',
        compute='_compute_total_weight')

    # --- Governance Definitions & Rules ---
    policy_statement = fields.Html(
        string='Assessment Governance Policy',
        help='Organizational policy statement governing succession evaluations.')
    exam_guideline = fields.Text(
        string='Examination Definition & Guidelines',
        help='Technical and banking knowledge evaluation scope and rules.')
    interview_guideline = fields.Text(
        string='Interview Definition & Guidelines',
        help='Competency-based behavioral interview methodology and scoring rubric.')
    pms_guideline = fields.Text(
        string='PMS Integration Rules',
        help='Rules governing the inclusion of annual performance appraisals.')
    waiver_guideline = fields.Text(
        string='Not Applicable (N/A) Governance & Rules',
        help='Criteria and authority required to approve marking components as Not Applicable (N/A).')

    @api.model
    def get_config(self):
        cfg = self.env.ref('bunna_succession_management.assessment_config_default', raise_if_not_found=False)
        if not cfg or not cfg.exists():
            records = self.search([], order='id desc')
            for r in records:
                if r.component_ids:
                    cfg = r
                    break
            if not cfg and records:
                cfg = records[0]
        if not cfg:
            cfg = self.sudo().create({
                'name': 'Global Assessment Configuration',
                'scoring_method': 'average',
            })
        # Auto-create default components when the config record exists but
        # has no component_ids (happens when noupdate="1" skips data insertion
        # because the config was already created before the data file ran).
        if not cfg.component_ids:
            cfg.sudo()._ensure_default_components()
        return cfg

    def _ensure_default_components(self):
        """Create the 4 standard assessment components when the config has none.

        This is a self-healing fallback for the common deployment scenario where
        the config record exists in the DB before the XML data file is processed
        (noupdate="1" prevents re-insertion, leaving component_ids empty).
        """
        self.ensure_one()
        if self.component_ids:
            return  # already populated — nothing to do
        default_components = [
            {
                'config_id': self.id,
                'sequence': 10,
                'name': 'Written Exam',
                'evaluation_type': 'exam',
                'source': 'manual',
                'weight': 20.0,
                'max_score': 100.0,
                'mandatory': True,
                'waivable': True,
                'enabled': True,
                'active': True,
                'description': (
                    'Technical banking knowledge, regulatory frameworks, '
                    'risk management, and operational decision-making exam.'
                ),
            },
            {
                'config_id': self.id,
                'sequence': 20,
                'name': 'Interview Exam',
                'evaluation_type': 'interview',
                'source': 'manual',
                'weight': 20.0,
                'max_score': 100.0,
                'mandatory': True,
                'waivable': True,
                'enabled': True,
                'active': True,
                'description': (
                    'Structured competency-based panel interview evaluating '
                    'leadership behaviors, executive presence, and ethics.'
                ),
            },
            {
                'config_id': self.id,
                'sequence': 30,
                'name': 'Performance Appraisal (PMS)',
                'evaluation_type': 'pms',
                'source': 'pms',
                'weight': 20.0,
                'max_score': 100.0,
                'mandatory': False,
                'waivable': True,
                'enabled': True,
                'active': True,
                'description': (
                    'Audited annual Performance Management System (PMS) score '
                    'automatically fetched from the appraisal system.'
                ),
            },
            {
                'config_id': self.id,
                'sequence': 40,
                'name': 'Succession Competency Assessment',
                'evaluation_type': 'competency_eval',
                'source': 'competency_eval',
                'weight': 40.0,
                'max_score': 100.0,
                'mandatory': True,
                'waivable': False,
                'enabled': True,
                'active': True,
                'description': (
                    'Evaluates candidate against target role competencies via '
                    'Manager, Self, and SPMC multi-rater evaluation.'
                ),
            },
        ]
        self.env['succession.assessment.component'].sudo().with_context(
            install_mode=True
        ).create(default_components)
        self.invalidate_recordset(['component_ids'])

    @api.depends('component_ids.weight', 'component_ids.enabled')
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = sum(rec.component_ids.filtered('enabled').mapped('weight'))

    @api.constrains('pass_mark')
    def _check_config(self):
        for rec in self:
            if not 0.0 <= rec.pass_mark <= 100.0:
                raise ValidationError(_('The pass mark must be between 0 and 100.'))

    # ------------------------------------------------------------------
    # Bulk propagation to all nominated candidates
    # ------------------------------------------------------------------

    def action_sync_all_nominated_candidates(self):
        """Propagate assessment components to every nominated candidate.

        Called:
          - manually via the 'Propagate to All Candidates' button on the
            Assessment Configuration form
          - automatically after the config or any of its component_ids are
            saved (write hook below)
        """
        nominated = self.env['succession.candidate'].sudo().search([
            ('state', '=', 'nominated'),
        ])
        if not nominated:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Action Needed'),
                    'message': _('There are currently no nominated candidates to sync.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        success = 0
        failed = []
        for cand in nominated:
            try:
                cand.action_load_assessment_components()
                # Also ensure competency scorecard lines are populated
                try:
                    cand.action_populate_competency_eval_lines()
                except Exception:
                    pass
                success += 1
            except Exception as ex:
                failed.append('%s (%s)' % (cand.employee_id.name or str(cand.id), str(ex)))
        msg = _('%d nominated candidate(s) successfully synced with the assessment plan.') % success
        if failed:
            msg += _('\n\nFailed (%d): %s') % (len(failed), ', '.join(failed))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Plan Propagated'),
                'message': msg,
                'type': 'success' if not failed else 'warning',
                'sticky': bool(failed),
            },
        }

    def write(self, vals):
        res = super().write(vals)
        return res

class SuccessionAssessmentComponent(models.Model):
    """One configurable component of the assessment (Exam, Interview, PMS, Self-Assessment, SPMC...)."""
    _name = 'succession.assessment.component'
    _description = 'Succession Assessment Component'
    _order = 'sequence, id'

    config_id = fields.Many2one(
        'succession.assessment.config', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Component', required=True)
    evaluation_type = fields.Selection([
        ('exam', 'Written Examination'),
        ('interview', 'Interview Exam'),
        ('pms', 'PMS Appraisal'),
        ('competency_eval', 'Multi-Rater Evaluation'),
    ], string='Evaluation Type', default='exam', required=True)
    source = fields.Selection([
        ('manual', 'Manual Score Entry'),
        ('pms', 'PMS Integration'),
        ('competency_eval', 'Multi-Rater Matrix'),
    ], string='Integration Source', default='manual', required=True)
    weight = fields.Float(string='Weight (%)', default=0.0)
    max_score = fields.Float(string='Max Score', default=100.0)
    mandatory = fields.Boolean(
        string='Mandatory', default=True,
        help='A mandatory component must have a result (or be waived) before the '
             'candidate can be marked as Assessed. A non-mandatory component with '
             'no result is simply left out of the calculation.')
    waivable = fields.Boolean(
        string='Can be Not Applicable (N/A)', default=True,
        help='Authorized evaluators may mark this component as Not Applicable (N/A) for a candidate with documented justification.')
    active = fields.Boolean(string='Active', default=True)
    enabled = fields.Boolean(string='Enabled', default=True)

    @api.onchange('enabled')
    def _onchange_enabled(self):
        self.active = self.enabled

    @api.onchange('active')
    def _onchange_active(self):
        self.enabled = self.active
    description = fields.Text(string='Definition & Criteria')

    _name_config_uniq = models.Constraint(
        'unique(config_id, name)',
        'An assessment component with this name already exists.',
    )

    @api.constrains('weight', 'max_score')
    def _check_values(self):
        for rec in self:
            if not 0.0 <= rec.weight <= 100.0:
                raise ValidationError(_('A component weight must be between 0 and 100.'))
            if rec.max_score <= 0.0:
                raise ValidationError(_('The max score must be greater than zero.'))

    # ---- change history on the configuration chatter ----
    _WATCH = ('name', 'source', 'weight', 'max_score', 'mandatory', 'waivable', 'enabled')

    @api.onchange('evaluation_type')
    def _onchange_evaluation_type(self):
        if self.evaluation_type == 'pms':
            self.source = 'pms'
        elif self.evaluation_type == 'competency_eval':
            self.source = 'competency_eval'
        else:
            self.source = 'manual'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('mandatory', True)
            vals.setdefault('waivable', True)
            if 'enabled' in vals and 'active' not in vals:
                vals['active'] = vals['enabled']
            elif 'active' in vals and 'enabled' not in vals:
                vals['enabled'] = vals['active']
            if 'evaluation_type' not in vals:
                n = (vals.get('name') or '').lower()
                s = vals.get('source') or 'manual'
                if s == 'pms' or 'pms' in n:
                    vals['evaluation_type'] = 'pms'
                elif s == 'competency_eval' or 'competency' in n:
                    vals['evaluation_type'] = 'competency_eval'
                elif 'interview' in n:
                    vals['evaluation_type'] = 'interview'
                else:
                    vals['evaluation_type'] = 'exam'
            etype = vals.get('evaluation_type')
            if etype == 'pms':
                vals['source'] = 'pms'
            elif etype == 'competency_eval':
                vals['source'] = 'competency_eval'
            else:
                vals.setdefault('source', 'manual')
        recs = super().create(vals_list)
        if not self.env.context.get('install_mode'):
            for rec in recs:
                rec.config_id.message_post(body=_(
                    'Component added: %(n)s (weight %(w)s%%, max %(m)s)') % {
                        'n': rec.name, 'w': rec.weight, 'm': rec.max_score})
        return recs

    def write(self, vals):
        if 'enabled' in vals and 'active' not in vals:
            vals['active'] = vals['enabled']
        elif 'active' in vals and 'enabled' not in vals:
            vals['enabled'] = vals['active']
        watch = set(self._WATCH) & set(vals)
        old = {r.id: {f: r[f] for f in watch} for r in self} if watch else {}
        res = super().write(vals)
        for rec in self.filtered(lambda r: r.id in old):
            diffs = ['%s: %s -> %s' % (f, old[rec.id][f], rec[f])
                     for f in watch if old[rec.id][f] != rec[f]]
            if diffs and not self.env.context.get('install_mode'):
                rec.config_id.message_post(body=_('Component %(n)s changed: %(d)s') % {
                    'n': rec.name, 'd': '; '.join(diffs)})
        return res

    def unlink(self):
        # Cleanly remove any candidate result lines linked to this component before deletion
        results = self.env['succession.candidate.assessment.result'].sudo().search([
            ('component_id', 'in', self.ids)
        ])
        candidates = results.mapped('candidate_id')
        if results:
            results.unlink()
        for cand in candidates:
            cand._refresh_assessment_scores()
        for rec in self:
            rec.config_id.message_post(body=_('Component removed: %s') % rec.name)
        return super().unlink()


class SuccessionCandidateAssessmentResult(models.Model):
    """
    One result line per candidate per assessment component.
    Manual components (exam, interview...) are typed in by authorized users;
    the PMS component is read automatically from the candidate's PMS score.
    A component can be waived for a candidate (reason recorded and audited).
    """
    _name = 'succession.candidate.assessment.result'
    _description = 'Candidate Assessment Result'
    _order = 'sequence, id'

    candidate_id = fields.Many2one(
        'succession.candidate', required=True, ondelete='cascade', index=True)
    component_id = fields.Many2one(
        'succession.assessment.component', required=True, ondelete='cascade', domain="[('active', '=', True), ('enabled', '=', True)]")
    sequence = fields.Integer(related='component_id.sequence', store=True)
    component_source = fields.Selection(related='component_id.source')
    weight = fields.Float(string='Weight (%)', default=0.0)
    max_score = fields.Float(string='Max Score', default=100.0)
    waivable = fields.Boolean(related='component_id.waivable')

    score = fields.Float(string='Entered Score')
    score_entered = fields.Boolean(readonly=True, copy=False)
    waived = fields.Boolean(string='Not Applicable (N/A)')
    waiver_reason = fields.Char(string='Reason Not Applicable (N/A)')
    applicability_status = fields.Selection([
        ('applicable', 'Applicable'),
        ('not_applicable', 'Not Applicable (N/A)'),
    ], string='Plan Applicability', compute='_compute_applicability_status', store=True)
    entered_by_id = fields.Many2one('res.users', string='Entered By', readonly=True)
    entered_date = fields.Datetime(string='Entered On', readonly=True)

    @api.depends('waived')
    def _compute_applicability_status(self):
        for rec in self:
            rec.applicability_status = 'not_applicable' if rec.waived else 'applicable'

    is_locked = fields.Boolean(compute='_compute_is_locked')
    is_scored = fields.Boolean(compute='_compute_line')
    is_applicable = fields.Boolean(compute='_compute_line')
    display_score = fields.Float(
        string='Score (0–100)', compute='_compute_line',
        inverse='_inverse_display_score', digits=(16, 2))
    status_label = fields.Char(string='Status', compute='_compute_line')
    effective_score = fields.Float(string='Score Used', compute='_compute_line')
    normalized_score = fields.Float(string='Score (%)', compute='_compute_line')
    effective_weight = fields.Float(string='Effective Weight (%)', compute='_compute_line')
    contribution = fields.Float(string='Contribution', compute='_compute_line')
    source_type_display = fields.Char(
        string='Evaluation Scope / Source', compute='_compute_source_type_display')

    def _inverse_display_score(self):
        for rec in self:
            if rec.component_source == 'manual' and not rec.waived:
                rec.score = rec.display_score
                rec.score_entered = True
                rec.entered_by_id = self.env.user
                rec.entered_date = fields.Datetime.now()

    _candidate_component_uniq = models.Constraint(
        'unique(candidate_id, component_id)',
        'This component already exists on the candidate.',
    )

    # ---------------- computes ----------------
    @api.depends('component_id.source', 'component_id.name',
                 'candidate_id.plan_include_manager',
                 'candidate_id.plan_include_self',
                 'candidate_id.plan_include_spmc')
    def _compute_source_type_display(self):
        for rec in self:
            comp = rec.component_id
            cand = rec.candidate_id
            if comp.source == 'competency_eval':
                evaluators = []
                if cand.plan_include_manager:
                    evaluators.append('Manager')
                if cand.plan_include_self:
                    evaluators.append('Self')
                if cand.plan_include_spmc:
                    evaluators.append('SPMC')
                if len(evaluators) > 1:
                    pct = round(100.0 / len(evaluators), 1)
                    rec.source_type_display = f"Multi-Rater ({' + '.join(evaluators)}: {pct}% each)"
                elif len(evaluators) == 1:
                    rec.source_type_display = f"{evaluators[0]} Evaluation (100%)"
                else:
                    rec.source_type_display = "Role Competencies Assessment"
            elif comp.source == 'pms':
                rec.source_type_display = "Automatic (Annual PMS Appraisal)"
            else:
                rec.source_type_display = "Manual Score Entry"

    @api.depends('candidate_id.assessment_done', 'candidate_id.state')
    def _compute_is_locked(self):
        for rec in self:
            rec.is_locked = bool(rec.candidate_id.assessment_done or rec.candidate_id.state in ('assessed', 'approved', 'placed'))

    @api.depends('score', 'score_entered', 'waived', 'weight', 'max_score',
                 'component_id.source', 'component_id.enabled', 'component_id.active',
                 'candidate_id.succession_competency_score',
                 'candidate_id.latest_pms_score')
    def _compute_line(self):
        for rec in self:
            comp = rec.component_id
            cand = rec.candidate_id

            if rec.waived or not (comp.enabled and comp.active):
                rec.status_label = 'N/A'
                rec.effective_weight = 0.0
                rec.display_score = 0.0
                rec.effective_score = 0.0
                rec.is_scored = False
                rec.is_applicable = False
                rec.normalized_score = 0.0
                rec.contribution = 0.0
                continue

            if comp.source == 'competency_eval':
                calc_score = cand.succession_competency_score or 0.0
                rec.display_score = calc_score
                rec.effective_score = calc_score
                has_ratings = bool(cand.eval_line_ids and any(l.score for l in cand.eval_line_ids))
                has_self = bool(cand.plan_include_self and (cand.self_assessment_score or 0) > 0)
                has_spmc = bool(cand.plan_include_spmc and (cand.spmc_score or 0) > 0)
                rec.is_scored = bool(has_ratings or has_self or has_spmc)
            elif comp.source == 'pms':
                rec.effective_score = cand.latest_pms_score or 0.0
                rec.display_score = rec.effective_score
                rec.is_scored = bool(cand.latest_pms_score and cand.latest_pms_score > 0)
            else:
                rec.effective_score = rec.score or 0.0
                rec.display_score = rec.score or 0.0
                rec.is_scored = bool(rec.score_entered)

            if rec.is_scored:
                rec.status_label = 'Scored'
                rec.effective_weight = rec.weight or 0.0
            else:
                rec.status_label = 'Pending'
                rec.effective_weight = rec.weight or 0.0

            rec.is_applicable = bool(comp.enabled and not rec.waived and rec.effective_weight > 0)
            max_s = rec.max_score or 100.0
            rec.normalized_score = min(max(rec.effective_score / max_s * 100.0, 0.0), 100.0) if max_s else 0.0
            rec.contribution = (rec.normalized_score * rec.effective_weight / 100.0) if rec.is_applicable else 0.0

    @api.onchange('score')
    def _onchange_score(self):
        for rec in self:
            if rec.score is not False and rec.score is not None:
                rec.score_entered = True
                rec.entered_by_id = self.env.user
                rec.entered_date = fields.Datetime.now()
            else:
                rec.score_entered = False

    @api.onchange('display_score')
    def _onchange_display_score(self):
        for rec in self:
            if rec.component_source == 'manual' and not rec.waived:
                rec.score = rec.display_score
                rec.score_entered = True
                rec.entered_by_id = self.env.user
                rec.entered_date = fields.Datetime.now()

    @api.onchange('waived')
    def _onchange_waived(self):
        for rec in self:
            if rec.waived:
                rec.score = 0.0
                rec.display_score = 0.0
                rec.score_entered = False
            else:
                rec.waiver_reason = False

    # ---------------- validation ----------------
    @api.constrains('score', 'component_id', 'max_score')
    def _check_score(self):
        for rec in self:
            comp = rec.component_id
            if comp.source == 'manual' and rec.score_entered:
                max_s = rec.max_score or comp.max_score or 100.0
                if not (0.0 <= rec.score <= max_s):
                    raise ValidationError(_(
                        '%(c)s: the score must be between 0 and %(m)s.') % {
                            'c': comp.name, 'm': max_s})

    @api.constrains('waived', 'waiver_reason', 'component_id')
    def _check_waiver(self):
        # Skip validation during system sync operations
        if self.env.context.get('skip_waiver_check') or self.env.context.get('force_write') or self.env.context.get('skip_waiver_reason_check'):
            return
        cfg = self.env['succession.assessment.config'].get_config()
        for rec in self:
            if not rec.waived:
                continue
            if not rec.component_id.enabled:
                continue
            if rec.component_id.source == 'competency_eval':
                continue
            if not rec.component_id.waivable:
                raise ValidationError(_('%s cannot be marked as Not Applicable.') % rec.component_id.name)
            if cfg.waiver_reason_required and not (rec.waiver_reason or '').strip():
                raise ValidationError(_(
                    'A reason is required to mark %s as Not Applicable (N/A).') % rec.component_id.name)

    def _check_not_locked(self):
        if any(self.mapped('is_locked')):
            raise UserError(_(
                'Assessment results are locked because the candidate has been assessed. '
                'SPMC can reopen the assessment (with a reason) to allow corrections.'))

    # ---------------- audit ----------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'score' in vals and vals['score'] is not False and vals['score'] is not None:
                vals['score_entered'] = True
                vals['entered_by_id'] = self.env.user.id
                vals['entered_date'] = fields.Datetime.now()
        return super().create(vals_list)

    def write(self, vals):
        if 'display_score' in vals and 'score' not in vals:
            vals['score'] = vals['display_score']
            vals['score_entered'] = True
        tracked = {'score', 'display_score', 'waived', 'waiver_reason'} & set(vals)
        old = {}
        if tracked:
            self._check_not_locked()
            vals = dict(vals)
            if 'score' in vals and vals['score'] is not False and vals['score'] is not None:
                vals['score_entered'] = True
            vals['entered_by_id'] = self.env.user.id
            vals['entered_date'] = fields.Datetime.now()
            old = {r.id: (r.score, r.waived, r.waiver_reason) for r in self}
        res = super().write(vals)
        for rec in self.filtered(lambda r: r.id in old):
            rec._log_change(*old[rec.id])
        if tracked:
            for cand in self.mapped('candidate_id'):
                cand._compute_assessment_scores()
        return res

    def _log_change(self, old_score, old_waived, old_reason):
        self.ensure_one()
        name = self.component_id.name
        if self.waived and not old_waived:
            self.candidate_id._log_candidate_event(
                'assessment_waived', '%s marked as Not Applicable (N/A). Reason: %s' % (name, self.waiver_reason or '-'))
        elif old_waived and not self.waived:
            self.candidate_id._log_candidate_event(
                'assessment_waived', '%s Not Applicable (N/A) status removed.' % name)
        elif self.waived and self.waiver_reason != old_reason:
            self.candidate_id._log_candidate_event(
                'assessment_waived', '%s Not Applicable (N/A) reason updated: %s' % (name, self.waiver_reason or '-'))
        elif self.score != old_score:
            self.candidate_id._log_candidate_event(
                'assessment_result', '%s result entered: %s -> %s (max %s)' % (
                    name, old_score, self.score, self.max_score))
