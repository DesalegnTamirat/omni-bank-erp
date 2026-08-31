# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class CompetencyDashboardSnapshot(models.Model):
    """Stored snapshot model for cycle-over-cycle trend analytics (FR-RPT-010)."""
    _name = 'competency.dashboard.snapshot'
    _description = 'Competency Dashboard Cycle Snapshot'
    _order = 'snapshot_date desc, cycle_id desc, department_id asc'

    name = fields.Char(string='Snapshot Reference', compute='_compute_name', store=True)
    snapshot_date = fields.Date(string='Snapshot Date', default=fields.Date.context_today, required=True, index=True)
    cycle_id = fields.Many2one('competency.assessment.cycle', string='Assessment Cycle', required=True, ondelete='cascade', index=True)
    department_id = fields.Many2one('hr.department', string='Department', ondelete='cascade', index=True)
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit', ondelete='cascade', index=True)
    pillar = fields.Selection([
        ('core', 'Core'),
        ('leadership', 'Leadership'),
        ('technical', 'Technical'),
        ('all', 'All Pillars'),
    ], string='Pillar', default='all', required=True, index=True)

    total_assessed = fields.Integer(string='Total Assessed Employees', default=0)
    avg_gap = fields.Float(string='Average Competency Gap', digits=(16, 2), default=0.0)
    below_count = fields.Integer(string='Underqualified (Below Target)', default=0)
    meets_count = fields.Integer(string='Fit / Qualified (Meets Target)', default=0)
    exceeds_count = fields.Integer(string='Overqualified (Exceeds Target)', default=0)

    @api.depends('cycle_id', 'department_id', 'pillar', 'snapshot_date')
    def _compute_name(self):
        for rec in self:
            c_name = rec.cycle_id.name if rec.cycle_id else 'General'
            d_name = rec.department_id.name if rec.department_id else 'Bank-Wide'
            p_name = dict(rec._fields['pillar'].selection).get(rec.pillar, rec.pillar)
            rec.name = f"{c_name} — {d_name} ({p_name}) [{rec.snapshot_date}]"

    @api.model
    def _cron_take_dashboard_snapshot(self):
        """Cron method to calculate and store trend snapshots across active cycles (FR-RPT-010)."""
        # Guard 1: Only snapshot active open cycles
        cycles = self.env['competency.assessment.cycle'].search([('state', '=', 'open')])
        departments = self.env['hr.department'].search([])
        today = fields.Date.context_today(self)

        snapshot_count = 0
        for cycle in cycles:
            # 1. Bank-Wide General Snapshot
            for pillar_val in ['all', 'core', 'leadership', 'technical']:
                # Guard 2: Prevent duplicate snapshots for same date, cycle, department, pillar
                existing = self.search([
                    ('cycle_id', '=', cycle.id),
                    ('department_id', '=', False),
                    ('pillar', '=', pillar_val),
                    ('snapshot_date', '=', today)
                ], limit=1)
                if existing:
                    continue

                lines = self.env['competency.assessment.line'].search([
                    ('cycle_id', '=', cycle.id),
                    ('pillar', '=', pillar_val) if pillar_val != 'all' else (1, '=', 1)
                ])
                gaps = [l.gap for l in lines if l.gap is not None]
                avg_g = round(sum(gaps) / len(gaps), 2) if gaps else 0.0

                self.create({
                    'snapshot_date': today,
                    'cycle_id': cycle.id,
                    'department_id': False,
                    'pillar': pillar_val,
                    'total_assessed': len(lines.mapped('assessment_id')),
                    'avg_gap': avg_g,
                    'below_count': len(lines.filtered(lambda l: l.tna_measure == 'below')),
                    'meets_count': len(lines.filtered(lambda l: l.tna_measure == 'meets')),
                    'exceeds_count': len(lines.filtered(lambda l: l.tna_measure == 'exceeds')),
                })
                snapshot_count += 1

            # 2. Per Department Snapshot
            for dept in departments:
                for pillar_val in ['all', 'core', 'leadership', 'technical']:
                    existing_dept = self.search([
                        ('cycle_id', '=', cycle.id),
                        ('department_id', '=', dept.id),
                        ('pillar', '=', pillar_val),
                        ('snapshot_date', '=', today)
                    ], limit=1)
                    if existing_dept:
                        continue

                    lines = self.env['competency.assessment.line'].search([
                        ('cycle_id', '=', cycle.id),
                        ('department_id', '=', dept.id),
                        ('pillar', '=', pillar_val) if pillar_val != 'all' else (1, '=', 1)
                    ])
                    if not lines:
                        continue
                    gaps = [l.gap for l in lines if l.gap is not None]
                    avg_g = round(sum(gaps) / len(gaps), 2) if gaps else 0.0

                    self.create({
                        'snapshot_date': today,
                        'cycle_id': cycle.id,
                        'department_id': dept.id,
                        'operating_unit_id': dept.operating_unit_id.id if hasattr(dept, 'operating_unit_id') else False,
                        'pillar': pillar_val,
                        'total_assessed': len(lines.mapped('assessment_id')),
                        'avg_gap': avg_g,
                        'below_count': len(lines.filtered(lambda l: l.tna_measure == 'below')),
                        'meets_count': len(lines.filtered(lambda l: l.tna_measure == 'meets')),
                        'exceeds_count': len(lines.filtered(lambda l: l.tna_measure == 'exceeds')),
                    })
                    snapshot_count += 1

        return snapshot_count
