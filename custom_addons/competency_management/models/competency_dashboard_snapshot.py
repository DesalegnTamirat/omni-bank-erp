# -*- coding: utf-8 -*-
import base64
import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


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
    def _cron_take_dashboard_snapshot(self, cycle_ids=None):
        """Optimized: calculate and store trend snapshots for active/closed cycles using high-speed SQL aggregation."""
        today = fields.Date.context_today(self)
        
        if cycle_ids:
            cycles = self.env['competency.assessment.cycle'].browse(cycle_ids)
        else:
            cycles = self.env['competency.assessment.cycle'].search([('state', 'in', ('open', 'closed'))])

        if not cycles:
            return 0

        snapshot_count = 0
        c_ids = tuple(cycles.ids)

        query = """
            SELECT 
                a.cycle_id,
                e.department_id,
                COALESCE(c.pillar, 'all') AS pillar_val,
                COUNT(DISTINCT a.id) AS total_assessed,
                ROUND(AVG(l.gap)::numeric, 2) AS avg_gap,
                COUNT(CASE WHEN l.tna_measure = 'below' THEN 1 END) AS below_cnt,
                COUNT(CASE WHEN l.tna_measure = 'meets' THEN 1 END) AS meets_cnt,
                COUNT(CASE WHEN l.tna_measure = 'exceeds' THEN 1 END) AS exceeds_cnt
            FROM competency_assessment_line l
            JOIN competency_assessment a ON a.id = l.assessment_id
            JOIN hr_employee e ON e.id = a.employee_id
            LEFT JOIN competency_competency c ON c.id = l.competency_id
            WHERE a.cycle_id IN %s
            GROUP BY GROUPING SETS (
                (a.cycle_id, COALESCE(c.pillar, 'all')),
                (a.cycle_id, e.department_id, COALESCE(c.pillar, 'all'))
            );
        """
        self.env.cr.execute(query, (c_ids,))
        rows = self.env.cr.dictfetchall()

        if not rows:
            return 0

        # Pre-fetch existing snapshots for today in a single query
        existing_records = self.search([
            ('cycle_id', 'in', c_ids),
            ('snapshot_date', '=', today),
        ])
        existing_keys = {(s.cycle_id.id, s.department_id.id, s.pillar) for s in existing_records}

        # Pre-fetch departments to resolve operating units
        dept_ids = list({r['department_id'] for r in rows if r.get('department_id')})
        depts = self.env['hr.department'].browse(dept_ids) if dept_ids else self.env['hr.department']
        dept_ou_map = {d.id: getattr(d, 'operating_unit_id', False).id for d in depts if hasattr(d, 'operating_unit_id') and d.operating_unit_id}

        vals_list = []
        for row in rows:
            cy_id = row['cycle_id']
            dept_id = row['department_id']
            pillar_val = row['pillar_val'] if row['pillar_val'] in ('core', 'leadership', 'technical') else 'all'

            if (cy_id, dept_id, pillar_val) in existing_keys:
                continue

            existing_keys.add((cy_id, dept_id, pillar_val))
            ou_id = dept_ou_map.get(dept_id, False)

            vals_list.append({
                'snapshot_date': today,
                'cycle_id': cy_id,
                'department_id': dept_id,
                'operating_unit_id': ou_id,
                'pillar': pillar_val,
                'total_assessed': row['total_assessed'] or 0,
                'avg_gap': float(row['avg_gap'] or 0.0),
                'below_count': row['below_cnt'] or 0,
                'meets_count': row['meets_cnt'] or 0,
                'exceeds_count': row['exceeds_cnt'] or 0,
            })

        if vals_list:
            self.create(vals_list)
        return len(vals_list)

    @api.model
    def _cron_send_scheduled_competency_reports(self):
        """Cron: generate and email the organizational capability report to admins and supervisors."""
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
