# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyAssessmentCycle(models.Model):
    """Scheduled competency assessment cycle /010,."""
    _name = 'competency.assessment.cycle'
    _description = 'Competency Assessment Cycle'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Cycle Name', required=True)
    code = fields.Char(string='Cycle Code', index=True)
    period_start = fields.Date(string='Period Start', required=True, default=fields.Date.context_today)
    period_end = fields.Date(string='Period End')
    assessment_deadline = fields.Date(string='Assessment Deadline')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('in_review', 'In Review'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True)
    assessment_ids = fields.One2many('competency.assessment', 'cycle_id', string='Assessments')
    assessment_count = fields.Integer(string='Total Assessments', compute='_compute_assessment_counts')
    pending_assessment_count = fields.Integer(string='Pending Assessments', compute='_compute_assessment_counts')
    submitted_assessment_count = fields.Integer(string='Submitted Assessments', compute='_compute_assessment_counts')
    sampling_audit_log = fields.Text(string='360 Rater Sampling Audit Trail', readonly=True)
    eligible_rater_count = fields.Integer(string='Eligible Raters Pool Size', default=0, readonly=True)
    selected_rater_count = fields.Integer(string='Sampled Raters Size', default=0, readonly=True)
    notes = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group('competency_management.group_competency_admin') and not self.env.su:
            raise UserError(_("Only Competency Administrators can create new Assessment Cycles."))
        return super().create(vals_list)

    @api.depends('assessment_ids', 'assessment_ids.state')
    def _compute_assessment_counts(self):
        for rec in self:
            rec.assessment_count = len(rec.assessment_ids)
            rec.pending_assessment_count = len(rec.assessment_ids.filtered(lambda a: a.state == 'draft'))
            rec.submitted_assessment_count = len(rec.assessment_ids.filtered(lambda a: a.state != 'draft'))

    def action_view_assessments(self):
        """Smart button action to view all paginated assessments for this cycle."""
        self.ensure_one()
        return {
            'name': _('Assessments: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'competency.assessment',
            'view_mode': 'list,form',
            'domain': [('cycle_id', '=', self.id)],
            'context': {'default_cycle_id': self.id},
        }

    def action_view_pending_assessments(self):
        """Smart button action for HR to view all unsubmitted/pending draft assessments for this cycle."""
        self.ensure_one()
        return {
            'name': _('Pending Assessments (Drafts): %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'competency.assessment',
            'view_mode': 'list,form',
            'domain': [('cycle_id', '=', self.id), ('state', '=', 'draft')],
            'context': {'default_cycle_id': self.id, 'search_default_state_draft': 1},
        }

    def action_send_deadline_reminders(self):
        """Send warning/reminder notifications to all assessors with pending draft assessments for this cycle."""
        self.ensure_one()
        pending_asms = self.assessment_ids.filtered(lambda a: a.state == 'draft')
        if not pending_asms:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Pending Assessments'),
                    'message': _('All assessments for this cycle have already been submitted!'),
                    'type': 'info',
                    'sticky': False,
                }
            }

        assessors = pending_asms.mapped('assessor_id')
        sent_count = 0
        deadline_str = self.assessment_deadline.strftime('%b %d, %Y') if self.assessment_deadline else _('Not set')

        for assessor in assessors:
            assessor_pending = pending_asms.filtered(lambda a: a.assessor_id == assessor)
            partner = assessor.partner_id
            if not partner:
                continue

            emp_names = ", ".join(assessor_pending.mapped('employee_id.name')[:5])
            extra = _(" and %d more") % (len(assessor_pending) - 5) if len(assessor_pending) > 5 else ""

            msg_body = _(
                "⚠️ <strong>Competency Assessment Deadline Warning:</strong><br/>"
                "You have %d pending competency assessment(s) assigned to you for cycle '<strong>%s</strong>' "
                "(Assessments for: %s%s).<br/>"
                "The submission deadline is <strong>%s</strong>. Please complete and submit your assessments before the deadline."
            ) % (len(assessor_pending), self.name, emp_names, extra, deadline_str)

            self.message_post(
                body=msg_body,
                partner_ids=[partner.id],
                subtype_xmlid='mail.mt_comment'
            )
            sent_count += 1

        self.message_post(body=_("Sent deadline warning notifications to %d assessor(s) with pending draft assessments.") % sent_count)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Notifications Sent'),
                'message': _('Successfully sent deadline warning reminders to %d assessor(s) with pending assessments.') % sent_count,
                'type': 'success',
                'sticky': False,
            }
        }

    @api.constrains('period_start', 'period_end')
    def _check_periods(self):
        for rec in self:
            if rec.period_end and rec.period_start and rec.period_end < rec.period_start:
                raise ValidationError(_('Period End cannot be before Period Start.'))

    def action_start(self):
        """Draft -> Open: Automatically generate 360-degree assessments (Self, Supervisor, Team, Peer, Subordinate) with random sampling caps."""
        self.with_context(force_write=True).write({'state': 'open'})
        for rec in self:
            created_asms = rec._generate_cycle_assessments_batch()
            rec._send_cycle_start_notifications(created_asms)
            rec.message_post(body=_('Assessment cycle %s opened and 360-degree evaluations generated. Deadline: %s.') % (rec.name, rec.assessment_deadline or 'Not set'))
        return True

    def _send_cycle_start_notifications(self, assessments):
        """Send notifications to all assigned raters/assessors when a cycle starts."""
        self.ensure_one()
        deadline_str = self.assessment_deadline.strftime('%b %d, %Y') if self.assessment_deadline else _('Not set')
        assessor_map = {}
        for asm in assessments:
            if asm.assessor_id and asm.assessor_id.partner_id:
                assessor_map.setdefault(asm.assessor_id, []).append(asm)

        for assessor, asms in assessor_map.items():
            partner = assessor.partner_id
            msg_body = _(
                "📋 <strong>Competency Assessment Cycle Started:</strong><br/>"
                "The assessment cycle '<strong>%s</strong>' has started. You have <strong>%d</strong> assigned competency assessment(s) to fill.<br/>"
                "Submission Deadline: <strong>%s</strong>.<br/>"
                "Please log in and submit your evaluations before the deadline."
            ) % (self.name, len(asms), deadline_str)
            self.message_post(
                body=msg_body,
                partner_ids=[partner.id],
                subtype_xmlid='mail.mt_comment'
            )

    def _generate_cycle_assessments_batch(self):
        """Generate pre-populated 360-degree assessments for all active employees for this cycle.
        Uses evaluatee-centric quota sampling:
        Every evaluatee gets min(eligible_pool_size, max_config_limit) peer and subordinate assessments.
        Assessor workloads are balanced dynamically.
        """
        self.ensure_one()
        import random

        config = self.env['competency.matrix.config'].get_active_config()
        max_peers = config.max_peer_assessments or 3
        max_subs = config.max_subordinate_assessments or 2

        active_employees = self.env['hr.employee'].search([('active', '=', True)])
        
        # Track created assessments to avoid duplicates: (cycle_id, employee_id, assessor_id, assessment_type)
        existing_pairs = set(
            self.env['competency.assessment'].search([('cycle_id', '=', self.id)]).mapped(
                lambda a: (a.employee_id.id, a.assessor_id.id if a.assessor_id else False, a.assessment_type)
            )
        )

        assessments_to_create = []
        total_eligible_raters = 0
        total_sampled_raters = 0

        # Track assessor workloads to balance rater load across evaluatees
        peer_assessor_workload = {}  # user_id -> count
        sub_assessor_workload = {}   # user_id -> count

        # 1. Create Self, Supervisor, and Team assessments for all active employees
        for emp in active_employees:
            if not emp.user_id:
                continue

            emp_id = emp.id
            u_id = emp.user_id.id

            # Self Assessment (mandatory)
            pair_self = (emp_id, u_id, 'self')
            if pair_self not in existing_pairs:
                assessments_to_create.append({
                    'cycle_id': self.id,
                    'employee_id': emp_id,
                    'assessor_id': u_id,
                    'assessment_type': 'self',
                })
                existing_pairs.add(pair_self)

            # Supervisor Assessment (coach/parent assesses employee)
            coach = getattr(emp, 'coach_id', False) or emp.parent_id
            if coach and coach.user_id:
                pair_sup = (emp_id, coach.user_id.id, 'supervisor')
                if pair_sup not in existing_pairs:
                    assessments_to_create.append({
                        'cycle_id': self.id,
                        'employee_id': emp_id,
                        'assessor_id': coach.user_id.id,
                        'assessment_type': 'supervisor',
                    })
                    existing_pairs.add(pair_sup)

            # Team Assessment (direct reports assess manager)
            direct_reports = active_employees.filtered(lambda r: (r.parent_id == emp or getattr(r, 'coach_id', False) == emp) and r.id != emp.id)
            for dr in direct_reports:
                if dr.user_id:
                    pair_team = (emp_id, dr.user_id.id, 'team')
                    if pair_team not in existing_pairs:
                        assessments_to_create.append({
                            'cycle_id': self.id,
                            'employee_id': emp_id,
                            'assessor_id': dr.user_id.id,
                            'assessment_type': 'team',
                        })
                        existing_pairs.add(pair_team)

        # 2. Evaluatee-Centric Sampling for Peer and Subordinate Assessments
        for evaluatee in active_employees:
            if not evaluatee.user_id:
                continue

            # --- PEER SAMPLING FOR EVALUATEE ---
            eligible_peers = self.env['competency.assessment']._get_eligible_peers_for_emp(evaluatee)
            valid_peer_candidates = eligible_peers.filtered(lambda p: p.id != evaluatee.id and p.user_id)
            pool_size = len(valid_peer_candidates)
            total_eligible_raters += pool_size

            # Target quota for evaluatee: min(pool_size, max_peers)
            target_peer_quota = min(pool_size, max_peers) if max_peers > 0 else pool_size
            if target_peer_quota > 0 and valid_peer_candidates:
                candidate_list = list(valid_peer_candidates)
                random.shuffle(candidate_list)
                candidate_list.sort(key=lambda c: peer_assessor_workload.get(c.user_id.id, 0))

                selected_peers = candidate_list[:target_peer_quota]
                total_sampled_raters += len(selected_peers)

                for peer in selected_peers:
                    peer_u_id = peer.user_id.id
                    pair_peer = (evaluatee.id, peer_u_id, 'peer')
                    if pair_peer not in existing_pairs:
                        assessments_to_create.append({
                            'cycle_id': self.id,
                            'employee_id': evaluatee.id,
                            'assessor_id': peer_u_id,
                            'assessment_type': 'peer',
                        })
                        existing_pairs.add(pair_peer)
                        peer_assessor_workload[peer_u_id] = peer_assessor_workload.get(peer_u_id, 0) + 1

            # --- SUBORDINATE SAMPLING FOR EVALUATEE ---
            eligible_subs = self.env['competency.assessment']._get_eligible_subordinates_for_emp(evaluatee)
            valid_sub_candidates = eligible_subs.filtered(lambda s: s.id != evaluatee.id and s.user_id)
            sub_pool_size = len(valid_sub_candidates)
            total_eligible_raters += sub_pool_size

            target_sub_quota = min(sub_pool_size, max_subs) if max_subs > 0 else sub_pool_size
            if target_sub_quota > 0 and valid_sub_candidates:
                candidate_list = list(valid_sub_candidates)
                random.shuffle(candidate_list)
                candidate_list.sort(key=lambda c: sub_assessor_workload.get(c.user_id.id, 0))

                selected_subs = candidate_list[:target_sub_quota]
                total_sampled_raters += len(selected_subs)

                for sub in selected_subs:
                    sub_u_id = sub.user_id.id
                    pair_sub = (evaluatee.id, sub_u_id, 'subordinate')
                    if pair_sub not in existing_pairs:
                        assessments_to_create.append({
                            'cycle_id': self.id,
                            'employee_id': evaluatee.id,
                            'assessor_id': sub_u_id,
                            'assessment_type': 'subordinate',
                        })
                        existing_pairs.add(pair_sub)
                        sub_assessor_workload[sub_u_id] = sub_assessor_workload.get(sub_u_id, 0) + 1

        # Audit trail
        self.sudo().write({
            'eligible_rater_count': total_eligible_raters,
            'selected_rater_count': total_sampled_raters,
            'sampling_audit_log': f"360 Evaluatee-Centric Sampling Audit: Total Eligible Candidate Raters={total_eligible_raters}, Total Sampled Raters={total_sampled_raters}, Created Assessments={len(assessments_to_create)}",
        })

        if not assessments_to_create:
            return self.env['competency.assessment']

        import threading

        chunk_size = 500
        created_asms = self.env['competency.assessment']
        AssessmentSudo = self.env['competency.assessment'].with_context(
            tracking_disable=True,
            mail_create_nolog=True,
            mail_create_nosubscribe=True,
        )

        for i in range(0, len(assessments_to_create), chunk_size):
            chunk = assessments_to_create[i:i + chunk_size]
            asms_chunk = AssessmentSudo.create(chunk)
            created_asms |= asms_chunk

        return created_asms

    def action_start_review(self):
        self.with_context(force_write=True).write({'state': 'in_review'})
        return True

    def action_close(self):
        self.with_context(force_write=True).write({'state': 'closed'})
        for rec in self:
            rec.message_post(body=_('Assessment cycle %s closed.') % rec.name)
        return True

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state == 'closed' and not force_write and not self.env.su:
                locked_fields = {'name', 'period_start', 'period_end', 'assessment_deadline'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(_("This assessment cycle (%s) is closed and cannot be edited.") % rec.name)
        return super().write(vals)


class CompetencyAssessment(models.Model):
    """A single employee assessment within a cycle (FR-COM-011, FR-COM-012)."""
    _name = 'competency.assessment'
    _description = 'Competency Assessment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, copy=False)
    cycle_id = fields.Many2one(
        'competency.assessment.cycle', string='Assessment Cycle', required=True,
        domain="[('state', '=', 'open')]", ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    department_id = fields.Many2one(related='employee_id.department_id', string='Department', store=True, readonly=True)
    job_id = fields.Many2one(related='employee_id.job_id', string='Job Position', store=True, readonly=True)

    @api.model
    def _get_assessment_type_selection(self):
        """Complete 360-degree assessment type selection options."""
        return [
            ('self', 'Self-Assessment'),
            ('peer', 'Peer Assessment'),
            ('subordinate', 'Subordinate Assessment'),
            ('supervisor', 'Supervisor Assessment'),
            ('team', 'Team Assessment'),
        ]



    assessor_id = fields.Many2one('res.users', string='Assessor', default=lambda self: self.env.user, readonly=True)
    assessment_type = fields.Selection(
        selection='_get_assessment_type_selection', string='Assessment Type',
        required=True, tracking=True)

    @api.model
    def _get_employee_ou_id(self, emp):
        if not emp:
            return False
        if getattr(emp, 'default_operating_unit_id', False):
            return emp.default_operating_unit_id.id
        if emp.department_id and getattr(emp.department_id, 'operating_unit_id', False):
            return emp.department_id.operating_unit_id.id
        return False

    @api.model
    def _resolve_employee_grade(self, emp):
        """Resolves the employee's assigned employee.grade record safely across hr_employee_custom variants."""
        if not emp:
            return self.env['employee.grade']

        # 1. Direct job_grade on employee
        grade = getattr(emp, 'job_grade', False)
        if grade and getattr(grade, '_name', '') == 'employee.grade':
            return grade

        # 2. Active contract in hr.version
        if 'hr.version' in self.env:
            contract = self.env['hr.version'].search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['open', 'probation', 'draft'])
            ], order='id desc', limit=1)
            if contract and getattr(contract, 'job_grade', False):
                g = contract.job_grade
                if getattr(g, '_name', '') == 'employee.grade':
                    return g

        # 3. Operating Unit Job Position
        if emp.job_id and 'operating.unit.job.position' in self.env:
            ou_id = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id.operating_unit_id if emp.department_id else False)
            if ou_id:
                pos = self.env['operating.unit.job.position'].search([
                    ('job_position_id', '=', emp.job_id.id),
                    ('operating_unit_id', '=', ou_id.id)
                ], limit=1)
                if pos and pos.job_grade_id and getattr(pos.job_grade_id, '_name', '') == 'employee.grade':
                    return pos.job_grade_id
            pos = self.env['operating.unit.job.position'].search([
                ('job_position_id', '=', emp.job_id.id)
            ], limit=1)
            if pos and pos.job_grade_id and getattr(pos.job_grade_id, '_name', '') == 'employee.grade':
                return pos.job_grade_id

        # 4. Check grade_id on employee (may be employee.grade or hr.employee.grade)
        grade = getattr(emp, 'grade_id', False)
        if grade:
            if getattr(grade, '_name', '') == 'employee.grade':
                return grade
            code = getattr(grade, 'code', False) or getattr(grade, 'grade_code', False)
            name = getattr(grade, 'name', False) or getattr(grade, 'grade_name', False)
            if code:
                found = self.env['employee.grade'].search([('grade_code', '=ilike', str(code).strip())], limit=1)
                if found:
                    return found
            if name:
                found = self.env['employee.grade'].search(['|', ('grade_name', '=ilike', str(name).strip()), ('grade_code', '=ilike', str(name).strip())], limit=1)
                if found:
                    return found

        # 5. Check job position
        if emp.job_id:
            g = getattr(emp.job_id, 'grade', False) or getattr(emp.job_id, 'grade_id', False)
            if g:
                if getattr(g, '_name', '') == 'employee.grade':
                    return g
                code = getattr(g, 'code', False) or getattr(g, 'grade_code', False)
                name = getattr(g, 'name', False) or getattr(g, 'grade_name', False)
                if code:
                    found = self.env['employee.grade'].search([('grade_code', '=ilike', str(code).strip())], limit=1)
                    if found:
                        return found
                if name:
                    found = self.env['employee.grade'].search(['|', ('grade_name', '=ilike', str(name).strip()), ('grade_code', '=ilike', str(name).strip())], limit=1)
                    if found:
                        return found

        return self.env['employee.grade']

    @api.model
    def _get_employee_grade_id(self, emp):
        if not emp:
            return False
        grade = self._resolve_employee_grade(emp)
        return grade.id if grade else False

    @api.model
    def _get_grade_number(self, emp):
        """Extract numeric grade level (1..17) from employee's assigned job grade or position."""
        if not emp:
            return 0
        grade_rec = self._resolve_employee_grade(emp)
        raw_str = ''
        if grade_rec:
            raw_str = getattr(grade_rec, 'grade_name', False) or getattr(grade_rec, 'grade_code', False) or ''
        if not raw_str:
            raw = getattr(emp, 'grade_id', False) or getattr(emp, 'job_grade', False)
            if raw:
                raw_str = getattr(raw, 'name', False) or getattr(raw, 'code', False) or getattr(raw, 'grade_name', False) or str(raw)
        if not raw_str and emp.job_id:
            raw = getattr(emp.job_id, 'grade', False) or getattr(emp.job_id, 'grade_id', False)
            if raw:
                raw_str = getattr(raw, 'name', False) or getattr(raw, 'code', False) or getattr(raw, 'grade_name', False) or str(raw)

        g_str = str(raw_str).lower().strip()
        if not g_str:
            return 0

        tokens = g_str.replace('-', ' ').replace('_', ' ').split()
        roman_map = {
            'xvii': 17, 'xvi': 16, 'xv': 15, 'xiv': 14, 'xiii': 13, 'xii': 12, 'xi': 11,
            'x': 10, 'ix': 9, 'viii': 8, 'vii': 7, 'vi': 6, 'v': 5, 'iv': 4, 'iii': 3, 'ii': 2, 'i': 1
        }
        for token in tokens:
            if token in roman_map:
                return roman_map[token]
        if g_str in roman_map:
            return roman_map[g_str]

        import re
        numbers = re.findall(r'\d+', g_str)
        if numbers:
            return int(numbers[0])

        return 0

    @api.model
    def _is_director_or_chief(self, emp):
        """Strictly classify as Director (Grade 16) or Chief (Grade 17). Exclude Grade II, III, IV, etc."""
        if not emp or not emp.active:
            return False
        g_num = self._get_grade_number(emp)
        if g_num in (16, 17):
            return True
        return False

    @api.model
    def _is_branch_manager(self, emp):
        if not emp or not emp.job_id:
            return False
        j_name = (emp.job_id.name or '').lower()
        return 'branch manager' in j_name or j_name.startswith('bm') or ' bm ' in j_name or 'bm-' in j_name or 'bm ' in j_name

    @api.model
    def _is_manager(self, emp):
        if not emp:
            return False
        if self._is_director_or_chief(emp) or self._is_branch_manager(emp) or self._is_district_manager_emp(emp):
            return True
        j_name = (emp.job_id.name or '').lower() if emp.job_id else ''
        return any(k in j_name for k in ['manager', 'head', 'lead', 'leader', 'president', 'vp', 'supervisor'])

    @api.model
    def _is_director_emp(self, emp):
        return self._is_director_or_chief(emp)

    @api.model
    def _is_district_manager_emp(self, emp):
        if not emp or not emp.job_id:
            return False
        job_name = emp.job_id.name or ''
        return 'district manager' in job_name.lower() or ('district' in job_name.lower() and 'manager' in job_name.lower())

    @api.model
    def _get_eligible_peers_for_emp(self, emp):
        """Get eligible peer candidates for employee emp based on category grid:
        1. Directors and Chiefs (Exceptions):
           - Configured via competency.director.peer.config OR 1. Same Job Grade (Coach, OU, Position unlisted -> open).
        2. Branch Managers:
           - 1. Same Coach, 2. Same Job Grade, 4. Same Job Position (OU unlisted -> open).
        3. Managerial Positions HO & District Office:
           - 1. Same Coach, 2. Same Job Grade, 3. Same Work Unit (Job Position unlisted -> open).
        4. Non Managerial Positions:
           - 1. Same Coach, 2. Same Job Grade, 3. Same Work Unit, 4. Same Job Position.
        """
        if not emp or not emp.active:
            return self.env['hr.employee']

        # 1. Directors & Chiefs Exception: Strictly manual assignment via competency.director.peer.config
        if self._is_director_or_chief(emp):
            peers = self.env['hr.employee']
            config = self.env['competency.director.peer.config'].search([('director_id', '=', emp.id)], limit=1)
            if config and config.peer_ids:
                peers |= config.peer_ids.filtered(lambda p: p.active and p.id != emp.id)
            other_configs = self.env['competency.director.peer.config'].search([('peer_ids', 'in', [emp.id])])
            if other_configs:
                peers |= other_configs.mapped('director_id').filtered(lambda d: d.active and d.id != emp.id)
            # Returns manually assigned peers ONLY (no random auto-assignment if unassigned)
            return peers

        emp_coach = getattr(emp, 'coach_id', False) or emp.parent_id
        emp_grade_id = self._get_employee_grade_id(emp)
        emp_ou_id = self._get_employee_ou_id(emp)
        emp_job_id = emp.job_id.id if emp.job_id else False

        domain = [('id', '!=', emp.id), ('active', '=', True)]
        if emp_coach:
            domain += ['|', ('parent_id', '=', emp_coach.id), ('coach_id', '=', emp_coach.id)]

        candidates = self.env['hr.employee'].search(domain)

        # 2. Branch Manager: Same Coach, Same Grade, Same Position (OU unlisted -> open)
        if self._is_branch_manager(emp):
            matched = candidates.filtered(lambda c: (
                (self._get_employee_grade_id(c) == emp_grade_id if emp_grade_id else True) and
                (c.job_id.id == emp_job_id if (c.job_id and emp_job_id) else True)
            ))
        # 3. Managerial Positions HO & District Office: Same Coach, Same Grade, Same OU (Position unlisted -> open)
        elif self._is_manager(emp):
            matched = candidates.filtered(lambda c: (
                (self._get_employee_grade_id(c) == emp_grade_id if emp_grade_id else True) and
                (self._get_employee_ou_id(c) == emp_ou_id if (self._get_employee_ou_id(c) and emp_ou_id) else True)
            ))
        # 4. Non-Managerial Positions: Same Coach, Same Grade, Same OU, Same Position
        else:
            matched = candidates.filtered(lambda c: (
                (self._get_employee_grade_id(c) == emp_grade_id if emp_grade_id else True) and
                (self._get_employee_ou_id(c) == emp_ou_id if (self._get_employee_ou_id(c) and emp_ou_id) else True) and
                (c.job_id.id == emp_job_id if (c.job_id and emp_job_id) else True)
            ))

        if not matched and candidates:
            # Fallback if strict criteria returns 0: match same grade under coach
            matched = candidates.filtered(lambda c: self._get_employee_grade_id(c) == emp_grade_id) or candidates

        return matched

    @api.model
    def _get_eligible_subordinates_for_emp(self, emp):
        """Get eligible subordinate candidates for employee emp:
        1. Chiefs / Directors (Exceptions):
           - 1. Same Coach, 2. Different Job Grade (OU & Job Position unlisted -> open).
        2. Non Managerial & Managerial Positions:
           - 1. Same Coach, 2. Different Job Grade, 3. Same Work Unit, 4. Different Job Position.
        """
        if not emp or not emp.active:
            return self.env['hr.employee']

        emp_coach = getattr(emp, 'coach_id', False) or emp.parent_id
        emp_grade_id = self._get_employee_grade_id(emp)
        emp_ou_id = self._get_employee_ou_id(emp)
        emp_job_id = emp.job_id.id if emp.job_id else False

        domain = [('id', '!=', emp.id), ('active', '=', True)]
        if emp_coach:
            domain += ['|', ('parent_id', '=', emp_coach.id), ('coach_id', '=', emp_coach.id)]

        candidates = self.env['hr.employee'].search(domain)

        # 1. Chief / Director Subordinates Exception: Same Coach, Different Grade (OU & Job Position unlisted -> open)
        if self._is_director_or_chief(emp):
            matched = candidates.filtered(lambda c: (
                self._get_employee_grade_id(c) != emp_grade_id if (self._get_employee_grade_id(c) and emp_grade_id) else True
            ))
        # 2. General Subordinates (Non-Manager & Manager): Same Coach, Different Grade, Same OU, Different Position
        else:
            matched = candidates.filtered(lambda c: (
                (self._get_employee_grade_id(c) != emp_grade_id if (self._get_employee_grade_id(c) and emp_grade_id) else True) and
                (self._get_employee_ou_id(c) == emp_ou_id if (self._get_employee_ou_id(c) and emp_ou_id) else True) and
                (c.job_id.id != emp_job_id if (c.job_id and emp_job_id) else True)
            ))

        if not matched and candidates:
            # Fallback if strict criteria returns 0: match candidates under same coach with different grade or position
            matched = candidates.filtered(lambda c: c.job_id.id != emp_job_id) or candidates

        # Include employee's coach as eligible candidate for subordinate assessment (assessing coach from employee perspective)
        if emp_coach and emp_coach.id != emp.id:
            matched |= emp_coach

        return matched

    @api.onchange('assessment_type')
    def _onchange_assessment_type_set_employee_domain(self):
        """Rule 2: Restrict employee selection domain strictly based on chosen assessment type and auto-assign valid default."""
        user = self.env.user
        emp = user.employee_id

        if self.assessment_type == 'self':
            if emp:
                self.employee_id = emp.id
            return {'domain': {'employee_id': [('id', '=', emp.id if emp else False)]}}

        if not emp:
            self.employee_id = False
            return {'domain': {'employee_id': [('id', '=', False)]}}

        if self.assessment_type == 'peer':
            peers = self._get_eligible_peers_for_emp(emp)
            self.employee_id = peers[0].id if peers else False
            return {'domain': {'employee_id': [('id', 'in', peers.ids)]}}

        elif self.assessment_type == 'subordinate':
            subs = self._get_eligible_subordinates_for_emp(emp)
            emp_coach = getattr(emp, 'coach_id', False) or emp.parent_id
            if emp_coach and emp_coach in subs:
                self.employee_id = emp_coach.id
            else:
                self.employee_id = subs[0].id if subs else False
            return {'domain': {'employee_id': [('id', 'in', subs.ids)]}}

        elif self.assessment_type == 'supervisor':
            supervisors = self.env['hr.employee']
            if emp.parent_id:
                supervisors |= emp.parent_id
            if getattr(emp, 'coach_id', False) and emp.coach_id:
                supervisors |= emp.coach_id
            if emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.id != emp.id:
                supervisors |= emp.department_id.manager_id

            if not supervisors and emp.department_id:
                dept = emp.department_id.parent_id
                while dept and not supervisors:
                    if dept.manager_id and dept.manager_id.id != emp.id:
                        supervisors |= dept.manager_id
                    dept = dept.parent_id

            if not supervisors:
                supervisors = self.env['hr.employee'].search([
                    ('id', '!=', emp.id),
                    '|', ('job_id.name', 'ilike', 'manager'), ('job_id.name', 'ilike', 'director')
                ], limit=30)

            self.employee_id = supervisors[0].id if supervisors else False
            return {'domain': {'employee_id': [('id', 'in', supervisors.ids)]}}

        elif self.assessment_type == 'team':
            subordinates = self.env['hr.employee'].search([('parent_id', '=', emp.id)])
            if not subordinates and emp.department_id and emp.department_id.manager_id.id == emp.id:
                subordinates = self.env['hr.employee'].search([('department_id', '=', emp.department_id.id), ('id', '!=', emp.id)])

            self.employee_id = subordinates[0].id if subordinates else False
            return {'domain': {'employee_id': [('id', 'in', subordinates.ids)]}}

        return {'domain': {'employee_id': []}}

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('supervisor_review', 'Supervisor Review'),
        ('hr_verified', 'HR Verified'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], string='Status', default='draft', tracking=True)
    line_ids = fields.One2many('competency.assessment.line', 'assessment_id', string='Competency Ratings')
    core_line_ids = fields.One2many('competency.assessment.line', 'assessment_id', string='Core Competencies', domain=[('pillar', '=', 'core')])
    leadership_line_ids = fields.One2many('competency.assessment.line', 'assessment_id', string='Leadership Competencies', domain=[('pillar', '=', 'leadership')])
    technical_line_ids = fields.One2many('competency.assessment.line', 'assessment_id', string='Technical Competencies', domain=[('pillar', '=', 'technical')])
    average_gap = fields.Float(string='Average Gap', compute='_compute_average_gap', store=True)
    is_locked = fields.Boolean(string='Locked', compute='_compute_is_locked')
    cycle_deadline = fields.Date(related='cycle_id.assessment_deadline', string='Cycle Deadline', readonly=True)
    is_deadline_passed = fields.Boolean(
        string='Submission Deadline Passed', compute='_compute_is_deadline_passed', store=True,
        help='True if current date exceeds the assessment cycle submission deadline.')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('cycle_id', 'cycle_id.assessment_deadline')
    def _compute_is_deadline_passed(self):
        today = fields.Date.today()
        for rec in self:
            dl = fields.Date.to_date(rec.cycle_id.assessment_deadline) if (rec.cycle_id and rec.cycle_id.assessment_deadline) else False
            rec.is_deadline_passed = bool(dl and today > dl)

    # 360 Multi-Rater extension fields (FR-COM-012, FR-ASM-002, FR-ASM-005)
    parent_assessment_id = fields.Many2one('competency.assessment', string='Parent 360 Assessment', ondelete='cascade', tracking=True)
    child_assessment_ids = fields.One2many('competency.assessment', 'parent_assessment_id', string='Rater Assessments')
    is_rater_assessment = fields.Boolean(string='Is Child Rater Assessment', default=False)
    rater_type = fields.Selection([
        ('self', 'Self'),
        ('peer', 'Peer'),
        ('subordinate', 'Subordinate'),
        ('supervisor', 'Supervisor'),
        ('other', 'Other'),
    ], string='Rater Type')
    rater_id = fields.Many2one('res.users', string='Rater User')
    is_anonymous = fields.Boolean(string='Anonymize 360 Feedback', default=False,
                                   help='Hide rater name from line managers for peer/subordinate 360 reviews (FR-ASM-002).')
    anonymized_rater_label = fields.Char(string='Display Rater Label', compute='_compute_anonymized_rater_label')

    @api.depends('is_anonymous', 'rater_type', 'rater_id')
    def _compute_anonymized_rater_label(self):
        for rec in self:
            if rec.is_anonymous and rec.rater_type in ('peer', 'subordinate'):
                rec.anonymized_rater_label = _("Anonymous 360 Rater (%s)") % (rec.rater_type.capitalize() if rec.rater_type else 'Peer')
            elif rec.rater_id:
                rec.anonymized_rater_label = rec.rater_id.name
            else:
                rec.anonymized_rater_label = _("Unassigned")

    def action_consolidate_multi_source(self):
        """Consolidate Self, Manager, 360 Feedback, and Skills Test scores into one weighted
        achievement determination (FR-ASM-005).

        Uses the same configured rater weights (competency.matrix.config) as the live 360°
        calculation on assessment lines (_compute_360_ratings), so the consolidated result is
        consistent with Scenario 5's Weighted Gap Calculation instead of a naive unweighted
        average across however many raters happened to submit.
        """
        config = self.env['competency.matrix.config'].sudo().get_active_config()
        weight_by_type = {
            'self': float(config.weight_self or 2.0),
            'peer': float(config.weight_peer or 1.0),
            'subordinate': float(config.weight_subordinate or 1.0),
            'supervisor': float(config.weight_supervisor or 3.0),
            'team': float(config.weight_team or 0.0),
        }
        # Verified skills-test evidence is treated with the same authority as a supervisor rating.
        skills_test_weight = weight_by_type['supervisor']

        for parent in self:
            if not parent.employee_id:
                continue

            # cid -> list of (score, weight) pairs
            competency_scores = {}
            competency_reqs = {}

            # 1. Child 360 raters, weighted by rater/assessment type
            for child in parent.child_assessment_ids.filtered(lambda c: c.state in ('submitted', 'supervisor_review', 'hr_verified', 'approved', 'locked')):
                rater_weight = weight_by_type.get(child.assessment_type, 1.0)
                for line in child.line_ids:
                    if not line.current_level:
                        continue
                    cid = line.competency_id.id
                    competency_scores.setdefault(cid, []).append((int(line.current_level), rater_weight))
                    competency_reqs[cid] = line.required_level

            # 2. Skills Tests (FR-ASM-003) — verified/objective evidence
            skills_tests = self.env['competency.skills.test'].search([('employee_id', '=', parent.employee_id.id)])
            for test in skills_tests:
                if test.verified_level:
                    cid = test.competency_id.id
                    competency_scores.setdefault(cid, []).append((int(test.verified_level), skills_test_weight))

            # Update line ratings using the same weighted-average formula as the live 360 engine
            for cid, weighted_pairs in competency_scores.items():
                num = sum(score * w for score, w in weighted_pairs)
                den = sum(w for score, w in weighted_pairs)
                if den > 0:
                    avg_score = round(num / den)
                else:
                    avg_score = round(sum(score for score, w in weighted_pairs) / len(weighted_pairs))
                lvl_str = str(max(1, min(4, avg_score)))
                existing_line = parent.line_ids.filtered(lambda l: l.competency_id.id == cid)
                if existing_line:
                    existing_line.write({'current_level': lvl_str})
                else:
                    self.env['competency.assessment.line'].create({
                        'assessment_id': parent.id,
                        'competency_id': cid,
                        'current_level': lvl_str,
                        'required_level': competency_reqs.get(cid, '2'),
                    })
            parent.message_post(body=_("Multi-source assessment scores (360 feedback + Skills Tests) consolidated into final achievement levels using configured rater weights."))

    @api.depends('line_ids', 'line_ids.gap', 'line_ids.current_level', 'line_ids.current_level_num')
    def _compute_average_gap(self):
        for rec in self:
            rated_lines = rec.line_ids.filtered(lambda l: l.current_level_num > 0 or (l.current_level and str(l.current_level).isdigit() and int(l.current_level) > 0))
            gaps = [line.gap for line in rated_lines if line.gap is not False and line.gap is not None]
            rec.average_gap = round(sum(gaps) / len(gaps), 2) if gaps else 0.0

    @api.depends('state')
    def _compute_is_locked(self):
        for rec in self:
            rec.is_locked = rec.state == 'locked'

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = seq.next_by_code('competency.assessment') or 'CMP-A-NEW'
        return super().create(vals_list)

    @api.model
    def _get_matrix_required_level(self, pillar, grade=False, job=False, job_name=''):
        """Determine required proficiency level (1..4) checking Job Position exception matrix first, then falling back to Job Grade matrix baseline."""
        config = self.env['competency.matrix.config'].get_active_config()
        
        # 1. Job Position Matrix Check (Exceptions Override)
        if job:
            j_line = self.env['competency.job.matrix'].search([
                ('config_id', '=', config.id),
                ('job_id', '=', job.id)
            ], limit=1)
            if j_line:
                if pillar == 'core': return j_line.required_core_level
                elif pillar == 'leadership': return j_line.required_leadership_level if j_line.required_leadership_level != '0' else '1'
                else: return j_line.required_technical_level

        # 2. Job Grade Matrix Check (Baseline Standard)
        if grade:
            g_line = self.env['competency.grade.matrix'].search([
                ('config_id', '=', config.id),
                ('grade_id', '=', grade.id)
            ], limit=1)
            if g_line:
                if pillar == 'core': return g_line.required_core_level
                elif pillar == 'leadership': return g_line.required_leadership_level if g_line.required_leadership_level != '0' else '1'
                else: return g_line.required_technical_level

        # Fallback to standard guidelines
        g_name = (grade.grade_name or '').lower() if grade else ''
        j_name = (job.name if job else job_name or '').lower()
        
        # Chief & D/Chief
        if 'chief' in g_name or 'chief' in j_name:
            if pillar == 'core': return '4'
            elif pillar == 'leadership': return '4'
            else: return '2'
            
        # Director I, II & ToT Leaders
        if 'director' in g_name or 'director' in j_name or 'tot leader' in j_name:
            if pillar == 'core': return '4'
            elif pillar == 'leadership': return '3'
            else: return '3'
            
        # BM-II, III, Division Managers & STL
        if 'division manager' in j_name or 'bm-ii' in j_name or 'bm-iii' in j_name or 'stl' in j_name:
            if pillar == 'core': return '3'
            elif pillar == 'leadership': return '2'
            else: return '3'
            
        # Team Leader, BM-I & related
        if 'team leader' in j_name or 'bm-i' in j_name or 'manager' in j_name:
            if pillar == 'core': return '3'
            elif pillar == 'leadership': return '2'
            else: return '4'
            
        # Non Supervisory Job Grade 11-12
        if any(x in g_name for x in ['11', '12', 'xi', 'xii']):
            if pillar == 'core': return '2'
            elif pillar == 'leadership': return '1'
            else: return '4'
            
        # Non Supervisory Job Grade 7-10
        if any(x in g_name for x in ['7', '8', '9', '10', 'vii', 'viii', 'ix', 'x']):
            if pillar == 'core': return '2'
            elif pillar == 'leadership': return '1'
            else: return '3'
            
        # Default / Grade 6 and below
        if pillar == 'core': return '1'
        elif pillar == 'leadership': return '1'
        else: return '2'

    @api.onchange('employee_id')
    def _onchange_employee_id_populate_competencies(self):
        """Automatically populate/refresh competency rating lines when employee_id changes in draft state."""
        if self.state == 'draft' and self.employee_id:
            self._do_populate_lines()

    def _do_populate_lines(self):
        """Internal helper to populate competency rating lines for self.employee_id according to configured pillar scope."""
        self = self.sudo()
        if not self.employee_id:
            self.line_ids = [(5, 0, 0)]
            return 0, ''
        
        # Determine allowed pillars for this assessment_type from configuration
        config = self.env['competency.matrix.config'].get_active_config()
        allowed_pillars = config.get_allowed_pillars_for_type(self.assessment_type or 'self')

        employee = self.employee_id
        job_pos = employee.job_id or getattr(employee, 'job_position', False)
        mapping = False
        if job_pos:
            emp_ou = getattr(employee, 'default_operating_unit_id', False) or getattr(employee.department_id, 'operating_unit_id', False)
            
            # Priority 1: Specific Operating Unit Mapping
            if emp_ou:
                mapping = self.env['competency.role.mapping'].search([
                    ('job_position_id', '=', job_pos.id),
                    ('state', '=', 'approved'),
                    ('is_operating_unit_specific', '=', True),
                    ('operating_unit_ids', 'in', [emp_ou.id])
                ], order='id desc', limit=1)

            # Priority 2: Global / All Operating Units Mapping
            if not mapping:
                mapping = self.env['competency.role.mapping'].search([
                    ('job_position_id', '=', job_pos.id),
                    ('state', '=', 'approved'),
                    ('is_operating_unit_specific', '=', False)
                ], order='id desc', limit=1)

            # Priority 3: General Fallback (any approved)
            if not mapping:
                mapping = self.env['competency.role.mapping'].search([
                    ('job_position_id', '=', job_pos.id),
                    ('state', '=', 'approved')
                ], order='id desc', limit=1)

            # Priority 4: Draft/Any mapping
            if not mapping:
                mapping = self.env['competency.role.mapping'].search([
                    ('job_position_id', '=', job_pos.id)
                ], order='id desc', limit=1)

        raw_line_vals = []
        if mapping and mapping.line_ids:
            for mline in mapping.line_ids:
                if mline.competency_id:
                    cpillar = mline.competency_id.pillar or 'technical'
                    if cpillar in allowed_pillars:
                        raw_line_vals.append({
                            'competency_id': mline.competency_id.id,
                            'pillar': cpillar,
                            'current_level': False,
                            'required_level': mline.required_proficiency or '2',
                        })
            mapping_name_str = mapping.mapping_name
        else:
            grade_rec = self._resolve_employee_grade(employee)
            j_name = job_pos.name if job_pos else ''
            j_lower = j_name.lower()
            is_managerial = any(k in j_lower for k in ['manager', 'director', 'chief', 'leader', 'head', 'supervisor', 'president', 'vp']) or getattr(employee, 'is_managerial', False)

            if 'core' in allowed_pillars:
                core_comps = self.env['competency.competency'].search([('pillar', '=', 'core'), ('status', '=', 'active')])
                for comp in core_comps:
                    req_lvl = self._get_matrix_required_level('core', grade=grade_rec, job=job_pos, job_name=j_name)
                    raw_line_vals.append({
                        'competency_id': comp.id,
                        'pillar': 'core',
                        'current_level': False,
                        'required_level': req_lvl or '2',
                    })

            if 'leadership' in allowed_pillars and is_managerial:
                lead_comps = self.env['competency.competency'].search([('pillar', '=', 'leadership'), ('status', '=', 'active')])
                for comp in lead_comps:
                    req_lvl = self._get_matrix_required_level('leadership', grade=grade_rec, job=job_pos, job_name=j_name)
                    raw_line_vals.append({
                        'competency_id': comp.id,
                        'pillar': 'leadership',
                        'current_level': False,
                        'required_level': req_lvl or '2',
                    })

            if 'technical' in allowed_pillars:
                tech_comps = self.env['competency.competency']
                if job_pos and getattr(job_pos, 'department_id', False):
                    dept_name = job_pos.department_id.name
                    tech_comps = self.env['competency.competency'].search([
                        ('pillar', '=', 'technical'),
                        ('status', '=', 'active'),
                        ('functional_domain', '=ilike', dept_name)
                    ])
                if not tech_comps:
                    tech_comps = self.env['competency.competency'].search([
                        ('pillar', '=', 'technical'),
                        ('status', '=', 'active')
                    ], limit=5)

                for comp in tech_comps:
                    req_lvl = self._get_matrix_required_level('technical', grade=grade_rec, job=job_pos, job_name=j_name)
                    raw_line_vals.append({
                        'competency_id': comp.id,
                        'pillar': 'technical',
                        'current_level': False,
                        'required_level': req_lvl or '2',
                    })

            mapping_name_str = _("Competency Matrix Guidelines (%s)") % (j_name or 'Default')

        # Check if record is saved (real database integer ID) or unsaved (onchange/NewId)
        if isinstance(self.id, int):
            self.line_ids.sudo().unlink()
            if raw_line_vals:
                create_vals = [dict(v, assessment_id=self.id) for v in raw_line_vals]
                created_lines = self.env['competency.assessment.line'].sudo().create(create_vals)
                cnt = len(created_lines)
            else:
                cnt = 0
        else:
            commands = [(5, 0, 0)] + [(0, 0, v) for v in raw_line_vals]
            self.line_ids = commands
            cnt = len(raw_line_vals)

        return cnt, mapping_name_str

    def action_populate_competencies(self):
        """Populate competency rating lines explicitly upon user clicking 'Populate Competencies'."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Competencies can only be populated when the assessment is in Draft state."))
        if not self.cycle_id or not self.assessment_type or not self.employee_id:
            raise UserError(_("Assessment Cycle, Assessment Type, and Employee are required before populating competencies."))
        
        cnt, mapping_name_str = self.with_context(force_write=True)._do_populate_lines()
        self.message_post(body=_('Competency rating lines populated from %s (%d competencies).') % (mapping_name_str, cnt))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Competency Assessment'),
            'res_model': 'competency.assessment',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'main',
        }

    def action_auto_fill_lines(self):
        return self.action_populate_competencies()

    def _check_submission_deadline(self):
        """Guard method: Enforce cycle submission deadline (FR-ASM-005)."""
        today = fields.Date.today()
        for rec in self:
            dl = fields.Date.to_date(rec.cycle_id.assessment_deadline) if (rec.cycle_id and rec.cycle_id.assessment_deadline) else False
            if dl and today > dl:
                deadline_str = dl.strftime('%b %d, %Y')
                raise UserError(_(
                    "The submission deadline (%s) for assessment cycle '%s' has passed. "
                    "Submissions are no longer accepted unless HR extends the deadline."
                ) % (deadline_str, rec.cycle_id.name))

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state == 'locked' and not force_write and not self.env.su:
                locked_fields = {'employee_id', 'cycle_id', 'assessment_type', 'assessor_id', 'line_ids', 'notes'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(_("Assessment %s is locked. Only Competency Administrators can unlock finalized assessments using the Unlock action.") % rec.name)
            today = fields.Date.today()
            cycle = rec.cycle_id.sudo() if rec.cycle_id else False
            dl = fields.Date.to_date(cycle.assessment_deadline) if (cycle and cycle.assessment_deadline) else False
            is_expired = rec.is_deadline_passed or bool(dl and today > dl)
            if is_expired and rec.state == 'draft' and not force_write:
                protected_fields = {'employee_id', 'cycle_id', 'assessment_type', 'assessor_id', 'line_ids', 'core_line_ids', 'leadership_line_ids', 'technical_line_ids', 'notes'}
                if set(vals.keys()) & protected_fields:
                    deadline_str = dl.strftime('%b %d, %Y') if dl else 'N/A'
                    raise UserError(_(
                        "The submission deadline (%s) for assessment cycle '%s' has passed. "
                        "This assessment is locked for editing and submissions are closed unless HR extends the deadline."
                    ) % (deadline_str, rec.cycle_id.name))
        return super(CompetencyAssessment, self).write(vals)

    def _notify_user_inbox_and_activity(self, target_user, summary, note, msg_text, target_rec=None):
        """Ensure notification appears in ALL Odoo notification channels:
        1. Top Header Clock Icon (mail.activity)
        2. Top Header Speech Bubble Notifications tab (mail.notification with inbox type)
        3. Direct Discuss Chat Channel popover / popup window (discuss.channel)
        """
        if not target_user:
            return
        rec_to_notify = target_rec or self
        
        # 1. Top Header Clock Icon (Activity Badge)
        rec_to_notify.activity_schedule(
            'mail.mail_activity_data_todo',
            summary=summary,
            note=note,
            user_id=target_user.id,
        )

        # 2. Document Chatter Message & In-App Notification
        if target_user.partner_id:
            msg = rec_to_notify.message_post(
                body=msg_text,
                partner_ids=[target_user.partner_id.id],
                subtype_xmlid='mail.mt_comment',
            )
            # Guarantee an unread in-app inbox notification entry
            notif = self.env['mail.notification'].sudo().search([
                ('mail_message_id', '=', msg.id),
                ('res_partner_id', '=', target_user.partner_id.id),
            ], limit=1)
            if notif:
                notif.write({'notification_type': 'inbox', 'is_read': False})
            else:
                self.env['mail.notification'].sudo().create({
                    'mail_message_id': msg.id,
                    'res_partner_id': target_user.partner_id.id,
                    'notification_type': 'inbox',
                    'notification_status': 'sent',
                    'is_read': False,
                })

            # 3. Direct Discuss Chat Channel Popup / Window (OdooBot Direct Message)
            try:
                chat_channel = self.env['discuss.channel'].sudo()._get_or_create_chat(partners_to=[target_user.partner_id.id])
                if chat_channel:
                    chat_channel.message_post(
                        body=msg_text,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
            except Exception:
                pass

    def action_submit(self):
        """Draft -> Submitted with deadline checks, unrated checks, and bidirectional employee/coach notifications (FR-COM-047)."""
        for rec in self:
            rec._check_submission_deadline()
            if not rec.line_ids:
                raise UserError(_('Add at least one competency rating line before submitting.'))
            unrated = rec.line_ids.filtered(lambda l: not l.current_level or l.current_level == '0')
            if unrated:
                unrated_names = ", ".join(unrated.mapped('competency_id.name')[:5])
                raise ValidationError(_('Validation Error: Please rate all competencies before submitting! %d competency(ies) remaining unrated: %s%s') % (
                    len(unrated), unrated_names, "..." if len(unrated) > 5 else ""
                ))
            rec.with_context(force_write=True).write({'state': 'submitted'})
            rec.line_ids._trigger_sibling_360_recompute()
            rec.message_post(body=_('Assessment %s submitted for review.') % rec.name)

            # Targeted Notifications & Systray Activities on Submission
            if rec.assessment_type == 'self':
                # Confirmation activity for employee
                if rec.employee_id and rec.employee_id.user_id:
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('Self-Assessment Submitted: %s') % rec.name,
                        note=_('Your competency self-assessment %s has been submitted successfully.') % rec.name,
                        user_id=rec.employee_id.user_id.id,
                    )

                coach_emp = rec.employee_id.coach_id or rec.employee_id.parent_id
                coach_user = coach_emp.user_id if (coach_emp and coach_emp.user_id) else False

                sup_asm = False
                if rec.cycle_id and rec.employee_id:
                    sup_asm = self.env['competency.assessment'].search([
                        ('cycle_id', '=', rec.cycle_id.id),
                        ('employee_id', '=', rec.employee_id.id),
                        ('assessment_type', 'in', ('supervisor', 'team')),
                    ], limit=1)
                    if not coach_user and sup_asm and sup_asm.assessor_id:
                        coach_user = sup_asm.assessor_id

                if coach_user:
                    msg_text = _("📥 Subordinate Employee <strong>%s</strong> has completed and submitted their Self-Assessment for cycle '<strong>%s</strong>'.") % (
                        rec.employee_id.name, rec.cycle_id.name if rec.cycle_id else ''
                    )
                    summary_str = _('Subordinate Self-Assessment Submitted: %s') % rec.employee_id.name
                    note_str = _('Employee %s has submitted their self-assessment for cycle %s. You may now evaluate.') % (
                        rec.employee_id.name, rec.cycle_id.name if rec.cycle_id else ''
                    )
                    target_rec = sup_asm or rec
                    rec._notify_user_inbox_and_activity(coach_user, summary_str, note_str, msg_text, target_rec=target_rec)

            elif rec.assessment_type in ('supervisor', 'team'):
                emp_user = rec.employee_id.user_id if (rec.employee_id and rec.employee_id.user_id) else False

                self_asm = False
                if rec.cycle_id and rec.employee_id:
                    self_asm = self.env['competency.assessment'].search([
                        ('cycle_id', '=', rec.cycle_id.id),
                        ('employee_id', '=', rec.employee_id.id),
                        ('assessment_type', '=', 'self'),
                    ], limit=1)

                coach_name = rec.assessor_id.name if rec.assessor_id else _("Supervisor/Coach")
                msg_text = _("✅ Your supervisor/coach (<strong>%s</strong>) has completed and submitted your competency assessment for cycle '<strong>%s</strong>'.") % (
                    coach_name, rec.cycle_id.name if rec.cycle_id else ''
                )
                summary_str = _('Supervisor Assessment Completed: %s') % coach_name
                note_str = _('Your supervisor/coach (%s) has completed and submitted your competency assessment for cycle \'%s\'.') % (
                    coach_name, rec.cycle_id.name if rec.cycle_id else ''
                )

                if emp_user:
                    target_rec = self_asm or rec
                    rec._notify_user_inbox_and_activity(emp_user, summary_str, note_str, msg_text, target_rec=target_rec)

    def compute_aggregate_360_ratings(self):
        return self.action_consolidate_multi_source()

    def _check_segregation_of_duties(self):
        """Segregation of duties guard: Block self-approval by subject, assessor, or creator (FR-COM-055)."""
        for rec in self:
            subject_user = rec.employee_id.user_id if rec.employee_id else False
            assessor_user = rec.assessor_id or False
            creator_user = rec.create_uid or False
            current_user = self.env.user

            if not self.env.su:
                if (subject_user and current_user == subject_user) or \
                   (assessor_user and current_user == assessor_user) or \
                   (creator_user and current_user == creator_user):
                    raise ValidationError(_("You cannot approve your own assessment/IDP. This action must be performed by a different authorized user."))

    def action_supervisor_review(self):
        """Submitted -> Supervisor Review with supervisor activity notification (FR-COM-048)."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'supervisor_review'})
            supervisor_user = rec.employee_id.parent_id.user_id if (rec.employee_id and rec.employee_id.parent_id) else False
            if supervisor_user:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Supervisor Review Needed: Assessment %s') % rec.name,
                    note=_('Please review and complete assessment for %s.') % rec.employee_id.name,
                    user_id=supervisor_user.id,
                    date_deadline=rec.cycle_id.assessment_deadline or fields.Date.context_today(self),
                )

    def action_hr_verify(self):
        for rec in self:
            rec._check_segregation_of_duties()
            rec.with_context(force_write=True).write({'state': 'hr_verified'})

    def action_approve(self):
        """Approved -> final approval with Segregation of Duties guard (FR-COM-055)."""
        for rec in self:
            rec._check_segregation_of_duties()
            rec.with_context(force_write=True).write({'state': 'approved'})
            rec.message_post(body=_('Assessment %s approved.') % rec.name)
            
            gap_lines = rec.line_ids.filtered(lambda l: int(l.current_level or 1) < int(l.required_level or 1))
            # Auto-feed TNA entry into EDS cycle if EDS is available
            if 'eds.tna.entry' in self.env:
                cycle = self.env['eds.tna.cycle'].search([('state', 'in', ['draft', 'collecting'])], limit=1)
                if cycle:
                    for line in gap_lines:
                        existing_tna = self.env['eds.tna.entry'].search([
                            ('cycle_id', '=', cycle.id),
                            ('employee_id', '=', rec.employee_id.id),
                            ('competency_id', '=', line.competency_id.id),
                        ], limit=1)
                        if not existing_tna:
                            self.env['eds.tna.entry'].create({
                                'cycle_id': cycle.id,
                                'employee_id': rec.employee_id.id,
                                'competency_id': line.competency_id.id,
                                'source': 'competency_gap',
                                'justification': _('Auto-generated from Competency Assessment %s gap.') % rec.name,
                            })

    def action_lock(self):
        """Lock finalized assessment against further modification."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'locked'})
            rec.message_post(body=_('Assessment %s locked.') % rec.name)

    def action_unlock(self):
        """Authorized override with justification."""
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('competency_management.group_competency_admin')):
            raise UserError(_('Only Competency Administrators can unlock finalized assessments.'))
        if not self.notes:
            raise UserError(_('Provide a justification in Notes before unlocking.'))
        self.with_context(force_write=True).write({'state': 'approved'})
        self.message_post(body=_('Assessment %s unlocked by %s.') % (self.name, self.env.user.name))



    @api.model
    def _cron_pending_assessment_reminders(self):
        """Daily cron: pending assessment reminders, upcoming deadline alerts & overdue escalations (FR-COM-046, FR-COM-048)."""
        today = fields.Date.context_today(self)
        
        # 1. Upcoming Deadline Alerts (7 days, 3 days, 1 day before deadline)
        upcoming_assessments = self.search([
            ('state', 'in', ['draft', 'submitted', 'supervisor_review']),
            ('cycle_id.assessment_deadline', '!=', False),
            ('cycle_id.assessment_deadline', '>', today)
        ])
        for asm in upcoming_assessments:
            days_left = (asm.cycle_id.assessment_deadline - today).days
            if days_left in (7, 3, 1):
                target_user = False
                if asm.state in ('draft', 'submitted') and asm.employee_id.user_id:
                    target_user = asm.employee_id.user_id
                elif asm.state == 'supervisor_review' and asm.employee_id.parent_id and asm.employee_id.parent_id.user_id:
                    target_user = asm.employee_id.parent_id.user_id
                    
                if target_user:
                    asm.activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('UPCOMING DEADLINE (%d days left): Competency Assessment %s') % (days_left, asm.name),
                        note=_('Reminder: Your competency assessment %s is due in %d days (Deadline: %s).') % (asm.name, days_left, asm.cycle_id.assessment_deadline),
                        user_id=target_user.id,
                        date_deadline=asm.cycle_id.assessment_deadline,
                    )

        # 2. Overdue Assessments (Deadline reached or passed)
        overdue_assessments = self.search([
            ('state', 'in', ['draft', 'submitted', 'supervisor_review']),
            ('cycle_id.assessment_deadline', '!=', False),
            ('cycle_id.assessment_deadline', '<=', today)
        ])
        for asm in overdue_assessments:
            target_user = False
            if asm.state in ('draft', 'submitted') and asm.employee_id.user_id:
                target_user = asm.employee_id.user_id
            elif asm.state == 'supervisor_review' and asm.employee_id.parent_id and asm.employee_id.parent_id.user_id:
                target_user = asm.employee_id.parent_id.user_id
                
            if target_user:
                asm.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('OVERDUE: Competency Assessment %s') % asm.name,
                    note=_('URGENT: Competency Assessment %s passed its deadline (%s) and is overdue for completion.') % (asm.name, asm.cycle_id.assessment_deadline),
                    user_id=target_user.id,
                    date_deadline=today,
                )

    def get_achievement_summary_sentence(self):
        """Returns plain-language alignment sentence (FR-RPT-001 / FR-GAP-007)."""
        self.ensure_one()
        total = len(self.line_ids)
        if not total:
            return _("No competencies rated for position %s.") % (self.job_id.name if self.job_id else 'N/A')
        meets_or_exceeds = len(self.line_ids.filtered(lambda l: l.achievement_status in ('meets', 'exceeds')))
        pct = round((meets_or_exceeds / total) * 100, 1)
        job_name = self.job_id.name if self.job_id else 'assigned position'
        return _("Employee meets %d of %d required competencies (%s%% alignment) for position %s.") % (
            meets_or_exceeds, total, pct, job_name
        )

    def get_recommended_development_actions(self):
        """Returns recommended action mappings for below-status competencies (FR-GAP-004)."""
        self.ensure_one()
        below_lines = self.line_ids.filtered(lambda l: l.achievement_status == 'below')
        recommendations = []
        for line in below_lines:
            comp_name = line.competency_id.name
            pillar = line.pillar or 'technical'
            gap = line.gap or 1
            if pillar == 'core':
                action = _("Structured Corporate Culture & Execution Workshop / Peer Coaching")
            elif pillar == 'leadership':
                action = _("Executive Leadership Mentoring & Supervisory Management Seminar")
            else:
                if gap > 1:
                    action = _("Formal Technical Training Program & Intensive Hands-on Workshop")
                else:
                    action = _("On-the-job Coaching & Guided Shadowing with Senior Officer")
            recommendations.append({
                'competency': comp_name,
                'pillar': pillar.capitalize(),
                'gap': gap,
                'priority': (line.gap_priority or 'medium').capitalize(),
                'action': action,
            })
        return recommendations


class CompetencyAssessmentLine(models.Model):
    """One competency rating inside an assessment (FR-ASM-006, FR-GAP-005)."""
    _name = 'competency.assessment.line'
    _description = 'Competency Assessment Line'

    assessment_id = fields.Many2one(
        'competency.assessment', string='Assessment', required=True, ondelete='cascade')
    cycle_id = fields.Many2one(related='assessment_id.cycle_id', string='Assessment Cycle', store=True, readonly=True, index=True)
    employee_id = fields.Many2one(related='assessment_id.employee_id', string='Employee', store=True, readonly=True, index=True)
    department_id = fields.Many2one(related='assessment_id.department_id', string='Department', store=True, readonly=True, index=True)
    operating_unit_id = fields.Many2one(related='assessment_id.employee_id.operating_unit_id', string='Operating Unit', store=True, readonly=True, index=True)
    job_id = fields.Many2one(related='assessment_id.job_id', string='Job Position', store=True, readonly=True, index=True)
    grade_id = fields.Many2one(related='assessment_id.employee_id.grade_id', string='Job Grade', store=True, readonly=True, index=True)
    state = fields.Selection(related='assessment_id.state', string='Assessment Status', store=True, readonly=True, index=True)
    is_deadline_passed = fields.Boolean(related='assessment_id.is_deadline_passed', string='Deadline Passed', readonly=True)

    tna_measure = fields.Selection([
        ('below', 'Underqualified'),
        ('meets', 'Fit'),
        ('exceeds', 'Overqualified'),
    ], string='Fitness Status', compute='_compute_tna_measure', store=True, index=True)

    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade',
        domain="[('state', '=', 'approved'), ('status', '=', 'active')]")
    functional_domain = fields.Char(related='competency_id.functional_domain', string='Functional Domain', store=True, readonly=True)
    competency_definition = fields.Text(related='competency_id.definition', string='Competency Definition', readonly=True)
    pillar = fields.Selection(related='competency_id.pillar', string='Pillar', readonly=True, store=True)
    
    indicator_level_1 = fields.Text(string='Level 1 (Basic) Indicator', compute='_compute_level_indicators')
    indicator_level_2 = fields.Text(string='Level 2 (Intermediate) Indicator', compute='_compute_level_indicators')
    indicator_level_3 = fields.Text(string='Level 3 (Advanced) Indicator', compute='_compute_level_indicators')
    indicator_level_4 = fields.Text(string='Level 4 (Expert) Indicator', compute='_compute_level_indicators')
    current_level_indicator = fields.Text(string='Level Indicator Preview', compute='_compute_current_level_indicator')
    
    behavioral_guide_html = fields.Html(string='Proficiency Behavioral Indicators Guide', compute='_compute_level_indicators')

    @api.depends('current_level', 'indicator_level_1', 'indicator_level_2', 'indicator_level_3', 'indicator_level_4')
    def _compute_current_level_indicator(self):
        for rec in self:
            lvl = str(rec.current_level or '1')
            if lvl == '1':
                rec.current_level_indicator = rec.indicator_level_1 or 'Level 1 Basic behavioral indicator.'
            elif lvl == '2':
                rec.current_level_indicator = rec.indicator_level_2 or 'Level 2 Intermediate behavioral indicator.'
            elif lvl == '3':
                rec.current_level_indicator = rec.indicator_level_3 or 'Level 3 Advanced behavioral indicator.'
            elif lvl == '4':
                rec.current_level_indicator = rec.indicator_level_4 or 'Level 4 Expert behavioral indicator.'
            else:
                rec.current_level_indicator = False

    @api.depends('competency_id')
    def _compute_level_indicators(self):
        matrix_config = self.env['competency.matrix.config'].get_active_config()
        for rec in self:
            if rec.competency_id:
                levels = self.env['competency.proficiency.level'].search([
                    ('competency_id', '=', rec.competency_id.id)
                ])
                l_map = {l.level: l.behavioral_indicators for l in levels if l.behavioral_indicators}
                
                l1 = l_map.get('1') or (getattr(matrix_config, 'tech_indicator_level_1') if rec.competency_id.pillar == 'technical' else 'Level 1 (Basic) behavioral indicators.')
                l2 = l_map.get('2') or (getattr(matrix_config, 'tech_indicator_level_2') if rec.competency_id.pillar == 'technical' else 'Level 2 (Intermediate) behavioral indicators.')
                l3 = l_map.get('3') or (getattr(matrix_config, 'tech_indicator_level_3') if rec.competency_id.pillar == 'technical' else 'Level 3 (Advanced) behavioral indicators.')
                l4 = l_map.get('4') or (getattr(matrix_config, 'tech_indicator_level_4') if rec.competency_id.pillar == 'technical' else 'Level 4 (Expert) behavioral indicators.')
                
                rec.indicator_level_1 = l1
                rec.indicator_level_2 = l2
                rec.indicator_level_3 = l3
                rec.indicator_level_4 = l4
                
                rec.behavioral_guide_html = f"""
                <div style="font-family: inherit; font-size: 13px; color: #1d2b32;">
                    <div style="margin-bottom: 8px; padding: 8px 12px; background-color: #f8f9fa; border-left: 4px solid #726732; border-radius: 4px;">
                        <strong style="color: #726732;">Level 1 (Basic):</strong> {l1}
                    </div>
                    <div style="margin-bottom: 8px; padding: 8px 12px; background-color: #f8f9fa; border-left: 4px solid #1d2b32; border-radius: 4px;">
                        <strong style="color: #1d2b32;">Level 2 (Intermediate):</strong> {l2}
                    </div>
                    <div style="margin-bottom: 8px; padding: 8px 12px; background-color: #f8f9fa; border-left: 4px solid #c17540; border-radius: 4px;">
                        <strong style="color: #c17540;">Level 3 (Advanced):</strong> {l3}
                    </div>
                    <div style="margin-bottom: 8px; padding: 8px 12px; background-color: #f8f9fa; border-left: 4px solid #541718; border-radius: 4px;">
                        <strong style="color: #541718;">Level 4 (Expert):</strong> {l4}
                    </div>
                </div>
                """
            else:
                rec.indicator_level_1 = False
                rec.indicator_level_2 = False
                rec.indicator_level_3 = False
                rec.indicator_level_4 = False
                rec.behavioral_guide_html = False

    current_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Current Proficiency', required=False, default=False)
    required_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Required Proficiency', required=True, default='2')
    gap = fields.Integer(string='Gap', compute='_compute_gap', store=True, group_operator='avg',
                         help='Required minus Current proficiency (positive = development gap).')
    current_level_num = fields.Integer(string='Current Level (Numeric)', compute='_compute_level_nums', store=True, group_operator='avg')
    required_level_num = fields.Integer(string='Required Level (Numeric)', compute='_compute_level_nums', store=True, group_operator='avg')

    # 360 Multi-Rater Ratings Breakdown
    self_rating = fields.Float(string='Self Rating', compute='_compute_360_ratings', store=True, group_operator='avg')
    peer_avg = fields.Float(string='Peer Avg', compute='_compute_360_ratings', store=True, group_operator='avg')
    subordinate_avg = fields.Float(string='Subordinate Avg', compute='_compute_360_ratings', store=True, group_operator='avg')
    supervisor_avg = fields.Float(string='Supervisor Avg', compute='_compute_360_ratings', store=True, group_operator='avg')
    team_avg = fields.Float(string='Team Avg', compute='_compute_360_ratings', store=True, group_operator='avg')
    weighted_current_level = fields.Float(string='Weighted Current Level', compute='_compute_360_ratings', store=True, group_operator='avg')

    @api.depends('assessment_id.employee_id', 'assessment_id.cycle_id', 'competency_id', 'current_level')
    def _compute_360_ratings(self):
        config = self.env['competency.matrix.config'].sudo().get_active_config()
        w_self = float(config.weight_self or 2.0)
        w_peer = float(config.weight_peer or 1.0)
        w_sub = float(config.weight_subordinate or 1.0)
        w_sup = float(config.weight_supervisor or 3.0)
        w_team = float(config.weight_team or 0.0)

        for line in self:
            emp = line.employee_id
            cycle = line.cycle_id
            comp = line.competency_id

            if not (emp and cycle and comp):
                s_init = int(line.current_level) if line.current_level and str(line.current_level).isdigit() else 0.0
                line.self_rating = s_init if line.assessment_id.assessment_type == 'self' else 0.0
                line.peer_avg = 0.0
                line.subordinate_avg = 0.0
                line.supervisor_avg = s_init if line.assessment_id.assessment_type in ('supervisor', 'team') else 0.0
                line.team_avg = 0.0
                line.weighted_current_level = s_init
                continue

            comp_lines = self.env['competency.assessment.line'].sudo().search([
                ('employee_id', '=', emp.id),
                ('cycle_id', '=', cycle.id),
                ('competency_id', '=', comp.id),
                ('current_level', '!=', False)
            ])

            self_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'self']
            peer_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'peer']
            sub_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'subordinate']
            sup_lines = [l for l in comp_lines if l.assessment_id.assessment_type in ('supervisor', 'team')]
            team_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'team_member_eval']

            s_val = int(self_lines[0].current_level) if (self_lines and str(self_lines[0].current_level).isdigit()) else (int(line.current_level) if (line.assessment_id.assessment_type == 'self' and line.current_level and str(line.current_level).isdigit()) else 0.0)
            p_val = round(sum(int(l.current_level) for l in peer_lines if str(l.current_level).isdigit()) / len(peer_lines), 2) if peer_lines else 0.0
            sub_val = round(sum(int(l.current_level) for l in sub_lines if str(l.current_level).isdigit()) / len(sub_lines), 2) if sub_lines else 0.0
            sup_val = round(sum(int(l.current_level) for l in sup_lines if str(l.current_level).isdigit()) / len(sup_lines), 2) if sup_lines else 0.0
            t_val = round(sum(int(l.current_level) for l in team_lines if str(l.current_level).isdigit()) / len(team_lines), 2) if team_lines else 0.0

            line.self_rating = float(s_val)
            line.peer_avg = float(p_val)
            line.subordinate_avg = float(sub_val)
            line.supervisor_avg = float(sup_val)
            line.team_avg = float(t_val)

            num = 0.0
            den = 0.0
            if s_val:
                num += s_val * w_self
                den += w_self
            if p_val:
                num += p_val * w_peer
                den += w_peer
            if sub_val:
                num += sub_val * w_sub
                den += w_sub
            if sup_val:
                num += sup_val * w_sup
                den += w_sup
            elif t_val and w_team > 0:
                num += t_val * w_team
                den += w_team

            line.weighted_current_level = round(num / den, 2) if den > 0 else float(s_val or sup_val or sub_val or t_val or 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        force_write = self.env.context.get('force_write')
        for vals in vals_list:
            if not force_write and not self.env.su and vals.get('assessment_id'):
                asm = self.env['competency.assessment'].browse(vals['assessment_id'])
                if asm.state == 'locked':
                    raise ValidationError(_("Cannot add rating lines to locked assessment %s.") % asm.name)
                today = fields.Date.today()
                dl = fields.Date.to_date(asm.cycle_id.assessment_deadline) if (asm.cycle_id and asm.cycle_id.assessment_deadline) else False
                if (asm.is_deadline_passed or (dl and today > dl)) and asm.state == 'draft':
                    deadline_str = dl.strftime('%b %d, %Y') if dl else 'N/A'
                    raise UserError(_(
                        "The submission deadline (%s) for assessment cycle '%s' has passed. "
                        "Rating lines cannot be added or edited after the deadline."
                    ) % (deadline_str, asm.cycle_id.name))
        lines = super().create(vals_list)
        if not self.env.context.get('skip_360_recompute'):
            lines._trigger_sibling_360_recompute()
        return lines

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for line in self:
            if not force_write and not self.env.su and line.assessment_id:
                asm = line.assessment_id
                if asm.state == 'locked':
                    raise ValidationError(_("Cannot modify rating lines on locked assessment %s.") % asm.name)
                today = fields.Date.today()
                dl = fields.Date.to_date(asm.cycle_id.assessment_deadline) if (asm.cycle_id and asm.cycle_id.assessment_deadline) else False
                if (asm.is_deadline_passed or (dl and today > dl)) and asm.state == 'draft':
                    deadline_str = dl.strftime('%b %d, %Y') if dl else 'N/A'
                    raise UserError(_(
                        "The submission deadline (%s) for assessment cycle '%s' has passed. "
                        "Rating lines cannot be added or edited after the deadline."
                    ) % (deadline_str, asm.cycle_id.name))
        res = super().write(vals)
        if ('current_level' in vals or 'state' in vals) and not self.env.context.get('skip_360_recompute'):
            self._trigger_sibling_360_recompute()
        return res

    def _trigger_sibling_360_recompute(self):
        config = self.env['competency.matrix.config'].sudo().get_active_config()
        w_self = float(config.weight_self or 2.0)
        w_peer = float(config.weight_peer or 1.0)
        w_sub = float(config.weight_subordinate or 1.0)
        w_sup = float(config.weight_supervisor or 3.0)
        w_team = float(config.weight_team or 0.0)

        emp_cycle_comps = set()
        for line in self:
            if line.employee_id and line.cycle_id and line.competency_id:
                emp_cycle_comps.add((line.employee_id.id, line.cycle_id.id, line.competency_id.id))

        for (emp_id, cycle_id, comp_id) in emp_cycle_comps:
            comp_lines = self.env['competency.assessment.line'].sudo().search([
                ('employee_id', '=', emp_id),
                ('cycle_id', '=', cycle_id),
                ('competency_id', '=', comp_id),
                ('current_level', '!=', False)
            ])

            self_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'self']
            peer_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'peer']
            sub_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'subordinate']
            sup_lines = [l for l in comp_lines if l.assessment_id.assessment_type in ('supervisor', 'team')]
            team_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'team_member_eval']

            s_val = int(self_lines[0].current_level) if (self_lines and str(self_lines[0].current_level).isdigit()) else 0.0
            p_val = round(sum(int(l.current_level) for l in peer_lines if str(l.current_level).isdigit()) / len(peer_lines), 2) if peer_lines else 0.0
            sub_val = round(sum(int(l.current_level) for l in sub_lines if str(l.current_level).isdigit()) / len(sub_lines), 2) if sub_lines else 0.0
            sup_val = round(sum(int(l.current_level) for l in sup_lines if str(l.current_level).isdigit()) / len(sup_lines), 2) if sup_lines else 0.0
            t_val = round(sum(int(l.current_level) for l in team_lines if str(l.current_level).isdigit()) / len(team_lines), 2) if team_lines else 0.0

            num = 0.0
            den = 0.0
            if s_val:
                num += s_val * w_self
                den += w_self
            if p_val:
                num += p_val * w_peer
                den += w_peer
            if sub_val:
                num += sub_val * w_sub
                den += w_sub
            if sup_val:
                num += sup_val * w_sup
                den += w_sup
            elif t_val and w_team > 0:
                num += t_val * w_team
                den += w_team

            calc_weighted = round(num / den, 2) if den > 0 else float(s_val or sup_val or sub_val or t_val or 0.0)

            all_lines = self.env['competency.assessment.line'].sudo().search([
                ('employee_id', '=', emp_id),
                ('cycle_id', '=', cycle_id),
                ('competency_id', '=', comp_id),
            ])
            all_lines.with_context(skip_360_recompute=True).write({
                'self_rating': float(s_val),
                'peer_avg': float(p_val),
                'subordinate_avg': float(sub_val),
                'supervisor_avg': float(sup_val),
                'team_avg': float(t_val),
                'weighted_current_level': calc_weighted,
            })

    achievement_status = fields.Selection([
        ('exceeds', 'Exceeds Required Level'),
        ('meets', 'Meets Required Level'),
        ('below', 'Below Required Level'),
    ], string='Achievement Status', compute='_compute_achievement_status_and_priority', store=True)
    gap_priority = fields.Selection([
        ('high', 'High Priority'),
        ('medium', 'Medium Priority'),
        ('low', 'Low Priority / No Gap'),
    ], string='Gap Priority', compute='_compute_achievement_status_and_priority', store=True)
    comments = fields.Text(string='Comments')
    evidence_attachment_ids = fields.Many2many('ir.attachment', string='Supporting Evidence')

    is_primary_reporting_line = fields.Boolean(
        string='Is Primary Reporting Line', compute='_compute_is_primary_reporting_line', store=True, index=True,
        help='Designates the single consolidated line per (employee, cycle, competency) used for reporting views.')

    @api.depends('assessment_id.assessment_type', 'assessment_id.employee_id', 'assessment_id.cycle_id', 'competency_id')
    def _compute_is_primary_reporting_line(self):
        emp_cycle_comps = set()
        for line in self:
            if line.employee_id and line.cycle_id and line.competency_id:
                emp_cycle_comps.add((line.employee_id.id, line.cycle_id.id, line.competency_id.id))

        for (emp_id, cycle_id, comp_id) in emp_cycle_comps:
            comp_lines = self.env['competency.assessment.line'].sudo().search([
                ('employee_id', '=', emp_id),
                ('cycle_id', '=', cycle_id),
                ('competency_id', '=', comp_id),
            ], order='id asc')

            self_line = comp_lines.filtered(lambda l: l.assessment_id.assessment_type == 'self')
            if self_line:
                primary_id = self_line[0].id
            else:
                sup_line = comp_lines.filtered(lambda l: l.assessment_id.assessment_type in ('supervisor', 'team'))
                primary_id = sup_line[0].id if sup_line else (comp_lines[0].id if comp_lines else False)

            for l in comp_lines:
                l.is_primary_reporting_line = (l.id == primary_id)

        for line in self:
            if not (line.employee_id and line.cycle_id and line.competency_id):
                line.is_primary_reporting_line = True

    @api.constrains('competency_id')
    def _check_competency_status(self):
        for line in self:
            if line.competency_id and line.competency_id.state == 'retired':
                raise ValidationError(_("The competency '%s' is retired and cannot be assessed.") % line.competency_id.name)

    @api.depends('current_level', 'required_level', 'weighted_current_level')
    def _compute_level_nums(self):
        for rec in self:
            c_num = 0
            if rec.current_level and str(rec.current_level).isdigit():
                c_num = int(rec.current_level)
            elif rec.weighted_current_level:
                c_num = int(round(rec.weighted_current_level))
            rec.current_level_num = c_num
            rec.required_level_num = int(rec.required_level) if rec.required_level and str(rec.required_level).isdigit() else 0

    @api.depends('current_level_num', 'required_level_num')
    def _compute_gap(self):
        for rec in self:
            if rec.current_level_num:
                rec.gap = rec.required_level_num - rec.current_level_num
            else:
                rec.gap = False

    @api.depends('gap', 'current_level_num')
    def _compute_tna_measure(self):
        for rec in self:
            if not rec.current_level_num:
                rec.tna_measure = False
                continue
            gap_val = rec.gap or 0
            if gap_val > 0:
                rec.tna_measure = 'below'
            elif gap_val == 0:
                rec.tna_measure = 'meets'
            else:
                rec.tna_measure = 'exceeds'

    @api.depends('gap', 'current_level_num')
    def _compute_achievement_status_and_priority(self):
        for rec in self:
            if not rec.current_level_num:
                rec.achievement_status = False
                rec.gap_priority = False
                continue
            gap_val = rec.gap or 0
            if gap_val < 0:
                rec.achievement_status = 'exceeds'
                rec.gap_priority = 'low'
            elif gap_val == 0:
                rec.achievement_status = 'meets'
                rec.gap_priority = 'low'
            elif gap_val == 1:
                rec.achievement_status = 'below'
                rec.gap_priority = 'medium'
            else:
                rec.achievement_status = 'below'
                rec.gap_priority = 'high'

    _sql_constraints = [
        ('assessment_competency_uniq', 'unique(assessment_id, competency_id)',
         'This competency is already rated in the assessment!'),
    ]

    @api.ondelete(at_uninstall=False)
    def _prevent_unlink_on_locked(self):
        for line in self:
            if line.assessment_id and not self.env.context.get('force_write') and not self.env.su:
                if line.assessment_id.state == 'locked':
                    raise ValidationError(_("Cannot delete rating lines from locked assessment %s.") % line.assessment_id.name)
                if line.assessment_id.is_deadline_passed and line.assessment_id.state == 'draft':
                    deadline_str = line.assessment_id.cycle_id.assessment_deadline.strftime('%b %d, %Y') if line.assessment_id.cycle_id and line.assessment_id.cycle_id.assessment_deadline else 'N/A'
                    raise UserError(_("The submission deadline (%s) for cycle '%s' has passed. Rating lines cannot be deleted.") % (deadline_str, line.assessment_id.cycle_id.name))

    def action_view_360_breakdown(self):
        """Action button to open the 360° Rater Score Breakdown pop-up modal wizard."""
        self.ensure_one()
        if self.employee_id.user_id == self.env.user and not self.env.user.has_group('competency_management.group_competency_supervisor') and not self.env.su:
            raise UserError(_("Individual multi-rater score breakdowns are restricted to Supervisors and HR Officers to maintain 360-degree feedback anonymity."))
        emp = self.employee_id
        cycle = self.cycle_id
        comp = self.competency_id

        # Search for all rated lines for this (employee, cycle, competency)
        rated_lines = self.env['competency.assessment.line'].sudo().search([
            ('employee_id', '=', emp.id),
            ('cycle_id', '=', cycle.id),
            ('competency_id', '=', comp.id),
            ('current_level', '!=', False)
        ], order='id asc')

        breakdown_lines_vals = []
        for r_line in rated_lines:
            asm = r_line.assessment_id
            assessor = asm.assessor_id
            assessor_emp = assessor.employee_id if (assessor and getattr(assessor, 'employee_id', False)) else False
            
            # Anonymize peer/subordinate names if anonymized 360 settings are active
            if asm.is_anonymous and asm.assessment_type in ('peer', 'subordinate'):
                r_name = _("Anonymous 360 Rater (%s)") % asm.assessment_type.capitalize()
            elif assessor_emp:
                r_name = assessor_emp.name
            elif assessor:
                r_name = assessor.name
            else:
                r_name = _("System / Unassigned")

            lvl_map = {'1': 'Level 1 - Basic', '2': 'Level 2 - Intermediate', '3': 'Level 3 - Advanced', '4': 'Level 4 - Expert'}
            lvl_str = lvl_map.get(str(r_line.current_level), f"Level {r_line.current_level}")
            
            state_map = dict(asm._fields['state'].selection or [])
            st_label = state_map.get(asm.state, asm.state.capitalize())

            breakdown_lines_vals.append((0, 0, {
                'assessor_name': r_name,
                'rater_type': asm.assessment_type or 'self',
                'rating_level_str': lvl_str,
                'rating_num': int(r_line.current_level) if str(r_line.current_level).isdigit() else 0,
                'assessment_name': asm.name or '',
                'assessment_state': st_label,
                'comments': r_line.comments or '',
            }))

        wizard = self.env['competency.rater.breakdown.wizard'].create({
            'line_id': self.id,
            'employee_id': emp.id if emp else False,
            'department_id': self.department_id.id if self.department_id else False,
            'job_id': self.job_id.id if self.job_id else False,
            'cycle_id': cycle.id if cycle else False,
            'competency_id': comp.id if comp else False,
            'self_rating': self.self_rating,
            'peer_avg': self.peer_avg,
            'subordinate_avg': self.subordinate_avg,
            'supervisor_avg': self.supervisor_avg,
            'team_avg': self.team_avg,
            'weighted_current_level': self.weighted_current_level,
            'rater_line_ids': breakdown_lines_vals,
        })

        return {
            'name': _('360° Rater Score Breakdown: %s — %s') % (comp.name if comp else '', emp.name if emp else ''),
            'type': 'ir.actions.act_window',
            'res_model': 'competency.rater.breakdown.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }




