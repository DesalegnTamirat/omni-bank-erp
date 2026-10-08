# -*- coding: utf-8 -*-
import re
from datetime import timedelta
from odoo import api, fields, models, _


class HrEmployeeCompetency(models.Model):
    """hr.employee extension: competency profile smart buttons."""
    _inherit = 'hr.employee'

    competency_assessment_ids = fields.One2many(
        'competency.assessment', 'employee_id', string='Competency Assessments')
    competency_assessment_count = fields.Integer(
        string='Competency Assessments', compute='_compute_competency_assessment_count')

    latest_competency_assessment_id = fields.Many2one(
        'competency.assessment', string='Latest Competency Assessment',
        compute='_compute_latest_competency_assessment', store=False,
        help="Points to the employee's most recent approved/completed competency evaluation.")
    latest_competency_overall_score = fields.Float(
        string='Latest Competency Score (%)',
        compute='_compute_latest_competency_assessment', store=False,
        help="Overall weighted score percentage achieved in the latest evaluation.")
    latest_competency_assessment_date = fields.Date(
        string='Latest Assessment Date',
        compute='_compute_latest_competency_assessment', store=False)
    latest_competency_gap_summary = fields.Text(
        string='Latest Competency Gap Summary',
        compute='_compute_latest_competency_assessment', store=False,
        help="Summary of competency requirements, achieved levels, and gaps for Career Path and external analytics.")

    is_director_or_chief = fields.Boolean(
        string='Is Director or Chief',
        compute='_compute_is_director_or_chief',
        search='_search_is_director_or_chief',
        help='Indicates if employee is classified as Executive (Grade 15, Director, Chief, VP, President).'
    )

    @api.depends('job_id', 'job_id.name', 'grade_id', 'job_grade')
    def _compute_is_director_or_chief(self):
        for emp in self:
            emp.is_director_or_chief = emp._check_is_director_or_chief()

    def _check_is_director_or_chief(self):
        self.ensure_one()
        if not self.active:
            return False
        j_name = (self.job_id.name or '').strip().lower()
        if any(k in j_name for k in ['director', 'chief', 'vp', 'vice president', 'president']):
            return True

        raw_str = ''
        grade_rec = getattr(self, 'grade_id', False) or getattr(self, 'job_grade', False) or getattr(self, 'grade', False)
        if grade_rec:
            raw_str = (
                getattr(grade_rec, 'grade_name', False)
                or getattr(grade_rec, 'grade_code', False)
                or getattr(grade_rec, 'name', False)
                or getattr(grade_rec, 'code', False)
                or str(grade_rec)
            )
        if not raw_str and self.job_id:
            job_g = getattr(self.job_id, 'grade', False) or getattr(self.job_id, 'grade_id', False)
            if job_g:
                raw_str = (
                    getattr(job_g, 'grade_name', False)
                    or getattr(job_g, 'grade_code', False)
                    or getattr(job_g, 'name', False)
                    or getattr(job_g, 'code', False)
                    or str(job_g)
                )

        g_str = str(raw_str).lower().strip()
        if g_str:
            tokens = g_str.replace('-', ' ').replace('_', ' ').split()
            roman_map = {
                'xvii': 17, 'xvi': 16, 'xv': 15, 'xiv': 14, 'xiii': 13, 'xii': 12, 'xi': 11,
                'x': 10, 'ix': 9, 'viii': 8, 'vii': 7, 'vi': 6, 'v': 5, 'iv': 4, 'iii': 3, 'ii': 2, 'i': 1
            }
            g_num = 0
            for token in tokens:
                if token in roman_map:
                    g_num = roman_map[token]
                    break
            if not g_num and g_str in roman_map:
                g_num = roman_map[g_str]
            if not g_num:
                nums = re.findall(r'\d+', g_str)
                if nums:
                    g_num = int(nums[0])
            if g_num in (15, 16, 17):
                return True
        return False

    def _search_is_director_or_chief(self, operator, value):
        if operator not in ('=', '!='):
            return []
        try:
            candidates = self.env['hr.employee'].sudo().search([('active', '=', True)])
            matched_ids = [e.id for e in candidates if e._check_is_director_or_chief()]
        except Exception:
            matched_ids = []

        is_true = bool(value) if operator == '=' else not bool(value)
        return [('id', 'in', matched_ids)] if is_true else [('id', 'not in', matched_ids)]

    def _is_competency_scoped_context(self):
        ctx = self.env.context
        active_model = str(ctx.get('active_model') or '')
        params_model = str((ctx.get('params') or {}).get('model') or '')
        params_active_model = str((ctx.get('params') or {}).get('active_model') or '')

        is_competency_ctx = bool(
            ctx.get('competency_employee_select')
            or ctx.get('competency_peer_select')
            or active_model.startswith('competency.')
            or params_model.startswith('competency.')
            or params_active_model.startswith('competency.')
        )
        if not is_competency_ctx:
            return False
        user = self.env.user
        return bool(
            user.has_group('competency_management.group_competency_admin')
            or user.has_group('competency_management.group_competency_officer')
            or user.has_group('competency_management.group_competency_supervisor')
            or self.env.su
            or self.env.is_admin()
        )

    def _check_access(self, operation: str):
        if operation == 'read' and self._is_competency_scoped_context():
            return None
        return super()._check_access(operation)

    def check_access(self, operation: str) -> None:
        if operation == 'read' and self._is_competency_scoped_context():
            return None
        return super().check_access(operation)

    def check_access_rule(self, operation):
        if operation == 'read' and self._is_competency_scoped_context():
            return None
        return super().check_access_rule(operation)

    def _filter_access_rules_python(self, operation='read'):
        if operation == 'read' and self._is_competency_scoped_context():
            return self
        return super()._filter_access_rules_python(operation=operation)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if self._is_competency_scoped_context():
            bypass_access = True
        return super()._search(domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)

    def web_read(self, specification):
        if self._is_competency_scoped_context():
            return super(HrEmployeeCompetency, self.sudo()).web_read(specification)
        return super().web_read(specification)

    def read(self, fields=None, load='_classic_read'):
        if self._is_competency_scoped_context():
            return super(HrEmployeeCompetency, self.sudo()).read(fields=fields, load=load)
        return super().read(fields=fields, load=load)

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100, **kwargs):
        if self._is_competency_scoped_context():
            return super(HrEmployeeCompetency, self.sudo()).name_search(name=name, domain=domain, operator=operator, limit=limit, **kwargs)
        return super().name_search(name=name, domain=domain, operator=operator, limit=limit, **kwargs)

    @api.model
    def web_search_read(self, domain=None, specification=None, offset=0, limit=None, order=None, count_limit=None):
        try:
            with self.env.cr.savepoint():
                if self._is_competency_scoped_context():
                    return super(HrEmployeeCompetency, self.sudo()).web_search_read(
                        domain=domain, specification=specification, offset=offset, limit=limit, order=order, count_limit=count_limit
                    )
                return super().web_search_read(domain=domain, specification=specification, offset=offset, limit=limit, order=order, count_limit=count_limit)
        except Exception:
            return super().web_search_read(domain=domain, specification=specification, offset=offset, limit=limit, order=order, count_limit=count_limit)

    @api.depends('competency_assessment_ids', 'competency_assessment_ids.state', 'competency_assessment_ids.create_date', 'competency_assessment_ids.line_ids')
    def _compute_latest_competency_assessment(self):
        for emp in self:
            assessments = emp.competency_assessment_ids.filtered(
                lambda a: a.state in ('approved', 'locked')
            ).sorted(key=lambda a: (a.create_date or fields.Datetime.now(), a.id), reverse=True)
            if not assessments:
                # Fallback to any assessment if none approved
                assessments = emp.competency_assessment_ids.sorted(key=lambda a: (a.create_date or fields.Datetime.now(), a.id), reverse=True)

            latest = assessments[0] if assessments else False
            if latest:
                emp.latest_competency_assessment_id = latest.id
                emp.latest_competency_overall_score = getattr(latest, 'average_gap', 0.0) or 0.0
                emp.latest_competency_assessment_date = fields.Date.to_date(latest.create_date) if latest.create_date else False

                lines_summary = []
                for line in getattr(latest, 'line_ids', []):
                    comp_name = line.competency_id.name if line.competency_id else 'N/A'
                    req_lvl = line.required_level or 'N/A'
                    ach_lvl = line.current_level or 'N/A'
                    gap = getattr(line, 'gap', 0) or 0
                    lines_summary.append(f"- {comp_name}: Required={req_lvl}, Achieved={ach_lvl}, Gap={gap}")
                emp.latest_competency_gap_summary = "\n".join(lines_summary) if lines_summary else "No line details available."
            else:
                emp.latest_competency_assessment_id = False
                emp.latest_competency_overall_score = 0.0
                emp.latest_competency_assessment_date = False
                emp.latest_competency_gap_summary = "No competency assessment logged."

    def get_latest_competency_evaluation(self):
        """API helper method for Career Path, HR Analytics, and external modules to fetch the employee's latest evaluation."""
        self.ensure_one()
        latest = self.latest_competency_assessment_id
        if not latest:
            return {
                'employee_id': self.id,
                'employee_name': self.name,
                'has_assessment': False,
                'assessment_id': False,
                'evaluation_date': False,
                'overall_score': 0.0,
                'average_gap': 0.0,
                'cycle_name': False,
                'state': False,
                'lines': [],
            }

        line_data = []
        for line in getattr(latest, 'line_ids', []):
            comp = line.competency_id
            line_data.append({
                'competency_id': comp.id if comp else False,
                'competency_name': comp.name if comp else '',
                'pillar': comp.pillar if comp else '',
                'required_level': line.required_level or '1',
                'current_level': line.current_level or '0',
                'weighted_current_level': line.weighted_current_level or 0.0,
                'gap': getattr(line, 'gap', 0.0) or 0.0,
            })

        return {
            'employee_id': self.id,
            'employee_name': self.name,
            'has_assessment': True,
            'assessment_id': latest.id,
            'evaluation_date': fields.Date.to_date(latest.create_date) if latest.create_date else False,
            'overall_score': getattr(latest, 'average_gap', 0.0) or 0.0,
            'average_gap': getattr(latest, 'average_gap', 0.0) or 0.0,
            'cycle_name': latest.cycle_id.name if getattr(latest, 'cycle_id', False) else '',
            'state': latest.state or '',
            'lines': line_data,
        }

    @api.depends('competency_assessment_ids')
    def _compute_competency_assessment_count(self):
        for rec in self:
            rec.competency_assessment_count = len(rec.competency_assessment_ids)

    baseline_assessment_deadline = fields.Date(
        string='Baseline Assessment Deadline',
        compute='_compute_baseline_assessment_deadline',
        store=False,
        help='Automatically set to 3 months (90 days) from hire or employee creation.'
    )

    def _compute_baseline_assessment_deadline(self):
        for emp in self:
            base_date = fields.Date.to_date(emp.create_date) if emp.create_date else fields.Date.today()
            emp.baseline_assessment_deadline = base_date + timedelta(days=90)

    is_eligible_for_promotion = fields.Boolean(
        string='Eligible for Promotion',
        compute='_compute_is_eligible_for_promotion',
        store=False,
        help='False if employee missed baseline assessment deadline.'
    )

    @api.depends('competency_assessment_ids.state')
    def _compute_is_eligible_for_promotion(self):
        today = fields.Date.context_today(self)
        for emp in self:
            # Check baseline deadline compliance
            has_logged_assessment = bool(emp.competency_assessment_ids.filtered(lambda a: a.state in ('approved', 'locked')))
            missed_baseline = bool(emp.baseline_assessment_deadline and emp.baseline_assessment_deadline < today and not has_logged_assessment)
            emp.is_eligible_for_promotion = not missed_baseline

    @api.model
    def _cron_baseline_assessment_reminders(self):
        """Cron action: Sends reminders to supervisor 14 days before baseline deadline if no assessment logged."""
        today = fields.Date.context_today(self)
        target_date = today + timedelta(days=14)
        target_create_date = target_date - timedelta(days=90)
        employees_due = self.search([
            ('create_date', '>=', f"{target_create_date} 00:00:00"),
            ('create_date', '<=', f"{target_create_date} 23:59:59"),
            ('parent_id', '!=', False)
        ])
        for emp in employees_due:
            try:
                has_assessment = emp.competency_assessment_ids.filtered(lambda a: a.state in ('approved', 'locked'))
                if not has_assessment and emp.parent_id.user_id:
                    emp.activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('REMINDER: Baseline Competency Assessment Due Soon for %s') % emp.name,
                        note=_('3-Month Baseline Assessment deadline for %s is on %s (14 days remaining).') % (emp.name, emp.baseline_assessment_deadline),
                        user_id=emp.parent_id.user_id.id,
                    )
            except Exception:
                pass


    def action_view_competency_assessments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Competency Assessments',
            'res_model': 'competency.assessment',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }

    # ── Coach Supervisor Role Auto-Assignment ─────────────────────────────────

    @api.model
    def _sync_coach_supervisor_group(self, coach_ids=None):
        """Automatically grant group_competency_supervisor to users whose employee is a coach/manager."""
        sup_group = self.env.ref('competency_management.group_competency_supervisor', raise_if_not_found=False)
        if not sup_group:
            return

        domain = [('active', '=', True), ('user_id', '!=', False)]
        if coach_ids:
            domain.append(('id', 'in', list(coach_ids)))
        else:
            # All coaches/managers of active employees
            self.env.cr.execute("""
                SELECT DISTINCT coach.id
                FROM hr_employee sub
                JOIN hr_employee coach ON (coach.id = sub.coach_id OR coach.id = sub.parent_id)
                WHERE sub.active = TRUE AND coach.active = TRUE AND coach.user_id IS NOT NULL;
            """)
            c_ids = [r[0] for r in self.env.cr.fetchall() if r[0]]
            if not c_ids:
                return
            domain.append(('id', 'in', c_ids))

        coaches = self.sudo().search(domain)
        for coach in coaches:
            user = coach.user_id
            if user:
                user_groups = user.group_ids if 'group_ids' in user._fields else getattr(user, 'groups_id', self.env['res.groups'])
                if sup_group not in user_groups:
                    field_name = 'group_ids' if 'group_ids' in user._fields else 'groups_id'
                    user.sudo().write({field_name: [(4, sup_group.id)]})

    @api.model
    def _sync_all_coach_supervisor_groups(self):
        """Batch maintenance cron / upgrade hook: Ensures all active coaches have Supervisor access."""
        self._sync_coach_supervisor_group()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        coach_ids = set()
        for vals in vals_list:
            if vals.get('coach_id'):
                coach_ids.add(vals['coach_id'])
            if vals.get('parent_id'):
                coach_ids.add(vals['parent_id'])
        user_emp_ids = [rec.id for rec in records if rec.user_id]
        if user_emp_ids:
            found = self.sudo().search([
                ('active', '=', True),
                '|', ('coach_id', 'in', user_emp_ids), ('parent_id', 'in', user_emp_ids)
            ])
            coach_ids.update(found.mapped('coach_id').ids + found.mapped('parent_id').ids)
        if coach_ids:
            self._sync_coach_supervisor_group(coach_ids)
        return records

    def write(self, vals):
        res = super().write(vals)
        trigger_fields = {'coach_id', 'parent_id', 'user_id', 'active'}
        if trigger_fields.intersection(vals.keys()):
            coach_ids = set()
            if vals.get('coach_id'):
                coach_ids.add(vals['coach_id'])
            if vals.get('parent_id'):
                coach_ids.add(vals['parent_id'])
            for emp in self:
                if emp.coach_id:
                    coach_ids.add(emp.coach_id.id)
                if emp.parent_id:
                    coach_ids.add(emp.parent_id.id)
            if 'user_id' in vals:
                u_emp_ids = [emp.id for emp in self if emp.user_id]
                if u_emp_ids:
                    found = self.sudo().search([
                        ('active', '=', True),
                        '|', ('coach_id', 'in', u_emp_ids), ('parent_id', 'in', u_emp_ids)
                    ])
                    coach_ids.update(found.mapped('coach_id').ids + found.mapped('parent_id').ids)
            if coach_ids:
                self._sync_coach_supervisor_group(coach_ids)
        return res



