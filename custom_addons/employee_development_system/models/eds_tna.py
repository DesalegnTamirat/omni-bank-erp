# -*- coding: utf-8 -*-
import calendar
from datetime import date, timedelta
from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round

from .eds_action_notification import notify_action, notify_employee_batch, role_users
from .eds_employee_projection import safe_employee_web_read


class EdsTnaCycle(models.Model):
    """Training needs collection cycle; close collection before annual planning."""
    _name = 'eds.tna.cycle'
    _description = 'TNA Cycle'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'
    _rec_names_search = ['cycle_title', 'name']

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False, default=lambda self: _('New'))
    cycle_title = fields.Char(
        string='Cycle Name', tracking=True,
        help='Optional descriptive name shown alongside the TNA reference.')
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
    active = fields.Boolean(default=True, index=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('collecting', 'Collecting Needs'),
        ('closed', 'Closed'),
        ('archived', 'Archived'),
    ], string='Status', default='draft', tracking=True)
    announcement_state = fields.Selection([
        ('idle', 'Not Scheduled'), ('pending', 'Waiting to Send'),
        ('sending', 'Sending'), ('done', 'Sent'),
    ], default='idle', readonly=True, copy=False, string='Employee Announcement')
    announcement_cursor = fields.Integer(readonly=True, copy=False, default=0)
    announcement_sent_count = fields.Integer(
        string='Employees Notified', readonly=True, copy=False, default=0)
    collection_opened_by_id = fields.Many2one(
        'res.users', readonly=True, copy=False, string='Opened By')
    restrict_tna_courses = fields.Boolean(
        string='Only Selected Catalog Courses', tracking=True,
        help='Offer only the selected catalog courses for individual and work-unit requests. '
             'Competency and PMS gaps are still recorded, but only matching selected courses '
             'can enter this cycle’s course demand and plan.')
    request_course_ids = fields.Many2many(
        'eds.course', 'eds_tna_cycle_request_course_rel', 'cycle_id', 'course_id',
        string='Courses Available in This Cycle', domain=[('status', '=', 'active')],
        help='Catalog courses available to request and to recommend from competency or PMS gaps in this cycle.')
    restrict_tna_audience = fields.Boolean(
        string='Only Selected Employees', tracking=True,
        help='Restrict this cycle to employees matching all selected department, work unit, '
             'job position and employee filters. Leave off to offer it to all employees.')
    target_department_ids = fields.Many2many(
        'hr.department', 'eds_tna_cycle_department_rel', 'cycle_id', 'department_id',
        string='Departments')
    target_work_unit_ids = fields.Many2many(
        'operating.unit', 'eds_tna_cycle_unit_rel', 'cycle_id', 'unit_id',
        string='Work Units')
    target_job_position_ids = fields.Many2many(
        'hr.job', 'eds_tna_cycle_job_rel', 'cycle_id', 'job_id',
        string='Job Positions')
    target_employee_ids = fields.Many2many(
        'hr.employee', 'eds_tna_cycle_employee_rel', 'cycle_id', 'employee_id',
        string='Specific Employees')
    available_target_unit_ids = fields.Many2many(
        'operating.unit', compute='_compute_target_options')
    available_target_job_ids = fields.Many2many(
        'hr.job', compute='_compute_target_options')
    available_target_employee_ids = fields.Many2many(
        'hr.employee', compute='_compute_target_options')
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
    custom_course_entry_ids = fields.One2many(
        'eds.tna.entry', 'cycle_id', string='Custom / Uncataloged Course Requests',
        domain=[('is_custom_course', '=', True), ('state', '!=', 'draft')])
    custom_course_count = fields.Integer(
        string='Custom Course Count', compute='_compute_custom_course_count')
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
        string='Days Until Submission Deadline', compute='_compute_days_until_deadline')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('name', 'cycle_title')
    def _compute_display_name(self):
        for cycle in self:
            title = (cycle.cycle_title or '').strip()
            cycle.display_name = '%s (%s)' % (title, cycle.name) if title else cycle.name

    def _require_cycle_staff(self):
        if self.env.su or any(self.env.user.has_group(
                'employee_development_system.' + group) for group in (
                    'group_eds_officer', 'group_eds_manager', 'group_eds_admin')):
            return
        raise UserError(_('Only L&D staff may open, close or plan from a TNA cycle.'))

    def _target_employee_domain(self, include_explicit=True):
        """Apply the selected audience as an intersection, using indexed HR fields."""
        self.ensure_one()
        domain = [('active', '=', True)]
        if not self.restrict_tna_audience:
            return domain
        compat = self.env['eds.hr.compat']
        domain += compat.get_employee_domain(
            department=self.target_department_ids,
            operating_unit=self.target_work_unit_ids)
        jobs = self.target_job_position_ids.ids
        if jobs:
            fields_available = self.env['hr.employee']._fields
            if 'job_position' in fields_available and 'job_id' in fields_available:
                domain += ['|', ('job_position', 'in', jobs), ('job_id', 'in', jobs)]
            elif 'job_position' in fields_available:
                domain.append(('job_position', 'in', jobs))
            else:
                domain.append(('job_id', 'in', jobs))
        if include_explicit and self.target_employee_ids:
            domain.append(('id', 'in', self.target_employee_ids.ids))
        return domain

    def _is_employee_targeted(self, employee):
        self.ensure_one()
        if not self.restrict_tna_audience:
            return True
        if not employee or not employee.active:
            return False
        return bool(self.env['hr.employee'].sudo().search_count(
            [('id', '=', employee.id)] + self._target_employee_domain()))

    def _target_relation_domain(self, relation='employee_id'):
        """Push audience filtering into diagnostic queries instead of one query per gap."""
        return [
            (f'{relation}.{part[0]}', part[1], part[2]) if isinstance(part, tuple)
            else part for part in self._target_employee_domain()
        ]

    @api.depends('restrict_tna_audience', 'target_department_ids',
                 'target_work_unit_ids', 'target_job_position_ids', 'state')
    def _compute_target_options(self):
        compat = self.env['eds.hr.compat']
        Employee = self.env['hr.employee'].sudo()
        Unit = self.env['operating.unit'].sudo()
        Job = self.env['hr.job'].sudo()
        for cycle in self:
            if not cycle.restrict_tna_audience or cycle.state != 'draft':
                cycle.available_target_unit_ids = Unit.browse()
                cycle.available_target_job_ids = Job.browse()
                cycle.available_target_employee_ids = Employee.browse()
                continue
            if cycle.target_department_ids:
                department_employees = Employee.search([
                    ('active', '=', True),
                    ('department_id', 'in', cycle.target_department_ids.ids),
                ])
                units = department_employees.mapped('default_operating_unit_id')
                if 'operating_unit_id' in Employee._fields:
                    units |= department_employees.mapped('operating_unit_id')
                cycle.available_target_unit_ids = units
            else:
                cycle.available_target_unit_ids = Unit.browse()
            base_domain = [('active', '=', True)] + compat.get_employee_domain(
                department=cycle.target_department_ids,
                operating_unit=cycle.target_work_unit_ids)
            if cycle.target_department_ids or cycle.target_work_unit_ids:
                employees = Employee.search(base_domain)
                cycle.available_target_job_ids = employees.mapped('job_position') | employees.mapped('job_id')
            else:
                cycle.available_target_job_ids = Job.browse()
            if (cycle.target_department_ids or cycle.target_work_unit_ids
                    or cycle.target_job_position_ids):
                cycle.available_target_employee_ids = Employee.search(
                    cycle._target_employee_domain(include_explicit=False))
            else:
                cycle.available_target_employee_ids = Employee.browse()

    @api.onchange('restrict_tna_audience')
    def _onchange_restrict_tna_audience(self):
        if not self.restrict_tna_audience:
            self.target_department_ids = False
            self.target_work_unit_ids = False
            self.target_job_position_ids = False
            self.target_employee_ids = False

    @api.onchange('target_department_ids', 'target_work_unit_ids', 'target_job_position_ids')
    def _onchange_target_hierarchy(self):
        if self.target_department_ids:
            self.target_work_unit_ids &= self.available_target_unit_ids
        if self.target_department_ids or self.target_work_unit_ids:
            self.target_job_position_ids &= self.available_target_job_ids
        if self.target_department_ids or self.target_work_unit_ids or self.target_job_position_ids:
            self.target_employee_ids &= self.available_target_employee_ids

    # consolidations per cycle
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

    def _filter_cycle_courses(self, courses):
        """Keep diagnoses but offer only selected courses in a restricted cycle."""
        self.ensure_one()
        return courses & self.request_course_ids if self.restrict_tna_courses else courses

    def action_pull_competency_gaps(self):
        """Auto-pull diagnosed gaps from the Competency Assessment framework into this TNA cycle."""
        self.ensure_one()
        if self.state not in ('draft', 'collecting'):
            raise UserError(_('Competency gaps can only be pulled into Draft or Collecting cycles.'))

        if 'competency.assessment.line' not in self.env:
            raise UserError(_('Competency Management module is not installed.'))

        AssessmentLine = self.env['competency.assessment.line']

        # Use the latest closed competency cycle and its consolidated line for
        # each employee/competency. Raw 360 rater lines can disagree on the gap
        # and must not independently create training needs.
        AssessmentCycle = self.env['competency.assessment.cycle'].sudo()
        latest_cycle = AssessmentCycle.search([
            ('state', '=', 'closed'),
            ('active', '=', True),
            ('period_end', '!=', False),
        ], order='period_end desc, id desc', limit=1)
        if not latest_cycle:
            latest_cycle = AssessmentCycle.search([
                ('state', '=', 'closed'),
                ('active', '=', True),
            ], order='id desc', limit=1)

        gap_lines = AssessmentLine.sudo().search([
            ('cycle_id', '=', latest_cycle.id if latest_cycle else 0),
            ('is_primary_reporting_line', '=', True),
            ('active', '=', True),
            ('tna_measure', '=', 'below'),
            ('gap', '<', 0),
            ('employee_id.active', '=', True),
        ] + self._target_relation_domain())

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

            gap_val = abs(line.gap) if line.gap is not None else max(int(line.required_level or 2) - int(line.current_level or 1), 0)
            if gap_val <= 0:
                continue
            severity = 'critical' if gap_val >= 3 else ('high' if gap_val == 2 else 'medium')

            comp_courses = self.env['eds.course.competency.line'].sudo().search([
                ('competency_id', '=', line.competency_id.id),
                ('required_level', '>=', str(line.required_level or '1')),
                ('course_id.status', 'in', ('active', 'draft'))
            ]).mapped('course_id')
            comp_courses = self._filter_cycle_courses(comp_courses)
            if not comp_courses:
                comp_courses = self.env['eds.course.competency.line'].sudo().search([
                    ('competency_id', '=', line.competency_id.id),
                    ('course_id.status', 'in', ('active', 'draft'))
                ]).mapped('course_id')
                comp_courses = self._filter_cycle_courses(comp_courses)
            if not comp_courses:
                fallback_prog = (_("%s Mastery Program") % line.competency_id.name).strip()
                matched_c = self.env['eds.course'].sudo().search([
                    ('name', '=ilike', fallback_prog),
                    ('status', 'in', ('active', 'draft')),
                ], limit=1)
                if not matched_c:
                    matched_c = self.env['eds.course'].sudo().search([
                        ('name', '=ilike', line.competency_id.name.strip()),
                        ('status', 'in', ('active', 'draft')),
                    ], limit=1)
                if matched_c:
                    comp_courses = self._filter_cycle_courses(matched_c)
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

    @api.depends('custom_course_entry_ids')
    def _compute_custom_course_count(self):
        for rec in self:
            rec.custom_course_count = len(rec.custom_course_entry_ids)

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
        targeted_employee_ids = (set(self.env['hr.employee'].sudo().search(
            self._target_employee_domain()).ids)
            if self.restrict_tna_audience else None)

        course_data = {}

        for entry in entries:
            target_courses = Course.browse()
            # A possible match for a proposed custom course is only a review
            # hint; it must not add a second course to demand automatically.
            if not entry.is_custom_course:
                if entry.request_level == 'individual' and entry.source == 'manual' and entry.requested_course_ids:
                    target_courses |= entry.requested_course_ids
                elif entry.source in ('competency_gap', 'pms') and entry.suggested_course_ids:
                    target_courses |= entry.suggested_course_ids
                elif entry.course_id:
                    target_courses |= entry.course_id
            else:
                # Custom courses only enter course demand when mapped to a catalog course
                if entry.course_id:
                    target_courses |= entry.course_id

            if not target_courses and not entry.is_custom_course:
                if entry.source in ('pms', 'competency_gap'):
                    # Diagnostic gaps must only match configured course mappings, never ad-hoc titles
                    pass
                else:
                    lookup_name = (entry.proposed_program or '').strip()
                    matched = Course.browse()
                    if lookup_name:
                        matched = Course.search([
                            ('name', '=ilike', lookup_name),
                            ('status', 'in', ('active', 'draft')),
                        ], limit=1)
                    if matched:
                        if not self.restrict_tna_courses or self._filter_cycle_courses(matched):
                            target_courses = matched
                            if not entry.course_id:
                                entry.sudo().write({
                                    'course_id': matched.id,
                                    'suggested_course_ids': [(4, matched.id)],
                                })

            if self.restrict_tna_courses:
                target_courses = self._filter_cycle_courses(target_courses)
                if not target_courses:
                    continue

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
            elif not entry.is_custom_course and not self.restrict_tna_courses:
                # Gaps from PMS and Competency must NEVER create outside-catalog course lines.
                # If unmapped, they remain in the diagnostic requests list as Unmapped Gaps.
                if entry.source in ('pms', 'competency_gap'):
                    continue
                name = (entry.proposed_program or '').strip()
                if not name:
                    continue
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
                if targeted_employee_ids is not None:
                    employee_ids &= targeted_employee_ids
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
            line = existing.get(key)
            excluded_ids = ({demand.employee_id.id for demand in line.employee_demand_ids
                             if demand.excluded_from_planning} if line else set())
            eligible_ids = data['employee_ids'] - excluded_ids
            eligible_request_ids = set().union(*(
                data['employee_evidence'].get(employee_id, set())
                for employee_id in eligible_ids)) if eligible_ids else set()
            emp_ids = list(eligible_ids)
            vals = {
                'cycle_id': self.id,
                'course_id': data['course_id'],
                'course_name': data['course_name'],
                'duration_days': data['duration_days'],
                'delivery_method': data['delivery_method'],
                'target_quarter': data['target_quarter'],
                'count_individual': len(data['individual_ids'] & eligible_ids),
                'count_work_unit': len(data['work_unit_ids'] & eligible_ids),
                'count_competency': len(data['competency_ids'] & eligible_ids),
                'count_pms': len(data['pms_ids'] & eligible_ids),
                'request_count': len(eligible_request_ids),
                'total_employees': len(emp_ids),
                'employee_ids': [(6, 0, emp_ids)],
            }
            if line:
                updates = {field: vals[field] for field in (
                    'course_name', 'delivery_method', 'count_individual', 'count_work_unit',
                    'count_competency', 'count_pms', 'request_count',
                    'total_employees') if line[field] != vals[field]}
                if set(line.employee_ids.ids) != eligible_ids:
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
        return {
            'type': 'ir.actions.client',
            'tag': 'bunna_refresh_form',
            'params': {
                'res_model': self._name,
                'res_id': self.id,
                'title': _("Course Demand Refreshed"),
                'message': _("Aggregated %d course demand summaries from %d training needs.") % (line_count, entry_count),
                'type': 'success',
            },
        }

    def action_go_to_planning(self):
        """Convert selected course demands into Annual L&D Plan lines and navigate to Planning."""
        self.ensure_one()
        self._require_cycle_staff()
        if self.state != 'closed':
            raise UserError(_('Close this TNA cycle after collecting needs before sending its courses to planning.'))
        if self.year != str(fields.Date.context_today(self).year):
            raise UserError(_('This cycle belongs to %s. Create the annual plan for that assessment year instead.') % self.year)
        if self.course_demand_dirty or not self.course_demand_last_sync:
            self._sync_course_demand()

        selected_courses = self.course_summary_ids.filtered(
            lambda line: line.selected_for_planning and line.total_employees > 0)
        if not selected_courses:
            raise UserError(_(
                "Select at least one course with eligible employees in Course Demand before going to planning."))

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
                'restrict_tna_cycles': True,
                'selected_tna_cycle_ids': [(6, 0, self.ids)],
            })
        else:
            existing_cycles = (
                plan.line_ids.mapped('course_demand_ids.cycle_id')
                | plan.line_ids.mapped('course_demand_id.cycle_id'))
            plan.write({
                'restrict_tna_cycles': True,
                'selected_tna_cycle_ids': [(6, 0, (
                    plan.selected_tna_cycle_ids | existing_cycles | self).ids)],
            })

        plan._add_course_demands(selected_courses)

        self.message_post(body=_("Created/updated Annual L&D Plan %s with %d courses selected from this TNA cycle.") % (plan.name, len(selected_courses)))

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
        """Remind L&D staff to close collecting cycles near their submission deadline."""
        today = date.today()
        cycles = self.search([
            ('state', '=', 'collecting'),
            ('submission_end_date', '!=', False),
        ])
        manager_group = self.env.ref('employee_development_system.group_eds_manager', raise_if_not_found=False)
        recipients = manager_group.user_ids if manager_group else self.env['res.users']
        partner_ids = recipients.filtered('partner_id').mapped('partner_id').ids
        for cycle in cycles:
            days_left = (cycle.submission_end_date - today).days
            if days_left > 14:
                continue
            if cycle.last_reminder_date and (today - cycle.last_reminder_date).days < 7:
                continue
            if days_left >= 0:
                msg_text = _('TNA cycle %s closes for requests on %s - %d days left. Review the collected needs and close the cycle when collection is complete.') % (
                    cycle.name, cycle.submission_end_date, days_left)
            else:
                msg_text = _('TNA cycle %s passed its submission deadline (%s) by %d days. Close the collection cycle when the needs are ready for planning.') % (
                    cycle.name, cycle.submission_end_date, -days_left)

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

    @api.depends('submission_end_date')
    def _compute_days_until_deadline(self):
        today = date.today()
        for rec in self:
            rec.days_until_deadline = (rec.submission_end_date - today).days if rec.submission_end_date else 0

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

    def write(self, vals):
        if {'restrict_tna_courses', 'request_course_ids', 'restrict_tna_audience',
                'target_department_ids', 'target_work_unit_ids',
                'target_job_position_ids', 'target_employee_ids'} & vals.keys():
            if any(cycle.state != 'draft' for cycle in self):
                raise UserError(_(
                    'Cycle courses and employee audience can only be changed while the TNA cycle is a draft.'))
        if {'restrict_tna_audience', 'target_department_ids', 'target_work_unit_ids',
                'target_job_position_ids', 'target_employee_ids'} & vals.keys():
            if any(cycle.entry_ids for cycle in self):
                raise UserError(_(
                    'Set the employee audience before pulling gaps or entering training needs. '
                    'This cycle already has training needs.'))
        return super().write(vals)

    @api.constrains('state', 'restrict_tna_courses', 'request_course_ids')
    def _check_request_course_selection(self):
        for cycle in self:
            if cycle.state != 'draft' and cycle.restrict_tna_courses and not cycle.request_course_ids:
                raise ValidationError(_(
                    'Select at least one catalog course before opening a restricted TNA cycle.'))

    @api.constrains('state', 'restrict_tna_audience', 'target_department_ids',
                    'target_work_unit_ids', 'target_job_position_ids', 'target_employee_ids')
    def _check_target_audience(self):
        for cycle in self:
            if not cycle.restrict_tna_audience:
                continue
            if cycle.state != 'draft' and not (
                    cycle.target_department_ids or cycle.target_work_unit_ids
                    or cycle.target_job_position_ids or cycle.target_employee_ids):
                raise ValidationError(_('Select at least one employee audience filter before opening this restricted cycle.'))
            if cycle.target_department_ids and cycle.target_work_unit_ids:
                for unit in cycle.target_work_unit_ids:
                    domain = self.env['eds.hr.compat'].get_employee_domain(
                        department=cycle.target_department_ids, operating_unit=unit)
                    if not self.env['hr.employee'].sudo().search_count(
                            [('active', '=', True)] + domain):
                        raise ValidationError(_('Each selected work unit must belong to a selected department.'))
            if cycle.target_employee_ids:
                matched = self.env['hr.employee'].sudo().search(
                    [('id', 'in', cycle.target_employee_ids.ids)]
                    + cycle._target_employee_domain(include_explicit=False))
                if set(matched.ids) != set(cycle.target_employee_ids.ids):
                    raise ValidationError(_('Specific employees must match the selected department, work unit and job position filters.'))

    def web_read(self, specification):
        if 'course_summary_ids' in specification or 'course_summary_count' in specification:
            for cycle in self:
                if cycle.course_demand_dirty or not cycle.course_demand_last_sync:
                    cycle.sudo()._sync_course_demand()
        return super().web_read(specification)

    # ── Workflow ──────────────────────────────────────
    def action_start_collection(self):
        """Draft -> Collecting (opens the submission window)."""
        self._require_cycle_staff()
        today = fields.Date.today()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft TNA cycles can start collection.'))
            rec._check_target_audience()
            if rec.restrict_tna_courses:
                if not rec.request_course_ids:
                    raise UserError(_(
                        'Select at least one catalog course before opening a restricted TNA cycle.'))
                if rec.request_course_ids.filtered(lambda course: course.status != 'active'):
                    raise UserError(_(
                        'Only active catalog courses may be offered for TNA requests.'))
            if rec.submission_end_date and rec.submission_end_date < today:
                raise UserError(_(
                    "Cannot start collection: Submission End Date (%s) has already passed. "
                    "Please update the submission end date to an active date before opening collection."
                ) % rec.submission_end_date)
            if rec.start_date and rec.start_date > today:
                rec.start_date = today
            rec.write({
                'state': 'collecting', 'announcement_state': 'pending',
                'announcement_cursor': 0, 'announcement_sent_count': 0,
                'collection_opened_by_id': self.env.user.id,
            })
            rec.message_post(body=_('TNA cycle %s opened for collection. Submission window: %s to %s.')
                             % (rec.name, rec.start_date, rec.submission_end_date))
        if self:
            self._trigger_cycle_announcements()

    def _trigger_cycle_announcements(self):
        cron = self.env.ref(
            'employee_development_system.cron_eds_tna_cycle_announcement',
            raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    def action_announce_existing_collection(self):
        """Queue a one-time notice for a cycle opened before announcements existed."""
        self._require_cycle_staff()
        for cycle in self:
            if cycle.state != 'collecting' or cycle.announcement_state != 'idle':
                raise UserError(_('Only an unannounced collecting cycle can be announced.'))
            if cycle.submission_end_date and cycle.submission_end_date < fields.Date.today():
                raise UserError(_('This cycle has passed its submission deadline.'))
            cycle.write({
                'announcement_state': 'pending',
                'announcement_cursor': 0,
                'announcement_sent_count': 0,
                'collection_opened_by_id': self.env.user.id,
            })
            cycle.message_post(body=_('Employee announcements queued for this open TNA cycle.'))
        if self:
            self._trigger_cycle_announcements()

    @api.model
    def _cron_send_cycle_announcements(self, batch_size=500, max_batches=2):
        """Send opening notices in bounded batches without delaying cycle creation."""
        cycle = self.sudo().search([
            ('state', '=', 'collecting'),
            ('announcement_state', 'in', ('pending', 'sending')),
        ], order='id', limit=1)
        if not cycle:
            return True
        action = self.env.ref(
            'employee_development_system.action_eds_tna_entry_own',
            raise_if_not_found=False)
        for _batch in range(max_batches):
            employees = self.env['hr.employee'].sudo().search(
                cycle._target_employee_domain() + [
                    ('company_id', '=', cycle.company_id.id),
                    ('id', '>', cycle.announcement_cursor),
                ], order='id', limit=batch_size)
            if not employees:
                cycle.write({'announcement_state': 'done'})
                break
            message = _(
                'TNA cycle %s is open. Submit your training needs by %s in My Training Needs.') % (
                    cycle.name, cycle.submission_end_date or _('the closing date'))
            actor = cycle.collection_opened_by_id or self.env.user
            sent = notify_employee_batch(
                cycle.with_user(actor).sudo(), employees,
                _('Training needs collection is open'), message,
                action_id=action.id if action else None)
            cycle.write({
                'announcement_state': 'sending',
                'announcement_cursor': employees[-1].id,
                'announcement_sent_count': cycle.announcement_sent_count + sent,
            })
            if len(employees) < batch_size:
                cycle.write({'announcement_state': 'done'})
                break
        return True

    def action_finish_collection(self):
        """Collecting -> Closed. This is the only cycle completion step."""
        self._require_cycle_staff()
        for rec in self:
            if rec.state != 'collecting':
                raise UserError(_('Only a cycle collecting needs can be closed.'))
            rec.state = 'closed'
            if rec.announcement_state in ('pending', 'sending'):
                rec.announcement_state = 'done'
            rec._sync_course_demand()
            rec.message_post(body=_('TNA cycle %s closed for collection. Select courses in Course Demand, then go to planning.') % rec.name)
            notify_action(
                rec, role_users(rec, 'group_eds_officer'),
                _('Review closed TNA demand'),
                _('TNA cycle %s is closed. Select the courses to include in the annual plan.')
                % rec.name)


    def action_archive(self):
        """Retire a cycle without deleting its training needs or history."""
        self._require_cycle_staff()
        for rec in self:
            if rec.state == 'archived':
                continue
            rec.write({
                'state': 'archived',
                'active': False,
                'announcement_state': 'done',
            })
            rec.message_post(body=_('TNA Cycle %s has been archived.') % rec.display_name)
        return self.env.ref('employee_development_system.action_eds_tna_cycle').sudo().read()[0]

    def unlink(self):
        """The UI Delete command archives a cycle instead of deleting records."""
        self.action_archive()
        return True

    def write(self, vals):
        if 'active' in vals or 'state' in vals:
            for rec in self:
                if rec.state == 'archived' and (vals.get('active', False) or vals.get('state') != 'archived'):
                    raise UserError(_('Archived TNA cycles cannot be reactivated.'))
        return super().write(vals)


class EdsTnaEntry(models.Model):
    """A single training need within a cycle."""
    _name = 'eds.tna.entry'
    _description = 'TNA Training Need Entry'
    _inherit = ['mail.thread']
    _order = 'id desc'
    _rec_name = 'name'

    def _default_employee_id(self):
        return self.env['hr.employee'].sudo().search([('user_id', '=', self.env.user.id)], limit=1)

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
    available_cycle_ids = fields.Many2many(
        'eds.tna.cycle', compute='_compute_available_cycles',
        string='Cycles Available to Request')
    restrict_request_courses = fields.Boolean(
        related='cycle_id.restrict_tna_courses', readonly=True)
    allowed_request_course_ids = fields.Many2many(
        'eds.course', related='cycle_id.request_course_ids', readonly=True)
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
        'operating.unit', compute='_compute_work_unit_request_scope',
        string='Work Units I Manage')
    allowed_department_ids = fields.Many2many(
        'hr.department', compute='_compute_work_unit_request_scope',
        string='Departments I Manage')
    available_work_unit_ids = fields.Many2many(
        'operating.unit', compute='_compute_available_work_units',
        string='Work Units in Selected Department')
    can_request_work_unit = fields.Boolean(compute='_compute_work_unit_request_scope')
    can_choose_department = fields.Boolean(compute='_compute_work_unit_request_scope')
    can_choose_work_unit = fields.Boolean(compute='_compute_available_work_units')
    eligible_work_unit_employee_ids = fields.Many2many(
        'hr.employee', compute='_compute_eligible_work_unit_employees',
        string='Eligible Work Unit Employees')

    @api.depends_context('uid')
    def _compute_work_unit_request_scope(self):
        if self.env.su or self.env.user.has_group('employee_development_system.group_eds_officer'):
            units = self.env['operating.unit'].search([('active', '=', True)])
            departments = self.env['hr.department'].search([('active', '=', True)])
        else:
            units, departments = self.env['eds.hr.compat'].get_managed_training_scope()
            units = units.filtered('active')
            departments = departments.filtered('active')
        for rec in self:
            rec.allowed_work_unit_ids = units
            rec.allowed_department_ids = departments
            rec.can_request_work_unit = bool(units)
            rec.can_choose_department = len(departments) > 1

    @api.depends('department_id', 'allowed_work_unit_ids', 'allowed_department_ids')
    def _compute_available_work_units(self):
        compat = self.env['eds.hr.compat']
        for rec in self:
            units = compat.get_available_work_units_for_department(
                rec.allowed_work_unit_ids, rec.department_id,
                rec.allowed_department_ids)
            rec.available_work_unit_ids = units
            rec.can_choose_work_unit = len(units) > 1

    @api.depends('request_level', 'work_unit_id', 'department_id', 'cycle_id',
                 'cycle_id.restrict_tna_audience', 'cycle_id.target_employee_ids',
                 'cycle_id.target_department_ids', 'cycle_id.target_work_unit_ids',
                 'cycle_id.target_job_position_ids')
    def _compute_eligible_work_unit_employees(self):
        Employee = self.env['hr.employee'].sudo()
        for rec in self:
            if rec.request_level != 'work_unit' or not rec.work_unit_id:
                rec.eligible_work_unit_employee_ids = Employee.browse()
                continue
            domain = self.env['eds.hr.compat'].get_employee_domain(
                operating_unit=rec.work_unit_id)
            if rec.department_id:
                dept_domain = [('department_id', '=', rec.department_id.id)]
                scoped = Employee.search([('active', '=', True)] + domain + dept_domain)
                if scoped:
                    domain += dept_domain
            if rec.cycle_id:
                domain += rec.cycle_id._target_employee_domain()
            rec.eligible_work_unit_employee_ids = Employee.search(
                [('active', '=', True)] + domain)

    @api.depends('request_level', 'employee_id', 'work_unit_id')
    @api.depends_context('uid')
    def _compute_available_cycles(self):
        cycles = self.env['eds.tna.cycle'].search([('state', '=', 'collecting')])
        compat = self.env['eds.hr.compat']
        managed_units = self.env['operating.unit']
        if not (self.env.su or self.env.user.has_group(
                'employee_development_system.group_eds_officer')):
            managed_units, _departments = compat.get_managed_training_scope()
        for rec in self:
            if rec.request_level == 'work_unit':
                units = rec.work_unit_id or managed_units
                if not units and (self.env.su or self.env.user.has_group(
                        'employee_development_system.group_eds_officer')):
                    units = self.env['operating.unit'].search([('active', '=', True)])
                rec.available_cycle_ids = cycles.filtered(lambda cycle: bool(units) and bool(
                    self.env['hr.employee'].sudo().search_count(
                        compat.get_employee_domain(operating_unit=units)
                        + cycle._target_employee_domain())))
            else:
                employee = rec.employee_id or rec._default_employee_id()
                rec.available_cycle_ids = cycles.filtered(
                    lambda cycle: cycle._is_employee_targeted(employee))
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
    ], string='Target Group / Audience', default='all_staff', tracking=True,
        help='Legacy category from imported HR TNA templates. Employee selection and course demand use the actual employee or nominated work-unit employees, not this category.')
    target_participant_count = fields.Integer(
        string='Number of Participants', compute='_compute_participant_count',
        store=True, readonly=True,
        help='Number of selected work-unit employees, or the individual employee on this need.')
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
    catalog_status = fields.Selection([
        ('catalog', 'Catalog Course'),
        ('outside_catalog', 'Outside Catalog'),
    ], string='Catalog Status', compute='_compute_catalog_status', store=True, index=True)
    course_mapping_status = fields.Selection([
        ('mapped', 'Mapped'),
        ('not_mapped', 'Not Mapped'),
    ], string='Course Mapping', compute='_compute_course_mapping_status', store=True, index=True)
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
    course_request_display = fields.Char(
        string='Course(s)', compute='_compute_course_request_display',
        help='The requested catalog courses, one legacy catalog course, or a work-unit proposed course.')
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
        help='Courses integrated with this gap that are offered in the selected TNA cycle.')
    cycle_course_status = fields.Selection([
        ('offered', 'Offered in Cycle'),
        ('not_offered', 'No Selected Course'),
        ('mapped', 'Catalog Match'),
        ('unmapped', 'No Catalog Match'),
    ], string='Cycle Course Match', compute='_compute_cycle_course_status',
        help='A diagnosis remains visible even when none of its mapped courses are selected for this cycle; it does not enter course demand.')
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
        ('exact', 'Catalog Name Match'),
        ('higher', 'Possible Catalog Match'),
        ('no_course', 'No Catalog Match'),
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

    # ── Consolidation & Prioritization ──
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

    @api.depends('course_id', 'requested_course_ids', 'suggested_course_ids',
                 'is_custom_course', 'source', 'request_level')
    def _compute_course_mapping_status(self):
        for rec in self:
            if rec.course_id:
                rec.course_mapping_status = 'mapped'
            elif rec.source == 'manual' and rec.request_level == 'individual' and rec.requested_course_ids:
                rec.course_mapping_status = 'mapped'
            elif rec.source in ('competency_gap', 'pms') and rec.suggested_course_ids:
                rec.course_mapping_status = 'mapped'
            else:
                rec.course_mapping_status = 'not_mapped'

    @api.depends('course_mapping_status')
    def _compute_catalog_status(self):
        for rec in self:
            rec.catalog_status = 'catalog' if rec.course_mapping_status == 'mapped' else 'outside_catalog'

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

    @api.depends('source', 'competency_id', 'competency_level', 'pms_measure_id',
                 'pms_appraisal_score', 'pms_appraisal_rating', 'course_id',
                 'cycle_id.restrict_tna_courses',
                 'cycle_id.request_course_ids')
    def _compute_suggested_courses(self):
        Course = self.env['eds.course']
        for rec in self:
            courses = Course.browse()
            if rec.source not in ('competency_gap', 'pms'):
                rec.suggested_course_ids = [(6, 0, [])]
                continue
            if rec.course_id:
                courses |= rec.course_id
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
                if not courses:
                    comp_lines = self.env['eds.course.competency.line'].search([
                        ('competency_id', '=', rec.competency_id.id),
                        ('course_id.status', 'in', ('active', 'draft'))
                    ])
                    courses |= comp_lines.mapped('course_id')
                if not courses:
                    fallback_name = (_("%s Mastery Program") % rec.competency_id.name).strip()
                    matched = Course.search([
                        ('name', '=ilike', fallback_name),
                        ('status', 'in', ('active', 'draft')),
                    ], limit=1)
                    if not matched:
                        matched = Course.search([
                            ('name', '=ilike', rec.competency_id.name.strip()),
                            ('status', 'in', ('active', 'draft')),
                        ], limit=1)
                    courses |= matched
            if not courses and rec.proposed_program:
                matched = Course.search([
                    ('name', '=ilike', rec.proposed_program.strip()),
                    ('status', 'in', ('active', 'draft')),
                ], limit=1)
                courses |= matched
            if rec.pms_measure_id:
                pms_domain = [
                    ('job_measure_id', '=', rec.pms_measure_id.id),
                    ('course_id.status', 'in', ('active', 'draft'))
                ]
                if (rec.pms_appraisal_rating or '').strip().casefold() != 'unsatisfactory':
                    pms_domain.append(('min_threshold', '>', rec.pms_appraisal_score))
                pms_lines = self.env['eds.course.pms.line'].search(pms_domain)
                courses |= pms_lines.mapped('course_id')
            if rec.cycle_id:
                courses = rec.cycle_id._filter_cycle_courses(courses)
            rec.suggested_course_ids = [(6, 0, courses.ids)]

    @api.depends('source', 'cycle_id.restrict_tna_courses',
                 'cycle_id.request_course_ids', 'suggested_course_ids',
                 'course_id', 'recommended_course_id')
    def _compute_cycle_course_status(self):
        for rec in self:
            if rec.source not in ('competency_gap', 'pms'):
                rec.cycle_course_status = False
                continue
            courses = rec.suggested_course_ids | rec.course_id | rec.recommended_course_id
            if rec.cycle_id and rec.cycle_id.restrict_tna_courses:
                rec.cycle_course_status = (
                    'offered' if rec.cycle_id._filter_cycle_courses(courses)
                    else 'not_offered')
            else:
                rec.cycle_course_status = 'mapped' if courses else 'unmapped'

    @api.depends('gap_severity', 'urgency', 'source')
    def _compute_score_gap_severity(self):
        """Use diagnosed gap severity, or request urgency when no gap was measured."""
        weights = {'critical': 100.0, 'high': 75.0, 'medium': 50.0, 'low': 25.0}
        for rec in self:
            severity = rec.urgency if rec.source == 'manual' else rec.gap_severity
            rec.score_gap_severity = weights.get(severity, 50.0)

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

    @api.depends('course_id', 'requested_course_ids', 'is_custom_course', 'custom_course_title',
                 'source', 'suggested_course_ids')
    def _compute_proposed_program(self):
        for rec in self:
            if rec.source in ('competency_gap', 'pms'):
                if rec.course_id:
                    rec.proposed_program = rec.course_id.name
                elif rec.suggested_course_ids:
                    rec.proposed_program = rec.suggested_course_ids[0].name
                else:
                    rec.proposed_program = False
            elif rec.is_custom_course and rec.custom_course_title:
                rec.proposed_program = rec.custom_course_title
            elif not rec.is_custom_course and rec.course_id:
                rec.proposed_program = rec.course_id.name
            elif not rec.is_custom_course and rec.requested_course_ids:
                rec.proposed_program = (
                    rec.requested_course_ids.name if len(rec.requested_course_ids) == 1 else False
                )
            elif not rec.proposed_program:
                rec.proposed_program = False

    @api.depends('requested_course_ids.name', 'course_id.name', 'is_custom_course',
                 'custom_course_title', 'proposed_program', 'suggested_course_ids.name', 'source')
    def _compute_course_request_display(self):
        for rec in self:
            if rec.is_custom_course and rec.custom_course_title:
                rec.course_request_display = _('%s (outside catalog)') % rec.custom_course_title
            elif rec.requested_course_ids:
                rec.course_request_display = ', '.join(rec.requested_course_ids.mapped('name'))
            elif rec.course_id:
                rec.course_request_display = rec.course_id.name
            elif rec.source in ('competency_gap', 'pms') and rec.suggested_course_ids:
                rec.course_request_display = ', '.join(rec.suggested_course_ids.mapped('name'))
            elif rec.source in ('competency_gap', 'pms'):
                rec.course_request_display = _('Unmapped Gap')
            else:
                rec.course_request_display = rec.proposed_program or _('Unmapped')

    @api.depends('request_level', 'source', 'course_id', 'requested_course_ids',
                 'is_custom_course', 'custom_course_title', 'competency_id', 'proposed_program',
                 'suggested_course_ids', 'cycle_id.restrict_tna_courses',
                 'cycle_id.request_course_ids')
    def _compute_recommended_course(self):
        Course = self.env['eds.course']
        for rec in self:
            restricted = bool(rec.cycle_id and rec.cycle_id.restrict_tna_courses)
            allowed_ids = rec.cycle_id.request_course_ids.ids if restricted else []
            if rec.request_level == 'individual' and rec.source == 'manual':
                rec.recommended_course_id = False
                rec.course_match_status = False
                continue
            if rec.source in ('competency_gap', 'pms'):
                # Diagnostic recommendations must be backed by the configured
                # competency or PMS mapping, never a similar course title.
                mapped_course = rec.suggested_course_ids[:1]
                rec.recommended_course_id = mapped_course or False
                rec.course_match_status = 'exact' if mapped_course else 'no_course'
                continue
            # 1. Direct Catalog Course Selection
            if not rec.is_custom_course and rec.course_id and (
                    not restricted or rec.course_id.id in allowed_ids):
                rec.recommended_course_id = rec.course_id
                rec.course_match_status = 'exact'
                continue

            # 2. Match via Diagnosed Competency
            if rec.competency_id:
                line_domain = [
                    ('competency_id', '=', rec.competency_id.id),
                    ('course_id.status', 'in', ('active', 'draft'))
                ]
                if restricted:
                    line_domain.append(('course_id', 'in', allowed_ids))
                course_line = self.env['eds.course.competency.line'].search(
                    line_domain, limit=1)
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
                name_domain = [
                    ('status', 'in', ('active', 'draft')),
                ]
                if restricted:
                    name_domain.append(('id', 'in', allowed_ids))
                c_exact = Course.search(name_domain + [('name', '=ilike', term)], limit=1)
                if c_exact:
                    matched_course = c_exact
                    is_exact = True
                    break
                c_search = Course.search(name_domain + [('name', 'ilike', term)], limit=1)
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

    @api.onchange('cycle_id')
    def _onchange_cycle_request_courses(self):
        if not self.cycle_id or not self.cycle_id.restrict_tna_courses or self.source != 'manual':
            return
        allowed = self.cycle_id.request_course_ids
        removed = self.requested_course_ids - allowed
        changed = bool(removed)
        if self.course_id and self.course_id not in allowed:
            self.course_id = False
            changed = True
        if removed:
            self.requested_course_ids = self.requested_course_ids & allowed
        if self.is_custom_course:
            self.is_custom_course = False
            self.custom_course_title = False
            self.custom_course_description = False
            changed = True
        if changed:
            return {'warning': {
                'title': _('Courses Updated'),
                'message': _('Courses outside this cycle’s selected catalog were removed from the request.'),
            }}

    @api.onchange('urgency')
    def _onchange_urgency(self):
        if self.urgency:
            self.gap_severity = self.urgency

    @api.onchange('is_custom_course', 'custom_course_title', 'custom_course_description')
    def _onchange_custom_course(self):
        if self.is_custom_course:
            self.course_id = False
            if not self.custom_course_title and self.template_participant_count and self.proposed_program:
                self.custom_course_title = self.proposed_program
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

    def action_quick_create_course(self):
        """Create a new course in the catalog in draft status from this custom course proposal,
        map it to the proposal, and open its form view so the user can configure competencies,
        activate it, and return to the TNA cycle."""
        self.ensure_one()
        title = (self.custom_course_title or self.proposed_program or '').strip()
        if not title:
            raise UserError(_('A custom course title is required to create a course catalog record.'))
        Course = self.env['eds.course'].sudo()
        target_course = Course.search([('name', '=ilike', title)], limit=1)
        if not target_course:
            code_prefix = 'CRS-'
            last_course = Course.search([('code', '=like', code_prefix + '%')], order='id desc', limit=1)
            new_num = (last_course.id + 1) if last_course else 1
            code = f"{code_prefix}{new_num:04d}"
            rec_source = 'elearning' if self.delivery_mode in ('e_learning', 'elearning') else 'internal'
            course_vals = {
                'name': title,
                'code': code,
                'description': self.custom_course_description or False,
                'status': 'draft',
                'recommended_source': rec_source,
                'delivery_method': rec_source,
                'duration_days': 1,
                'origin_tna_cycle_id': self.cycle_id.id if self.cycle_id else False,
            }
            if self.department_id:
                course_vals['department_ids'] = [(4, self.department_id.id)]
            if self.competency_id:
                level_map = {'basic': '1', 'intermediate': '2', 'advanced': '3', 'expert': '4',
                             '1': '1', '2': '2', '3': '3', '4': '4'}
                course_vals['competency_line_ids'] = [(0, 0, {
                    'competency_id': self.competency_id.id,
                    'required_level': level_map.get(str(self.competency_level), '2'),
                    'weight_pct': 100,
                })]
            target_course = Course.create(course_vals)
        else:
            if self.cycle_id and not target_course.origin_tna_cycle_id:
                target_course.write({'origin_tna_cycle_id': self.cycle_id.id})

        # Map this entry and any sibling proposals with the same title in the cycle
        self.write({'course_id': target_course.id})
        if self.cycle_id:
            sibling_entries = self.cycle_id.custom_course_entry_ids.filtered(
                lambda e: not e.course_id and (e.custom_course_title or e.proposed_program or '').strip().casefold() == title.casefold()
            )
            if sibling_entries:
                sibling_entries.write({'course_id': target_course.id})
            self.cycle_id._sync_course_demand()

        return {
            'name': _('Course: %s') % target_course.name,
            'type': 'ir.actions.act_window',
            'res_model': 'eds.course',
            'res_id': target_course.id,
            'view_mode': 'form',
            'views': [(self.env.ref('employee_development_system.view_eds_course_form').id, 'form')],
            'target': 'current',
            'context': dict(self.env.context, origin_tna_cycle_id=self.cycle_id.id if self.cycle_id else False),
        }

    def action_open_mapped_course(self):
        """Open the mapped catalog course in form view."""
        self.ensure_one()
        if not self.course_id:
            raise UserError(_('No catalog course mapped to this entry.'))
        if self.cycle_id and not self.course_id.origin_tna_cycle_id:
            self.course_id.sudo().write({'origin_tna_cycle_id': self.cycle_id.id})
        return {
            'name': _('Course: %s') % self.course_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'eds.course',
            'res_id': self.course_id.id,
            'view_mode': 'form',
            'views': [(self.env.ref('employee_development_system.view_eds_course_form').id, 'form')],
            'target': 'current',
            'context': dict(self.env.context, origin_tna_cycle_id=self.cycle_id.id if self.cycle_id else False),
        }

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

    @api.onchange('request_level')
    def _onchange_request_level(self):
        if self.request_level == 'work_unit':
            self.source = 'manual'
            self.employee_id = False
            self.job_position_id = False
            departments = self.allowed_department_ids
            if len(departments) == 1:
                self.department_id = departments
            elif self._selected_record_id(self.department_id) not in departments.ids:
                self.department_id = False
            units = self.available_work_unit_ids
            if len(units) == 1:
                self.work_unit_id = units
            elif self._selected_record_id(self.work_unit_id) not in units.ids:
                self.work_unit_id = False
        elif self.request_level == 'individual':
            self.work_unit_employee_ids = False
            self.employee_id = self._default_employee_id()
            self._onchange_employee_id()

    @staticmethod
    def _selected_record_id(record):
        """Use the database ID when an onchange wraps a selection in a NewId."""
        return record._origin.id or record.id

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
        if self.request_level == 'work_unit':
            units = self.available_work_unit_ids
            selected_ou_id = self._selected_record_id(self.work_unit_id)
            if selected_ou_id not in units.ids:
                self.work_unit_id = units if len(units) == 1 else False
            self.job_position_id = False
            self.work_unit_employee_ids &= self.eligible_work_unit_employee_ids
            return {
                'domain': {
                    'work_unit_id': [('id', 'in', units.ids)],
                    'work_unit_employee_ids': [('id', 'in', self.eligible_work_unit_employee_ids.ids)],
                }
            }

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
        if self.request_level == 'work_unit':
            selected_ou_id = self._selected_record_id(self.work_unit_id)
            if selected_ou_id and selected_ou_id not in self.available_work_unit_ids.ids:
                self.work_unit_id = False
            self.job_position_id = False
            self.work_unit_employee_ids &= self.eligible_work_unit_employee_ids
            return {
                'domain': {
                    'work_unit_employee_ids': [('id', 'in', self.eligible_work_unit_employee_ids.ids)],
                }
            }

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
        if self.request_level == 'work_unit':
            return
        if self.employee_id:
            job = self.env['eds.hr.compat'].get_employee_job(self.employee_id)
            if job:
                self.job_position_id = job
            if self.employee_id.department_id:
                self.department_id = self.employee_id.department_id
            ou = self.env['eds.hr.compat'].get_employee_operating_unit(self.employee_id)
            if ou:
                self.work_unit_id = ou

    @api.onchange('work_unit_id', 'department_id')
    def _onchange_work_unit_employee_scope(self):
        if self.request_level == 'work_unit':
            self.work_unit_employee_ids &= self.eligible_work_unit_employee_ids

    @api.onchange('cycle_id', 'course_id', 'work_unit_employee_ids', 'request_level')
    def _onchange_repeat_work_unit_nomination(self):
        """Inform the requester without blocking another valid group request."""
        if (self.request_level != 'work_unit' or self.source != 'manual'
                or not self.cycle_id or not self.course_id
                or not self.work_unit_employee_ids):
            return
        employee_ids = set((self.work_unit_employee_ids._origin
                            or self.work_unit_employee_ids).ids)
        if not employee_ids:
            return
        domain = [
            ('cycle_id', '=', (self.cycle_id._origin or self.cycle_id).id),
            ('course_id', '=', (self.course_id._origin or self.course_id).id),
            ('request_level', '=', 'work_unit'),
            ('source', '=', 'manual'),
            ('state', 'not in', ('draft', 'excluded')),
            ('is_duplicate', '=', False),
            ('exclusion_type', '=', False),
            ('work_unit_employee_ids', 'in', list(employee_ids)),
        ]
        if self._origin:
            domain.append(('id', '!=', self._origin.id))
        earlier = self.env['eds.tna.entry'].sudo().search(domain)
        repeated_ids = employee_ids & set(earlier.mapped('work_unit_employee_ids').ids)
        if not repeated_ids:
            return
        names = self.env['hr.employee'].sudo().browse(sorted(repeated_ids)).mapped('name')
        display = ', '.join(names[:3])
        if len(names) > 3:
            display += _(' and %d more') % (len(names) - 3)
        return {'warning': {
            'title': _('Already Nominated for This Course'),
            'message': _(
                '%s already appears in another submitted work-unit request for this '
                'course and cycle. You may submit this request. Course Demand will '
                'count each employee once and use the highest Work Unit priority score.') % display,
        }}

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

    @api.constrains('cycle_id', 'source', 'request_level', 'employee_id',
                    'work_unit_employee_ids', 'state')
    def _check_cycle_audience(self):
        for rec in self:
            cycle = rec.cycle_id
            if not cycle:
                continue
            if (not self.env.su and rec.source == 'manual'
                    and rec.state == 'draft' and cycle.state != 'collecting'):
                raise ValidationError(_('Choose a TNA cycle that is open for collection.'))
            if not cycle.restrict_tna_audience:
                continue
            if rec.request_level == 'individual' and rec.employee_id:
                if not cycle._is_employee_targeted(rec.employee_id):
                    raise ValidationError(_('%s is outside the selected employee audience for this TNA cycle.') % rec.employee_id.name)
            elif rec.request_level == 'work_unit' and rec.work_unit_employee_ids:
                matched = self.env['hr.employee'].sudo().search(
                    [('id', 'in', rec.work_unit_employee_ids.ids)]
                    + cycle._target_employee_domain())
                if set(matched.ids) != set(rec.work_unit_employee_ids.ids):
                    raise ValidationError(_('Every nominated employee must match this TNA cycle’s selected audience.'))

    @api.constrains('cycle_id', 'employee_id', 'request_level', 'source', 'state',
                    'requested_course_ids', 'course_id', 'is_custom_course', 'work_unit_employee_ids', 'work_unit_id')
    def _check_max_individual_courses(self):
        max_courses_param = max(1, int(self.env['ir.config_parameter'].sudo().get_param(
            'eds.max_tna_courses_per_employee', '3')))
        for rec in self:
            if rec.source == 'manual' and rec.cycle_id.restrict_tna_courses:
                allowed = rec.cycle_id.request_course_ids
                selected = rec.requested_course_ids | rec.course_id
                if selected - allowed:
                    raise ValidationError(_(
                        'This TNA cycle only accepts its selected catalog courses. '
                        'Choose a course from the cycle’s available courses.'))
                if rec.is_custom_course:
                    raise ValidationError(_(
                        'Courses outside the catalog are not available in this restricted TNA cycle.'))
            if rec.state == 'excluded':
                continue
            if rec.request_level == 'individual' and rec.source == 'manual' and rec.is_custom_course:
                raise ValidationError(_('A course outside the catalog may only be proposed in a work-unit request.'))
            if rec.request_level == 'work_unit' and rec.state != 'draft':
                if not rec.work_unit_id or not rec.work_unit_employee_ids:
                    raise ValidationError(_('A work-unit request needs a work unit and selected employees.'))
                if rec.is_custom_course:
                    if not rec.custom_course_title:
                        raise ValidationError(_('A work-unit custom course needs a title.'))
                elif not rec.course_id:
                    raise ValidationError(_('Select one catalog course for this work-unit request.'))
                employee_domain = self.env['eds.hr.compat'].get_employee_domain(
                    operating_unit=rec.work_unit_id) + rec.cycle_id._target_employee_domain()
                Employee = self.env['hr.employee'].sudo()
                eligible_ids = set(Employee.search([
                    ('id', 'in', rec.work_unit_employee_ids.ids),
                ] + employee_domain).ids)
                if eligible_ids != set(rec.work_unit_employee_ids.ids):
                    raise ValidationError(_(
                        'Every selected employee must belong to the selected work unit.'))
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

    @api.constrains('request_level', 'source', 'employee_id', 'work_unit_id',
                    'department_id', 'cycle_id')
    def _check_manual_request_scope(self):
        for rec in self:
            if rec.request_level == 'work_unit' and rec.source != 'manual':
                raise ValidationError(_(
                    'Work-unit requests are submitted directly by a unit leader; choose Individual for imported diagnostic gaps.'))
        if self.env.su or self.env.user.has_group('employee_development_system.group_eds_officer'):
            return
        compat = self.env['eds.hr.compat']
        managed_units, managed_departments = compat.get_managed_training_scope()
        for rec in self.filtered(lambda entry: entry.source == 'manual'):
            if rec.cycle_id.state != 'collecting':
                raise ValidationError(_('Training needs can only be submitted to a cycle open for collection.'))
            if rec.request_level == 'work_unit':
                if rec.work_unit_id not in managed_units:
                    raise ValidationError(_('You may submit a work-unit request only for a unit you lead.'))
                if managed_departments:
                    if rec.department_id not in managed_departments:
                        raise ValidationError(_(
                            'Select a department within your reporting responsibility.'))
                    available_units = compat.get_available_work_units_for_department(
                        managed_units, rec.department_id, managed_departments)
                    if rec.work_unit_id not in available_units:
                        raise ValidationError(_(
                            'The selected work unit is outside the chosen department in your reporting scope.'))
            elif rec.employee_id.user_id != self.env.user:
                raise ValidationError(_('An individual TNA request must be for your own employee record.'))

    def onchange(self, values, field_names, fields_spec):
        return super(EdsTnaEntry, self.with_context(
            eds_employee_select=True, active_model='eds.tna.entry'
        )).onchange(values, field_names, fields_spec)

    def web_read(self, specification):
        return safe_employee_web_read(
            self.with_context(eds_employee_select=True, active_model='eds.tna.entry'),
            specification,
            super().web_read,
            ('employee_id',)
        )

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
            if vals.get('request_level', 'individual') == 'work_unit':
                vals['job_position_id'] = False
                vals['employee_id'] = False
                vals.pop('target_participant_count', None)
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
        if (vals.get('request_level') == 'work_unit'
                or (self and all(rec.request_level == 'work_unit' for rec in self))):
            vals = dict(vals, job_position_id=False)
            vals.pop('target_participant_count', None)
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
            rec._check_cycle_audience()
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
    """Aggregated course demand line on TNA Cycle.

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
    catalog_status = fields.Selection([
        ('catalog', 'Catalog Course'),
        ('outside_catalog', 'Outside Catalog'),
    ], string='Catalog Status', compute='_compute_catalog_status')
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

    @api.depends('course_id')
    def _compute_catalog_status(self):
        for rec in self:
            rec.catalog_status = 'catalog' if rec.course_id else 'outside_catalog'

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

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_ids',)
        )


class EdsTnaCycleCourseEmployee(models.Model):
    """One employee per course, with all independent TNA evidence retained."""

    _name = 'eds.tna.cycle.course.employee'
    _description = 'Course Demand Employee'
    _order = 'overall_priority_score desc, source_count desc, id'
    _rec_name = 'employee_id'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',)
        )

    course_line_id = fields.Many2one('eds.tna.cycle.course.line', required=True,
                                     ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True)
    excluded_from_planning = fields.Boolean(
        string='Invalidated', default=False, index=True,
        help='Keep the original TNA evidence visible, but exclude this employee '
             'from this course’s planning count and suggested session participants.')
    exclusion_reason = fields.Text(string='Invalidation Reason', readonly=True)
    excluded_by_id = fields.Many2one('res.users', string='Invalidated By', readonly=True)
    excluded_on = fields.Datetime(string='Invalidated On', readonly=True)
    restored_by_id = fields.Many2one('res.users', string='Restored By', readonly=True)
    restored_on = fields.Datetime(string='Restored On', readonly=True)
    work_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', store=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', store=True)
    job_position_id = fields.Many2one('hr.job', related='employee_id.job_position', store=True)
    evidence_ids = fields.One2many('eds.tna.cycle.course.evidence', 'demand_id', string='Sources')
    source_count = fields.Integer(compute='_compute_sources', store=True)
    evidence_count = fields.Integer(compute='_compute_sources', store=True)
    source_summary = fields.Char(compute='_compute_sources', store=True)
    overall_priority_score = fields.Float(
        string='Overall Weighted Priority', compute='_compute_overall_priority_score',
        store=True, digits=(6, 0),
        help='Use the highest Work Unit request score for repeat nominations and average '
             'distinct evidence within other source types, then average those source types. '
             'Add five points per additional independent source type and round to a whole number, capped at 100.')
    need_severity = fields.Selection([
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'),
        ('critical', 'Critical'),
    ], string='Highest Need Severity', compute='_compute_need_severity', store=True,
        help='Highest severity among this employee’s individual, work-unit, competency, and PMS evidence for the course.')
    from_individual = fields.Boolean(compute='_compute_sources', store=True)
    from_work_unit = fields.Boolean(compute='_compute_sources', store=True)
    from_competency = fields.Boolean(compute='_compute_sources', store=True)
    from_pms = fields.Boolean(compute='_compute_sources', store=True)

    def write(self, vals):
        decision_fields = {
            'excluded_from_planning', 'exclusion_reason', 'excluded_by_id',
            'excluded_on', 'restored_by_id', 'restored_on',
        }
        if (decision_fields.intersection(vals) and not self.env.su
                and not self.env.context.get('eds_demand_review_action')):
            raise UserError(_(
                'Use Invalidate or Restore to change a course candidate’s planning status.'))
        return super().write(vals)

    def _require_lnd_review(self):
        if self.env.su or any(self.env.user.has_group(
                'employee_development_system.' + group) for group in (
                    'group_eds_officer', 'group_eds_manager', 'group_eds_admin')):
            return
        raise UserError(_('Only L&D staff may invalidate or restore course candidates.'))

    def _linked_plan_lines(self):
        course_lines = self.mapped('course_line_id')
        if not course_lines:
            return self.env['eds.annual.plan.line']
        return self.env['eds.annual.plan.line'].search([
            '|', ('course_demand_id', 'in', course_lines.ids),
            ('course_demand_ids', 'in', course_lines.ids),
        ])

    def _check_reviewable(self):
        self._require_lnd_review()
        plan_lines = self._linked_plan_lines()
        if plan_lines.filtered(lambda line: line.plan_id.state != 'draft'):
            raise UserError(_(
                'This course already belongs to a plan under review or published. '
                'Change the plan through its review or amendment workflow first.'))
        active_enrollments = self.env['eds.enrollment'].search([
            ('course_demand_employee_id', 'in', self.ids),
            ('state', 'not in', ('suggested', 'cancelled', 'declined', 'replaced')),
        ])
        if plan_lines:
            active_enrollments |= self.env['eds.enrollment'].search([
                ('session_id.plan_line_id', 'in', plan_lines.ids),
                ('employee_id', 'in', self.mapped('employee_id').ids),
                ('state', 'not in', ('suggested', 'cancelled', 'declined', 'expired', 'replaced')),
            ])
        if active_enrollments:
            raise UserError(_(
                'One or more selected employees already have a training invitation or '
                'attendance record. Resolve those session participants before invalidating them.'))
        return plan_lines

    def _refresh_planning_after_review(self, plan_lines):
        for cycle in self.mapped('course_line_id.cycle_id'):
            cycle._sync_course_demand()
        for line in plan_lines:
            demands = line.course_demand_ids | line.course_demand_id
            eligible = demands.filtered(
                lambda demand: demand.selected_for_planning and demand.total_employees > 0)
            if not eligible:
                if (line.session_ids or line.budget_allocated or line.manual_budget_allocated
                        or line.status != 'planned'):
                    raise UserError(_(
                        'Removing all candidates would leave plan line %s with a session, '
                        'budget or delivery progress. Resolve that plan line first.') % line.program_name)
                line.unlink()
                continue
            line.planned_participants = len(set(eligible.mapped('employee_ids').ids))
            valid_employee_ids = set(eligible.mapped('employee_ids').ids)
            valid_rows = eligible.mapped('employee_demand_ids').filtered(
                lambda row: not row.excluded_from_planning)
            for session in line.session_ids:
                for enrollment in session.enrollment_ids.filtered(
                        lambda row: row.state == 'suggested'):
                    if enrollment.employee_id.id not in valid_employee_ids:
                        # Screening removes a suggestion because its demand is no
                        # longer eligible. It is not a manual roster omission: a
                        # later restore must be able to suggest the employee again.
                        enrollment.with_context(eds_replacing_source=True).unlink()
                    elif enrollment.course_demand_employee_id.excluded_from_planning:
                        replacement = valid_rows.filtered(
                            lambda row: row.employee_id == enrollment.employee_id)[:1]
                        if replacement:
                            enrollment.course_demand_employee_id = replacement

    def action_open_invalidate_wizard(self):
        self._require_lnd_review()
        selected = self.filtered(lambda row: not row.excluded_from_planning)
        if not selected:
            raise UserError(_('Select at least one eligible employee to invalidate.'))
        return {
            'name': _('Invalidate Course Candidates'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.tna.demand.invalidate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_demand_ids': [(6, 0, selected.ids)]},
        }

    def action_invalidate_with_reason(self, reason):
        self._require_lnd_review()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_('Enter a reason for invalidating these course candidates.'))
        selected = self.filtered(lambda row: not row.excluded_from_planning)
        if not selected:
            raise UserError(_('No eligible employees were selected.'))
        plan_lines = selected._check_reviewable()
        selected.with_context(eds_demand_review_action=True).write({
            'excluded_from_planning': True,
            'exclusion_reason': reason,
            'excluded_by_id': self.env.user.id,
            'excluded_on': fields.Datetime.now(),
        })
        selected._refresh_planning_after_review(plan_lines)
        for course_line in selected.mapped('course_line_id'):
            count = len(selected.filtered(lambda row: row.course_line_id == course_line))
            course_line.cycle_id.message_post(body=Markup('<p>%s</p>') % escape(_(
                '%d employees invalidated for %s. Reason: %s')
                % (count, course_line.course_name, reason)))
        cycles = selected.mapped('course_line_id.cycle_id')
        if len(cycles) == 1:
            return {
                'type': 'ir.actions.client',
                'tag': 'bunna_refresh_form',
                'params': {'res_model': 'eds.tna.cycle', 'res_id': cycles.id},
            }
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_restore(self):
        self._require_lnd_review()
        selected = self.filtered('excluded_from_planning')
        if not selected:
            raise UserError(_('Select at least one invalidated employee to restore.'))
        plan_lines = selected._check_reviewable()
        selected.with_context(eds_demand_review_action=True).write({
            'excluded_from_planning': False,
            'restored_by_id': self.env.user.id,
            'restored_on': fields.Datetime.now(),
        })
        selected._refresh_planning_after_review(plan_lines)
        for course_line in selected.mapped('course_line_id'):
            count = len(selected.filtered(lambda row: row.course_line_id == course_line))
            course_line.cycle_id.message_post(body=Markup('<p>%s</p>') % escape(_(
                '%d employees restored for %s.') % (count, course_line.course_name)))
        cycles = selected.mapped('course_line_id.cycle_id')
        if len(cycles) == 1:
            return {
                'type': 'ir.actions.client',
                'tag': 'bunna_refresh_form',
                'params': {'res_model': 'eds.tna.cycle', 'res_id': cycles.id},
            }
        return {'type': 'ir.actions.client', 'tag': 'reload'}

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

    @api.depends('evidence_ids', 'evidence_ids.entry_id.priority_score',
                 'evidence_ids.source_kind', 'source_count')
    def _compute_overall_priority_score(self):
        for rec in self:
            by_source = {}
            for evidence in rec.evidence_ids:
                by_source.setdefault(evidence.source_kind, []).append(
                    evidence.entry_id.priority_score)
            if not by_source:
                rec.overall_priority_score = 0.0
                continue
            source_averages = [
                max(scores) if source_kind == 'work_unit' else sum(scores) / len(scores)
                for source_kind, scores in by_source.items()
            ]
            rec.overall_priority_score = min(100.0, float_round(
                sum(source_averages) / len(source_averages)
                + max(0, len(by_source) - 1) * 5.0,
                precision_digits=0))

    @api.depends('evidence_ids', 'evidence_ids.need_severity')
    def _compute_need_severity(self):
        rank = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
        for rec in self:
            levels = [level for level in rec.evidence_ids.mapped('need_severity')
                      if level in rank]
            rec.need_severity = max(levels, key=lambda level: rank[level]) if levels else False


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
    need_severity = fields.Selection([
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'),
        ('critical', 'Critical'),
    ], string='Need Severity', compute='_compute_need_severity', store=True,
        help='Manual request urgency, diagnosed competency level gap, or PMS gap severity.')
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

    @api.depends('entry_id.source', 'entry_id.urgency', 'entry_id.gap_severity',
                 'entry_id.competency_gap_level_diff')
    def _compute_need_severity(self):
        for rec in self:
            entry = rec.entry_id
            if entry.source == 'manual':
                rec.need_severity = entry.urgency or 'medium'
            elif entry.source == 'competency_gap' and entry.competency_gap_level_diff > 0:
                gap = entry.competency_gap_level_diff
                rec.need_severity = 'critical' if gap >= 3 else ('high' if gap == 2 else 'medium')
            else:
                rec.need_severity = entry.gap_severity or 'medium'
