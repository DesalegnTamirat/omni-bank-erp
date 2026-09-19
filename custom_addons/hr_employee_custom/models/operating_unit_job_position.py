# models/operating_unit_job_position.py
from odoo.exceptions import UserError, ValidationError
from odoo import api, fields, models, _


class OperatingUnitJobPosition(models.Model):
    _name = 'operating.unit.job.position'
    _description = 'Job Position Planning per Operating Unit'
    _rec_name = 'job_position_id'
    _order = 'operating_unit_id, job_position_id'

    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            'unique_job_position_per_operating_unit',
            'unique(operating_unit_id, job_position_id)',
            'This Job Position has already been added for this Work Unit.',
        ),
    ]

    operating_unit_id = fields.Many2one(
        comodel_name='operating.unit',
        string='Work Unit',
        required=True,
        ondelete='cascade',
        index=True,
    )
    job_position_id = fields.Many2one(
        comodel_name='hr.job',
        string='Job Position',
        required=True,
        index=True,
    )
    job_grade_id = fields.Many2one(
        comodel_name='employee.grade',
        string='Job Grade',
        compute='_compute_job_grade',
        store=True,
        readonly=False,
    )

    baseline_count = fields.Integer(
        string='Baseline Count',
        compute='_compute_baseline_count',
        store=True,
        help=(
            "Auto-computed: count of active employees with an active contract "
            "(state open or probation) for this job position and work unit."
        ),
    )
    approved_plan_count = fields.Integer(
        string='Approved Plan Count',
        compute='_compute_approved_plan_count',
        store=True,
        readonly=False,
        default=0,
        help="Approved manpower plan additions from PBMS (display_approved_annual_total).",
    )
    plan_fulfillment_promotion = fields.Integer(
        string='Approved Promotion Plan',
        compute='_compute_approved_plan_count',
        store=True,
        default=0,
        help="Approved manpower additions earmarked for Promotion (fulfillment_promotion).",
    )
    plan_fulfillment_lateral = fields.Integer(
        string='Approved Lateral/Transfer Plan',
        compute='_compute_approved_plan_count',
        store=True,
        default=0,
        help="Approved manpower additions earmarked for Lateral/Transfer (fulfillment_lateral).",
    )
    plan_fulfillment_external = fields.Integer(
        string='Approved External Plan',
        compute='_compute_approved_plan_count',
        store=True,
        default=0,
        help="Approved manpower additions earmarked for External Vacancy (fulfillment_external).",
    )
    total_headcount = fields.Integer(
        string='Total Headcount',
        compute='_compute_total_headcount',
        store=True,
        help="Total Target Establishment = Baseline + Approved Plan.",
    )
    active_employee_count = fields.Integer(
        string='Active Employee Count',
        compute='_compute_active_employee_count',
        store=True,
        help="Current live count of active employees on duty for this position and unit.",
    )
    vacant_position_count = fields.Integer(
        string='Vacant Position Count',
        compute='_compute_vacant_position_count',
        store=True,
        help="Vacant Posts = Total Headcount - Active Employees.",
    )

    # Movement / Lifecycle Counters
    lateral_count = fields.Integer(
        string='Lateral / Transfer Count',
        default=0,
        help="Number of lateral transfers into/out of this position.",
    )
    replacement_count = fields.Integer(
        string='Replacement Count',
        default=0,
        help="Number of replacement positions initiated.",
    )
    promotion_count = fields.Integer(
        string='Promotion Count',
        default=0,
        help="Number of promotions out of / into this position.",
    )
    resignation_count = fields.Integer(
        string='Resignation Count',
        default=0,
        help="Number of resignations / terminations.",
    )
    vacancy_count = fields.Integer(
        string='Vacancies',
        compute='_compute_vacancy_count',
        help="Number of job vacancies created for this position and work unit.",
    )

    def _compute_vacancy_count(self):
        if 'job.vacancy' not in self.env:
            for rec in self:
                rec.vacancy_count = 0
            return
        JobVacancy = self.env['job.vacancy']
        for rec in self:
            if rec.job_position_id and rec.operating_unit_id:
                rec.vacancy_count = JobVacancy.search_count([
                    ('job_position', '=', rec.job_position_id.id),
                    ('operating_unit_id', '=', rec.operating_unit_id.id),
                ])
            else:
                rec.vacancy_count = 0

    def action_view_vacancies(self):
        self.ensure_one()
        return {
            'name': _('Vacancies: %s') % (self.job_position_id.name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'job.vacancy',
            'view_mode': 'list,form',
            'target': 'current',
            'domain': [
                ('job_position', '=', self.job_position_id.id),
                ('operating_unit_id', '=', self.operating_unit_id.id),
            ],
            'context': {
                'default_job_position': self.job_position_id.id,
                'default_operating_unit_id': self.operating_unit_id.id,
            },
        }

    def action_create_vacancy(self):
        self.ensure_one()
        from datetime import timedelta

        # Revalidate that approved plan is greater than 0 for planned requests
        if not self.env.context.get('unplanned') and self.approved_plan_count <= 0:
            raise UserError(_(
                "Cannot create vacancy: The approved manpower plan count for '%(job)s' at '%(unit)s' is %(plan)s. "
                "The number of opening vacancies cannot exceed the approved plan count."
            ) % {
                'job': self.job_position_id.name or '',
                'unit': self.operating_unit_id.name or '',
                'plan': self.approved_plan_count,
            })

        # Check specific sourcing fulfillment
        prom_plan = self.plan_fulfillment_promotion or 0
        lat_plan = self.plan_fulfillment_lateral or 0
        ext_plan = self.plan_fulfillment_external or 0
        has_sourcing = (prom_plan > 0 or lat_plan > 0 or ext_plan > 0)

        # Determine movement type & sourcing based on fulfillment strategy:
        # If approved plan is fulfillment_lateral and not promotion -> lateral transfer
        if has_sourcing and lat_plan > 0 and prom_plan <= 0:
            movement_type = 'lateral'
            sourcing_type = 'internal'
            recruitment_type = 'Internal'
            target_openings_cap = lat_plan
        elif has_sourcing and prom_plan > 0 and lat_plan <= 0:
            movement_type = 'promotion'
            sourcing_type = 'internal'
            recruitment_type = 'Internal'
            target_openings_cap = prom_plan
        elif has_sourcing and prom_plan > 0 and lat_plan > 0:
            movement_type = 'promotion'
            sourcing_type = 'internal'
            recruitment_type = 'Internal'
            target_openings_cap = prom_plan
        elif has_sourcing and ext_plan > 0:
            movement_type = 'external'
            sourcing_type = 'external'
            recruitment_type = 'External'
            target_openings_cap = ext_plan
        else:
            movement_type = 'promotion'
            sourcing_type = 'internal'
            recruitment_type = 'Internal'
            target_openings_cap = self.approved_plan_count

        # Calculate number of openings: strictly capped by target_openings_cap
        if self.vacant_position_count > 0:
            openings = min(self.vacant_position_count, target_openings_cap)
        else:
            openings = target_openings_cap
        openings = max(1, min(openings, target_openings_cap))

        grade_id = self.job_grade_id.id if self.job_grade_id else (
            self.job_position_id.grade.id if getattr(self.job_position_id, 'grade', False) else False
        )
        responsible_id = self.env.user.employee_id.id if self.env.user.employee_id else False
        today = fields.Date.context_today(self)

        context = {
            'default_job_position': self.job_position_id.id,
            'default_operating_unit_id': self.operating_unit_id.id,
            'default_job_grade': grade_id,
            'default_no_of_vacancies': openings,
            'default_type_of_employment': 'Permanent',
            'default_sourcing_type': sourcing_type,
            'default_recruitment_type': recruitment_type,
            'default_internal_movement_type': movement_type,
            'default_responsible': responsible_id,
            'default_opening_date': today,
            'default_last_date_to_apply': today + timedelta(days=3),
            'default_vacancy_description': (
                self.job_position_id.description or
                _("Vacancy for %s at %s") % (self.job_position_id.name, self.operating_unit_id.name)
            ),
            'default_hiring_details': [(0, 0, {
                'work_unit': self.operating_unit_id.id,
                'responsible_employee': responsible_id,
                'number_of_openings': openings,
                'planned_positions': openings,
                'status': 'In Progress',
            })],
        }

        return {
            'name': _('Create Job Vacancy'),
            'type': 'ir.actions.act_window',
            'res_model': 'job.vacancy',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': context,
        }

    @api.depends('job_position_id', 'job_position_id.grade')
    def _compute_job_grade(self):
        for rec in self:
            if rec.job_position_id and getattr(rec.job_position_id, 'grade', False):
                rec.job_grade_id = rec.job_position_id.grade
            elif not rec.job_grade_id:
                rec.job_grade_id = False

    @api.depends('operating_unit_id', 'job_position_id')
    def _compute_active_employee_count(self):
        for rec in self:
            if rec.operating_unit_id and rec.job_position_id:
                self.env.cr.execute("""
                    SELECT COUNT(DISTINCT v.id)
                    FROM hr_version v
                    WHERE v.active = true
                      AND v.job_id = %s
                      AND v.operating_unit_id = %s
                """, (rec.job_position_id.id, rec.operating_unit_id.id))
                rec.active_employee_count = self.env.cr.fetchone()[0] or 0
            else:
                rec.active_employee_count = 0

    @api.depends('operating_unit_id', 'job_position_id', 'active_employee_count', 'approved_plan_count')
    def _compute_baseline_count(self):
        """Baseline Count = active employee count + approved_plan_count."""
        for rec in self:
            if rec.operating_unit_id and rec.job_position_id:
                act = rec.active_employee_count or 0
                plan = rec.approved_plan_count or 0
                rec.baseline_count = act + plan
            else:
                rec.baseline_count = 0

    @api.depends('operating_unit_id', 'job_position_id')
    def _compute_approved_plan_count(self):
        PlanLine = self.env['pbms.plan.category.line'] if 'pbms.plan.category.line' in self.env else None
        Cycle = self.env['pbms.planning.cycle'] if 'pbms.planning.cycle' in self.env else None
        for rec in self:
            if PlanLine is not None and rec.operating_unit_id and rec.job_position_id:
                cycle_domain = [
                    ('line_type', '=', 'manpower'),
                    ('org_unit_id', '=', rec.operating_unit_id.id),
                    ('job_id', '=', rec.job_position_id.id),
                ]
                active_cycle = False
                if Cycle is not None:
                    active_cycle = Cycle.search([('active', '=', True)], order='id desc', limit=1)
                if active_cycle:
                    cycle_domain.append(('cycle_id', '=', active_cycle.id))

                lines = PlanLine.search(cycle_domain)
                if not lines and active_cycle:
                    lines = PlanLine.search([
                        ('line_type', '=', 'manpower'),
                        ('org_unit_id', '=', rec.operating_unit_id.id),
                        ('job_id', '=', rec.job_position_id.id),
                    ])

                rec.approved_plan_count = int(sum(lines.mapped('display_approved_annual_total')) or 0)
                rec.plan_fulfillment_promotion = int(sum(lines.mapped('fulfillment_promotion')) or 0) if 'fulfillment_promotion' in PlanLine._fields else 0
                lat = int(sum(lines.mapped('fulfillment_lateral')) or 0) if 'fulfillment_lateral' in PlanLine._fields else 0
                trans = int(sum(lines.mapped('fulfillment_transfer')) or 0) if 'fulfillment_transfer' in PlanLine._fields else 0
                rec.plan_fulfillment_lateral = lat + trans if (lat + trans) > 0 else 0
                rec.plan_fulfillment_external = int(sum(lines.mapped('fulfillment_external')) or 0) if 'fulfillment_external' in PlanLine._fields else 0
            else:
                rec.approved_plan_count = 0
                rec.plan_fulfillment_promotion = 0
                rec.plan_fulfillment_lateral = 0
                rec.plan_fulfillment_external = 0

    @api.depends('baseline_count', 'approved_plan_count')
    def _compute_total_headcount(self):
        for rec in self:
            rec.total_headcount = rec.baseline_count or 0

    @api.depends('total_headcount', 'active_employee_count')
    def _compute_vacant_position_count(self):
        for rec in self:
            rec.vacant_position_count = (rec.total_headcount or 0) - (rec.active_employee_count or 0)

    def _recompute_all_counts(self):
        """Helper: recompute active, approved plan, baseline, total, and vacant counts for this recordset."""
        self._compute_active_employee_count()
        self._compute_approved_plan_count()
        self._compute_baseline_count()
        self._compute_total_headcount()
        self._compute_vacant_position_count()

    @api.constrains('operating_unit_id', 'job_position_id')
    def _check_unique_job_position(self):
        for rec in self:
            duplicate = self.search([
                ('id', '!=', rec.id),
                ('operating_unit_id', '=', rec.operating_unit_id.id),
                ('job_position_id', '=', rec.job_position_id.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "Job Position '%s' is already added for Work Unit '%s'."
                ) % (rec.job_position_id.display_name, rec.operating_unit_id.display_name))

    def unlink(self):
        raise UserError(_(
            "Job Position lines cannot be deleted. Please archive them instead."
        ))


class HrEmployeeJobPositionSync(models.Model):
    """Keeps operating.unit.job.position counts in sync whenever an
    employee's job, default operating unit, active state, or contract changes."""
    _inherit = 'hr.employee'

    def write(self, vals):
        if self.env.context.get('in_sync_job_position_counts'):
            return super().write(vals)

        # Collect previous states before write
        old_pairs = []
        for emp in self:
            old_job = emp.job_position.id if emp.job_position else False
            old_ou = emp.default_operating_unit_id.id if emp.default_operating_unit_id else False
            old_active = emp.active
            old_pairs.append((emp.id, old_job, old_ou, old_active))

        res = super().write(vals)

        if any(f in vals for f in ('job_position', 'default_operating_unit_id', 'active')):
            OUJobPosition = self.env['operating.unit.job.position']
            affected_job_ids = set()
            affected_ou_ids = set()

            for emp_id, old_job, old_ou, old_active in old_pairs:
                emp = self.browse(emp_id)
                new_job = emp.job_position.id if emp.job_position else False
                new_ou = emp.default_operating_unit_id.id if emp.default_operating_unit_id else False
                new_active = emp.active

                # Collect old and new (job, ou) for recomputation
                if old_job:
                    affected_job_ids.add(old_job)
                if new_job:
                    affected_job_ids.add(new_job)
                if old_ou:
                    affected_ou_ids.add(old_ou)
                if new_ou:
                    affected_ou_ids.add(new_ou)

                # Track movement if job or default OU changed
                if old_active and (old_job != new_job or old_ou != new_ou):
                    if old_job and old_ou:
                        former_lines = OUJobPosition.search([
                            ('job_position_id', '=', old_job),
                            ('operating_unit_id', '=', old_ou),
                        ])
                        if old_job != new_job:
                            for fl in former_lines:
                                fl.promotion_count = (fl.promotion_count or 0) + 1
                        else:
                            for fl in former_lines:
                                fl.lateral_count = (fl.lateral_count or 0) + 1

                # Track resignation / departure
                if old_active and not new_active:
                    if old_job and old_ou:
                        former_lines = OUJobPosition.search([
                            ('job_position_id', '=', old_job),
                            ('operating_unit_id', '=', old_ou),
                        ])
                        for fl in former_lines:
                            fl.resignation_count = (fl.resignation_count or 0) + 1

            if affected_job_ids and affected_ou_ids:
                lines = OUJobPosition.search([
                    ('job_position_id', 'in', list(affected_job_ids)),
                    ('operating_unit_id', 'in', list(affected_ou_ids)),
                ])
                ctx = {'in_sync_job_position_counts': True}
                lines.with_context(**ctx)._compute_baseline_count()
                lines.with_context(**ctx)._compute_active_employee_count()
                lines.with_context(**ctx)._compute_total_headcount()
                lines.with_context(**ctx)._compute_vacant_position_count()

        return res

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('in_sync_job_position_counts'):
            return super().create(vals_list)
        records = super().create(vals_list)
        records.with_context(in_sync_job_position_counts=True)._sync_job_position_counts()
        return records

    def _sync_job_position_counts(self):
        OUJobPosition = self.env['operating.unit.job.position']
        job_ids = self.mapped('job_position').ids
        ou_ids = self.mapped('default_operating_unit_id').ids
        if job_ids and ou_ids:
            lines = OUJobPosition.search([
                ('job_position_id', 'in', job_ids),
                ('operating_unit_id', 'in', ou_ids),
            ])
            lines._compute_baseline_count()
            lines._compute_active_employee_count()
            lines._compute_total_headcount()
            lines._compute_vacant_position_count()


class HrVersionBaselineSync(models.Model):
    """Triggers baseline_count recomputation on operating.unit.job.position
    whenever a contract (hr.version) changes its state or operating_unit_id
    (e.g. probation → open, open → expired/cancelled, new contract activated)."""
    _inherit = 'hr.version'

    def write(self, vals):
        if not any(f in vals for f in ('state', 'operating_unit_id')):
            return super().write(vals)

        # Capture affected (job_position_id, operating_unit_id) pairs before write
        affected_pairs = set()
        for version in self:
            emp = version.employee_id
            if emp and emp.active and emp.job_position and emp.default_operating_unit_id:
                # Old contract's operating_unit_id
                if version.operating_unit_id:
                    affected_pairs.add((emp.job_position.id, version.operating_unit_id.id))
                # Also the employee's default OU (in case they differ)
                affected_pairs.add((emp.job_position.id, emp.default_operating_unit_id.id))

        res = super().write(vals)

        # After write: also pick up the new operating_unit_id if it changed
        for version in self:
            emp = version.employee_id
            if emp and emp.active and emp.job_position and version.operating_unit_id:
                affected_pairs.add((emp.job_position.id, version.operating_unit_id.id))

        if affected_pairs:
            OUJobPosition = self.env['operating.unit.job.position']
            for job_id, ou_id in affected_pairs:
                lines = OUJobPosition.search([
                    ('job_position_id', '=', job_id),
                    ('operating_unit_id', '=', ou_id),
                ])
                if lines:
                    lines._compute_baseline_count()
                    lines._compute_total_headcount()
                    lines._compute_vacant_position_count()

        return res
