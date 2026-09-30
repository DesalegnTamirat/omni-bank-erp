# -*- coding: utf-8 -*-
from markupsafe import Markup, escape
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError, AccessError


class CompetencyAssessmentCycle(models.Model):
    """Scheduled competency assessment cycle."""
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
    active = fields.Boolean(string='Active', default=True, tracking=True)
    assessment_ids = fields.One2many('competency.assessment', 'cycle_id', string='Assessments')
    assessment_count = fields.Integer(string='Total Assessments', compute='_compute_assessment_counts')
    pending_assessment_count = fields.Integer(string='Pending Assessments', compute='_compute_assessment_counts')
    submitted_assessment_count = fields.Integer(string='Submitted Assessments', compute='_compute_assessment_counts')
    sampling_audit_log = fields.Text(string='360 Rater Sampling Audit Trail', readonly=True)
    eligible_rater_count = fields.Integer(string='Eligible Raters Pool Size', default=0, readonly=True)
    selected_rater_count = fields.Integer(string='Sampled Raters Size', default=0, readonly=True)
    notes = fields.Text(string='Notes')
    is_open_or_latest = fields.Boolean(
        string='Is Current or Latest Cycle',
        compute='_compute_is_open_or_latest', store=True, index=True
    )

    @api.constrains('name')
    def _check_unique_name(self):
        for rec in self:
            if rec.name:
                duplicate = self.search([
                    ('id', '!=', rec.id),
                    ('name', '=ilike', rec.name.strip()),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_("An Assessment Cycle named '%s' already exists. Cycle names must be unique.") % rec.name.strip())

    @api.depends('state', 'active')
    def _compute_is_open_or_latest(self):
        all_cycles = self.search([('active', '=', True)])
        open_cycles = all_cycles.filtered(lambda c: c.state == 'open')
        if open_cycles:
            target_ids = set(open_cycles.ids)
        else:
            latest = all_cycles.sorted(key=lambda c: (c.period_end or fields.Date.today(), c.id), reverse=True)
            target_ids = {latest[0].id} if latest else set()

        for rec in self:
            rec.is_open_or_latest = rec.id in target_ids

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals or 'active' in vals:
            self._recompute_is_open_or_latest_sql()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group('competency_management.group_competency_admin') and not self.env.su:
            raise UserError(_("Only Competency Administrators can create new Assessment Cycles."))
        records = super().create(vals_list)
        self._recompute_is_open_or_latest_sql()
        return records

    @api.model
    def _recompute_is_open_or_latest_sql(self):
        # Update is_open_or_latest for all cycles in a single SQL statement.
        # Open cycles take priority; if none are open, the most recently ended active cycle wins.
        self.env.cr.execute("""
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           ORDER BY
                               CASE WHEN state = 'open' THEN 0 ELSE 1 END,
                               COALESCE(period_end, CURRENT_DATE) DESC,
                               id DESC
                       ) AS rn
                FROM competency_assessment_cycle
                WHERE active = true
            )
            UPDATE competency_assessment_cycle
            SET is_open_or_latest = (id IN (SELECT id FROM ranked WHERE rn = 1));
        """)
        self.invalidate_model(['is_open_or_latest'])

    @api.depends('assessment_ids', 'assessment_ids.state')
    def _compute_assessment_counts(self):
        # Query counts in bulk for persisted cycles
        real_records = self.filtered(lambda r: isinstance(r.id, int))
        count_map = {}
        if real_records:
            grouped = self.env['competency.assessment']._read_group(
                [('cycle_id', 'in', real_records.ids)], ['cycle_id', 'state'], ['__count']
            )
            for cycle_rec, state_val, cnt in grouped:
                cid = cycle_rec.id
                if cid not in count_map:
                    count_map[cid] = {'total': 0, 'draft': 0, 'submitted': 0}
                count_map[cid]['total'] += cnt
                if state_val == 'draft':
                    count_map[cid]['draft'] += cnt
                else:
                    count_map[cid]['submitted'] += cnt

        # Always assign every record in self (including NewId during onchange/form creation)
        for rec in self:
            data = count_map.get(rec.id, {}) if isinstance(rec.id, int) else {}
            rec.assessment_count = data.get('total', 0)
            rec.pending_assessment_count = data.get('draft', 0)
            rec.submitted_assessment_count = data.get('submitted', 0)

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
        self.env.cr.execute("""
            SELECT DISTINCT ca.assessor_id
            FROM competency_assessment ca
            WHERE ca.cycle_id = %s AND ca.state = 'draft' AND ca.active = TRUE AND ca.assessor_id IS NOT NULL;
        """, (self.id,))
        pending_assessor_ids = [r[0] for r in self.env.cr.fetchall()]
        if not pending_assessor_ids:
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

        cycle_id = self.id
        cycle_name = self.name
        dbname = self.env.cr.dbname

        import threading

        def _async_send_deadline_reminders():
            import odoo
            from odoo.modules.registry import Registry
            import logging
            _logger = logging.getLogger(__name__)
            try:
                registry = Registry(dbname)
                with registry.cursor() as new_cr:
                    new_env = odoo.api.Environment(new_cr, odoo.SUPERUSER_ID, {})
                    cycle_rec = new_env['competency.assessment.cycle'].browse(cycle_id)
                    if not cycle_rec.exists():
                        return

                    if cycle_rec.assessment_deadline:
                        deadline_str = cycle_rec.assessment_deadline.strftime('%b %d, %Y')
                        deadline_phrase = _("The submission deadline is <b>%s</b>. Please complete and submit your assessments before the deadline.") % deadline_str
                        summary_str = _("URGENT: %d Pending Assessment(s) Due %s") % (pending_count, deadline_str)
                        note_str = _("You have %d pending assessment(s) for cycle '%s'. Deadline: %s.") % (pending_count, cycle_name, deadline_str)
                    else:
                        deadline_phrase = _("Please complete and submit your assessments at your earliest convenience.")
                        summary_str = _("Action Required: %d Pending Assessment(s)") % pending_count
                        note_str = _("You have %d pending assessment(s) for cycle '%s'.") % (pending_count, cycle_name)

                    new_cr.execute("""
                        SELECT ca.assessor_id,
                               count(ca.id) as pending_count,
                               min(ca.id) as sample_assessment_id,
                               array_agg(DISTINCT he.name) as emp_names
                        FROM competency_assessment ca
                        LEFT JOIN hr_employee he ON ca.employee_id = he.id
                        WHERE ca.cycle_id = %s AND ca.state = 'draft' AND ca.active = TRUE AND ca.assessor_id IS NOT NULL
                        GROUP BY ca.assessor_id;
                    """, (cycle_id,))
                    assessor_rows = new_cr.fetchall()

                    sent_count = 0
                    for row in assessor_rows:
                        assessor_id, pending_count, sample_asm_id, emp_names = row
                        assessor = new_env['res.users'].browse(assessor_id)
                        partner = assessor.partner_id
                        if not partner:
                            continue

                        names_clean = [n for n in (emp_names or []) if n]
                        emp_names_str = ", ".join(names_clean[:5])
                        extra = _(" and %d more") % (len(names_clean) - 5) if len(names_clean) > 5 else ""

                        msg_body = Markup(_(
                            "⚠️ <b>Competency Assessment Deadline Warning:</b><br/>"
                            "You have %d pending competency assessment(s) assigned to you for cycle '<b>%s</b>' "
                            "(Assessments for: %s%s).<br/>"
                            "%s"
                            "<div style='margin-top: 10px;'>"
                            "<a href='/web#action=competency_management.action_my_competency_assessment' style='background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;'>"
                            "👉 Open My Competency Assessments</a></div>"
                        )) % (pending_count, escape(cycle_name or ''), escape(emp_names_str or ''), escape(extra or ''), deadline_phrase)

                        target_rec = new_env['competency.assessment'].browse(sample_asm_id) if sample_asm_id else cycle_rec
                        target_rec._notify_user_inbox_and_activity(
                            assessor, summary_str, note_str, msg_body, target_rec=target_rec
                        )
                        sent_count += 1

                        if sent_count % 100 == 0:
                            new_cr.commit()

                    cycle_rec.message_post(body=_("Sent deadline warning notifications to %d assessor(s) with pending draft assessments.") % sent_count)
                    new_cr.commit()
                    _logger.info("Delivered deadline warnings to %d assessors for cycle %s", sent_count, cycle_name)
            except Exception as exc:
                _logger.exception("Error sending deadline warnings for cycle %d: %s", cycle_id, exc)

        thread = threading.Thread(target=_async_send_deadline_reminders, daemon=True)
        thread.start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Deadline Warnings Queued'),
                'message': _('Deadline warning reminders are being dispatched in the background to %d assessor(s) with pending assessments. Progress will be logged in the cycle chatter.') % len(pending_assessor_ids),
                'type': 'success',
                'sticky': False,
            }
        }

    def _notify_cycle_open_to_assessors(self):
        """Asynchronously notify all employees and evaluators who have pending assessments to fill for this cycle."""
        self.ensure_one()
        return self.action_notify_assessors()

    def action_notify_assessors(self):
        """Manual button action for Competency Admin to broadcast cycle opening notification to all pending assessors."""
        self.ensure_one()
        self.env.cr.execute("""
            SELECT DISTINCT ca.assessor_id
            FROM competency_assessment ca
            WHERE ca.cycle_id = %s AND ca.state = 'draft' AND ca.active = TRUE AND ca.assessor_id IS NOT NULL;
        """, (self.id,))
        pending_assessor_ids = [r[0] for r in self.env.cr.fetchall()]
        if not pending_assessor_ids:
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

        cycle_id = self.id
        cycle_name = self.name
        dbname = self.env.cr.dbname

        import threading

        def _async_notify_cycle_open():
            import odoo
            from odoo.modules.registry import Registry
            import logging
            _logger = logging.getLogger(__name__)
            try:
                registry = Registry(dbname)
                with registry.cursor() as new_cr:
                    new_env = odoo.api.Environment(new_cr, odoo.SUPERUSER_ID, {})
                    cycle_rec = new_env['competency.assessment.cycle'].browse(cycle_id)
                    if not cycle_rec.exists():
                        return

                    if cycle_rec.assessment_deadline:
                        deadline_str = cycle_rec.assessment_deadline.strftime('%b %d, %Y')
                        deadline_line = Markup("<br/><b>Submission Deadline:</b> %s.") % deadline_str
                        deadline_note_suffix = _(" by %s") % deadline_str
                    else:
                        deadline_line = Markup("<br/><i>Please complete your evaluations at your earliest convenience.</i>")
                        deadline_note_suffix = _(" at your earliest convenience")

                    new_cr.execute("""
                        SELECT ca.assessor_id,
                               count(ca.id) as total_pending,
                               min(ca.id) as sample_assessment_id,
                               sum(CASE WHEN ca.assessment_type = 'self' THEN 1 ELSE 0 END) as self_count,
                               sum(CASE WHEN ca.assessment_type IN ('supervisor', 'team') THEN 1 ELSE 0 END) as sup_count,
                               sum(CASE WHEN ca.assessment_type = 'peer' THEN 1 ELSE 0 END) as peer_count,
                               sum(CASE WHEN ca.assessment_type = 'subordinate' THEN 1 ELSE 0 END) as sub_count
                        FROM competency_assessment ca
                        WHERE ca.cycle_id = %s AND ca.state = 'draft' AND ca.active = TRUE AND ca.assessor_id IS NOT NULL
                        GROUP BY ca.assessor_id;
                    """, (cycle_id,))
                    assessor_rows = new_cr.fetchall()

                    sent_count = 0
                    for row in assessor_rows:
                        assessor_id, total_pending, sample_asm_id, self_cnt, sup_cnt, peer_cnt, sub_cnt = row
                        assessor = new_env['res.users'].browse(assessor_id)
                        if not assessor.active or not assessor.partner_id:
                            continue

                        details = []
                        if self_cnt > 0:
                            details.append(_("Self-Assessment"))
                        if sup_cnt > 0:
                            details.append(_("%d Team Member Evaluation(s)") % sup_cnt)
                        if peer_cnt > 0:
                            details.append(_("%d Peer Evaluation(s)") % peer_cnt)
                        if sub_cnt > 0:
                            details.append(_("%d Upward Evaluation(s)") % sub_cnt)

                        details_str = ", ".join(details) if details else (_("%d Evaluation(s)") % total_pending)

                        msg_body = Markup(_(
                            "📢 <b>Competency Assessment Campaign Open: %s</b><br/>"
                            "Assessment Cycle '<b>%s</b>' is now open for evaluation.<br/>"
                            "Please navigate to <b>Competency Management → Assessments → My Competency Assessments</b> to complete your evaluations.<br/>"
                            "<b>Assigned to you:</b> %s.%s"
                            "<div style='margin-top: 10px;'>"
                            "<a href='/web#action=competency_management.action_my_competency_assessment' style='background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;'>"
                            "👉 Open My Competency Assessments</a></div>"
                        )) % (escape(cycle_name or ''), escape(cycle_name or ''), escape(details_str or ''), deadline_line)

                        summary_str = _("Fill Competency Assessment: %s") % cycle_name
                        note_str = _("Assessment cycle '%s' is open. Please complete your evaluations (%s) on the My Competency Assessments page%s.") % (
                            cycle_name, details_str, deadline_note_suffix
                        )

                        target_rec = new_env['competency.assessment'].browse(sample_asm_id) if sample_asm_id else cycle_rec
                        target_rec._notify_user_inbox_and_activity(
                            assessor, summary_str, note_str, msg_body, target_rec=target_rec
                        )
                        sent_count += 1

                        if sent_count % 100 == 0:
                            new_cr.commit()

                    cycle_rec.message_post(body=_("Sent cycle opening notifications to %d employee/assessor(s).") % sent_count)
                    new_cr.commit()
                    _logger.info("Delivered cycle open notifications to %d assessors for cycle %s", sent_count, cycle_name)
            except Exception as exc:
                _logger.exception("Error broadcasting cycle open notifications for cycle %d: %s", cycle_id, exc)

        thread = threading.Thread(target=_async_notify_cycle_open, daemon=True)
        thread.start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Notifications Queued'),
                'message': _('Cycle opening notifications are being dispatched in the background to %d employee(s)/assessor(s). Progress will be logged in the cycle chatter.') % len(pending_assessor_ids),
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
        """Draft -> Open: Sets state to open immediately and generates 360 assessments asynchronously in a background thread."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Only cycles in Draft state can be started."))

        self.with_context(force_write=True).write({'state': 'open'})
        self.env.cr.commit()

        cycle_id = self.id
        cycle_name = self.name
        dbname = self.env.cr.dbname

        import threading

        def _async_generate_assessments():
            import odoo
            from odoo.modules.registry import Registry
            import logging
            _logger = logging.getLogger(__name__)
            try:
                registry = Registry(dbname)
                with registry.cursor() as new_cr:
                    new_env = odoo.api.Environment(new_cr, odoo.SUPERUSER_ID, {})
                    cycle_rec = new_env['competency.assessment.cycle'].browse(cycle_id)
                    if cycle_rec.exists():
                        _logger.info("Starting background assessment generation for cycle %s (id=%d)", cycle_rec.name, cycle_id)
                        cycle_rec._generate_cycle_assessments_batch()
                        new_cr.commit()
                        _logger.info("Finished background assessment generation for cycle %s", cycle_rec.name)
            except Exception as exc:
                _logger.exception("Error during background assessment generation for cycle %d: %s", cycle_id, exc)

        thread = threading.Thread(target=_async_generate_assessments, daemon=True)
        thread.start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Cycle Started'),
                'message': _("Assessment cycle '%s' has started! 360-degree assessments are generating in the background. You can continue working.") % cycle_name,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }

    def _generate_cycle_assessments_batch(self):
        """Generate all 360-degree assessment records for this cycle in a single batched pass.

        Pre-caches all active employee metadata before building assessment pairs to avoid
        repeated ORM lookups inside loops. Assessment records are bulk-created in chunks
        of 1,000 to keep each transaction manageable.
        """
        self.ensure_one()
        import random

        config = self.env['competency.matrix.config'].sudo().get_active_config()
        max_peers = config.max_peer_assessments or 3
        max_subs = config.max_subordinate_assessments or 2

        active_employees = self.env['hr.employee'].sudo().search([('active', '=', True)])
        if not active_employees:
            return self.env['competency.assessment']

        # Existing assessment pairs to prevent duplicate creation
        self.env.cr.execute(
            "SELECT employee_id, assessor_id, assessment_type FROM competency_assessment WHERE cycle_id = %s",
            (self.id,)
        )
        existing_pairs = set(self.env.cr.fetchall())

        # Director Peer Configurations
        dir_configs = self.env['competency.director.peer.config'].sudo().search([])
        dir_peer_map = {
            c.director_id.id: [p.id for p in c.peer_ids if p.active and p.user_id]
            for c in dir_configs if c.director_id
        }

        # 1. Pre-cache metadata for all active employees in 1 pass
        peer_cfg = self.env['competency.director.peer.config']
        emp_cache = {}
        reports_by_manager = {}
        coached_by = {}

        for emp in active_employees:
            u_id = emp.user_id.id if emp.user_id else False
            coach = getattr(emp, 'coach_id', False) or emp.parent_id
            c_id = coach.id if coach else False
            ou = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id.operating_unit_id if emp.department_id else False)
            ou_id = ou.id if ou else False
            job = peer_cfg._get_employee_job(emp)
            j_id = job.id if job else False
            j_name = (job.name or '').strip().lower() if job else ''

            # Grade resolution
            g_rec = peer_cfg._resolve_employee_grade(emp)
            g_id = g_rec.id if g_rec else False
            g_code = (g_rec.grade_code or g_rec.grade_name or '').strip().upper() if g_rec else ''

            is_dir = False
            if hasattr(emp, 'is_director_or_chief') and emp.is_director_or_chief:
                is_dir = True
            elif hasattr(self.env['competency.assessment'], '_is_director_or_chief'):
                is_dir = self.env['competency.assessment']._is_director_or_chief(emp)

            is_chief = is_dir and ('chief' in j_name or 'president' in j_name or 'vp' in j_name)
            is_mgr_title = any(k in j_name for k in ['manager', 'head', 'lead', 'leader', 'supervisor', 'controller'])
            is_mgr = is_dir or is_mgr_title or (getattr(ou, 'manager_id', False) and ou.manager_id.id == emp.id)

            ou_type = (getattr(ou, 'work_unit_type', '') or '').strip().lower()
            is_bm = False
            is_district_mgr = False
            is_ho_mgr = False
            if is_mgr and not is_dir:
                if ou_type in ('branch', 'sub_branch') or 'branch manager' in j_name or j_name.startswith('bm') or ' bm ' in j_name or 'bm-' in j_name or 'bm ' in j_name:
                    is_bm = True
                elif ou_type in ('district_office', 'regional_office') or 'district manager' in j_name or ('district' in j_name and 'manager' in j_name):
                    is_district_mgr = True
                else:
                    is_ho_mgr = True

            emp_cache[emp.id] = {
                'user_id': u_id,
                'coach_id': c_id,
                'ou_id': ou_id,
                'ou_type': ou_type,
                'job_id': j_id,
                'job_name': j_name,
                'grade_id': g_id,
                'grade_code': g_code,
                'grade_num': peer_cfg._get_grade_number(emp),
                'is_director': is_dir,
                'is_chief': is_chief,
                'is_bm': is_bm,
                'is_district_mgr': is_district_mgr,
                'is_ho_mgr': is_ho_mgr,
                'is_manager': is_mgr,
            }
            if c_id:
                coached_by.setdefault(c_id, []).append(emp.id)
                reports_by_manager.setdefault(c_id, []).append(emp.id)

        assessments_to_create = []
        total_eligible_raters = 0
        total_sampled_raters = 0
        peer_assessor_workload = {}
        sub_assessor_workload = {}

        # 1. Self Assessment (100% mandatory for all active employees with user account)
        for emp in active_employees:
            e_id = emp.id
            e_data = emp_cache[e_id]
            u_id = e_data['user_id']
            if not u_id:
                continue
            pair_self = (e_id, u_id, 'self')
            if pair_self not in existing_pairs:
                assessments_to_create.append({
                    'cycle_id': self.id,
                    'employee_id': e_id,
                    'assessor_id': u_id,
                    'assessment_type': 'self',
                })
                existing_pairs.add(pair_self)

        # 2. Team Assessment (Boss / Coach evaluates team member / direct reports, 100% mandatory, no exceptions)
        for emp in active_employees:
            e_id = emp.id
            e_data = emp_cache[e_id]
            c_id = e_data['coach_id']
            if c_id and emp_cache.get(c_id, {}).get('user_id'):
                coach_u_id = emp_cache[c_id]['user_id']
                pair_team = (e_id, coach_u_id, 'team')
                if pair_team not in existing_pairs:
                    assessments_to_create.append({
                        'cycle_id': self.id,
                        'employee_id': e_id,
                        'assessor_id': coach_u_id,
                        'assessment_type': 'team',
                    })
                    existing_pairs.add(pair_team)

        # 3. Subordinate Assessment — teammates within the same coach group evaluate each other upward.
        # Eligibility: same coach, different job grade, same OU, different job position (non-director).
        # Chiefs/Directors: same coach + different job grade only.
        # Each candidate gets min(eligible_count, max_subs) subordinate raters, balanced by current workload.

        # A. Teammates assessing subordinates under the same coach (Different Job Grade)
        sub_candidates = {}
        for c_id, teammates in coached_by.items():
            for cand_id in teammates:
                cand_data = emp_cache.get(cand_id)
                if not cand_data or not cand_data['user_id']:
                    continue

                eligible_evaluators = []
                for eval_id in teammates:
                    if eval_id == cand_id:
                        continue
                    eval_data = emp_cache.get(eval_id)
                    if not eval_data or not eval_data['user_id']:
                        continue

                    # 1. Same Coach: guaranteed by teammates
                    # 2. Different Job Grade: Evaluator has different grade than candidate
                    diff_grade = (eval_data['grade_num'] != cand_data['grade_num']) if (eval_data['grade_num'] and cand_data['grade_num']) else (eval_data['grade_id'] != cand_data['grade_id'])
                    if not diff_grade:
                        continue

                    if eval_data['is_chief'] or eval_data['is_director'] or cand_data['is_chief'] or cand_data['is_director']:
                        # Chiefs & Directors: 1. Same Coach, 2. Different Job Grade
                        eligible_evaluators.append(eval_id)
                    else:
                        # Non-Managerial & Managerial: 1. Same Coach, 2. Different Job Grade, 3. Same Work Unit, 4. Different Job Position
                        same_ou = (cand_data['ou_id'] == eval_data['ou_id']) if (cand_data['ou_id'] and eval_data['ou_id']) else True
                        diff_job = (cand_data['job_id'] != eval_data['job_id']) if (cand_data['job_id'] and eval_data['job_id']) else True
                        if same_ou and diff_job:
                            eligible_evaluators.append(eval_id)

                if eligible_evaluators:
                    sub_candidates[cand_id] = eligible_evaluators

        for cand_id, eligible_evals in sub_candidates.items():
            k_sub = min(len(eligible_evals), max_subs) if max_subs > 0 else len(eligible_evals)
            total_eligible_raters += len(eligible_evals)
            sorted_evals = sorted(eligible_evals, key=lambda eid: (sub_assessor_workload.get(emp_cache[eid]['user_id'], 0), eid))
            chosen = 0
            for eval_id in sorted_evals:
                eval_u_id = emp_cache[eval_id]['user_id']
                pair_sub = (cand_id, eval_u_id, 'subordinate')
                if pair_sub not in existing_pairs:
                    assessments_to_create.append({
                        'cycle_id': self.id,
                        'employee_id': cand_id,
                        'assessor_id': eval_u_id,
                        'assessment_type': 'subordinate',
                    })
                    existing_pairs.add(pair_sub)
                    sub_assessor_workload[eval_u_id] = sub_assessor_workload.get(eval_u_id, 0) + 1
                    total_sampled_raters += 1
                    chosen += 1
                    if chosen >= k_sub:
                        break

        # B. Direct reports evaluating their coach/superior upward (When someone assesses his coach that is subordinate)
        # Rule: A coach is always evaluated upward by their team, whether in the same work unit or not.
        for m_id, dr_ids in reports_by_manager.items():
            m_data = emp_cache.get(m_id)
            if not m_data or not m_data['user_id']:
                continue

            eligible_subs = []
            for r in dr_ids:
                r_data = emp_cache.get(r)
                if not r_data or not r_data['user_id']:
                    continue

                # 1. Same Coach / Direct Reporting Line: guaranteed by dr_ids
                # 2. Different Job Grade:
                diff_grade = (r_data['grade_num'] != m_data['grade_num']) if (r_data['grade_num'] and m_data['grade_num']) else (r_data['grade_id'] != m_data['grade_id'])
                if not diff_grade:
                    continue

                # 3. Different Job Position:
                diff_job = (r_data['job_id'] != m_data['job_id']) if (r_data['job_id'] and m_data['job_id']) else True
                if diff_job:
                    eligible_subs.append(r)

            if not eligible_subs:
                continue

            k_sub = min(len(eligible_subs), max_subs) if max_subs > 0 else len(eligible_subs)
            total_eligible_raters += len(eligible_subs)
            sorted_subs = sorted(eligible_subs, key=lambda sid: (sub_assessor_workload.get(emp_cache[sid]['user_id'], 0), sid))
            chosen = 0
            for sid in sorted_subs:
                s_u_id = emp_cache[sid]['user_id']
                pair_sub = (m_id, s_u_id, 'subordinate')
                if pair_sub not in existing_pairs:
                    assessments_to_create.append({
                        'cycle_id': self.id,
                        'employee_id': m_id,
                        'assessor_id': s_u_id,
                        'assessment_type': 'subordinate',
                    })
                    existing_pairs.add(pair_sub)
                    sub_assessor_workload[s_u_id] = sub_assessor_workload.get(s_u_id, 0) + 1
                    total_sampled_raters += 1
                    chosen += 1
                    if chosen >= k_sub:
                        break

        # 4. Peer Assessment — matched within category-specific peer buckets.
        # Each employee gets min(eligible_peers, max_peers) peer raters, balanced by current workload.

        # A. Directors/Chiefs: manually configured via competency.director.peer.config (unidirectional, no auto-fallback).
        for d_id, p_ids in dir_peer_map.items():
            d_u_id = emp_cache.get(d_id, {}).get('user_id')
            if not d_u_id or not p_ids:
                continue
            for p_id in p_ids:
                if p_id == d_id or p_id not in emp_cache:
                    continue
                pair_peer = (p_id, d_u_id, 'peer')
                if pair_peer not in existing_pairs:
                    assessments_to_create.append({
                        'cycle_id': self.id,
                        'employee_id': p_id,
                        'assessor_id': d_u_id,
                        'assessment_type': 'peer',
                    })
                    existing_pairs.add(pair_peer)
                    peer_assessor_workload[d_u_id] = peer_assessor_workload.get(d_u_id, 0) + 1
                    total_sampled_raters += 1

        # B. Non-Director Peer Bucketing according to bank matrix:
        # Rule 1: Non-Managerial: 1. Same Coach, 2. Same Job Grade, 3. Same Work Unit, 4. Same Job Position
        # Rule 2: Managerial (HO & District): 1. Same Coach, 2. Same Job Grade, 3. Same Work Unit
        # Rule 3: Branch Managers (BMs): 1. Same Coach, 2. Same Job Grade, 3. Same Job Position (BM)
        peer_buckets = {}
        for e_id, e_data in emp_cache.items():
            if e_data['is_director'] or not e_data['user_id']:
                continue

            c_id = e_data['coach_id']
            if not c_id:
                continue

            g_id = e_data['grade_id'] or 0
            ou_id = e_data['ou_id'] or 0
            j_id = e_data['job_id'] or 0

            if e_data['is_bm']:
                # Rule 3: Branch Managers: 1. Same Coach, 2. Same Job Grade, 3. Same Job Position
                b_key = ('BM', c_id, g_id, 'BM_ROLE')
            elif e_data.get('is_district_mgr'):
                # Rule 2b: District Managers: 1. Same Coach, 2. Same Job Grade, 3. Same Work Unit
                b_key = ('DISTRICT_MGR', c_id, g_id, ou_id)
            elif e_data['is_manager']:
                # Rule 2a: Head Office Managers: 1. Same Coach, 2. Same Job Grade, 3. Same Work Unit
                b_key = ('HO_MGR', c_id, g_id, ou_id)
            else:
                # Rule 1: Non-Managerial: 1. Same Coach, 2. Same Job Grade, 3. Same Work Unit, 4. Same Job Position
                b_key = ('NON_MGR', c_id, g_id, ou_id, j_id)

            peer_buckets.setdefault(b_key, []).append(e_id)

        # Apply fair matching within each peer bucket
        for b_key, members in peer_buckets.items():
            m_len = len(members)
            if m_len > 1:
                k_peer = min(m_len - 1, max_peers) if max_peers > 0 else m_len - 1
                members_sorted = sorted(members)
                for i, e_id in enumerate(members_sorted):
                    total_eligible_raters += (m_len - 1)
                    # Candidate peers in circular order starting from the member after e_id
                    candidate_peers = [members_sorted[(i + j) % m_len] for j in range(1, m_len)]
                    # Sort candidates by current peer workload to balance assessor load
                    sorted_candidates = sorted(candidate_peers, key=lambda pid: (peer_assessor_workload.get(emp_cache[pid]['user_id'], 0), pid))
                    chosen = 0
                    for pid in sorted_candidates:
                        p_u_id = emp_cache[pid]['user_id']
                        pair_peer = (e_id, p_u_id, 'peer')
                        if pair_peer not in existing_pairs:
                            assessments_to_create.append({
                                'cycle_id': self.id,
                                'employee_id': e_id,
                                'assessor_id': p_u_id,
                                'assessment_type': 'peer',
                            })
                            existing_pairs.add(pair_peer)
                            peer_assessor_workload[p_u_id] = peer_assessor_workload.get(p_u_id, 0) + 1
                            total_sampled_raters += 1
                            chosen += 1
                            if chosen >= k_peer:
                                break

        # Audit log on cycle
        self.sudo().write({
            'eligible_rater_count': total_eligible_raters,
            'selected_rater_count': total_sampled_raters,
            'sampling_audit_log': f"360 Balanced Sampling Audit: Eligible Candidates={total_eligible_raters}, Sampled={total_sampled_raters}, Created Assessments={len(assessments_to_create)}",
        })

        if not assessments_to_create:
            return self.env['competency.assessment']

        # Pre-assign sequence names in bulk (0.01s instead of 15,000 SQL updates)
        seq_names = self.env['competency.assessment']._get_batch_sequence_names(len(assessments_to_create))
        for idx, vals in enumerate(assessments_to_create):
            if idx < len(seq_names):
                vals['name'] = seq_names[idx]

        # Bulk create in chunks of 1000
        chunk_size = 1000
        created_asms = self.env['competency.assessment']
        AssessmentSudo = self.env['competency.assessment'].sudo().with_context(
            tracking_disable=True,
            mail_create_nolog=True,
            mail_create_nosubscribe=True,
        )

        for i in range(0, len(assessments_to_create), chunk_size):
            chunk = assessments_to_create[i:i + chunk_size]
            asms_chunk = AssessmentSudo.create(chunk)
            created_asms |= asms_chunk
            # Commit each chunk immediately to persist assessments and release locks
            self.env.cr.commit()

        # Post single summary announcement on Cycle Chatter
        deadline_str = self.assessment_deadline.strftime('%b %d, %Y') if self.assessment_deadline else _('Not set')
        self.message_post(
            body=Markup(_(
                "Assessment cycle <b>%s</b> opened. Successfully generated <b>%d</b> 360-degree evaluations for %d employees. Submission Deadline: <b>%s</b>."
            )) % (escape(self.name or ''), len(assessments_to_create), len(active_employees), escape(deadline_str or ''))
        )
        self.env.cr.commit()

        return created_asms


    def action_start_review(self):
        self.with_context(force_write=True).write({'state': 'in_review'})
        return True

    def action_close(self):
        self.with_context(force_write=True).write({'state': 'closed'})
        for rec in self:
            rec.message_post(body=_('Assessment cycle %s closed.') % rec.name)
            self.env['competency.dashboard.snapshot'].sudo()._cron_take_dashboard_snapshot(cycle_ids=[rec.id])
        return True

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state == 'closed' and not force_write and not self.env.su:
                locked_fields = {'name', 'period_start', 'period_end', 'assessment_deadline'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(_("This assessment cycle (%s) is closed and cannot be edited.") % rec.name)
        res = super().write(vals)
        if 'active' in vals and not self.env.context.get('skip_active_cascade'):
            is_act = bool(vals['active'])
            cycle_ids = tuple(self.ids)
            self.env.cr.execute("""
                UPDATE competency_assessment SET active = %s WHERE cycle_id IN %s;
                UPDATE competency_assessment_line SET active = %s WHERE cycle_id IN %s;
            """, (is_act, cycle_ids, is_act, cycle_ids))
            self.invalidate_model()
        return res

    def unlink(self):
        """Soft-delete / archive cycles instead of physical deletion to protect historical data integrity."""
        for cycle in self:
            cycle.with_context(skip_active_cascade=True).write({'active': False})
            self.env.cr.execute("""
                UPDATE competency_assessment SET active = FALSE WHERE cycle_id = %s;
                UPDATE competency_assessment_line SET active = FALSE WHERE cycle_id = %s;
            """, (cycle.id, cycle.id))
        self.invalidate_model()
        return True


class CompetencyAssessment(models.Model):
    """A single employee assessment within a cycle."""
    _name = 'competency.assessment'
    _description = 'Competency Assessment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if not self.env.context.get('competency_employee_select'):
            self = self.with_context(competency_employee_select=True)
        return super()._search(domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)

    @api.model
    def web_search_read(self, domain=None, specification=None, offset=0, limit=None, order=None, count_limit=None):
        if not self.env.context.get('competency_employee_select'):
            self = self.with_context(competency_employee_select=True)
        return super().web_search_read(domain=domain, specification=specification, offset=offset, limit=limit, order=order, count_limit=count_limit)

    @api.model
    def _read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        if not self.env.context.get('competency_employee_select'):
            self = self.with_context(competency_employee_select=True)
        return super()._read_group(domain, groupby=groupby, aggregates=aggregates, having=having, offset=offset, limit=limit, order=order)

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        if not self.env.context.get('competency_employee_select'):
            self = self.with_context(competency_employee_select=True)
        return super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)

    name = fields.Char(string='Reference', readonly=True, copy=False)
    active = fields.Boolean(string='Active', default=True)
    cycle_id = fields.Many2one(
        'competency.assessment.cycle', string='Assessment Cycle', required=True,
        domain="[('state', '=', 'open')]", ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    department_id = fields.Many2one(related='employee_id.department_id', string='Department', store=True, readonly=True)
    job_id = fields.Many2one('hr.job', string='Job Position', compute='_compute_job_id', store=True, readonly=True)
    grade_id = fields.Many2one('employee.grade', string='Job Grade', compute='_compute_grade_id', store=True, readonly=True)

    @api.model
    def get_bunna_logo_base64(self):
        """Returns base64 string of the official Bunna Bank logo for reliable QWeb PDF rendering."""
        import base64
        import os
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if not os.path.exists(logo_path):
            alt_path = '/mnt/extra-addons/custom_recruitment/static/src/img/bunna_bank_official_logo.png'
            if os.path.exists(alt_path):
                logo_path = alt_path
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    @api.model
    def _get_employee_job(self, emp):
        """Safely fetch job position for an employee, prioritizing substantive custom job_position over version job_id."""
        if not emp:
            return self.env['hr.job']
        return getattr(emp, 'job_position', False) or emp.job_id or self.env['hr.job']

    @api.depends('employee_id', 'employee_id.job_id')
    def _compute_job_id(self):
        for rec in self:
            rec.job_id = self._get_employee_job(rec.employee_id) if rec.employee_id else False

    @api.depends('employee_id')
    def _compute_grade_id(self):
        for rec in self:
            rec.grade_id = self._resolve_employee_grade(rec.employee_id) if rec.employee_id else False

    @api.model
    def _get_assessment_type_selection(self):
        """Complete 360-degree assessment type selection options."""
        return [
            ('self', 'Self-Assessment'),
            ('team', 'Team Assessment'),
            ('peer', 'Peer Assessment'),
            ('subordinate', 'Subordinate Assessment'),
            ('supervisor', 'Supervisor Assessment (Legacy)'),
        ]



    assessor_id = fields.Many2one('res.users', string='Assessor', default=lambda self: self.env.user, readonly=True)
    assessor_employee_id = fields.Many2one(
        'hr.employee', string='Assessor Employee',
        compute='_compute_assessor_employee_id', store=True, index=True
    )
    assessor_job_id = fields.Many2one(
        'hr.job', string='Assessor Job Position',
        compute='_compute_assessor_job_and_grade', store=True, index=True
    )
    assessor_grade_id = fields.Many2one(
        'employee.grade', string='Assessor Job Grade',
        compute='_compute_assessor_job_and_grade', store=True, index=True
    )
    is_current_or_latest_cycle = fields.Boolean(
        string='Current or Latest Cycle',
        related='cycle_id.is_open_or_latest', store=False, index=False
    )
    assessment_type = fields.Selection(
        selection='_get_assessment_type_selection', string='Assessment Type',
        required=True, tracking=True)

    @api.depends('assessor_id', 'assessor_id.employee_id')
    def _compute_assessor_employee_id(self):
        for rec in self:
            rec.assessor_employee_id = rec.assessor_id.employee_id if rec.assessor_id else False

    @api.depends('assessor_employee_id')
    def _compute_assessor_job_and_grade(self):
        for rec in self:
            emp = rec.assessor_employee_id
            if emp:
                rec.assessor_job_id = self._get_employee_job(emp)
                rec.assessor_grade_id = self._resolve_employee_grade(emp)
            else:
                rec.assessor_job_id = False
                rec.assessor_grade_id = False

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

        # 0. Direct grade on employee (hr_employee_custom: grade = fields.Many2one('employee.grade'))
        grade = getattr(emp, 'grade', False)
        if grade and getattr(grade, '_name', '') == 'employee.grade':
            return grade

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
        job = self._get_employee_job(emp)
        if job and 'operating.unit.job.position' in self.env:
            ou_id = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id.operating_unit_id if emp.department_id else False)
            if ou_id:
                pos = self.env['operating.unit.job.position'].search([
                    ('job_position_id', '=', job.id),
                    ('operating_unit_id', '=', ou_id.id)
                ], limit=1)
                if pos and pos.job_grade_id and getattr(pos.job_grade_id, '_name', '') == 'employee.grade':
                    return pos.job_grade_id
            pos = self.env['operating.unit.job.position'].search([
                ('job_position_id', '=', job.id)
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
        if job:
            g = getattr(job, 'grade', False) or getattr(job, 'grade_id', False)
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
            raw = getattr(emp, 'grade_id', False) or getattr(emp, 'job_grade', False) or getattr(emp, 'grade', False)
            if raw:
                raw_str = getattr(raw, 'name', False) or getattr(raw, 'code', False) or getattr(raw, 'grade_name', False) or str(raw)
        job = self._get_employee_job(emp)
        if not raw_str and job:
            raw = getattr(job, 'grade', False) or getattr(job, 'grade_id', False)
            if raw:
                raw_str = getattr(raw, 'name', False) or getattr(raw, 'code', False) or getattr(raw, 'grade_name', False) or str(raw)

        g_str = str(raw_str).lower().strip()
        if not g_str:
            return 0

        tokens = g_str.replace('-', ' ').replace('_', ' ').split()
        roman_map = {
            'xx': 20, 'xix': 19, 'xviii': 18,
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
    def _parse_grade_rank(self, grade_code, grade_rec=None):
        """Parse Roman numeral or numeric grade into integer rank (e.g. IX -> 9, XII -> 12)."""
        roman_map = {
            'xx': 20, 'xix': 19, 'xviii': 18,
            'xvii': 17, 'xvi': 16, 'xv': 15, 'xiv': 14, 'xiii': 13, 'xii': 12, 'xi': 11,
            'x': 10, 'ix': 9, 'viii': 8, 'vii': 7, 'vi': 6, 'v': 5, 'iv': 4, 'iii': 3, 'ii': 2, 'i': 1
        }
        if grade_code:
            tokens = str(grade_code).lower().strip().replace('-', ' ').replace('_', ' ').split()
            if tokens and tokens[0] in roman_map:
                return roman_map[tokens[0]]
            import re
            m = re.findall(r'\d+', str(grade_code))
            if m:
                return int(m[0])
        return grade_rec.id if grade_rec else 0

    @api.model
    def _is_director_or_chief(self, emp):
        """Strictly classify as Executive: Grade 15, Director (Grade 16) or Chief (Grade 17). Exclude Grade II, III, IV, etc."""
        if not emp or not emp.active:
            return False
        g_num = self._get_grade_number(emp)
        if g_num in (15, 16, 17):
            return True
        return False

    @api.model
    def _is_manager(self, emp):
        if not emp or not emp.active:
            return False
        if self._is_director_or_chief(emp):
            return True
        ou = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id.operating_unit_id if emp.department_id else False)
        if getattr(ou, 'manager_id', False) and ou.manager_id.id == emp.id:
            return True
        job = self._get_employee_job(emp)
        j_name = (job.name or '').lower() if job else ''
        return any(k in j_name for k in ['manager', 'head', 'lead', 'leader', 'president', 'vp', 'supervisor', 'controller'])

    @api.model
    def _is_branch_manager(self, emp):
        if not emp or not self._is_manager(emp):
            return False
        ou = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id.operating_unit_id if emp.department_id else False)
        ou_type = (getattr(ou, 'work_unit_type', '') or '').strip().lower()
        if ou_type in ('branch', 'sub_branch'):
            return True
        job = self._get_employee_job(emp)
        j_name = (job.name or '').lower() if job else ''
        return 'branch manager' in j_name or j_name.startswith('bm') or ' bm ' in j_name or 'bm-' in j_name or 'bm ' in j_name

    @api.model
    def _is_director_emp(self, emp):
        return self._is_director_or_chief(emp)

    @api.model
    def _is_district_manager_emp(self, emp):
        if not emp or not self._is_manager(emp):
            return False
        ou = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id.operating_unit_id if emp.department_id else False)
        ou_type = (getattr(ou, 'work_unit_type', '') or '').strip().lower()
        if ou_type in ('district_office', 'regional_office'):
            return True
        job = self._get_employee_job(emp)
        job_name = (job.name or '').lower() if job else ''
        return 'district manager' in job_name or ('district' in job_name and 'manager' in job_name)

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
            # Returns manually assigned peers ONLY (strictly unidirectional: no reverse peering, no auto-assignment if unassigned)
            return peers

        emp_coach = getattr(emp, 'coach_id', False) or emp.parent_id
        emp_grade_id = self._get_employee_grade_id(emp)
        emp_ou_id = self._get_employee_ou_id(emp)
        emp_job = self._get_employee_job(emp)
        emp_job_id = emp_job.id if emp_job else False

        domain = [('id', '!=', emp.id), ('active', '=', True)]
        if emp_coach:
            domain += ['|', ('parent_id', '=', emp_coach.id), ('coach_id', '=', emp_coach.id)]

        candidates = self.env['hr.employee'].search(domain)

        # 2. Branch Manager: Same Coach, Same Grade, Same Position (OU unlisted -> open)
        if self._is_branch_manager(emp):
            matched = candidates.filtered(lambda c: (
                (self._get_employee_grade_id(c) == emp_grade_id if emp_grade_id else True) and
                (self._get_employee_job(c).id == emp_job_id if (self._get_employee_job(c) and emp_job_id) else True)
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
                (self._get_employee_job(c).id == emp_job_id if (self._get_employee_job(c) and emp_job_id) else True)
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
        emp_job = self._get_employee_job(emp)
        emp_job_id = emp_job.id if emp_job else False

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
                (self._get_employee_job(c).id != emp_job_id if (self._get_employee_job(c) and emp_job_id) else True)
            ))

        if not matched and candidates:
            # Fallback if strict criteria returns 0: match candidates under same coach with different grade or position
            matched = candidates.filtered(lambda c: self._get_employee_job(c).id != emp_job_id) or candidates

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
            bosses = self.env['hr.employee']
            if getattr(emp, 'coach_id', False) and emp.coach_id:
                bosses |= emp.coach_id
            if emp.parent_id:
                bosses |= emp.parent_id
            if emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.id != emp.id:
                bosses |= emp.department_id.manager_id
            all_subs = subs | bosses
            self.employee_id = all_subs[0].id if all_subs else False
            return {'domain': {'employee_id': [('id', 'in', all_subs.ids)]}}

        elif self.assessment_type in ('team', 'supervisor'):
            # Assessor is boss / coach evaluating their direct reports / team members
            team_members = self.env['hr.employee'].search([
                ('active', '=', True),
                ('id', '!=', emp.id),
                '|', ('coach_id', '=', emp.id), ('parent_id', '=', emp.id)
            ])
            if not team_members and emp.department_id and emp.department_id.manager_id.id == emp.id:
                team_members = self.env['hr.employee'].search([
                    ('active', '=', True),
                    ('department_id', '=', emp.department_id.id),
                    ('id', '!=', emp.id)
                ])
            self.employee_id = team_members[0].id if team_members else False
            return {'domain': {'employee_id': [('id', 'in', team_members.ids)]}}

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

    is_admin_user = fields.Boolean(
        string='Is Competency Admin', compute='_compute_is_admin_user',
        help='True if current user is Competency Administrator or System Admin.'
    )

    is_admin_or_officer = fields.Boolean(
        string='Is Admin or Officer', compute='_compute_is_admin_or_officer',
        help='True if current user has HR Officer or Competency Admin rights.'
    )

    is_override_active = fields.Boolean(string='Override Mode Active', default=False, tracking=True, copy=False)
    override_user_id = fields.Many2one('res.users', string='Override Enabled By', readonly=True, copy=False)
    override_date = fields.Datetime(string='Override Date', readonly=True, copy=False)

    @api.depends_context('uid')
    def _compute_is_admin_user(self):
        is_admin = bool(
            self.env.user.has_group('competency_management.group_competency_admin')
            or self.env.user.has_group('base.group_system')
            or self.env.su
            or self.env.is_admin()
        )
        for rec in self:
            rec.is_admin_user = is_admin

    @api.depends_context('uid')
    def _compute_is_admin_or_officer(self):
        is_officer_or_admin = bool(
            self.env.user.has_group('competency_management.group_competency_officer')
            or self.env.user.has_group('competency_management.group_competency_admin')
            or self.env.user.has_group('base.group_system')
            or self.env.su
            or self.env.is_admin()
        )
        for rec in self:
            rec.is_admin_or_officer = is_officer_or_admin

    @api.model
    def _is_elevated_evaluator(self, user=None):
        """Check if user has elevated HR administrative role authorized to override assessments:
        - HR / People Solution Officer (group_competency_officer)
        - Competency Administrator (group_competency_admin)
        - System Administrator (base.group_system)

        Coaches, Supervisors, Department Leaders, and Operating Unit Leaders who do not possess
        these HR roles CANNOT override assessments or fill ratings for other employees.
        """
        user = user or self.env.user
        return bool(
            user.has_group('competency_management.group_competency_officer')
            or user.has_group('competency_management.group_competency_admin')
            or user.has_group('base.group_system')
            or self.env.su
            or self.env.is_admin()
        )

    can_override = fields.Boolean(
        string='Can Override', compute='_compute_can_override',
        help='True if current user is an HR / People Solution Officer or Competency Administrator, '
             'is neither the assessor nor the evaluated employee, and the assessment is unapproved.'
    )

    @api.depends_context('uid')
    @api.depends('state', 'is_locked', 'cycle_id.state', 'assessor_id', 'employee_id')
    def _compute_can_override(self):
        user = self.env.user
        emp = user.employee_id
        is_elevated = self._is_elevated_evaluator(user)
        for rec in self:
            if not is_elevated:
                rec.can_override = False
                continue
            if rec.state == 'locked' or rec.is_locked:
                rec.can_override = False
                continue
            if rec.cycle_id and rec.cycle_id.state == 'closed':
                rec.can_override = False
                continue
            # Segregation of duties:
            # 1. If assessor, must finish on My Competency Assessments (no override)
            if rec.assessor_id and rec.assessor_id.id == user.id:
                rec.can_override = False
                continue
            # 2. If assessed employee, cannot override own assessment
            is_evaluatee = bool((emp and rec.employee_id and rec.employee_id.id == emp.id) or (rec.employee_id and rec.sudo().employee_id.user_id.id == user.id))
            if is_evaluatee:
                rec.can_override = False
                continue
            rec.can_override = True

    can_edit_ratings = fields.Boolean(
        string='Can Edit Ratings', compute='_compute_can_edit_ratings',
        help='True if assessment inputs are currently unlocked for editing.'
    )

    @api.depends_context('uid')
    @api.depends('state', 'is_locked', 'is_deadline_passed', 'cycle_id.state', 'assessor_id', 'employee_id', 'is_override_active')
    def _compute_can_edit_ratings(self):
        user = self.env.user
        emp = user.employee_id
        current_uid = user.id
        is_elevated = self._is_elevated_evaluator(user)

        for rec in self:
            # 1. Approved or locked assessments can NEVER be edited by anyone
            if rec.state in ('approved', 'locked') or rec.is_locked or (rec.cycle_id and rec.cycle_id.state == 'closed'):
                rec.can_edit_ratings = False
                continue

            # 2. Administrative Override active for elevated evaluator (Dept/OU Leader, HR Officer/Admin)
            # Segregation of duties: Must NOT be the assessor and NOT be the evaluatee
            is_assessor = bool(rec.assessor_id and rec.assessor_id.id == current_uid)
            is_evaluatee = bool((emp and rec.employee_id and rec.employee_id.id == emp.id) or (rec.employee_id and rec.sudo().employee_id.user_id.id == current_uid))
            if rec.is_override_active and is_elevated and not is_assessor and not is_evaluatee:
                rec.can_edit_ratings = True
                continue

            # 3. Designated Assessor editing their own draft assessment within deadline during open cycle
            cycle_open = not rec.cycle_id or rec.cycle_id.state == 'open'
            if is_assessor and rec.state == 'draft' and not rec.is_deadline_passed and cycle_open:
                rec.can_edit_ratings = True
                continue

            # 4. Default: Read-only
            rec.can_edit_ratings = False

    # 360 Multi-Rater extension fields
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
                                   help='Hide rater name from line managers for peer/subordinate 360 reviews.')
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
        achievement determination using configured rater weights from competency.matrix.config.
        """
        config = self.env['competency.matrix.config'].sudo().get_active_config()
        sup_weight = float(config.weight_supervisor or 3.0)
        weight_by_type = {
            'self': float(config.weight_self or 2.0),
            'peer': float(config.weight_peer or 1.0),
            'subordinate': float(config.weight_subordinate or 1.0),
            'supervisor': sup_weight,
            'team': sup_weight,
        }
        # Verified skills-test evidence is treated with the same authority as a supervisor rating.
        skills_test_weight = sup_weight

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

            # 2. Skills Tests — verified/objective evidence
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

    @api.model
    def _get_batch_sequence_names(self, count):
        """Efficiently reserve and generate batch sequence numbers in 1 SQL query."""
        if count <= 0:
            return []
        import datetime
        year = datetime.date.today().strftime('%Y')
        seq = self.env['ir.sequence'].sudo().search([('code', '=', 'competency.assessment')], limit=1)
        if not seq:
            return [f"CMP-A/{year}/{i:05d}" for i in range(1, count + 1)]

        if getattr(seq, 'use_date_range', False):
            return [seq.next_by_code('competency.assessment') for _ in range(count)]

        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "SELECT number_next, number_increment FROM ir_sequence WHERE id = %s FOR UPDATE",
                    (seq.id,)
                )
                row = self.env.cr.fetchone()
                if not row:
                    raise Exception("No sequence row")
                start_num = row[0]
                increment = row[1] or 1
                end_num = start_num + (count * increment)
                self.env.cr.execute(
                    "UPDATE ir_sequence SET number_next = %s WHERE id = %s",
                    (end_num, seq.id)
                )
                prefix = (seq.prefix or 'CMP-A/%(year)s/').replace('%(year)s', year)
                padding = seq.padding or 5
                format_str = f"{prefix}%0{padding}d"
                return [format_str % (start_num + i * increment) for i in range(count)]
        except Exception:
            return [seq.next_by_code('competency.assessment') for _ in range(count)]

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = seq.next_by_code('competency.assessment') or 'CMP-A-NEW'
        return super().create(vals_list)

    def web_read(self, specification):
        """Auto-populate rating lines when an assessor opens a draft assessment that has no lines yet."""
        for rec in self:
            if rec.state == 'draft' and not rec.line_ids and rec.employee_id and rec.cycle_id:
                try:
                    rec.sudo()._do_populate_lines()
                except Exception:
                    pass

        # Enforce competency.assessment's own row-level rules first (assessor_id = user,
        # supervisor/team rules, officer-sees-all) — unchanged, still blocks anyone not
        # entitled to view this specific assessment.
        self.check_access_rule('read')

        # Only once that passes: read with elevated rights so a linked boss/peer
        # employee_id (or any other hr.employee-linked field on this assessment) can be
        # displayed, without widening hr.employee access anywhere else in the system.
        return super(CompetencyAssessment, self.sudo()).web_read(specification)


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

    @api.onchange('employee_id', 'assessment_type')
    def _onchange_employee_id_populate_competencies(self):
        """Automatically populate/refresh competency rating lines when employee_id or assessment_type changes in draft state."""
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
        job_pos = self._get_employee_job(employee)
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

            core_req_lvl = self._get_matrix_required_level('core', grade=grade_rec, job=job_pos, job_name=j_name) or '2'
            if 'core' in allowed_pillars:
                core_comps = self.env['competency.competency'].search([('pillar', '=', 'core'), ('status', '=', 'active')])
                for comp in core_comps:
                    raw_line_vals.append({
                        'competency_id': comp.id,
                        'pillar': 'core',
                        'current_level': False,
                        'required_level': core_req_lvl,
                    })

            if 'leadership' in allowed_pillars and is_managerial:
                lead_req_lvl = self._get_matrix_required_level('leadership', grade=grade_rec, job=job_pos, job_name=j_name) or '2'
                lead_comps = self.env['competency.competency'].search([('pillar', '=', 'leadership'), ('status', '=', 'active')])
                for comp in lead_comps:
                    raw_line_vals.append({
                        'competency_id': comp.id,
                        'pillar': 'leadership',
                        'current_level': False,
                        'required_level': lead_req_lvl,
                    })

            if 'technical' in allowed_pillars:
                tech_req_lvl = self._get_matrix_required_level('technical', grade=grade_rec, job=job_pos, job_name=j_name) or '2'
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
                    raw_line_vals.append({
                        'competency_id': comp.id,
                        'pillar': 'technical',
                        'current_level': False,
                        'required_level': tech_req_lvl,
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
        """Enforce cycle submission deadline. Competency Admins can override."""
        is_admin = bool(
            self.env.user.has_group('competency_management.group_competency_admin')
            or self.env.user.has_group('base.group_system')
            or self.env.su
            or self.env.is_admin()
        )
        if is_admin:
            return
        today = fields.Date.today()
        for rec in self:
            dl = fields.Date.to_date(rec.cycle_id.assessment_deadline) if (rec.cycle_id and rec.cycle_id.assessment_deadline) else False
            if dl and today > dl:
                deadline_str = dl.strftime('%b %d, %Y')
                raise UserError(_(
                    "The submission deadline (%s) for assessment cycle '%s' has passed. "
                    "Submissions are no longer accepted unless HR extends the deadline."
                ) % (deadline_str, rec.cycle_id.name))

    def action_enable_override(self):
        """Enable administrative edit override for an unapproved assessment."""
        self.ensure_one()
        user = self.env.user
        emp = user.employee_id
        is_elevated = self._is_elevated_evaluator(user)
        if not is_elevated:
            raise AccessError(_("Only HR / People Solution Officers and Competency Administrators can enable administrative override."))

        # Exception 1: Assessor cannot override on All Assessments; must complete on My Competency Assessments
        if self.assessor_id and self.assessor_id.id == user.id:
            raise UserError(_(
                "You are the assigned assessor for this assessment. "
                "You cannot use administrative override on your own assigned evaluation. "
                "Please complete and submit it via 'My Competency Assessments'."
            ))

        # Exception 2: Assessed employee cannot override their own assessment
        is_evaluatee = bool((emp and self.employee_id and self.employee_id.id == emp.id) or (self.employee_id and self.sudo().employee_id.user_id.id == user.id))
        if is_evaluatee:
            raise UserError(_(
                "You cannot override an assessment where you are the evaluated employee. "
                "Self-override is strictly prohibited to prevent conflicts of interest. "
                "Another HR / People Solution Officer or Competency Administrator must perform this adjustment."
            ))

        if self.state == 'locked' or self.is_locked:
            raise UserError(_("Cannot override a locked assessment. Locked assessment results are permanently protected from modification."))
        if self.cycle_id and self.cycle_id.state == 'closed':
            raise UserError(_("Cannot override assessments in a closed cycle."))

        self.write({
            'is_override_active': True,
            'override_user_id': user.id,
            'override_date': fields.Datetime.now(),
        })
        self.message_post(
            body=Markup(_(
                "⚠️ <b>Administrative Override Activated</b> by %s. Rating inputs have been unlocked for authorized adjustment."
            )) % escape(user.name or ''),
            subtype_xmlid='mail.mt_comment'
        )
        return True

    def action_disable_override(self):
        """Lock and disable administrative edit override."""
        self.ensure_one()
        user = self.env.user
        if not self._is_elevated_evaluator(user):
            raise AccessError(_("Only HR / People Solution Officers and Competency Administrators can manage administrative override."))

        self.write({
            'is_override_active': False,
            'override_user_id': False,
            'override_date': False,
        })
        self.message_post(
            body=Markup(_(
                "🔒 <b>Administrative Override Locked</b> by %s. Rating inputs are now protected."
            )) % escape(user.name or ''),
            subtype_xmlid='mail.mt_comment'
        )
        return True

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        user = self.env.user
        emp = user.employee_id
        is_elevated = self._is_elevated_evaluator(user)

        for rec in self:
            # 1. Approved or locked assessment immutability check (cannot be modified by anyone)
            if (rec.state in ('approved', 'locked') or rec.is_locked) and not force_write:
                protected_fields = {'employee_id', 'cycle_id', 'assessment_type', 'assessor_id', 'line_ids',
                                    'core_line_ids', 'leadership_line_ids', 'technical_line_ids', 'notes'}
                if set(vals.keys()) & protected_fields:
                    raise ValidationError(_("Assessment %s is approved/locked. Already approved assessment results cannot be modified by anyone.") % rec.name)

            # 2. Check if modifying assessment content when user is not assessor or assessment is submitted/past deadline
            touching_content = bool(set(vals.keys()) & {'line_ids', 'core_line_ids', 'leadership_line_ids', 'technical_line_ids', 'notes'})
            if touching_content and not force_write:
                is_assessor = bool(rec.assessor_id and rec.assessor_id.id == user.id)
                is_evaluatee = bool((emp and rec.employee_id and rec.employee_id.id == emp.id) or (rec.employee_id and rec.sudo().employee_id.user_id.id == user.id))
                is_self_draft = bool(rec.assessment_type == 'self' and is_assessor and rec.state == 'draft')

                if is_evaluatee and not is_self_draft and not force_write:
                    raise UserError(_("You cannot modify ratings on your own evaluation. Another HR / People Solution Officer or Competency Administrator must perform this adjustment."))

                if not is_assessor:
                    if not is_elevated:
                        raise UserError(_("You are not authorized to edit this assessment. Only the assigned assessor or an authorized HR / People Solution Officer with Override can input ratings."))
                    if not rec.is_override_active:
                        raise UserError(_("Editing another user's assessment requires Administrative Override. Please click 'Override Ratings' first."))
                elif rec.state != 'draft' or rec.is_deadline_passed:
                    raise UserError(_(
                        "You are the assigned assessor for this assessment. "
                        "Assessments past deadline or already submitted cannot be edited by the assessor. "
                        "An HR / People Solution Officer or Competency Administrator must review or override."
                    ))

            today = fields.Date.today()
            cycle = rec.cycle_id.sudo() if rec.cycle_id else False
            dl = fields.Date.to_date(cycle.assessment_deadline) if (cycle and cycle.assessment_deadline) else False
            is_expired = rec.is_deadline_passed or bool(dl and today > dl)
            if is_expired and rec.state == 'draft' and not force_write and not (is_elevated and rec.is_override_active):
                protected_fields = {'employee_id', 'cycle_id', 'assessment_type', 'assessor_id', 'line_ids', 'core_line_ids', 'leadership_line_ids', 'technical_line_ids', 'notes'}
                if set(vals.keys()) & protected_fields:
                    deadline_str = dl.strftime('%b %d, %Y') if dl else 'N/A'
                    raise UserError(_(
                        "The submission deadline (%s) for assessment cycle '%s' has passed. "
                        "This assessment is locked for editing and submissions are closed unless HR extends the deadline or enables Override."
                    ) % (deadline_str, rec.cycle_id.name))
        return super(CompetencyAssessment, self).write(vals)

    def _notify_user_inbox_and_activity(self, target_user, summary, note, msg_text, target_rec=None):
        """Ensure notification appears in standard Odoo notification channels:
        1. Top Header Clock Icon (mail.activity)
        2. Top Header Notifications Tray / Inbox (mail.notification with inbox type)
        """
        if not target_user:
            return
        rec_to_notify = (target_rec or self).sudo()

        # 1. Top Header Clock Icon (Planned Activity)
        try:
            rec_to_notify.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=summary,
                note=note,
                user_id=target_user.id,
            )
        except Exception:
            pass

        # 2. Document Chatter Message & In-App Notification (authored by OdooBot / System)
        if target_user.partner_id:
            try:
                odoobot = self.env.ref('base.partner_root', raise_if_not_found=False)
                author_id = odoobot.id if odoobot else False
                msg = rec_to_notify.with_context(mail_create_nosubscribe=True).message_post(
                    body=msg_text,
                    partner_ids=[target_user.partner_id.id],
                    author_id=author_id,
                    message_type='notification',
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
            except Exception:
                pass

    def action_submit(self):
        """Submit assessment: validates deadline, ratings completeness, and notifies supervisor."""
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
            rec.with_context(force_write=True).sudo().write({'state': 'submitted'})
            rec.line_ids._trigger_sibling_360_recompute()
            
            # Log submission source (Self vs Admin on behalf of employee)
            current_user = self.env.user
            assessor_user = rec.assessor_id
            is_admin = bool(
                current_user.has_group('competency_management.group_competency_admin')
                or current_user.has_group('base.group_system')
                or self.env.su
            )
            if is_admin and assessor_user and current_user != assessor_user:
                rec.sudo().message_post(body=Markup(_(
                    'Assessment %s submitted by Administrator <b>%s</b> on behalf of <b>%s</b>.'
                )) % (escape(rec.name or ''), escape(current_user.name or ''), escape(assessor_user.name or (rec.employee_id.name if rec.employee_id else 'Employee'))))
            else:
                rec.sudo().message_post(body=_('Assessment %s submitted for review.') % rec.name)

            # Targeted Notifications & Systray Activities on Submission
            if rec.assessment_type == 'self':
                # Confirmation activity for employee
                if rec.employee_id and rec.sudo().employee_id.user_id:
                    try:
                        rec.sudo().activity_schedule(
                            'mail.mail_activity_data_todo',
                            summary=_('Self-Assessment Submitted: %s') % rec.name,
                            note=_('Your competency self-assessment %s has been submitted successfully.') % rec.name,
                            user_id=rec.sudo().employee_id.user_id.id,
                        )
                    except Exception:
                        pass

                coach_emp = rec.sudo().employee_id.coach_id or rec.sudo().employee_id.parent_id
                coach_user = coach_emp.user_id if (coach_emp and coach_emp.user_id) else False

                sup_asm = False
                if rec.cycle_id and rec.employee_id:
                    sup_asm = self.env['competency.assessment'].sudo().search([
                        ('cycle_id', '=', rec.cycle_id.id),
                        ('employee_id', '=', rec.employee_id.id),
                        ('assessment_type', 'in', ('supervisor', 'team')),
                    ], limit=1)
                    if not coach_user and sup_asm and sup_asm.assessor_id:
                        coach_user = sup_asm.assessor_id

                if coach_user:
                    msg_text = Markup(_("📥 Subordinate Employee <b>%s</b> has completed and submitted their Self-Assessment for cycle '<b>%s</b>'.")) % (
                        escape(rec.employee_id.name or ''), escape(rec.cycle_id.name if rec.cycle_id else '')
                    )
                    summary_str = _('Subordinate Self-Assessment Submitted: %s') % rec.employee_id.name
                    note_str = _('Employee %s has submitted their self-assessment for cycle %s. You may now evaluate.') % (
                        rec.employee_id.name, rec.cycle_id.name if rec.cycle_id else ''
                    )
                    target_rec = sup_asm or rec
                    rec._notify_user_inbox_and_activity(coach_user, summary_str, note_str, msg_text, target_rec=target_rec)

            elif rec.assessment_type in ('supervisor', 'team'):
                emp_user = rec.sudo().employee_id.user_id if (rec.employee_id and rec.sudo().employee_id.user_id) else False

                self_asm = False
                if rec.cycle_id and rec.employee_id:
                    self_asm = self.env['competency.assessment'].sudo().search([
                        ('cycle_id', '=', rec.cycle_id.id),
                        ('employee_id', '=', rec.employee_id.id),
                        ('assessment_type', '=', 'self'),
                    ], limit=1)

                coach_name = rec.assessor_id.name if rec.assessor_id else _("Supervisor/Coach")
                msg_text = Markup(_("✅ Your supervisor/coach (<b>%s</b>) has completed and submitted your competency assessment for cycle '<b>%s</b>'.")) % (
                    escape(coach_name or ''), escape(rec.cycle_id.name if rec.cycle_id else '')
                )
                summary_str = _('Supervisor Assessment Completed: %s') % coach_name
                note_str = _('Your supervisor/coach (%s) has completed and submitted your competency assessment for cycle \'%s\'.') % (
                    coach_name, rec.cycle_id.name if rec.cycle_id else ''
                )

                if emp_user:
                    target_rec = self_asm or rec
                    rec._notify_user_inbox_and_activity(emp_user, summary_str, note_str, msg_text, target_rec=target_rec)

            elif rec.assessment_type == 'subordinate':
                # Employee submitted assessment for boss / coach
                boss_user = rec.sudo().employee_id.user_id if (rec.employee_id and rec.sudo().employee_id.user_id) else False
                if boss_user:
                    msg_text = Markup(_("📥 A subordinate evaluation has been completed and submitted for cycle '<b>%s</b>'.")) % (
                        escape(rec.cycle_id.name if rec.cycle_id else '')
                    )
                    summary_str = _('Subordinate Evaluation Submitted: %s') % rec.name
                    note_str = _('A subordinate evaluation has been submitted for cycle %s.') % (
                        rec.cycle_id.name if rec.cycle_id else ''
                    )
                    rec._notify_user_inbox_and_activity(boss_user, summary_str, note_str, msg_text, target_rec=rec)

            elif rec.assessment_type == 'peer':
                peer_user = rec.sudo().employee_id.user_id if (rec.employee_id and rec.sudo().employee_id.user_id) else False
                if peer_user:
                    msg_text = Markup(_("📥 A peer evaluation has been completed and submitted for cycle '<b>%s</b>'.")) % (
                        escape(rec.cycle_id.name if rec.cycle_id else '')
                    )
                    summary_str = _('Peer Evaluation Submitted: %s') % rec.name
                    note_str = _('A peer evaluation has been submitted for cycle %s.') % (
                        rec.cycle_id.name if rec.cycle_id else ''
                    )
                    rec._notify_user_inbox_and_activity(peer_user, summary_str, note_str, msg_text, target_rec=rec)

    def compute_aggregate_360_ratings(self):
        return self.action_consolidate_multi_source()

    def _check_segregation_of_duties(self):
        """Block self-approval by the assessed subject, assessor, or record creator."""
        for rec in self:
            subject_user = rec.sudo().employee_id.user_id if rec.employee_id else False
            assessor_user = rec.assessor_id or False
            creator_user = rec.create_uid or False
            current_user = self.env.user

            if not self.env.su:
                if (subject_user and current_user == subject_user) or \
                   (assessor_user and current_user == assessor_user) or \
                   (creator_user and current_user == creator_user):
                    raise ValidationError(_("You cannot approve your own assessment/IDP. This action must be performed by a different authorized user."))

    def action_supervisor_review(self):
        """Transition assessment to Supervisor Review state and notify supervisor."""
        for rec in self:
            rec.with_context(force_write=True).sudo().write({'state': 'supervisor_review'})
            supervisor_user = rec.sudo().employee_id.parent_id.user_id if (rec.employee_id and rec.sudo().employee_id.parent_id) else False
            if supervisor_user:
                try:
                    rec.sudo().activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('Supervisor Review Needed: Assessment %s') % rec.name,
                        note=_('Please review and complete assessment for %s.') % (rec.sudo().employee_id.name or 'Employee'),
                        user_id=supervisor_user.id,
                        date_deadline=rec.cycle_id.assessment_deadline or fields.Date.context_today(self),
                    )
                except Exception:
                    pass

    def action_hr_verify(self):
        for rec in self:
            rec._check_segregation_of_duties()
            rec.with_context(force_write=True).write({'state': 'hr_verified'})

    def action_approve(self):
        """Approve assessment with Segregation of Duties guard."""
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
        """Daily cron: pending assessment reminders, upcoming deadline alerts & overdue escalations."""
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
                emp_sudo = asm.sudo().employee_id
                if asm.state in ('draft', 'submitted') and emp_sudo and emp_sudo.user_id:
                    target_user = emp_sudo.user_id
                elif asm.state == 'supervisor_review' and emp_sudo and emp_sudo.parent_id and emp_sudo.parent_id.user_id:
                    target_user = emp_sudo.parent_id.user_id
                    
                if target_user:
                    try:
                        asm.sudo().activity_schedule(
                            'mail.mail_activity_data_todo',
                            summary=_('UPCOMING DEADLINE (%d days left): Competency Assessment %s') % (days_left, asm.name),
                            note=_('Reminder: Your competency assessment %s is due in %d days (Deadline: %s).') % (asm.name, days_left, asm.cycle_id.assessment_deadline),
                            user_id=target_user.id,
                            date_deadline=asm.cycle_id.assessment_deadline,
                        )
                    except Exception:
                        pass

        # 2. Overdue Assessments (Deadline reached or passed)
        overdue_assessments = self.search([
            ('state', 'in', ['draft', 'submitted', 'supervisor_review']),
            ('cycle_id.assessment_deadline', '!=', False),
            ('cycle_id.assessment_deadline', '<=', today)
        ])
        for asm in overdue_assessments:
            target_user = False
            emp_sudo = asm.sudo().employee_id
            if asm.state in ('draft', 'submitted') and emp_sudo and emp_sudo.user_id:
                target_user = emp_sudo.user_id
            elif asm.state == 'supervisor_review' and emp_sudo and emp_sudo.parent_id and emp_sudo.parent_id.user_id:
                target_user = emp_sudo.parent_id.user_id
                
            if target_user:
                try:
                    asm.sudo().activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('OVERDUE: Competency Assessment %s') % asm.name,
                        note=_('URGENT: Competency Assessment %s passed its deadline (%s) and is overdue for completion.') % (asm.name, asm.cycle_id.assessment_deadline),
                        user_id=target_user.id,
                        date_deadline=today,
                    )
                except Exception:
                    pass

    def get_achievement_summary_sentence(self):
        """Returns plain-language alignment sentence for this assessment."""
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
        """Returns recommended development action mappings for below-target competencies."""
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
    """One competency rating line inside an assessment."""
    _name = 'competency.assessment.line'
    _description = 'Competency Assessment Line'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if not self.env.context.get('competency_employee_select'):
            self = self.with_context(competency_employee_select=True)
        return super()._search(domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)

    @api.model
    def web_search_read(self, domain=None, specification=None, offset=0, limit=None, order=None, count_limit=None):
        if not self.env.context.get('competency_employee_select'):
            self = self.with_context(competency_employee_select=True)
        return super().web_search_read(domain=domain, specification=specification, offset=offset, limit=limit, order=order, count_limit=count_limit)

    @api.model
    def _read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        if not self.env.context.get('competency_employee_select'):
            self = self.with_context(competency_employee_select=True)
        return super()._read_group(domain, groupby=groupby, aggregates=aggregates, having=having, offset=offset, limit=limit, order=order)

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        if not self.env.context.get('competency_employee_select'):
            self = self.with_context(competency_employee_select=True)
        return super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)

    assessment_id = fields.Many2one(
        'competency.assessment', string='Assessment', required=True, ondelete='cascade')
    cycle_id = fields.Many2one(related='assessment_id.cycle_id', string='Assessment Cycle', store=True, readonly=True, index=True)
    is_current_or_latest_cycle = fields.Boolean(
        string='Current or Latest Cycle',
        related='cycle_id.is_open_or_latest', store=False, index=False
    )
    employee_id = fields.Many2one(related='assessment_id.employee_id', string='Employee', store=True, readonly=True, index=True)
    gender = fields.Selection(related='assessment_id.employee_id.gender', string='Gender', store=True, readonly=True, index=True)
    department_id = fields.Many2one(related='assessment_id.department_id', string='Department', store=True, readonly=True, index=True)
    operating_unit_id = fields.Many2one(related='assessment_id.employee_id.default_operating_unit_id', string='Operating Unit', store=True, readonly=True, index=True)
    job_id = fields.Many2one('hr.job', string='Job Position', compute='_compute_job_and_grade_id', store=True, readonly=True, index=True)
    grade_id = fields.Many2one('employee.grade', string='Job Grade', compute='_compute_job_and_grade_id', store=True, readonly=True, index=True)

    @api.depends('assessment_id.job_id', 'assessment_id.grade_id', 'assessment_id.employee_id')
    def _compute_job_and_grade_id(self):
        asm_model = self.env['competency.assessment']
        for line in self:
            emp = line.assessment_id.employee_id if line.assessment_id else False
            line.job_id = (line.assessment_id.job_id if line.assessment_id and line.assessment_id.job_id else asm_model._get_employee_job(emp)) if emp else False
            line.grade_id = (line.assessment_id.grade_id if line.assessment_id and line.assessment_id.grade_id else asm_model._resolve_employee_grade(emp)) if emp else False

    state = fields.Selection(related='assessment_id.state', string='Assessment Status', store=True, readonly=True, index=True)
    is_deadline_passed = fields.Boolean(related='assessment_id.is_deadline_passed', string='Deadline Passed', readonly=True)
    is_admin_user = fields.Boolean(related='assessment_id.is_admin_user', string='Is Competency Admin', readonly=True)
    can_edit_ratings = fields.Boolean(compute='_compute_can_edit_ratings', string='Can Edit Ratings', readonly=True)

    @api.depends('assessment_id.can_edit_ratings', 'assessment_id.state', 'assessment_id.is_locked')
    def _compute_can_edit_ratings(self):
        for line in self:
            if line.assessment_id and (line.assessment_id.state in ('approved', 'locked') or line.assessment_id.is_locked):
                line.can_edit_ratings = False
            elif line.assessment_id:
                line.can_edit_ratings = line.assessment_id.can_edit_ratings
            else:
                line.can_edit_ratings = False

    def action_open_guide(self):
        """Opens the full behavioral indicators and rating popup for this line."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Behavioral Indicators & Rating: %s') % (self.competency_id.name if self.competency_id else ''),
            'res_model': 'competency.assessment.line',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('competency_management.view_competency_assessment_line_form').id, 'form')],
            'target': 'new',
            'context': self.env.context,
        }

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
        try:
            matrix_config = self.env['competency.matrix.config'].get_active_config()
        except Exception:
            matrix_config = None
        for rec in self:
            if rec.competency_id:
                levels = self.env['competency.proficiency.level'].search([
                    ('competency_id', '=', rec.competency_id.id)
                ])
                l_map = {l.level: l.behavioral_indicators for l in levels if l.behavioral_indicators}

                l1 = l_map.get('1') or (getattr(matrix_config, 'tech_indicator_level_1', None) if (matrix_config and rec.competency_id.pillar == 'technical') else None) or 'Level 1 (Basic) behavioral indicators.'
                l2 = l_map.get('2') or (getattr(matrix_config, 'tech_indicator_level_2', None) if (matrix_config and rec.competency_id.pillar == 'technical') else None) or 'Level 2 (Intermediate) behavioral indicators.'
                l3 = l_map.get('3') or (getattr(matrix_config, 'tech_indicator_level_3', None) if (matrix_config and rec.competency_id.pillar == 'technical') else None) or 'Level 3 (Advanced) behavioral indicators.'
                l4 = l_map.get('4') or (getattr(matrix_config, 'tech_indicator_level_4', None) if (matrix_config and rec.competency_id.pillar == 'technical') else None) or 'Level 4 (Expert) behavioral indicators.'

                rec.indicator_level_1 = l1
                rec.indicator_level_2 = l2
                rec.indicator_level_3 = l3
                rec.indicator_level_4 = l4

                rec.behavioral_guide_html = f"""
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; width: 100%; margin-top: 6px; font-family: inherit;">
                    <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-top: 4px solid #726732; border-radius: 6px; padding: 12px 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); display: flex; flex-direction: column;">
                        <div style="font-size: 11px; font-weight: 800; color: #726732; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Level 1 &bull; Basic</div>
                        <div style="font-size: 12.5px; color: #334155; line-height: 1.5; flex-grow: 1;">{l1}</div>
                    </div>
                    <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-top: 4px solid #1d2b32; border-radius: 6px; padding: 12px 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); display: flex; flex-direction: column;">
                        <div style="font-size: 11px; font-weight: 800; color: #1d2b32; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Level 2 &bull; Intermediate</div>
                        <div style="font-size: 12.5px; color: #334155; line-height: 1.5; flex-grow: 1;">{l2}</div>
                    </div>
                    <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-top: 4px solid #c17540; border-radius: 6px; padding: 12px 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); display: flex; flex-direction: column;">
                        <div style="font-size: 11px; font-weight: 800; color: #c17540; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Level 3 &bull; Advanced</div>
                        <div style="font-size: 12.5px; color: #334155; line-height: 1.5; flex-grow: 1;">{l3}</div>
                    </div>
                    <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-top: 4px solid #541718; border-radius: 6px; padding: 12px 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); display: flex; flex-direction: column;">
                        <div style="font-size: 11px; font-weight: 800; color: #541718; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Level 4 &bull; Expert</div>
                        <div style="font-size: 12.5px; color: #334155; line-height: 1.5; flex-grow: 1;">{l4}</div>
                    </div>
                </div>
                """
            else:
                rec.indicator_level_1 = False
                rec.indicator_level_2 = False
                rec.indicator_level_3 = False
                rec.indicator_level_4 = False
                rec.behavioral_guide_html = False

    active = fields.Boolean(string='Active', default=True)
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
    supervisor_avg = fields.Float(string='Supervisor Rating', compute='_compute_360_ratings', store=True, group_operator='avg')
    team_avg = fields.Float(string='Team Avg', compute='_compute_360_ratings', store=True, group_operator='avg')
    weighted_current_level = fields.Float(string='Weighted Current Level', compute='_compute_360_ratings', store=True, group_operator='avg')
    self_gap = fields.Float(string='Self Gap', compute='_compute_specific_gaps', store=True, group_operator='avg',
                            help='Required proficiency minus Self rating.')
    peer_gap = fields.Float(string='Peer Gap', compute='_compute_specific_gaps', store=True, group_operator='avg',
                            help='Required proficiency minus Peer average rating.')
    subordinate_gap = fields.Float(string='Subordinate Gap', compute='_compute_specific_gaps', store=True, group_operator='avg',
                                   help='Required proficiency minus Subordinate average rating.')
    supervisor_gap = fields.Float(string='Supervisor Gap', compute='_compute_specific_gaps', store=True, group_operator='avg',
                                  help='Required proficiency minus Supervisor rating.')

    @api.depends('assessment_id.employee_id', 'assessment_id.cycle_id', 'competency_id', 'current_level')
    def _compute_360_ratings(self):
        config = self.env['competency.matrix.config'].sudo().get_active_config()
        w_self = float(config.weight_self or 2.0)
        w_peer = float(config.weight_peer or 1.0)
        w_sub = float(config.weight_subordinate or 1.0)
        w_sup = float(config.weight_supervisor or 3.0)
        w_team = float(config.weight_team or 0.0)

        lines_with_data = self.filtered(lambda l: l.employee_id and l.cycle_id and l.competency_id)
        sibling_map = {}
        if lines_with_data:
            emp_ids = list({l.employee_id.id for l in lines_with_data})
            cycle_ids = list({l.cycle_id.id for l in lines_with_data})
            comp_ids = list({l.competency_id.id for l in lines_with_data})

            all_siblings = self.env['competency.assessment.line'].sudo().search([
                ('employee_id', 'in', emp_ids),
                ('cycle_id', 'in', cycle_ids),
                ('competency_id', 'in', comp_ids),
                ('current_level', '!=', False)
            ])
            for sline in all_siblings:
                key = (sline.employee_id.id, sline.cycle_id.id, sline.competency_id.id)
                sibling_map.setdefault(key, []).append(sline)

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

            comp_lines = sibling_map.get((emp.id, cycle.id, comp.id), [])

            self_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'self']
            peer_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'peer']
            sub_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'subordinate']
            sup_lines = [l for l in comp_lines if l.assessment_id.assessment_type in ('supervisor', 'team')]
            team_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'team_member_eval']

            s_val = int(self_lines[0].current_level) if (self_lines and str(self_lines[0].current_level).isdigit()) else (int(line.current_level) if (line.assessment_id.assessment_type == 'self' and line.current_level and str(line.current_level).isdigit()) else 0.0)
            p_val = round(sum(int(l.current_level) for l in peer_lines if str(l.current_level).isdigit()) / len(peer_lines), 2) if peer_lines else 0.0
            sub_val = round(sum(int(l.current_level) for l in sub_lines if str(l.current_level).isdigit()) / len(sub_lines), 2) if sub_lines else 0.0
            sup_val = int(sup_lines[0].current_level) if (len(sup_lines) == 1 and str(sup_lines[0].current_level).isdigit()) else (round(sum(int(l.current_level) for l in sup_lines if str(l.current_level).isdigit()) / len(sup_lines), 2) if sup_lines else 0.0)
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
        is_admin = bool(
            self.env.user.has_group('competency_management.group_competency_admin')
            or self.env.user.has_group('base.group_system')
            or self.env.su
            or self.env.is_admin()
        )
        for vals in vals_list:
            if not force_write and not self.env.su and vals.get('assessment_id'):
                asm = self.env['competency.assessment'].browse(vals['assessment_id'])
                if asm.state == 'locked' and not is_admin:
                    raise ValidationError(_("Cannot add rating lines to locked assessment %s.") % asm.name)
                today = fields.Date.today()
                dl = fields.Date.to_date(asm.cycle_id.assessment_deadline) if (asm.cycle_id and asm.cycle_id.assessment_deadline) else False
                if (asm.is_deadline_passed or (dl and today > dl)) and asm.state == 'draft' and not is_admin:
                    deadline_str = dl.strftime('%b %d, %Y') if dl else 'N/A'
                    raise UserError(_(
                        "The submission deadline (%s) for assessment cycle '%s' has passed. "
                        "Rating lines cannot be added or edited after the deadline."
                    ) % (deadline_str, asm.cycle_id.name))
                rating_fields = {'current_level', 'comments', 'evidence_attachment_ids'}
                if any(f in vals for f in rating_fields) and not is_admin:
                    if asm.assessor_id and asm.assessor_id != self.env.user:
                        raise UserError(_(
                            "You are not authorized to rate or edit this assessment. "
                            "Only the assigned assessor (%s) or an HR / People Solution Officer with Override can input ratings."
                        ) % (asm.assessor_id.name or 'Assessor'))
        lines = super().create(vals_list)
        if not self.env.context.get('skip_360_recompute'):
            lines._trigger_sibling_360_recompute()
        return lines

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        user = self.env.user
        emp = user.employee_id
        is_elevated = self.env['competency.assessment']._is_elevated_evaluator(user)
        rating_fields = {'current_level', 'comments', 'evidence_attachment_ids', 'required_level'}
        touching_ratings = bool(set(vals.keys()) & rating_fields)

        for line in self:
            if touching_ratings and not force_write:
                if line.assessment_id:
                    asm = line.assessment_id
                    # 2. Approved or locked assessment results can NEVER be changed
                    if asm.state in ('approved', 'locked') or asm.is_locked:
                        raise ValidationError(_("Cannot modify rating lines on approved or locked assessment %s. Approved results are permanent.") % asm.name)

                    # 3. Check authorization & override mode
                    is_assessor = bool(asm.assessor_id and asm.assessor_id == user)
                    is_evaluatee = bool((emp and asm.employee_id and asm.employee_id.id == emp.id) or (asm.employee_id and asm.sudo().employee_id.user_id.id == user.id))
                    is_self_draft = bool(asm.assessment_type == 'self' and is_assessor and asm.state == 'draft')

                    if is_evaluatee and not is_self_draft and not force_write:
                        raise UserError(_("You cannot modify rating lines on an assessment where you are the evaluated employee."))

                    if not is_assessor:
                        if not is_elevated:
                            raise UserError(_(
                                "You are not authorized to rate or edit this assessment. "
                                "Only the assigned assessor (%s) or an HR / People Solution Officer with Override can input ratings."
                            ) % (asm.assessor_id.name or 'Assessor'))
                        if not asm.is_override_active:
                            raise UserError(_("Editing another user's assessment ratings requires Administrative Override. Please click 'Override Ratings' on the assessment first."))
                    else:
                        # Assessor editing own assessment
                        if asm.state != 'draft':
                            raise UserError(_("This assessment has already been submitted and cannot be edited by the assessor."))
                        today = fields.Date.today()
                        dl = fields.Date.to_date(asm.cycle_id.assessment_deadline) if (asm.cycle_id and asm.cycle_id.assessment_deadline) else False
                        if asm.is_deadline_passed or (dl and today > dl):
                            deadline_str = dl.strftime('%b %d, %Y') if dl else 'N/A'
                            raise UserError(_(
                                "The submission deadline (%s) for assessment cycle '%s' has passed. "
                                "Rating lines cannot be edited after the deadline."
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

        if not emp_cycle_comps:
            return

        emp_ids = list({e[0] for e in emp_cycle_comps})
        cycle_ids = list({e[1] for e in emp_cycle_comps})
        comp_ids = list({e[2] for e in emp_cycle_comps})

        all_siblings = self.env['competency.assessment.line'].sudo().search([
            ('employee_id', 'in', emp_ids),
            ('cycle_id', 'in', cycle_ids),
            ('competency_id', 'in', comp_ids),
        ])
        sibling_map = {}
        for sline in all_siblings:
            key = (sline.employee_id.id, sline.cycle_id.id, sline.competency_id.id)
            sibling_map.setdefault(key, []).append(sline)

        for (emp_id, cycle_id, comp_id) in emp_cycle_comps:
            lines_for_key = sibling_map.get((emp_id, cycle_id, comp_id), [])
            comp_lines = [l for l in lines_for_key if l.current_level]

            self_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'self']
            peer_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'peer']
            sub_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'subordinate']
            sup_lines = [l for l in comp_lines if l.assessment_id.assessment_type in ('supervisor', 'team')]
            team_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'team_member_eval']

            s_val = int(self_lines[0].current_level) if (self_lines and str(self_lines[0].current_level).isdigit()) else 0.0
            p_val = round(sum(int(l.current_level) for l in peer_lines if str(l.current_level).isdigit()) / len(peer_lines), 2) if peer_lines else 0.0
            sub_val = round(sum(int(l.current_level) for l in sub_lines if str(l.current_level).isdigit()) / len(sub_lines), 2) if sub_lines else 0.0
            sup_val = int(sup_lines[0].current_level) if (len(sup_lines) == 1 and str(sup_lines[0].current_level).isdigit()) else (round(sum(int(l.current_level) for l in sup_lines if str(l.current_level).isdigit()) / len(sup_lines), 2) if sup_lines else 0.0)
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

            all_lines = self.env['competency.assessment.line'].browse([l.id for l in lines_for_key])
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
        lines_with_data = self.filtered(lambda l: l.employee_id and l.cycle_id and l.competency_id)
        if not lines_with_data:
            for line in self:
                line.is_primary_reporting_line = True
            return

        emp_ids = list({l.employee_id.id for l in lines_with_data})
        cycle_ids = list({l.cycle_id.id for l in lines_with_data})
        comp_ids = list({l.competency_id.id for l in lines_with_data})

        all_comp_lines = self.env['competency.assessment.line'].sudo().search([
            ('employee_id', 'in', emp_ids),
            ('cycle_id', 'in', cycle_ids),
            ('competency_id', 'in', comp_ids),
        ], order='id asc')

        grouped_lines = {}
        for l in all_comp_lines:
            key = (l.employee_id.id, l.cycle_id.id, l.competency_id.id)
            grouped_lines.setdefault(key, []).append(l)

        primary_ids = set()
        for key, lines_list in grouped_lines.items():
            self_line = [l for l in lines_list if l.assessment_id.assessment_type == 'self']
            if self_line:
                primary_ids.add(self_line[0].id)
            else:
                sup_line = [l for l in lines_list if l.assessment_id.assessment_type in ('supervisor', 'team')]
                if sup_line:
                    primary_ids.add(sup_line[0].id)
                elif lines_list:
                    primary_ids.add(lines_list[0].id)

        for line in self:
            if line.employee_id and line.cycle_id and line.competency_id:
                line.is_primary_reporting_line = (line.id in primary_ids)
            else:
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

    @api.depends('required_level_num', 'self_rating', 'peer_avg', 'subordinate_avg', 'supervisor_avg')
    def _compute_specific_gaps(self):
        for rec in self:
            req = float(rec.required_level_num or 0)
            rec.self_gap = round(req - rec.self_rating, 2) if rec.self_rating else 0.0
            rec.peer_gap = round(req - rec.peer_avg, 2) if rec.peer_avg else 0.0
            rec.subordinate_gap = round(req - rec.subordinate_avg, 2) if rec.subordinate_avg else 0.0
            rec.supervisor_gap = round(req - rec.supervisor_avg, 2) if rec.supervisor_avg else 0.0


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
        is_supervisor = self.env.user.has_group('competency_management.group_competency_supervisor')
        is_officer = self.env.user.has_group('competency_management.group_competency_officer')
        if not is_supervisor and not is_officer and not self.env.su:
            raise UserError(_("Individual multi-rater score breakdowns are restricted to Supervisors and HR Officers to maintain 360-degree feedback anonymity."))
        if self.sudo().employee_id.user_id == self.env.user and not is_officer and not self.env.su:
            raise UserError(_("You cannot view individual multi-rater score breakdowns for your own assessment to maintain 360-degree feedback anonymity."))
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
                r_name = assessor_emp.sudo().name
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
                'rater_type': 'supervisor' if asm.assessment_type in ('team', 'supervisor') else (asm.assessment_type or 'self'),
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




