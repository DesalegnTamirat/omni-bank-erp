# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PerformanceJobTemplate(models.Model):
    _name = 'performance.job.template'
    _description = 'Job Position Scorecard Template'
    _order = 'operating_unit_id, job_id'

    name = fields.Char(string='Template Name', compute='_compute_name', store=True)
    operating_unit_id = fields.Many2one(
        'operating.unit', string='Work Unit', required=True, index=True
    )
    work_unit_type = fields.Selection(
        related='operating_unit_id.work_unit_type',
        string='Work Unit Type',
        store=True,
        readonly=True,
    )
    is_branch_unit = fields.Boolean(
        string='Is Branch Unit',
        compute='_compute_is_branch_unit',
        store=True,
        help="If True, this template will automatically apply to all other branches with the same Job Position.",
    )
    job_id = fields.Many2one(
        'hr.job', string='Job Position', required=True, index=True
    )
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        'performance.job.template.line', 'template_id', string='Scorecard Lines', copy=True
    )
    total_weight = fields.Float(
        string='Total Weight (%)', compute='_compute_total_weight', store=True, digits=(5, 2)
    )
    weight_status = fields.Selection([
        ('complete', 'Complete (100%)'),
        ('incomplete', 'Incomplete (<100%)'),
        ('exceeded', 'Exceeded (>100%)'),
    ], string='Weight Status', compute='_compute_weight_status', store=True)

    line_count = fields.Integer(compute='_compute_line_count', string='KPI Count')
    perspective_summary = fields.Char(compute='_compute_perspective_summary', string='Perspectives')

    _unique_template_per_job = models.Constraint(
        'unique(operating_unit_id, job_id)',
        'A Scorecard Template already exists for this Job Position in this Work Unit.',
    )

    @api.depends('operating_unit_id', 'job_id')
    def _compute_name(self):
        for rec in self:
            unit_name = rec.operating_unit_id.name if rec.operating_unit_id else ''
            job_name = rec.job_id.name if rec.job_id else ''
            if unit_name and job_name:
                rec.name = f"{unit_name} - {job_name}"
            elif job_name:
                rec.name = job_name
            else:
                rec.name = "New Position Scorecard"

    @api.depends('operating_unit_id.work_unit_type')
    def _compute_is_branch_unit(self):
        for rec in self:
            unit = rec.operating_unit_id
            rec.is_branch_unit = bool(
                unit and hasattr(unit, 'work_unit_type') and unit.work_unit_type in ('branch', 'sub_branch', 'service_center')
            )

    @api.depends('line_ids.weight')
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = sum(rec.line_ids.mapped('weight'))

    @api.depends('total_weight')
    def _compute_weight_status(self):
        for rec in self:
            tw = round(rec.total_weight, 2)
            if tw == 100.0:
                rec.weight_status = 'complete'
            elif tw > 100.0:
                rec.weight_status = 'exceeded'
            else:
                rec.weight_status = 'incomplete'

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends('line_ids.perspective_id')
    def _compute_perspective_summary(self):
        for rec in self:
            names = [p.name for p in rec.line_ids.mapped('perspective_id') if p.name]
            rec.perspective_summary = ', '.join(dict.fromkeys(names)) if names else 'None'

    def _sync_to_job_measures(self):
        """Synchronize template lines to performance.job.objective and performance.job.measure
        so that all scorecards and wizards read the updated Job Position Measures.
        """
        ctx = dict(self.env.context, skip_percent_constrain=True)
        JobObjective = self.env['performance.job.objective'].sudo().with_context(ctx)
        JobMeasure = self.env['performance.job.measure'].sudo().with_context(ctx)
        T3Line = self.env['t3.scorecard.line'].sudo().with_context(ctx)
        T3AppraisalLine = self.env['t3.appraisal.line'].sudo().with_context(ctx)

        for template in self:
            if not template.operating_unit_id or not template.job_id:
                continue

            active_measure_ids = set()

            for line in template.line_ids:
                if not line.parent_measure_id:
                    continue

                parent_m = line.parent_measure_id
                kpi_name = (parent_m.kpi or parent_m.name or line.name or 'KPI').strip()
                job_measure_name = (line.name or parent_m.name).strip()

                # Find or create job objective
                job_obj = JobObjective.search([
                    ('operating_unit_id', '=', template.operating_unit_id.id),
                    ('job_id', '=', template.job_id.id),
                    ('parent_measure_id', '=', parent_m.id),
                ], limit=1)

                if not job_obj:
                    job_obj = JobObjective.create({
                        'operating_unit_id': template.operating_unit_id.id,
                        'job_id': template.job_id.id,
                        'name': kpi_name,
                        'parent_measure_id': parent_m.id,
                        'active': template.active,
                    })
                else:
                    if job_obj.name != kpi_name or job_obj.active != template.active:
                        job_obj.write({
                            'name': kpi_name,
                            'active': template.active,
                        })

                # Sync Job Position Measure (Dedicated 1-to-1 measure per template line)
                measure = False
                if line.job_measure_id and line.job_measure_id.exists():
                    measure = line.job_measure_id
                    measure.write({
                        'name': job_measure_name,
                        'weight': line.weight,
                        'target_type': line.target_type,
                        'job_objective_id': job_obj.id,
                        'active': template.active,
                    })
                else:
                    # Check if there is an unlinked measure that is not yet claimed by another line in this sync
                    existing_m = JobMeasure.search([
                        ('job_objective_id', '=', job_obj.id),
                        ('name', '=', job_measure_name),
                        ('id', 'not in', list(active_measure_ids)),
                    ], limit=1)
                    if existing_m:
                        existing_m.write({
                            'weight': line.weight,
                            'target_type': line.target_type,
                            'active': template.active,
                        })
                        measure = existing_m
                    else:
                        measure = JobMeasure.create({
                            'job_objective_id': job_obj.id,
                            'name': job_measure_name,
                            'weight': line.weight,
                            'target_type': line.target_type,
                            'active': template.active,
                        })
                    line.job_measure_id = measure.id

                active_measure_ids.add(measure.id)

            # Safely cleanup or archive removed measures for this position
            all_existing_measures = JobMeasure.search([
                ('operating_unit_id', '=', template.operating_unit_id.id),
                ('job_id', '=', template.job_id.id),
            ])
            for old_m in all_existing_measures:
                if old_m.id not in active_measure_ids:
                    is_used = (
                        T3Line.search_count([('job_measure_id', '=', old_m.id)]) > 0
                        or T3AppraisalLine.search_count([('job_measure_id', '=', old_m.id)]) > 0
                    )
                    if is_used:
                        old_m.write({'active': False})
                    else:
                        old_obj = old_m.job_objective_id
                        old_m.unlink()
                        if old_obj and not old_obj.measure_ids:
                            old_obj.unlink()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_to_job_measures()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._sync_to_job_measures()
        return res

    def unlink(self):
        JobMeasure = self.env['performance.job.measure'].sudo()
        T3Line = self.env['t3.scorecard.line'].sudo()
        T3AppraisalLine = self.env['t3.appraisal.line'].sudo()

        for template in self:
            measures = JobMeasure.search([
                ('operating_unit_id', '=', template.operating_unit_id.id),
                ('job_id', '=', template.job_id.id),
            ])
            for m in measures:
                is_used = (
                    T3Line.search_count([('job_measure_id', '=', m.id)]) > 0
                    or T3AppraisalLine.search_count([('job_measure_id', '=', m.id)]) > 0
                )
                if is_used:
                    m.write({'active': False})
                else:
                    obj = m.job_objective_id
                    m.unlink()
                    if obj and not obj.measure_ids:
                        obj.unlink()

        return super().unlink()

    @api.model
    def action_import_from_existing_kpis(self):
        """Build templates from any existing standalone performance.job.objective records."""
        JobObjective = self.env['performance.job.objective'].search([])
        pairs = set((o.operating_unit_id.id, o.job_id.id) for o in JobObjective if o.operating_unit_id and o.job_id)

        created_templates = self.browse()
        for unit_id, job_id in pairs:
            template = self.search([
                ('operating_unit_id', '=', unit_id),
                ('job_id', '=', job_id),
            ], limit=1)
            if not template:
                template = self.create({
                    'operating_unit_id': unit_id,
                    'job_id': job_id,
                })
                created_templates |= template

            existing_line_measure_ids = set(template.line_ids.mapped('job_measure_id').ids)
            objs = JobObjective.search([
                ('operating_unit_id', '=', unit_id),
                ('job_id', '=', job_id),
            ])
            lines_to_create = []
            for obj in objs:
                for m in obj.measure_ids:
                    if m.id not in existing_line_measure_ids:
                        lines_to_create.append({
                            'template_id': template.id,
                            'parent_measure_id': obj.parent_measure_id.id,
                            'name': m.name,
                            'weight': m.weight,
                            'target_type': m.target_type,
                            'job_measure_id': m.id,
                        })
            if lines_to_create:
                self.env['performance.job.template.line'].create(lines_to_create)

        return True


class PerformanceJobTemplateLine(models.Model):
    _name = 'performance.job.template.line'
    _description = 'Job Position Scorecard Template Line'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one(
        'performance.job.template', string='Scorecard Template', required=True, ondelete='cascade', index=True
    )
    operating_unit_id = fields.Many2one(
        'operating.unit', related='template_id.operating_unit_id', store=True, readonly=True
    )
    job_id = fields.Many2one(
        'hr.job', related='template_id.job_id', store=True, readonly=True
    )

    parent_measure_id = fields.Many2one(
        'performance.measure',
        string='Operating Unit Measure',
        required=True,
        domain="[('objective_id.employee_operating_unit_id', '=', operating_unit_id)]",
        help="Select the Operating Unit (Tier 2) Measure to cascade from. Perspective and Strategic Objective will automatically populate."
    )
    parent_objective_id = fields.Many2one(
        'performance.objective',
        related='parent_measure_id.objective_id',
        store=True,
        readonly=True,
        string='Strategic Objective',
    )
    perspective_id = fields.Many2one(
        'performance.perspective',
        related='parent_measure_id.objective_id.perspective_id',
        store=True,
        readonly=True,
        string='Perspective',
    )
    perspective_name = fields.Char(
        related='perspective_id.name',
        store=True,
        readonly=True,
    )

    name = fields.Char(
        string='Job Position Measure',
        required=True,
        placeholder='Type Job Position Measurement here...',
        help='The specific Tier 3 measurement for this Job Position that will appear on the employee scorecard.'
    )

    weight = fields.Float(
        string='Weight (%)',
        required=True,
        digits=(5, 2),
        default=0.0
    )
    target_type = fields.Selection([
        ('number', 'Number'),
        ('percent', 'Percent'),
        ('expense', 'Expense'),
        ('hours', 'Hours'),
        ('days', 'Days'),
        ('text', 'Text'),
    ], string='Target Type', default='percent', required=True)

    job_measure_id = fields.Many2one(
        'performance.job.measure', string='Linked Measure', ondelete='set null'
    )

    @api.onchange('parent_measure_id')
    def _onchange_parent_measure_id(self):
        if self.parent_measure_id:
            if not self.target_type or self.target_type == 'number':
                self.target_type = self.parent_measure_id.target_type or 'percent'

    @api.constrains('weight')
    def _check_weight(self):
        for rec in self:
            if rec.weight <= 0 or rec.weight > 100:
                raise ValidationError('Weight must be greater than 0 and no more than 100.')
