# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models, _


class CompetencyDashboardSnapshot(models.Model):
    """Stored periodic snapshot for cycle-over-cycle trend analytics."""
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
        """Cron: calculate and store trend snapshots for all active open cycles."""
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

    @api.model
    def _cron_send_scheduled_competency_reports(self):
        """Cron: generate and email the organizational capability report to admins and supervisors."""
        import logging
        _logger = logging.getLogger(__name__)

        admin_group = self.env.ref('competency_management.group_competency_admin', raise_if_not_found=False)
        supervisor_group = self.env.ref('competency_management.group_competency_supervisor', raise_if_not_found=False)

        recipients = self.env['res.users']
        if admin_group:
            recipients |= getattr(admin_group, 'users_ids', getattr(admin_group, 'users', self.env['res.users']))
        if supervisor_group:
            recipients |= getattr(supervisor_group, 'users_ids', getattr(supervisor_group, 'users', self.env['res.users']))

        if not recipients:
            return False

        active_cycle = self.env['competency.assessment.cycle'].sudo().search([('state', '=', 'open')], limit=1)
        cycle_name = active_cycle.name if active_cycle else 'Current Framework Status'
        total_comps = self.env['competency.competency'].search_count([('status', '=', 'active')])
        total_asms = self.env['competency.assessment'].search_count([('cycle_id', '=', active_cycle.id)]) if active_cycle else 0

        lines = self.env['competency.assessment.line'].search([('cycle_id', '=', active_cycle.id)]) if active_cycle else self.env['competency.assessment.line']
        below_cnt = len(lines.filtered(lambda l: l.tna_measure == 'below'))
        meets_cnt = len(lines.filtered(lambda l: l.tna_measure == 'meets'))
        exceeds_cnt = len(lines.filtered(lambda l: l.tna_measure == 'exceeds'))

        # Generate PDF report attachment
        pdf_attachment = False
        if active_cycle:
            try:
                report_wiz = self.env['competency.report.wizard'].create({
                    'cycle_id': active_cycle.id,
                    'report_type': 'org_capability',
                    'pillar': 'all',
                })
                pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf('competency_management.action_report_competency_org_capability', [report_wiz.id])
                if pdf_content:
                    pdf_attachment = self.env['ir.attachment'].create({
                        'name': 'Organizational_Capability_Report_%s.pdf' % active_cycle.name,
                        'type': 'binary',
                        'datas': base64.b64encode(pdf_content),
                        'res_model': 'competency.dashboard.snapshot',
                        'mimetype': 'application/pdf',
                    })
            except Exception as e:
                _logger.warning("Failed to render QWeb PDF report attachment for cron: %s", str(e))

        sent_count = 0
        for user in recipients:
            if not user.email:
                continue
            try:
                body = _("""
                <div style="font-family: Arial, sans-serif; color: #1d2b32; line-height: 1.5;">
                    <div style="background-color: #541718; color: #FFFFFF; padding: 16px 20px; border-radius: 6px; margin-bottom: 16px;">
                        <h2 style="margin: 0; font-size: 20px;">Bunna Bank S.C. — Scheduled Talent Capability &amp; TNA Report</h2>
                        <div style="font-size: 12px; color: #c17540; margin-top: 4px;">Cycle: %s</div>
                    </div>
                    <p>Hello <b>%s</b>,</p>
                    <p>Here is your scheduled competency capability and TNA assessment summary:</p>
                    <table style="width: 100%%; border-collapse: collapse; border: 1px solid #ddd; font-size: 13px; margin-bottom: 16px;">
                        <tr style="background-color: #f4f6f7;"><th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Metric</th><th style="padding: 8px; text-align: right; border: 1px solid #ddd;">Value</th></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">Framework Active Competencies</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd;"><b>%s</b></td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">Assessed Employees in Cycle</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd;"><b>%s</b></td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">Underqualified (Training Needed) Lines</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd; color: #541718;"><b>%s</b></td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">Fit / Qualified Lines</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd; color: #726732;"><b>%s</b></td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">Overqualified Lines</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd; color: #1d2b32;"><b>%s</b></td></tr>
                    </table>
                    <p>The full <b>Organizational Capability &amp; TNA PDF Report</b> is attached to this email. Log in to the Bunna Bank ERP Portal to view interactive gap analytics.</p>
                </div>
                """) % (cycle_name, user.name, total_comps, total_asms, below_cnt, meets_cnt, exceeds_cnt)

                mail_values = {
                    'subject': _('Scheduled Competency & TNA Report — %s') % cycle_name,
                    'body_html': body,
                    'email_to': user.email,
                    'attachment_ids': [(4, pdf_attachment.id)] if pdf_attachment else [],
                }
                self.env['mail.mail'].sudo().create(mail_values).send()
                sent_count += 1
            except Exception as e:
                _logger.warning("Failed to send scheduled competency email report to %s (%s): %s", user.name, user.email, str(e))

        return sent_count
