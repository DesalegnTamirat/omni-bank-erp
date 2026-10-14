# -*- coding: utf-8 -*-
import calendar
from datetime import date, timedelta
from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EdsTnaCycle(models.Model):
    """Annual Bank-wide Training Needs Assessment cycle (/002/009).

    Default start 1 April, submission window 10 working days,
    approval deadline 31 May - all configurable in EDS settings.
    """
    _name = 'eds.tna.cycle'
    _description = 'TNA Cycle'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False, default=lambda self: _('New'))
    year = fields.Char(string='Assessment Year', required=True, index=True,
                       default=lambda self: str(fields.Date.context_today(self).year),
                       readonly=True, tracking=True)
    start_date = fields.Date(string='Cycle Start Date', required=True, default=lambda self: self._default_start_date(), tracking=True)
    submission_end_date = fields.Date(
        string='Submission End Date', compute='_compute_dates', store=True, readonly=False, tracking=True)
    approval_deadline = fields.Date(
        string='Approval Deadline', compute='_compute_dates', store=True, readonly=False, tracking=True)
    methodology = fields.Text(string='Assessment Methodology')

    @api.model
    def _default_responsible_team(self):
        return self.env['hr.department'].search([
            '|', ('name', '=ilike', '%learning%'), ('name', '=ilike', '%development%')
        ], limit=1)

    responsible_team_id = fields.Many2one(
        'hr.department',
        string='Responsible Team',
        default=_default_responsible_team,
        help='L&D / Talent Development team coordinating this TNA cycle.'
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('collecting', 'Collecting Needs'),
        ('consolidating', 'Consolidating'),
        ('under_approval', 'Under Approval'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], string='Status', default='draft', tracking=True)
    entry_ids = fields.One2many('eds.tna.entry', 'cycle_id', string='Training Needs')
    entry_count = fields.Integer(string='Training Need Count', compute='_compute_entry_count')
    individual_entry_ids = fields.One2many(
        'eds.tna.entry', 'cycle_id', string='Individual Training Needs',
        domain=[('request_level', '=', 'individual'), ('source', '=', 'manual'),
                ('state', '!=', 'draft')])
    work_unit_entry_ids = fields.One2many(
        'eds.tna.entry', 'cycle_id', string='Work Unit Training Needs',
        domain=[('request_level', '=', 'work_unit'), ('state', '!=', 'draft')])
    diagnostic_entry_ids = fields.One2many(
        'eds.tna.entry', 'cycle_id', string='Competency / PMS Diagnostics',
        domain=[('source', 'in', ('competency_gap', 'pms')), ('state', '!=', 'draft')])
    duplicate_entry_ids = fields.One2many(
        'eds.tna.entry', 'cycle_id', string='Duplicate Needs',
        domain=[('is_duplicate', '=', True)])
    invalid_entry_ids = fields.One2many(
        'eds.tna.entry', 'cycle_id', string='Invalid or Excluded Needs',
        domain=['&', ('is_duplicate', '=', False), '|', ('state', '=', 'excluded'),
                ('exclusion_type', 'in', ('process', 'system', 'structural', 'other'))])
    course_summary_ids = fields.One2many(
        'eds.tna.cycle.course.line', 'cycle_id', string='Course Demand Summary')
    course_summary_count = fields.Integer(
        string='Demand Courses', compute='_compute_course_summary_count')
    course_demand_dirty = fields.Boolean(default=True, copy=False)
    course_demand_last_sync = fields.Datetime(copy=False)
    competency_gap_count = fields.Integer(string='Competency Gaps', compute='_compute_source_breakdown')
    pms_gap_count = fields.Integer(string='PMS Gaps', compute='_compute_source_breakdown')
    employee_sub_count = fields.Integer(string='Self-Submissions', compute='_compute_source_breakdown')
    manager_sub_count = fields.Integer(string='Manager Requests', compute='_compute_source_breakdown')
    days_until_deadline = fields.Integer(
        string='Days Until Approval Deadline', compute='_compute_days_until_deadline')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    # consolidations per cycle (-010)
    consolidation_ids = fields.One2many(
        'eds.tna.consolidation', 'cycle_id', string='Consolidations')
    consolidation_count = fields.Integer(
        string='Consolidation Count', compute='_compute_consolidation_count')
    last_reminder_date = fields.Date(string='Last Deadline Reminder', readonly=True)

    @api.depends('entry_ids.source')
    def _compute_source_breakdown(self):
        for rec in self:
            rec.competency_gap_count = len(rec.entry_ids.filtered(lambda e: e.source == 'competency_gap'))
            rec.pms_gap_count = len(rec.entry_ids.filtered(lambda e: e.source == 'pms'))
            rec.employee_sub_count = len(rec.entry_ids.filtered(lambda e: e.source == 'manual' and e.submitted_by.id == e.employee_id.user_id.id))
            rec.manager_sub_count = len(rec.entry_ids.filtered(lambda e: e.source == 'manual' and e.submitted_by.id != e.employee_id.user_id.id))

    def action_open_pull_competency_gaps(self):
        """Open wizard to pull diagnosed gaps from a closed competency assessment cycle."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pull Closed Competency Gaps'),
            'res_model': 'eds.competency.gap.import',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_cycle_id': self.id},
        }

    def action_open_pull_pms_gaps(self):
        """Open wizard to pull performance gaps from finalized PMS appraisals."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pull PMS Performance Gaps'),
            'res_model': 'eds.pms.gap.import',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_cycle_id': self.id},
        }

    def action_pull_competency_gaps(self):
        """Auto-pull diagnosed gaps from the Competency Assessment framework into this TNA cycle."""
        self.ensure_one()
        if self.state not in ('draft', 'collecting'):
            raise UserError(_('Competency gaps can only be pulled into Draft or Collecting cycles.'))

        if 'competency.assessment.line' not in self.env:
            raise UserError(_('Competency Management module is not installed.'))

        AssessmentLine = self.env['competency.assessment.line']

        # Query all active assessment lines with below proficiency
        gap_lines = AssessmentLine.sudo().search([
            '|',
            ('tna_measure', '=', 'below'),
            ('gap', '>', 0),
            ('employee_id.active', '=', True),
        ])

        created_count = 0
        existing_keys = set(
            self.entry_ids.filtered(lambda e: e.employee_id and e.competency_id).mapped(
                lambda e: (e.employee_id.id, e.competency_id.id)
            )
        )

        new_entries = []
        for line in gap_lines:
            if not line.employee_id or not line.competency_id:
                continue
            key = (line.employee_id.id, line.competency_id.id)
            if key in existing_keys:
                continue
            existing_keys.add(key)

            gap_val = line.gap or (int(line.required_level or 2) - int(line.current_level or 1))
            if gap_val <= 0:
                continue
            severity = 'critical' if gap_val >= 3 else ('high' if gap_val == 2 else 'medium')

            comp_courses = self.env['eds.course.competency.line'].sudo().search([
                ('competency_id', '=', line.competency_id.id),
                ('required_level', '>=', str(line.required_level or '1')),
                ('course_id.status', 'in', ('active', 'draft'))
            ]).mapped('course_id')
            prog_name = comp_courses[0].name if len(comp_courses) == 1 else (_("%s Mastery Program") % line.competency_id.name)

            emp = line.employee_id
            new_entries.append({
                'cycle_id': self.id,
                'request_level': 'individual',
                'employee_id': emp.id,
                'work_unit_id': getattr(emp, 'default_operating_unit_id', False) and emp.default_operating_unit_id.id or False,
                'department_id': emp.department_id.id if emp.department_id else False,
                'job_position_id': emp.job_position.id if getattr(emp, 'job_position', False) else (emp.job_id.id if emp.job_id else False),
                'competency_id': line.competency_id.id,
                'competency_level': {
                    '1': 'basic', '2': 'intermediate', '3': 'advanced', '4': 'expert',
                }.get(str(line.required_level), 'intermediate'),
                'competency_gap_level_diff': gap_val,
                'course_id': comp_courses[0].id if len(comp_courses) == 1 else False,
                'suggested_course_ids': [(6, 0, comp_courses.ids)],
                'gap_severity': severity,
                'source': 'competency_gap',
                'delivery_mode': 'classroom',
                'proposed_program': prog_name,
                'justification': _(
                    "Automated diagnostic from Competency Assessment (%s). Required Level: %s, Current Level: %s (Gap: %d)."
                ) % (line.assessment_id.name if line.assessment_id else 'Direct Assessment', line.required_level or '2', line.current_level or '1', gap_val),
                'state': 'submitted',
            })

        if new_entries:
            self.env['eds.tna.entry'].sudo().create(new_entries)
            created_count = len(new_entries)

        self.message_post(body=_(
            "Diagnostic sync: Successfully ingested %d competency assessment gaps into cycle %s."
        ) % (created_count, self.name))

        if created_count == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Competency Scan Complete'),
                    'message': _('Scan completed. No new competency assessment gaps found to ingest into cycle %s (or all diagnosed gaps already exist).') % self.name,
                    'type': 'warning',
                    'sticky': False,
                }
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Competency Gaps Ingested'),
                'message': _('Successfully pulled %d diagnosed competency gaps into TNA Cycle %s.') % (created_count, self.name),
                'type': 'success',
                'sticky': False,
            }
        }

    @api.depends('consolidation_ids')
    def _compute_consolidation_count(self):
        for rec in self:
            rec.consolidation_count = len(rec.consolidation_ids)

    def action_view_consolidations(self):
        """Open only this cycle's screening and approval registers."""
        self.ensure_one()
        action = self.env.ref(
            'employee_development_system.action_eds_tna_consolidation'
        ).read()[0]
        action['domain'] = [('cycle_id', '=', self.id)]
        action['context'] = {'default_cycle_id': self.id}
        return action

    @api.depends('course_summary_ids')
    def _compute_course_summary_count(self):
        for rec in self:
            rec.course_summary_count = len(rec.course_summary_ids)

    def _mark_course_demand_dirty(self):
        stale = self.filtered(lambda cycle: not cycle.course_demand_dirty)
        if stale:
            stale.sudo().write({'course_demand_dirty': True})

    def _sync_course_demand(self):
        """Persist course demand from eligible needs without changing planning choices."""
        self.ensure_one()
        CourseLine = self.env['eds.tna.cycle.course.line']
        Demand = self.env['eds.tna.cycle.course.employee']
        Evidence = self.env['eds.tna.cycle.course.evidence']
        Course = self.env['eds.course']

        entries = self.env['eds.tna.entry'].search([
            ('cycle_id', '=', self.id),
            ('state', 'not in', ('draft', 'excluded')),
            ('is_duplicate', '=', False),
            ('exclusion_type', '=', False),
        ])

        course_data = {}

        for entry in entries:
            target_courses = Course.browse()
            if entry.request_level == 'individual' and entry.source == 'manual' and entry.requested_course_ids:
                target_courses |= entry.requested_course_ids
            elif entry.source in ('competency_gap', 'pms') and entry.suggested_course_ids:
                target_courses |= entry.suggested_course_ids
            elif entry.course_id:
                target_courses |= entry.course_id
            elif entry.suggested_course_ids:
                target_courses |= entry.suggested_course_ids
            elif entry.recommended_course_id:
                target_courses |= entry.recommended_course_id

            if entry.request_level == 'work_unit':
                emps = entry.work_unit_employee_ids
                if not emps and entry.employee_id:
                    emps = entry.employee_id
            else:
                emps = entry.employee_id

            c_keys = []
            if target_courses:
                for c in target_courses:
                    c_keys.append(('course', c.id, c.name, c.duration_days,
                                   c.recommended_source or 'internal'))
            if entry.is_custom_course and entry.custom_course_title:
                c_keys.append(('custom', False, entry.custom_course_title, 1, 'internal'))
            elif not c_keys:
                name = entry.proposed_program or (entry.competency_id and entry.competency_id.name) or (entry.pms_measure_id and entry.pms_measure_id.name) or _('Unassigned Program')
                c_keys.append(('custom', False, name, 1, 'internal'))

            for c_key in c_keys:
                _c_type, cid, cname, duration, delivery = c_key
                dict_key = (cid or 0, '' if cid else cname.strip().casefold())
                if dict_key not in course_data:
                    course_data[dict_key] = {
                        'course_id': cid,
                        'course_name': cname,
                        'duration_days': duration or 1,
                        'delivery_method': delivery or 'internal',
                        'target_quarter': entry.quarter if entry.quarter in ('q1', 'q2', 'q3', 'q4') else 'q1',
                        'individual_ids': set(),
                        'work_unit_ids': set(),
                        'competency_ids': set(),
                        'pms_ids': set(),
                        'employee_ids': set(),
                        'request_ids': set(),
                        'employee_evidence': {},
                    }

                slot = course_data[dict_key]
                slot['request_ids'].add(entry.id)
                employee_ids = set(emps.ids)
                if entry.source == 'competency_gap':
                    slot['competency_ids'].update(employee_ids)
                elif entry.source == 'pms':
                    slot['pms_ids'].update(employee_ids)
                elif entry.request_level == 'work_unit':
                    slot['work_unit_ids'].update(employee_ids)
                else:
                    slot['individual_ids'].update(employee_ids)
                slot['employee_ids'].update(employee_ids)
                for employee_id in employee_ids:
                    slot['employee_evidence'].setdefault(employee_id, set()).add(entry.id)

        existing = {
            (line.course_id.id or 0, '' if line.course_id else (line.course_name or '').strip().casefold()): line
            for line in self.course_summary_ids
        }
        retained = CourseLine.browse()
        for key, data in course_data.items():
            emp_ids = list(data['employee_ids'])
            vals = {
                'cycle_id': self.id,
                'course_id': data['course_id'],
                'course_name': data['course_name'],
                'duration_days': data['duration_days'],
                'delivery_method': data['delivery_method'],
                'target_quarter': data['target_quarter'],
                'count_individual': len(data['individual_ids']),
                'count_work_unit': len(data['work_unit_ids']),
                'count_competency': len(data['competency_ids']),
                'count_pms': len(data['pms_ids']),
                'request_count': len(data['request_ids']),
                'total_employees': len(emp_ids),
                'employee_ids': [(6, 0, emp_ids)],
            }
            line = existing.get(key)
            if line:
                updates = {field: vals[field] for field in (
                    'course_name', 'count_individual', 'count_work_unit',
                    'count_competency', 'count_pms', 'request_count',
                    'total_employees') if line[field] != vals[field]}
                if set(line.employee_ids.ids) != data['employee_ids']:
                    updates['employee_ids'] = vals['employee_ids']
                if updates:
                    line.write(updates)
                retained |= line
            else:
                line = CourseLine.create(dict(vals, selected_for_planning=True))
                retained |= line
            # Preserve stable demand/evidence IDs so resyncs do not generate
            # thousands of unlink/create operations or invalidate open forms.
            demand_by_employee = {d.employee_id.id: d for d in line.employee_demand_ids}
            stale_demand_ids = [d.id for employee_id, d in demand_by_employee.items()
                                if employee_id not in data['employee_evidence']]
            if stale_demand_ids:
                Demand.browse(stale_demand_ids).unlink()
            new_employee_ids = sorted(set(data['employee_evidence']) - set(demand_by_employee))
            if new_employee_ids:
                created = Demand.create([{
                    'course_line_id': line.id, 'employee_id': employee_id,
                } for employee_id in new_employee_ids])
                demand_by_employee.update({d.employee_id.id: d for d in created})
            stale_evidence_ids = []
            new_evidence_vals = []
            for employee_id, entry_ids in data['employee_evidence'].items():
                demand = demand_by_employee[employee_id]
                existing_evidence = {e.entry_id.id: e for e in demand.evidence_ids}
                stale_evidence_ids.extend(e.id for entry_id, e in existing_evidence.items()
                                          if entry_id not in entry_ids)
                new_evidence_vals.extend({
                    'demand_id': demand.id, 'entry_id': entry_id,
                } for entry_id in entry_ids - set(existing_evidence))
            if stale_evidence_ids:
                Evidence.browse(stale_evidence_ids).unlink()
            if new_evidence_vals:
                Evidence.create(new_evidence_vals)
        (self.course_summary_ids - retained).unlink()

        self.write({
            'course_demand_dirty': False,
            'course_demand_last_sync': fields.Datetime.now(),
        })
        return len(retained), len(entries)

    def action_aggregate_courses(self):
        """Let staff refresh demand explicitly after an external data correction."""
        self.ensure_one()
        line_count, entry_count = self._sync_course_demand()

        self.message_post(body=_("Aggregated %d course demand summaries from %d training needs.") % (line_count, entry_count))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_go_to_planning(self):
        """Convert selected course demands into Annual L&D Plan lines and navigate to Planning."""
        self.ensure_one()
        if self.course_demand_dirty or not self.course_demand_last_sync:
            self._sync_course_demand()

        selected_courses = self.course_summary_ids.filtered('selected_for_planning')
        if not selected_courses:
            raise UserError(_("Select at least one course in Course Demand before going to planning."))

        Plan = self.env['eds.annual.plan']
        plan_domain = [
            ('fiscal_year', '=', self.year), ('state', '=', 'draft'),
            ('company_id', '=', self.company_id.id),
        ]
        if not (self.env.su or self.env.user.has_group(
                'employee_development_system.group_eds_manager')):
            plan_domain.append(('creator_id', '=', self.env.user.id))
        plan = Plan.search(plan_domain, limit=1)
        if not plan:
            plan = Plan.create({
                'fiscal_year': self.year,
                'company_id': self.company_id.id,
                'notes': _("Initialized from TNA Cycle %s.") % self.name,
            })

        existing_course_ids = set(plan.line_ids.mapped('course_id.id'))
        existing_names = set(plan.line_ids.mapped('program_name'))

        for c_summary in selected_courses:
            if c_summary.course_id and c_summary.course_id.id in existing_course_ids:
                continue
            if c_summary.course_name in existing_names:
                continue

            participants = c_summary.total_employees
            line_vals = {
                'plan_id': plan.id,
                'course_demand_id': c_summary.id,
                'course_id': c_summary.course_id.id if c_summary.course_id else False,
                'program_name': c_summary.course_name,
                'duration_days': c_summary.duration_days or 1,
                'planned_participants': participants,
                'quarter': c_summary.target_quarter or 'q1',
                'delivery_method': c_summary.delivery_method or 'internal',
            }
            plan_line = self.env['eds.annual.plan.line'].create(line_vals)
            plan_line._init_default_budget_lines()

            if c_summary.course_id:
                existing_course_ids.add(c_summary.course_id.id)
            existing_names.add(c_summary.course_name)

        self.message_post(body=_("Created/updated Annual L&D Plan %s with %d courses from cycle demand.") % (plan.name, len(selected_courses)))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Annual L&D Plan'),
            'res_model': 'eds.annual.plan',
            'res_id': plan.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def _cron_tna_deadline_reminder(self):
        """remind pending approvers before the approval deadline; escalate if breached.

        Runs daily (eds.cron_tna_deadline_reminder). Notifies the L&D Manager group via chatter
        once per 7-day window; once the deadline is breached the escalation text is used.
        """
        today = date.today()
        cycles = self.search([
            ('state', 'in', ('collecting', 'consolidating', 'under_approval')),
            ('approval_deadline', '!=', False),
        ])
        manager_group = self.env.ref('employee_development_system.group_eds_manager', raise_if_not_found=False)
        recipients = manager_group.user_ids if manager_group else self.env['res.users']
        partner_ids = recipients.filtered('partner_id').mapped('partner_id').ids
        for cycle in cycles:
            days_left = (cycle.approval_deadline - today).days
            if days_left > 14:
                continue
            if cycle.last_reminder_date and (today - cycle.last_reminder_date).days < 7:
                continue
            if days_left >= 0:
                msg_text = _('Reminder: TNA cycle %s must be approved by %s - %d days left.'
                             ' Pending approvers: PPDD Validation, Director PPDD, CPCO, SMC.') % (
                    cycle.name, cycle.approval_deadline, days_left)
            else:
                msg_text = _('DEADLINE BREACHED: TNA cycle %s approval deadline (%s) has been'
                             ' missed by %d days. Escalated for senior management review.') % (
                    cycle.name, cycle.approval_deadline, -days_left)

            action_link = f"/web#id={cycle.id}&model=eds.tna.cycle"
            body = Markup(f"""<p>{escape(msg_text)}</p>
<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">📋 Open TNA Cycle</a>
</div>""")
            cycle.message_post(body=body, partner_ids=partner_ids)
            cycle.last_reminder_date = today
        return True

    @api.model
    def _default_start_date(self):
        """Default: 1st of the configured TNA start month (BRD: 1 April)."""
        month = int(self.env['ir.config_parameter'].sudo().get_param('eds.tna_cycle_start_month', '4'))
        try:
            return date(date.today().year, month, 1)
        except ValueError:
            return date.today()

    @api.depends('start_date')
    def _compute_dates(self):
        for rec in self:
            if not rec.start_date:
                continue
            sub_days = rec._get_int_param('eds.tna_submission_days', 10)
            rec.submission_end_date = rec._add_working_days(rec.start_date, sub_days)
            approval_days = rec._get_int_param('eds.tna_approval_days', 30)
            rec.approval_deadline = rec._add_working_days(rec.submission_end_date, approval_days)

    @api.constrains('start_date', 'submission_end_date', 'approval_deadline')
    def _check_cycle_dates(self):
        for rec in self:
            if rec.start_date and rec.submission_end_date and rec.submission_end_date < rec.start_date:
                raise ValidationError(_("Submission End Date (%s) cannot be earlier than Cycle Start Date (%s).")
                                      % (rec.submission_end_date, rec.start_date))
            if rec.submission_end_date and rec.approval_deadline and rec.approval_deadline < rec.submission_end_date:
                raise ValidationError(_("Approval Deadline (%s) cannot be earlier than Submission End Date (%s).")
                                      % (rec.approval_deadline, rec.submission_end_date))

    @api.depends('entry_ids')
    def _compute_entry_count(self):
        for rec in self:
            rec.entry_count = len(rec.entry_ids)

    @api.depends('approval_deadline')
    def _compute_days_until_deadline(self):
        today = date.today()
        for rec in self:
            rec.days_until_deadline = (rec.approval_deadline - today).days if rec.approval_deadline else 0

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.model
    def _add_working_days(self, d, days):
        """Add N working days (Mon-Fri) to a date - used for submission windows/SLAs."""
        if not d or not days:
            return d
        current = d
        added = 0
        while added < days:
            current += timedelta(days=1)
            if current.weekday() < 5:
                added += 1
        return current

    @api.model_create_multi
    def create(self, vals_list):
        # sudo(): base security denies plain users direct ir.sequence access, which
        # would break self-service record creation .
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.tna.cycle') or _('New')
        return super().create(vals_list)

    def web_read(self, specification):
        if 'course_summary_ids' in specification or 'course_summary_count' in specification:
            for cycle in self:
                if cycle.course_demand_dirty or not cycle.course_demand_last_sync:
                    cycle.sudo()._sync_course_demand()
        return super().web_read(specification)

    # ── Workflow (/008/009/010) ──────────────────────────────────────
    def action_start_collection(self):
        """Draft -> Collecting (opens the submission window, /002)."""
        today = fields.Date.today()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft TNA cycles can start collection.'))
            if rec.submission_end_date and rec.submission_end_date < today:
                raise UserError(_(
                    "Cannot start collection: Submission End Date (%s) has already passed. "
                    "Please update the submission end date to an active date before opening collection."
                ) % rec.submission_end_date)
            if rec.start_date and rec.start_date > today:
                rec.start_date = today
            rec.state = 'collecting'
            rec.message_post(body=_('TNA cycle %s opened for collection. Submission window: %s to %s.')
                             % (rec.name, rec.start_date, rec.submission_end_date))

    def action_finish_collection(self):
        """Collecting -> Consolidating."""
        for rec in self:
            if not rec.entry_ids:
                raise UserError(_('No training needs were submitted for this cycle.'))
            rec.state = 'consolidating'
            rec.message_post(body=_('TNA cycle %s moved to consolidation.') % rec.name)

    def action_submit_for_approval(self):
        """Consolidating -> Under Approval (PPDD validation -> Director review ->
        CPCO endorsement -> SMC final approval; stages are tracked via chatter/approval log)."""
        for rec in self:
            if rec.state != 'consolidating':
                raise UserError(_('Only consolidating TNA cycles can be submitted for approval.'))
            if not rec.consolidation_ids:
                raise UserError(_(
                    'Consolidate the training needs before submitting this cycle for approval.'))
            outstanding = rec.entry_ids.filtered(
                lambda entry: entry.state in ('submitted', 'validated')
                and not entry.consolidation_id and not entry.exclusion_type)
            if outstanding:
                raise UserError(_(
                    '%d training needs are not in a consolidation. Re-run consolidation before submitting.')
                    % len(outstanding))
            rec.state = 'under_approval'
            rec.message_post(
                body=_('TNA %s submitted for approval (PPDD Validation -> Director PPDD -> CPCO -> SMC).')
                % rec.name)
            if all(consolidation.state in ('approved', 'locked')
                   for consolidation in rec.consolidation_ids):
                rec.action_approve()

    def action_approve(self):
        """Under Approval -> Approved (approved TNA becomes the official source)."""
        for rec in self:
            if rec.state != 'under_approval':
                raise UserError(_('Only cycles under approval can be approved.'))
            if not rec.consolidation_ids or any(
                consolidation.state not in ('approved', 'locked')
                for consolidation in rec.consolidation_ids
            ):
                raise UserError(_(
                    'The TNA cycle can be approved only after all its consolidations are approved.'))
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('TNA cycle %s approved. Approved needs are locked for curriculum planning.')
                             % rec.name)

    def action_lock(self):
        """Approved -> Locked ( control)."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only approved TNA cycles can be locked.'))
            rec.state = 'locked'
            rec.message_post(body=_('TNA cycle %s locked. Modifications require a documented change request.')
                             % rec.name)

    def action_unlock(self):
        """Locked -> Approved (admin only, documented change request)."""
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('Only EDS Administrators can unlock a locked TNA cycle.'))
        self.state = 'approved'
        self.message_post(body=_('TNA cycle %s unlocked with a documented change request.') % self.name)


class EdsTnaEntry(models.Model):
    """A single training need within a cycle (/004, ..005, )."""
    _name = 'eds.tna.entry'
    _description = 'TNA Training Need Entry'
    _inherit = ['mail.thread']
    _order = 'id desc'
    _rec_name = 'name'

    def _default_employee_id(self):
        return self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)

    def _default_work_unit_id(self):
        emp = self._default_employee_id()
        if emp and hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id:
            return emp.default_operating_unit_id
        return getattr(self.env.user, 'default_operating_unit_id', False)

    def _default_department_id(self):
        emp = self._default_employee_id()
        return emp.department_id if emp else False

    def _default_job_position_id(self):
        emp = self._default_employee_id()
        return emp.job_position if emp else False

    name = fields.Char(string='Reference', readonly=True, copy=False)
    cycle_id = fields.Many2one(
        'eds.tna.cycle', string='TNA Cycle', required=True, ondelete='cascade', index=True,
        domain=[('state', '=', 'collecting')], tracking=True)
    work_unit_id = fields.Many2one(
        'operating.unit', string='Work Unit', default=_default_work_unit_id, tracking=True)
    department_id = fields.Many2one(
        'hr.department', string='Department', default=_default_department_id, tracking=True)
    job_position_id = fields.Many2one(
        'hr.job', string='Job Position', default=_default_job_position_id, tracking=True)
    request_level = fields.Selection([
        ('individual', 'Individual'),
        ('work_unit', 'Work Unit'),
    ], string='Request Level', default='individual', required=True, tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', default=_default_employee_id, index=True, tracking=True)
    work_unit_employee_ids = fields.Many2many(
        'hr.employee', 'eds_tna_entry_work_unit_emps_rel', 'entry_id', 'employee_id',
        string='Selected Employees (Work Unit)',
        help='Employees nominated by the work unit leader for this course.')
    allowed_work_unit_ids = fields.Many2many(
        'operating.unit', compute='_compute_allowed_work_units',
        string='Work Units I Manage')
    eligible_work_unit_employee_ids = fields.Many2many(
        'hr.employee', compute='_compute_eligible_work_unit_employees',
        string='Eligible Work Unit Employees')

    @api.depends_context('uid')
    def _compute_allowed_work_units(self):
        units = (self.env['operating.unit'].search([])
                 if self.env.su or self.env.user.has_group('employee_development_system.group_eds_officer')
                 else self.env['eds.hr.compat'].get_managed_operating_units())
        for rec in self:
            rec.allowed_work_unit_ids = units

    @api.depends('request_level', 'work_unit_id', 'department_id', 'job_position_id')
    def _compute_eligible_work_unit_employees(self):
        Employee = self.env['hr.employee'].sudo()
        for rec in self:
            if rec.request_level != 'work_unit' or not rec.work_unit_id:
                rec.eligible_work_unit_employee_ids = Employee.browse()
                continue
            domain = self.env['eds.hr.compat'].get_employee_domain(
                department=rec.department_id, operating_unit=rec.work_unit_id,
                job=rec.job_position_id)
            rec.eligible_work_unit_employee_ids = Employee.search(
                [('active', '=', True)] + domain)
    competency_id = fields.Many2one(
        'competency.competency', string='Competency',
        help='Linked to the approved competency framework .', tracking=True)
    gap_severity = fields.Selection([
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ], string='Gap Severity', default='medium', required=True, tracking=True)
    source = fields.Selection([
        ('manual', 'Manual Entry'),
        ('competency_gap', 'Competency Gap Assessment'),
        ('pms', 'Performance Management (PMS)'),
        ('succession', 'Succession Planning'),
        ('audit', 'Audit Finding'),
        ('regulatory', 'Regulatory / Compliance'),
        ('customer_feedback', 'Customer Feedback'),
        ('industry_trend', 'Industry Trend'),
    ], string='Source', default='manual', required=True, tracking=True)
    target_audience = fields.Selection([
        ('bod', 'BoD (Board of Directors)'),
        ('smc', 'SMC (Senior Management Committee)'),
        ('mlm', 'MLM (Middle Level Management)'),
        ('below_mlm', 'Staff Below MLM'),
        ('all_staff', 'All Staff'),
    ], string='Target Group / Audience', default='all_staff', tracking=True)
    target_participant_count = fields.Integer(
        string='Number of Participants', default=1, compute='_compute_participant_count', store=True, readonly=False,
        help='Planned participant headcount for this training need.')
    template_participant_count = fields.Integer(
        string='HR Template Estimated Participants', readonly=True,
        help='Original headcount from the imported HR TNA template. Select actual employees before submitting the work-unit request.')
    competency_level = fields.Selection([
        ('basic', 'Basic'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert'),
    ], string='Required Competency Level', default='intermediate', tracking=True)
    delivery_mode = fields.Selection([
        ('classroom', 'Classroom'),
        ('virtual', 'Virtual'),
        ('e_learning', 'E-Learning'),
        ('blended', 'Blended'),
        ('workshop', 'Workshop'),
        ('on_the_job', 'On-the-job'),
        ('coaching', 'Coaching / Mentoring'),
        ('exposure', 'Abroad - Training & Exposure'),
        ('conference', 'Summit / Conference'),
    ], string='Delivery Mode', default='classroom', required=True, tracking=True,
        help='Decided at TNA stage: only Classroom (and the classroom part of '
             'Blended/Workshop) are actioned within EDS; pure E-Learning routes to the LMS.')
    # Course Pool Selection & Ad-Hoc Requests
    course_id = fields.Many2one(
        'eds.course', string='Course from Catalog', domain="[('status', '=', 'active')]", tracking=True)
    requested_course_ids = fields.Many2many(
        'eds.course', 'eds_tna_entry_requested_course_rel', 'entry_id', 'course_id',
        string='Courses Requested',
        help='One individual submission may contain several courses, up to the configured limit.')
    is_custom_course = fields.Boolean(string='Course Not in Catalog', default=False, tracking=True)
    custom_course_title = fields.Char(string='Custom Course Title', tracking=True)
    custom_course_description = fields.Text(string='What the Course is About / Content Summary')
    quarter = fields.Selection([
        ('q1', 'Q1 Jul-Sep'),
        ('q2', 'Q2 Oct-Dec'),
        ('q3', 'Q3 Jan-Mar'),
        ('q4', 'Q4 Apr-Jun'),
        ('all', 'Q1-Q4'),
        ('tbd', 'TBD'),
    ], string='Preferred Quarter', default='q1', tracking=True)
    urgency = fields.Selection([
        ('critical', 'Critical (Immediate Operational Urgency)'),
        ('high', 'High Priority'),
        ('medium', 'Medium Priority'),
        ('low', 'Low / Discretionary'),
    ], string='Urgency', default='medium', required=True, tracking=True)

    # HR Planning & Scheduling Decision Fields
    hr_target_quarter = fields.Selection([
        ('q1', 'Q1'),
        ('q2', 'Q2'),
        ('q3', 'Q3'),
        ('q4', 'Q4'),
    ], string='Planned Quarter', tracking=True)
    hr_target_delivery_date = fields.Date(string='Target Delivery Date', tracking=True)
    hr_assigned_participant_ids = fields.Many2many(
        'hr.employee', 'eds_tna_entry_participant_rel', 'entry_id', 'employee_id',
        string='Assigned Target Employees', help='HR specifies which employee(s) will take this training.')

    priority_score = fields.Float(string='Priority Score', compute='_compute_priority_score', store=True)
    justification = fields.Text(string='Justification', required=True)
    proposed_program = fields.Char(
        string='Proposed Program / Course',
        compute='_compute_proposed_program',
        store=True, readonly=False,
        help='Unified program title derived from the course catalog, custom title, or diagnostic gap.')
    estimated_cost = fields.Monetary(string='Estimated Cost', currency_field='company_currency_id')
    # Diagnostic Gap Details (Competency & PMS)
    pms_measure_id = fields.Many2one(
        'performance.job.measure', string='PMS Measurement', tracking=True,
        help='Individual measurement metric from the PMS module.')
    competency_or_measurement = fields.Char(
        string='Competency / Measurement', compute='_compute_competency_or_measurement', store=True)
    suggested_course_ids = fields.Many2many(
        'eds.course', 'eds_tna_entry_suggested_courses_rel', 'entry_id', 'course_id',
        string='Suggested Courses', compute='_compute_suggested_courses', store=True, readonly=False,
        help='All courses integrated with this competency gap or PMS measurement gap.')
    competency_gap_level_diff = fields.Integer(string='Competency Gap (Levels)', default=0,
                                               help='Difference between job required proficiency and employee current rating.')
    pms_kpi_reference = fields.Char(string='PMS KPI / Objective Ref', help='Performance evaluation objective or KPI code.')
    pms_appraisal_score = fields.Float(string='PMS Performance Score', help='Employee appraisal score for the evaluation period.')
    pms_measurement_name = fields.Char(
        string='PMS Measurement Name',
        help='Measurement title from the appraisal, including legacy appraisal criteria without a linked PMS measure record.')
    pms_appraisal_rating = fields.Char(string='PMS Rating')
    pms_target_type = fields.Char(string='PMS Target Type')
    pms_target_value = fields.Float(string='PMS Target')
    pms_actual_value = fields.Float(string='PMS Actual')

    # Intelligent Catalog Matching Engine
    recommended_course_id = fields.Many2one(
        'eds.course', string='Catalog Matching Course', compute='_compute_recommended_course', store=True,
        help='Automatically matched course from the Course Catalog addressing this diagnosed competency.')
    course_match_status = fields.Selection([
        ('exact', 'Catalog Exact Match'),
        ('higher', 'Related Tier Match'),
        ('no_course', 'New Course Development Required'),
    ], string='Catalog Match Status', compute='_compute_recommended_course', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('validated', 'Validated'),
        ('approved', 'Approved'),
        ('converted', 'Converted to Program'),
        ('excluded', 'Excluded'),
    ], string='Status', default='draft', index=True, tracking=True)
    submitted_by = fields.Many2one(
        'res.users', string='Submitted By', default=lambda self: self.env.user, readonly=True, copy=False)
    validated_by = fields.Many2one('res.users', string='Validated By', readonly=True)
    validation_date = fields.Datetime(string='Validation Date', readonly=True)
    excluded_reason = fields.Text(string='Exclusion Reason')
    converted_course_ref = fields.Char(string='Converted Program Reference')
    company_currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    # ── Consolidation & Prioritization (/007) ──
    consolidation_id = fields.Many2one(
        'eds.tna.consolidation', string='Consolidation',
        ondelete='set null', index=True, copy=False, tracking=True)
    is_duplicate = fields.Boolean(
        string='Duplicate Need', default=False, tracking=True,
        help='Auto-flagged during consolidation when the same employee+competency need appears '
             'from multiple sources.')
    duplicate_of_id = fields.Many2one('eds.tna.entry', string='Duplicate Of', ondelete='set null')
    exclusion_type = fields.Selection([
        ('duplicate', 'Duplicate Need'),
        ('process', 'Process Issue (Non-Training)'),
        ('system', 'System / Technical Issue (Non-Training)'),
        ('structural', 'Structural Issue (Non-Training)'),
        ('other', 'Other Out of Scope'),
    ], string='Non-Training / Exclusion Type', tracking=True,
        help='Flagged as a non-training item (process/system/structural) or duplicate for review & exclusion.')

    # Priority scoring criteria - each scored 0-100, weighted by eds.tna.priority.rule
    score_strategic_alignment = fields.Float(string='Strategic Alignment Score', default=50.0)
    score_tom_impact = fields.Float(string='TOM Impact Score', default=50.0)
    score_gap_severity = fields.Float(
        string='Gap Severity Score', compute='_compute_score_gap_severity', store=True)
    score_risk_level = fields.Float(string='Risk Level Score', default=50.0)
    score_regulatory = fields.Float(
        string='Regulatory Score', compute='_compute_score_regulatory', store=True)
    score_future_capability = fields.Float(string='Future Capability Score', default=50.0)

    @api.depends('request_level', 'work_unit_employee_ids', 'employee_id')
    def _compute_participant_count(self):
        for rec in self:
            if rec.request_level == 'work_unit':
                rec.target_participant_count = len(rec.work_unit_employee_ids)
            else:
                rec.target_participant_count = 1 if rec.employee_id else 0

    @api.depends('competency_id', 'pms_measure_id', 'pms_measurement_name',
                 'pms_kpi_reference', 'proposed_program', 'source')
    def _compute_competency_or_measurement(self):
        for rec in self:
            if rec.competency_id:
                rec.competency_or_measurement = rec.competency_id.name
            elif rec.pms_measure_id:
                rec.competency_or_measurement = rec.pms_measure_id.name
            elif rec.pms_measurement_name:
                rec.competency_or_measurement = rec.pms_measurement_name
            elif rec.pms_kpi_reference:
                rec.competency_or_measurement = rec.pms_kpi_reference
            elif rec.source == 'competency_gap':
                rec.competency_or_measurement = _('Competency Gap')
            elif rec.source == 'pms':
                rec.competency_or_measurement = _('PMS Measurement')
            else:
                rec.competency_or_measurement = rec.proposed_program or _('General Training Need')

    @api.depends('competency_id', 'competency_level', 'pms_measure_id', 'pms_appraisal_score',
                 'course_id', 'requested_course_ids')
    def _compute_suggested_courses(self):
        Course = self.env['eds.course']
        for rec in self:
            courses = Course.browse()
            if rec.course_id:
                courses |= rec.course_id
            courses |= rec.requested_course_ids
            if rec.competency_id:
                target_level = {
                    'basic': '1', 'intermediate': '2', 'advanced': '3', 'expert': '4',
                }.get(rec.competency_level, '1')
                comp_lines = self.env['eds.course.competency.line'].search([
                    ('competency_id', '=', rec.competency_id.id),
                    ('required_level', '>=', target_level),
                    ('course_id.status', 'in', ('active', 'draft'))
                ])
                courses |= comp_lines.mapped('course_id')
            if rec.pms_measure_id:
                pms_lines = self.env['eds.course.pms.line'].search([
                    ('job_measure_id', '=', rec.pms_measure_id.id),
                    ('min_threshold', '>', rec.pms_appraisal_score),
                    ('course_id.status', 'in', ('active', 'draft'))
                ])
                courses |= pms_lines.mapped('course_id')
            rec.suggested_course_ids = [(6, 0, courses.ids)]

    @api.depends('gap_severity')
    def _compute_score_gap_severity(self):
        """Map the gap severity selection onto the 0-100 scoring scale."""
        weights = {'critical': 100.0, 'high': 75.0, 'medium': 50.0, 'low': 25.0}
        for rec in self:
            rec.score_gap_severity = weights.get(rec.gap_severity, 50.0)

    @api.depends('source')
    def _compute_score_regulatory(self):
        """Regulatory/compliance-sourced needs score 100 on the regulatory criterion."""
        for rec in self:
            rec.score_regulatory = 100.0 if rec.source == 'regulatory' else 0.0

    def _criterion_score(self, criteria):
        """Return the 0-100 score for a priority criterion code."""
        mapping = {
            'strategic_alignment': 'score_strategic_alignment',
            'tom_impact': 'score_tom_impact',
            'gap_severity': 'score_gap_severity',
            'risk_level': 'score_risk_level',
            'regulatory': 'score_regulatory',
            'future_capability': 'score_future_capability',
        }
        return self[mapping[criteria]] or 0.0

    @api.depends('course_id', 'requested_course_ids', 'is_custom_course', 'custom_course_title')
    def _compute_proposed_program(self):
        for rec in self:
            if rec.is_custom_course and rec.custom_course_title:
                names = rec.requested_course_ids.mapped('name') + [rec.custom_course_title]
                rec.proposed_program = ', '.join(names)
            elif not rec.is_custom_course and rec.course_id:
                rec.proposed_program = rec.course_id.name
            elif not rec.is_custom_course and rec.requested_course_ids:
                rec.proposed_program = ', '.join(rec.requested_course_ids.mapped('name'))
            elif not rec.proposed_program:
                rec.proposed_program = False

    @api.depends('course_id', 'is_custom_course', 'custom_course_title', 'competency_id', 'proposed_program')
    def _compute_recommended_course(self):
        Course = self.env['eds.course']
        for rec in self:
            # 1. Direct Catalog Course Selection
            if not rec.is_custom_course and rec.course_id:
                rec.recommended_course_id = rec.course_id
                rec.course_match_status = 'exact'
                continue

            # 2. Match via Diagnosed Competency
            if rec.competency_id:
                course_line = self.env['eds.course.competency.line'].search([
                    ('competency_id', '=', rec.competency_id.id),
                    ('course_id.status', 'in', ('active', 'draft'))
                ], limit=1)
                if course_line:
                    rec.recommended_course_id = course_line.course_id
                    rec.course_match_status = 'exact'
                    continue

            # 3. Intelligent Keyword Search in Course Catalog
            search_terms = []
            if rec.is_custom_course and rec.custom_course_title:
                search_terms.append(rec.custom_course_title.strip())
            if rec.proposed_program and rec.proposed_program.strip() not in search_terms:
                search_terms.append(rec.proposed_program.strip())
            if rec.competency_id and rec.competency_id.name and rec.competency_id.name.strip() not in search_terms:
                search_terms.append(rec.competency_id.name.strip())

            matched_course = False
            is_exact = False
            for term in search_terms:
                if not term or len(term) < 3:
                    continue
                c_exact = Course.search([
                    ('status', 'in', ('active', 'draft')),
                    ('name', '=ilike', term)
                ], limit=1)
                if c_exact:
                    matched_course = c_exact
                    is_exact = True
                    break
                c_search = Course.search([
                    ('status', 'in', ('active', 'draft')),
                    ('name', 'ilike', term)
                ], limit=1)
                if c_search:
                    matched_course = c_search
                    is_exact = False
                    break

            if matched_course:
                rec.recommended_course_id = matched_course
                rec.course_match_status = 'exact' if is_exact else 'higher'
            else:
                rec.recommended_course_id = False
                rec.course_match_status = 'no_course'

    @api.onchange('course_id')
    def _onchange_course_id(self):
        if self.course_id:
            self.proposed_program = self.course_id.name
            if not self.competency_id and self.course_id.competency_line_ids:
                self.competency_id = self.course_id.competency_line_ids[0].competency_id.id
            if not self.justification and self.course_id.description:
                self.justification = self.course_id.description
            self.recommended_course_id = self.course_id
            self.course_match_status = 'exact'
        else:
            self.recommended_course_id = False
            self.course_match_status = 'no_course'

    @api.onchange('urgency')
    def _onchange_urgency(self):
        if self.urgency:
            self.gap_severity = self.urgency

    @api.onchange('is_custom_course', 'custom_course_title', 'custom_course_description')
    def _onchange_custom_course(self):
        if self.is_custom_course:
            self.course_id = False
            if self.custom_course_title:
                self.proposed_program = self.custom_course_title
                term = self.custom_course_title.strip()
                if len(term) >= 3:
                    c_exact = self.env['eds.course'].search([
                        ('status', 'in', ('active', 'draft')),
                        ('name', '=ilike', term)
                    ], limit=1)
                    if c_exact:
                        self.recommended_course_id = c_exact
                        self.course_match_status = 'exact'
                    else:
                        c_partial = self.env['eds.course'].search([
                            ('status', 'in', ('active', 'draft')),
                            ('name', 'ilike', term)
                        ], limit=1)
                        if c_partial:
                            self.recommended_course_id = c_partial
                            self.course_match_status = 'higher'
                        else:
                            self.recommended_course_id = False
                            self.course_match_status = 'no_course'
                else:
                    self.recommended_course_id = False
                    self.course_match_status = 'no_course'
            else:
                self.recommended_course_id = False
                self.course_match_status = 'no_course'
            if self.custom_course_description and not self.justification:
                self.justification = self.custom_course_description
        else:
            self.custom_course_title = False
            self.custom_course_description = False
            if self.course_id:
                self.proposed_program = self.course_id.name
                self.recommended_course_id = self.course_id
                self.course_match_status = 'exact'
            else:
                self.recommended_course_id = False
                self.course_match_status = 'no_course'

    def action_view_recommended_course(self):
        self.ensure_one()
        if not self.recommended_course_id:
            raise UserError(_("No matching catalog course found for this competency need."))
        return {
            'name': _('Catalog Matching Course'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.course',
            'res_id': self.recommended_course_id.id,
            'view_mode': 'form',
        }

    @api.depends('score_strategic_alignment', 'score_tom_impact', 'score_gap_severity',
                 'score_risk_level', 'score_regulatory', 'score_future_capability')
    def _compute_priority_score(self):
        """Weighted priority engine: weighted average of the active rule weights.

        score = sum(weight_i * score_i) / sum(weight_i), capped at 100.
        """
        for rec in self:
            rec.priority_score = rec._get_weighted_priority_score()

    def _get_weighted_priority_score(self):
        """Pure weighted-score computation - shared by the ORM compute and by the
        priority-rule model so changing a rule weight re-scores every consolidated entry."""
        rules = self.env['eds.tna.priority.rule'].search([('active', '=', True)])
        total_weight = sum(rules.mapped('weight'))
        if not rules or total_weight <= 0:
            return 0.0
        weighted = sum(rule.weight * self._criterion_score(rule.criteria) for rule in rules)
        return round(min(weighted / total_weight, 100.0), 2)

    @api.onchange('department_id')
    def _onchange_department_id(self):
        """Top of hierarchy: Department -> Operating Unit -> Job Position.
        - If department selected:
          work_unit_id domain restricted to operating units belonging to this department.
          If selected work_unit_id doesn't belong to the department, clear it.
          job_position_id and employee_id restricted to the department.
        - If no department selected:
          All operating units and jobs are available.
        """
        ou_domain = self.env['eds.hr.compat'].get_operating_unit_domain(departments=self.department_id)
        if self.department_id:
            if self.work_unit_id and not self.env['eds.hr.compat'].is_operating_unit_in_departments(self.work_unit_id, self.department_id):
                self.work_unit_id = False
            if self.job_position_id and self.job_position_id.department_id and self.job_position_id.department_id != self.department_id:
                self.job_position_id = False
            if self.employee_id and self.employee_id.department_id != self.department_id:
                self.employee_id = False
        job_domain = self.env['eds.hr.compat'].get_job_domain(
            departments=self.department_id, operating_units=self.work_unit_id)
        emp_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id, job=self.job_position_id)
        return {'domain': {'work_unit_id': ou_domain, 'job_position_id': job_domain, 'employee_id': emp_domain}}

    @api.onchange('work_unit_id')
    def _onchange_work_unit_id(self):
        """Middle of hierarchy: Operating Unit -> Job Position.
        Filter job position and employee based on selected work unit and department.
        """
        if self.work_unit_id and not self.department_id:
            if hasattr(self.work_unit_id, 'department') and self.work_unit_id.department:
                self.department_id = self.work_unit_id.department
            elif 'operating_unit_id' in self.env['hr.department']._fields:
                linked_dept = self.env['hr.department'].search([('operating_unit_id', '=', self.work_unit_id.id)], limit=1)
                if linked_dept:
                    self.department_id = linked_dept

        if self.work_unit_id:
            if self.employee_id:
                emp_ou = self.env['eds.hr.compat'].get_employee_operating_unit(self.employee_id)
                if emp_ou and emp_ou != self.work_unit_id:
                    self.employee_id = False
        job_domain = self.env['eds.hr.compat'].get_job_domain(
            departments=self.department_id, operating_units=self.work_unit_id)
        emp_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id, job=self.job_position_id)
        return {'domain': {'job_position_id': job_domain, 'employee_id': emp_domain}}

    @api.onchange('job_position_id')
    def _onchange_job_position_id(self):
        """Auto-populate department/unit if configured on job, and filter employee."""
        if self.job_position_id and self.job_position_id.department_id:
            if not self.department_id:
                self.department_id = self.job_position_id.department_id
            if self.department_id.operating_unit_id and not self.work_unit_id:
                self.work_unit_id = self.department_id.operating_unit_id
        if self.job_position_id and self.employee_id:
            emp_job = self.env['eds.hr.compat'].get_employee_job(self.employee_id)
            if emp_job and emp_job != self.job_position_id:
                self.employee_id = False
        emp_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id, job=self.job_position_id)
        return {'domain': {'employee_id': emp_domain}}

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """Populate job, department, and work unit from employee."""
        if self.employee_id:
            job = self.env['eds.hr.compat'].get_employee_job(self.employee_id)
            if job:
                self.job_position_id = job
            if self.employee_id.department_id:
                self.department_id = self.employee_id.department_id
            ou = self.env['eds.hr.compat'].get_employee_operating_unit(self.employee_id)
            if ou:
                self.work_unit_id = ou

    @api.onchange('work_unit_id', 'department_id', 'job_position_id')
    def _onchange_work_unit_employee_scope(self):
        if self.request_level == 'work_unit':
            self.work_unit_employee_ids &= self.eligible_work_unit_employee_ids

    @api.constrains('cycle_id', 'employee_id', 'competency_id', 'course_id', 'pms_measure_id', 'request_level')
    def _check_duplicate_need(self):
        for rec in self:
            if rec.request_level == 'work_unit' or not rec.employee_id:
                continue
            domain = [
                ('id', '!=', rec.id),
                ('cycle_id', '=', rec.cycle_id.id),
                ('employee_id', '=', rec.employee_id.id),
                ('request_level', '=', 'individual'),
                ('source', '=', rec.source),
                ('state', '!=', 'excluded'),
            ]
            if rec.competency_id:
                domain.append(('competency_id', '=', rec.competency_id.id))
            elif rec.pms_measure_id:
                domain.append(('pms_measure_id', '=', rec.pms_measure_id.id))
            elif rec.course_id:
                domain.append(('course_id', '=', rec.course_id.id))
            elif rec.proposed_program:
                domain.append(('proposed_program', '=', rec.proposed_program))

            if self.search(domain, limit=1):
                raise ValidationError(
                    _('A training need for employee %s with this course/competency/measurement already exists in this cycle.')
                    % rec.employee_id.name)

    @api.constrains('cycle_id', 'employee_id', 'request_level', 'source', 'state',
                    'requested_course_ids', 'course_id', 'is_custom_course', 'work_unit_employee_ids', 'work_unit_id')
    def _check_max_individual_courses(self):
        max_courses_param = max(1, int(self.env['ir.config_parameter'].sudo().get_param(
            'eds.max_tna_courses_per_employee', '3')))
        for rec in self:
            if rec.state == 'excluded':
                continue
            if rec.request_level == 'individual' and rec.source == 'manual' and rec.is_custom_course:
                raise ValidationError(_('A course outside the catalog may only be proposed in a work-unit request.'))
            if rec.request_level == 'work_unit' and rec.state != 'draft':
                if not rec.work_unit_id or not rec.work_unit_employee_ids:
                    raise ValidationError(_('A work-unit request needs a work unit and selected employees.'))
                if rec.is_custom_course:
                    if not rec.custom_course_title or rec.course_id:
                        raise ValidationError(_('A work-unit custom course needs a title and no catalog course.'))
                elif not rec.course_id:
                    raise ValidationError(_('Select one catalog course for this work-unit request.'))
                employee_domain = self.env['eds.hr.compat'].get_employee_domain(
                    department=rec.department_id, operating_unit=rec.work_unit_id,
                    job=rec.job_position_id)
                Employee = self.env['hr.employee'].sudo()
                eligible_ids = set(Employee.search([
                    ('id', 'in', rec.work_unit_employee_ids.ids),
                ] + employee_domain).ids)
                if eligible_ids != set(rec.work_unit_employee_ids.ids):
                    raise ValidationError(_(
                        'Every nominated employee must match the selected work unit, department, and job position.'))
            if rec.request_level == 'individual' and rec.employee_id and rec.cycle_id and rec.source == 'manual':
                chosen_count = len(rec.requested_course_ids) + bool(rec.is_custom_course and rec.custom_course_title)
                if not chosen_count and rec.course_id:
                    chosen_count = 1  # Existing single-course requests remain valid.
                if not chosen_count and rec.proposed_program:
                    chosen_count = 1  # Existing free-text requests can be reviewed and matched later.
                if chosen_count > max_courses_param:
                    raise ValidationError(_(
                        'An individual may request at most %d courses in one TNA cycle.') % max_courses_param)
                if rec.state != 'draft' and not chosen_count:
                    raise ValidationError(_('Select a course or describe a custom course before submitting.'))
                duplicates = self.search_count([
                    ('cycle_id', '=', rec.cycle_id.id),
                    ('employee_id', '=', rec.employee_id.id),
                    ('request_level', '=', 'individual'),
                    ('source', '=', 'manual'),
                    ('state', '!=', 'excluded'),
                    ('id', '!=', rec.id),
                ])
                if duplicates:
                    raise ValidationError(_(
                        'Employee %s already has an individual TNA submission for cycle %s. Edit that request to add courses.')
                        % (rec.employee_id.name, rec.cycle_id.name))

    @api.constrains('request_level', 'source', 'employee_id', 'work_unit_id', 'cycle_id')
    def _check_manual_request_scope(self):
        if self.env.su or self.env.user.has_group('employee_development_system.group_eds_officer'):
            return
        managed_units = self.env['eds.hr.compat'].get_managed_operating_units()
        for rec in self.filtered(lambda entry: entry.source == 'manual'):
            if rec.cycle_id.state != 'collecting':
                raise ValidationError(_('Training needs can only be submitted to a cycle open for collection.'))
            if rec.request_level == 'work_unit':
                if rec.work_unit_id not in managed_units:
                    raise ValidationError(_('You may submit a work-unit request only for a unit you lead.'))
            elif rec.employee_id.user_id != self.env.user:
                raise ValidationError(_('An individual TNA request must be for your own employee record.'))

    @api.model_create_multi
    def create(self, vals_list):
        # sudo(): see EdsTnaCycle.create - self-service entry creation must not
        # depend on the user having ir.sequence access.
        for vals in vals_list:
            if not self.env.su:
                if vals.get('state', 'draft') != 'draft':
                    raise UserError(_('A training need must start as a draft and follow the approval workflow.'))
                if not self.env.user.has_group('employee_development_system.group_eds_officer'):
                    if vals.get('source', 'manual') != 'manual':
                        raise UserError(_('Only L&D staff may create diagnostic training needs.'))
                    if {'is_duplicate', 'exclusion_type', 'duplicate_of_id', 'validated_by',
                            'validation_date', 'consolidation_id', 'converted_course_ref'} & vals.keys():
                        raise UserError(_('Screening and approval fields are managed by L&D.'))
            if (vals.get('request_level', 'individual') == 'individual'
                    and vals.get('source', 'manual') == 'manual' and vals.get('employee_id')):
                employee = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                compat = self.env['eds.hr.compat']
                unit = compat.get_employee_operating_unit(employee)
                job = compat.get_employee_job(employee)
                vals.update({
                    'work_unit_id': unit.id if unit else False,
                    'department_id': employee.department_id.id or False,
                    'job_position_id': job.id if job else False,
                })
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.tna.entry') or _('New')
        records = super().create(vals_list)
        records._check_manual_request_scope()
        records.mapped('cycle_id')._mark_course_demand_dirty()
        return records

    def write(self, vals):
        if not self.env.su:
            if 'state' in vals:
                raise UserError(_('Use the training need workflow actions to change its status.'))
            if not self.env.user.has_group('employee_development_system.group_eds_officer'):
                staff_fields = {'source', 'is_duplicate', 'exclusion_type', 'excluded_reason',
                                'duplicate_of_id', 'validated_by', 'validation_date',
                                'consolidation_id', 'converted_course_ref', 'priority_score'}
                if staff_fields.intersection(vals):
                    raise UserError(_('Only L&D staff may change screening or diagnostic fields.'))
                if any(rec.state != 'draft' for rec in self):
                    raise UserError(_('Reopen the submitted need before editing it.'))
        # a locked consolidation freezes its needs; edits require a documented
        # change request (unlock first). The state transition itself and the consolidation
        # engine (which flips flags on its own records) are allowed through sudo context.
        if not self.env.context.get('eds_allow_locked_edit'):
            for rec in self:
                if rec.consolidation_id and rec.consolidation_id.state == 'locked':
                    raise UserError(_(
                        'Training need %s belongs to the locked consolidation %s. Unlock the '
                        'consolidation with a documented change request before editing.')
                        % (rec.name, rec.consolidation_id.name))
        organization_fields = {'work_unit_id', 'department_id', 'job_position_id'}
        if any(rec.request_level == 'individual' and rec.source == 'manual' for rec in self):
            if organization_fields.intersection(vals) and 'employee_id' not in vals:
                raise UserError(_('Individual TNA organization details come from the employee master and cannot be edited.'))
            if vals.get('employee_id'):
                employee = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                compat = self.env['eds.hr.compat']
                unit = compat.get_employee_operating_unit(employee)
                job = compat.get_employee_job(employee)
                vals = dict(vals, work_unit_id=unit.id if unit else False,
                            department_id=employee.department_id.id or False,
                            job_position_id=job.id if job else False)
        demand_fields = {
            'cycle_id', 'state', 'source', 'request_level', 'employee_id',
            'work_unit_employee_ids', 'requested_course_ids', 'course_id',
            'suggested_course_ids', 'recommended_course_id', 'proposed_program',
            'is_custom_course', 'custom_course_title', 'competency_id',
            'pms_measure_id', 'pms_appraisal_score', 'competency_level',
            'quarter', 'is_duplicate', 'exclusion_type',
        }
        old_cycles = self.mapped('cycle_id') if demand_fields.intersection(vals) else self.env['eds.tna.cycle']
        result = super().write(vals)
        if {'cycle_id', 'source', 'request_level', 'employee_id', 'work_unit_id'}.intersection(vals):
            self._check_manual_request_scope()
        if old_cycles:
            (old_cycles | self.mapped('cycle_id'))._mark_course_demand_dirty()
        return result

    def _write_workflow_values(self, vals):
        """Internal transition path; public ORM writes cannot bypass review actions."""
        cycles = self.mapped('cycle_id')
        result = super(EdsTnaEntry, self).write(vals)
        if cycles:
            (cycles | self.mapped('cycle_id'))._mark_course_demand_dirty()
        return result

    def unlink(self):
        cycles = self.mapped('cycle_id')
        result = super().unlink()
        cycles._mark_course_demand_dirty()
        return result

    # ── Workflow (manager review; exclusion) ───────────
    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft entries can be submitted.'))
            if rec.source == 'manual' and rec.cycle_id.state != 'collecting':
                raise UserError(_('This TNA cycle is not open for collection.'))
            rec._check_manual_request_scope()
            rec._write_workflow_values({'state': 'submitted'})
            rec.message_post(body=_('Training need %s submitted.') % rec.name)

    def action_validate(self):
        """Line Manager or PPDD validation of a submitted entry."""
        for rec in self:
            rec._require_group('group_eds_line_manager')
            if rec.state not in ('submitted', 'validated'):
                raise UserError(_('Only submitted entries can be validated.'))
            rec._write_workflow_values({
                'state': 'validated',
                'validated_by': self.env.user.id,
                'validation_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('Training need %s validated.') % rec.name)

    def action_exclude(self):
        """Flag duplicate/invalid/non-training items for exclusion."""
        if len(self) == 1 and not self.excluded_reason:
            self._require_group('group_eds_officer')
            return {
                'name': _('Exclude Training Need'),
                'type': 'ir.actions.act_window',
                'res_model': 'eds.tna.exclude.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_entry_id': self.id,
                    'default_exclusion_type': self.exclusion_type or 'duplicate',
                    'default_excluded_reason': self.excluded_reason or '',
                },
            }
        for rec in self:
            rec._require_group('group_eds_officer')
            if not rec.excluded_reason:
                raise UserError(_('An exclusion reason is required.'))
            rec._write_workflow_values({'state': 'excluded'})
            rec.message_post(body=_('Training need %s excluded: %s') % (rec.name, rec.excluded_reason))

    def action_reopen_draft(self):
        for rec in self:
            is_submitter = (rec.submitted_by == self.env.user or rec.employee_id.user_id == self.env.user)
            if not (is_submitter and rec.state == 'submitted'):
                rec._require_group('group_eds_officer')
            rec._write_workflow_values({'state': 'draft'})

    def action_restore_from_exclusion(self):
        """Restore an excluded need back to submitted / validated active status."""
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state == 'excluded':
                target_state = 'validated' if rec.validated_by else 'submitted'
                rec._write_workflow_values({
                    'state': target_state,
                    'excluded_reason': False,
                    'exclusion_type': False,
                    'is_duplicate': False,
                    'duplicate_of_id': False,
                })
                rec.message_post(body=_('Training need %s restored from exclusion to %s.') % (rec.name, target_state))

    def action_clear_screening_flags(self):
        """Clear duplicate and non-training flags to keep the need active as training."""
        for rec in self:
            rec._require_group('group_eds_officer')
            rec.write({
                'is_duplicate': False,
                'exclusion_type': False,
                'duplicate_of_id': False,
            })
            rec.message_post(body=_('Screening flags cleared for training need %s. Kept active.') % rec.name)

    def action_create_development_request(self):
        """kick off course development for an approved need - opens a pre-filled
        development request (pre-created so the wizard-less flow is instant)."""
        self.ensure_one()
        if self.state not in ('approved', 'converted'):
            raise UserError(_('Only approved training needs can be converted to a course '
                              'development request.'))
        existing = self.env['eds.course.development.request'].search(
            [('tna_entry_ids', 'in', [self.id])], limit=1)
        if existing:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'eds.course.development.request',
                'res_id': existing.id,
                'view_mode': 'form',
            }
        request = self.env['eds.course.development.request'].create({
            'tna_entry_ids': [(6, 0, [self.id])],
            'competency_gap_ids': [(6, 0, self.competency_id.ids)] if self.competency_id else False,
            'target_job_ids': [(6, 0, self.job_position_id.ids)] if self.job_position_id else False,
            'expected_outcomes': self.justification,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.course.development.request',
            'res_id': request.id,
            'view_mode': 'form',
        }


class EdsTnaCycleCourseLine(models.Model):
    """Aggregated course demand line on TNA Cycle (/002/009).

    Groups training demands from individual requests, work-unit level requests,
    competency assessment gaps, and PMS individual measurement gaps.
    Sorted descending by total employees requested.
    """
    _name = 'eds.tna.cycle.course.line'
    _description = 'TNA Cycle Course Demand Summary Line'
    _order = 'total_employees desc, id'

    cycle_id = fields.Many2one(
        'eds.tna.cycle', string='TNA Cycle', ondelete='cascade', required=True, index=True)
    course_id = fields.Many2one(
        'eds.course', string='Course Catalog Item', ondelete='set null')
    course_name = fields.Char(string='Course / Program Name', required=True)
    duration_days = fields.Integer(string='Duration (Days)', default=1)
    delivery_method = fields.Selection([
        ('internal', 'Internal'),
        ('local_external', 'Local External Provider'),
        ('international', 'International Provider'),
    ], string='Delivery Method', default='internal')
    target_quarter = fields.Selection([
        ('q1', 'Q1 Jul-Sep'),
        ('q2', 'Q2 Oct-Dec'),
        ('q3', 'Q3 Jan-Mar'),
        ('q4', 'Q4 Apr-Jun'),
    ], string='Target Quarter', default='q1')

    count_individual = fields.Integer(string='From Individual', default=0)
    count_work_unit = fields.Integer(string='From Work Unit', default=0)
    count_competency = fields.Integer(string='From Competency Gap', default=0)
    count_pms = fields.Integer(string='From PMS Measurement', default=0)
    total_employees = fields.Integer(string='Total Employees', default=0)
    request_count = fields.Integer(string='Training Needs / Requests', default=0)

    employee_ids = fields.Many2many(
        'hr.employee', 'eds_tna_cycle_course_line_emp_rel', 'line_id', 'employee_id',
        string='Target Employees'
    )
    employee_demand_ids = fields.One2many(
        'eds.tna.cycle.course.employee', 'course_line_id', string='Employee Demand')
    selected_for_planning = fields.Boolean(
        string='Selected for Planning', default=True,
        help='Include this course when pushing demand to the Annual L&D Plan.'
    )
    remarks = fields.Char(string='Remarks')

    def action_open_employee_demand(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s — Employee Demand') % self.course_name,
            'res_model': 'eds.tna.cycle.course.employee',
            'view_mode': 'list,form',
            'domain': [('course_line_id', '=', self.id)],
            'context': {'search_default_group_by_work_unit': 0},
        }


class EdsTnaCycleCourseEmployee(models.Model):
    """One employee per course, with all independent TNA evidence retained."""

    _name = 'eds.tna.cycle.course.employee'
    _description = 'Course Demand Employee'
    _order = 'overall_priority_score desc, source_count desc, evidence_count desc, id'
    _rec_name = 'employee_id'

    course_line_id = fields.Many2one('eds.tna.cycle.course.line', required=True,
                                     ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True)
    work_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', store=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', store=True)
    job_position_id = fields.Many2one('hr.job', related='employee_id.job_position', store=True)
    evidence_ids = fields.One2many('eds.tna.cycle.course.evidence', 'demand_id', string='Sources')
    source_count = fields.Integer(compute='_compute_sources', store=True)
    evidence_count = fields.Integer(compute='_compute_sources', store=True)
    source_summary = fields.Char(compute='_compute_sources', store=True)
    overall_priority_score = fields.Float(
        string='Overall Weighted Priority', compute='_compute_overall_priority_score', store=True,
        help='Highest weighted TNA priority score plus five points for each additional independent source, capped at 100.')
    from_individual = fields.Boolean(compute='_compute_sources', store=True)
    from_work_unit = fields.Boolean(compute='_compute_sources', store=True)
    from_competency = fields.Boolean(compute='_compute_sources', store=True)
    from_pms = fields.Boolean(compute='_compute_sources', store=True)

    @api.depends('evidence_ids', 'evidence_ids.entry_id.source', 'evidence_ids.entry_id.request_level')
    def _compute_sources(self):
        labels = {
            'individual': _('Individual TNA'),
            'work_unit': _('Work Unit TNA'),
            'competency': _('Competency'),
            'pms': _('PMS'),
        }
        for rec in self:
            sources = {line.source_kind for line in rec.evidence_ids}
            rec.source_count = len(sources)
            rec.evidence_count = len(rec.evidence_ids)
            rec.source_summary = ', '.join(labels[key] for key in labels if key in sources)
            rec.from_individual = 'individual' in sources
            rec.from_work_unit = 'work_unit' in sources
            rec.from_competency = 'competency' in sources
            rec.from_pms = 'pms' in sources

    @api.depends('evidence_ids.entry_id.priority_score', 'source_count')
    def _compute_overall_priority_score(self):
        for rec in self:
            scores = rec.evidence_ids.mapped('entry_id.priority_score')
            rec.overall_priority_score = min(
                100.0, round((max(scores) if scores else 0.0) +
                             max(0, rec.source_count - 1) * 5.0, 2))


class EdsTnaCycleCourseEvidence(models.Model):
    """An original request or diagnostic behind one employee/course match."""

    _name = 'eds.tna.cycle.course.evidence'
    _description = 'Course Demand Source Evidence'
    _order = 'id'

    demand_id = fields.Many2one('eds.tna.cycle.course.employee', required=True,
                                ondelete='cascade', index=True)
    entry_id = fields.Many2one('eds.tna.entry', required=True, ondelete='cascade')
    source_kind = fields.Selection([
        ('individual', 'Individual TNA'), ('work_unit', 'Work Unit TNA'),
        ('competency', 'Competency'), ('pms', 'PMS'),
    ], compute='_compute_source_kind', store=True)
    competency_id = fields.Many2one(related='entry_id.competency_id', store=True)
    competency_level = fields.Selection(related='entry_id.competency_level', store=True)
    competency_gap_level_diff = fields.Integer(related='entry_id.competency_gap_level_diff', store=True)
    pms_measure_id = fields.Many2one(related='entry_id.pms_measure_id', store=True)
    pms_appraisal_score = fields.Float(related='entry_id.pms_appraisal_score', store=True)
    pms_measurement_name = fields.Char(related='entry_id.pms_measurement_name', store=True)
    pms_appraisal_rating = fields.Char(related='entry_id.pms_appraisal_rating', store=True)
    pms_target_type = fields.Char(related='entry_id.pms_target_type', store=True)
    pms_target_value = fields.Float(related='entry_id.pms_target_value', store=True)
    pms_actual_value = fields.Float(related='entry_id.pms_actual_value', store=True)
    pms_kpi_reference = fields.Char(related='entry_id.pms_kpi_reference', store=True)
    justification = fields.Text(related='entry_id.justification')

    @api.depends('entry_id.source', 'entry_id.request_level')
    def _compute_source_kind(self):
        for rec in self:
            if rec.entry_id.source == 'competency_gap':
                rec.source_kind = 'competency'
            elif rec.entry_id.source == 'pms':
                rec.source_kind = 'pms'
            elif rec.entry_id.request_level == 'work_unit':
                rec.source_kind = 'work_unit'
            else:
                rec.source_kind = 'individual'
