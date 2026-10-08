# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models, _

class PmProjectProgressUpdate(models.Model):
    _name = 'pm.project.progress.update'
    _description = 'Project Periodic Progress Update'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'report_date desc, id desc'

    name = fields.Char(string='Report Title', required=True, tracking=True)
    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade', tracking=True)
    report_type = fields.Selection([
        ('weekly', 'Weekly Update'),
        ('bi_weekly', 'Bi-Weekly Update'),
        ('monthly', 'Monthly Update'),
        ('ad_hoc', 'Ad-Hoc / Exception Brief')
    ], string='Report Frequency', default='weekly', required=True, tracking=True)
    report_date = fields.Date(string='Report Date', default=fields.Date.context_today, required=True, tracking=True)
    date_from = fields.Date(string='Period From')
    date_to = fields.Date(string='Period To')

    # Executive Snapshot Metrics (Stored & Immutable upon submit)
    manager_id = fields.Many2one('res.users', string='Project Manager', compute='_compute_manager_id', store=True, readonly=False)
    project_status = fields.Selection([
        ('draft', 'Initiation / Draft'),
        ('active', 'Active / In Progress'),
        ('on_hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Project Status', store=True)
    health_state = fields.Selection([
        ('initiation', 'Initiation'),
        ('planning', 'Planning'),
        ('on_track', 'On Track'),
        ('at_risk', 'At Risk'),
        ('off_track', 'Off Track'),
        ('on_hold', 'On Hold'),
        ('done', 'Done')
    ], string='Health Status', store=True)
    progress_rate = fields.Float(string='Current Progress (%)', store=True)
    milestones_summary = fields.Char(string='Milestones (Reached/Total)', store=True)
    deliverables_summary = fields.Char(string='Deliverables (Reached/Total)', store=True)
    project_date_start = fields.Date(string='Project Start', store=True)
    project_date_end = fields.Date(string='Project End', store=True)

    # 7 Sections Under Project Update
    # 1. Project Information (Managed with 1-column lines)
    info_line_ids = fields.One2many(
        'pm.project.update.info.line', 'update_id',
        string='Project Information Lines'
    )

    # 2. Executive Summary (Managed as clean text area)
    executive_summary = fields.Text(
        string='Executive Summary',
        help="High-level narrative of project trajectory, key accomplishments, and current status."
    )

    # 3. Overall Project Status (Managed with parameter lines)
    status_line_ids = fields.One2many(
        'pm.project.update.status.line', 'update_id',
        string='Overall Project Status Lines'
    )

    # 4. Major Activities / Deliverables Reached (Managed with lines)
    deliverable_line_ids = fields.One2many(
        'pm.project.update.deliverable.line', 'update_id',
        string='Major Activities / Deliverables Reached'
    )

    # 5. Task / Activities Completed (Managed with lines)
    task_line_ids = fields.One2many(
        'pm.project.update.task.line', 'update_id',
        string='Task / Activities Completed'
    )

    # 6. Milestones (Managed with lines, green/red delay indicators)
    milestone_line_ids = fields.One2many(
        'pm.project.update.milestone.line', 'update_id',
        string='Milestones'
    )

    # 7. Remark (Managed as clean text area)
    remark = fields.Text(
        string='Remark',
        help="Overall project progress remarks, key decisions needed, or management follow-up."
    )

    # Primary Governance Tabs (Word Doc Paragraph 9-13)
    risk_line_ids = fields.One2many(
        'pm.project.update.risk.line', 'update_id',
        string='Identified Risks'
    )
    challenge_line_ids = fields.One2many(
        'pm.project.update.challenge.line', 'update_id',
        string='Challenges'
    )
    issue_line_ids = fields.One2many(
        'pm.project.update.issue.line', 'update_id',
        string='Issues'
    )

    # Computed One-Page Consolidated Preview for Reading / Executive Sharing
    consolidated_preview_html = fields.Html(
        string='Consolidated One-Page Preview',
        compute='_compute_consolidated_preview_html',
        help='Dynamically rendered executive one-page briefing incorporating all 7 sections and governance.'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted / Shared'),
        ('reviewed', 'Reviewed by Stakeholders')
    ], string='Status', default='draft', tracking=True)

    @api.depends('project_id')
    def _compute_manager_id(self):
        for rec in self:
            if rec.project_id and not rec.manager_id:
                rec.manager_id = rec.project_id.manager_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('project_id'):
                p = self.env['pm.project'].browse(vals['project_id'])
                if not vals.get('name'):
                    vals['name'] = f"Progress update as on {fields.Date.today().strftime('%d-%m-%Y')}"
                if not vals.get('date_from'):
                    vals['date_from'] = fields.Date.today().replace(day=1)
                if not vals.get('date_to'):
                    vals['date_to'] = fields.Date.today()
                if 'manager_id' not in vals:
                    vals['manager_id'] = p.manager_id.id if p.manager_id else False
                if 'project_status' not in vals:
                    vals['project_status'] = p.status
                if 'health_state' not in vals:
                    vals['health_state'] = p.health_state
                if 'progress_rate' not in vals:
                    vals['progress_rate'] = p.progress_rate
                if 'project_date_start' not in vals:
                    vals['project_date_start'] = p.date_start
                if 'project_date_end' not in vals:
                    vals['project_date_end'] = p.date_end
                if 'milestones_summary' not in vals:
                    m_total = len(p.milestone_ids)
                    m_reached = len(p.milestone_ids.filtered(lambda m: m.progress_rate >= 100.0 or m.state == 'completed'))
                    vals['milestones_summary'] = f"{m_reached} / {m_total} reached"
                if 'deliverables_summary' not in vals:
                    d_total = len(p.deliverable_ids)
                    d_reached = len(p.deliverable_ids.filtered(lambda d: d.progress_rate >= 100.0 or d.state == 'completed'))
                    vals['deliverables_summary'] = f"{d_reached} / {d_total} reached"

        records = super().create(vals_list)
        for rec in records:
            if not rec.info_line_ids and rec.project_id:
                rec._populate_lines_from_project(rec.project_id)
        return records

    @api.depends('info_line_ids', 'executive_summary', 'status_line_ids', 'deliverable_line_ids',
                 'task_line_ids', 'milestone_line_ids', 'remark', 'risk_line_ids', 'challenge_line_ids', 'issue_line_ids')
    def _compute_consolidated_preview_html(self):
        for rec in self:
            parts = ['<div style="font-family: inherit; font-size: 13.5px; line-height: 1.6; color: #212529; padding: 10px 15px;">']

            # 1. Project Information
            parts.append('<h4 style="font-weight: 700; color: #0d6efd; margin-top: 10px; margin-bottom: 8px; border-bottom: 2px solid #0d6efd; padding-bottom: 4px;">1. Project Information</h4>')
            if rec.info_line_ids:
                parts.append('<ul style="margin: 4px 0 12px 20px; padding: 0;">')
                for line in rec.info_line_ids:
                    parts.append(f'<li style="margin-bottom: 3px;">{line.name}</li>')
                parts.append('</ul>')
            else:
                parts.append('<p style="color: #6c757d; margin-left: 20px;"><em>No project information lines specified.</em></p>')

            # 2. Executive Summary
            parts.append('<h4 style="font-weight: 700; color: #0d6efd; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #0d6efd; padding-bottom: 4px;">2. Executive Summary</h4>')
            if rec.executive_summary:
                parts.append(f'<div style="background-color: #f8f9fa; border-left: 4px solid #0d6efd; padding: 8px 12px; margin-bottom: 12px;">{rec.executive_summary}</div>')
            else:
                parts.append('<p style="color: #6c757d; margin-left: 20px;"><em>No executive summary entered.</em></p>')

            # 3. Overall Project Status
            parts.append('<h4 style="font-weight: 700; color: #0d6efd; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #0d6efd; padding-bottom: 4px;">3. Overall Project Status</h4>')
            if rec.status_line_ids:
                parts.append('<table style="width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 13px;">')
                parts.append('<tr style="background-color: #e9ecef;"><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Parameter</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Status / Value</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Health</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Notes</th></tr>')
                for s in rec.status_line_ids:
                    color = "#198754" if s.health == 'on_track' else ("#ffc107" if s.health == 'at_risk' else ("#dc3545" if s.health == 'off_track' else "#6c757d"))
                    health_label = dict(s._fields['health'].selection).get(s.health, s.health or '')
                    parts.append(f'<tr><td style="border: 1px solid #dee2e6; padding: 6px 10px; font-weight: bold;">{s.name}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{s.value or ""}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px; color: {color}; font-weight: bold;">{health_label}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{s.notes or ""}</td></tr>')
                parts.append('</table>')
            else:
                parts.append('<p style="color: #6c757d; margin-left: 20px;"><em>No status parameters recorded.</em></p>')

            # 4. Major Activities / Deliverables Reached
            parts.append('<h4 style="font-weight: 700; color: #0d6efd; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #0d6efd; padding-bottom: 4px;">4. Major Activities / Deliverables Reached</h4>')
            if rec.deliverable_line_ids:
                parts.append('<table style="width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 13px;">')
                parts.append('<tr style="background-color: #e9ecef;"><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Deliverable Title</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Deadline</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Progress</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Status</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Remark</th></tr>')
                for d in rec.deliverable_line_ids:
                    parts.append(f'<tr><td style="border: 1px solid #dee2e6; padding: 6px 10px; font-weight: bold;">{d.name}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{d.date_deadline.strftime("%d/%m/%Y") if d.date_deadline else "N/A"}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{d.progress_rate:.0f}%</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{dict(d._fields["state"].selection).get(d.state, d.state or "")}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{d.notes or ""}</td></tr>')
                parts.append('</table>')
            else:
                parts.append('<p style="color: #6c757d; margin-left: 20px;"><em>No deliverables listed for this period.</em></p>')

            # 5. Task / Activities Completed
            parts.append('<h4 style="font-weight: 700; color: #0d6efd; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #0d6efd; padding-bottom: 4px;">5. Task / Activities Completed</h4>')
            if rec.task_line_ids:
                parts.append('<table style="width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 13px;">')
                parts.append('<tr style="background-color: #e9ecef;"><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Task Name</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Assignee</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Deadline</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Progress</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Status</th></tr>')
                for t in rec.task_line_ids:
                    parts.append(f'<tr><td style="border: 1px solid #dee2e6; padding: 6px 10px; font-weight: bold;">{t.name}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{t.user_id.name if t.user_id else "-"}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{t.date_deadline.strftime("%d/%m/%Y") if t.date_deadline else "N/A"}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{t.progress_rate:.0f}%</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{dict(t._fields["state"].selection).get(t.state, t.state or "")}</td></tr>')
                parts.append('</table>')
            else:
                parts.append('<p style="color: #6c757d; margin-left: 20px;"><em>No completed tasks recorded.</em></p>')

            # 6. Milestones
            parts.append('<h4 style="font-weight: 700; color: #0d6efd; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #0d6efd; padding-bottom: 4px;">6. Milestones</h4>')
            if rec.milestone_line_ids:
                parts.append('<ul style="margin: 4px 0 12px 20px; padding: 0; list-style-type: none;">')
                for m in rec.milestone_line_ids:
                    due_str = m.date_deadline.strftime('%m/%d/%Y') if m.date_deadline else "N/A"
                    reached_str = m.date_reached.strftime('%m/%d/%Y') if m.date_reached else (fields.Date.today().strftime('%m/%d/%Y') if m.is_reached else "Pending")
                    if m.is_reached:
                        color = "#dc3545" if m.delay_status == 'delayed' else "#198754"
                        parts.append(f'<li style="margin-bottom: 6px; font-size: 13.5px;">&#9633; <strong>{m.name}</strong> (due {due_str} - reached on <span style="color: {color}; font-weight: bold;">{reached_str}</span>)</li>')
                    else:
                        color = "#dc3545" if m.delay_status == 'overdue' else "#0d6efd"
                        parts.append(f'<li style="margin-bottom: 6px; font-size: 13.5px;">&#9633; {m.name} (due {due_str} - <span style="color: {color}; font-weight: bold;">{m.progress_rate:.0f}%</span>)</li>')
                parts.append('</ul>')
            else:
                parts.append('<p style="color: #6c757d; margin-left: 20px;"><em>No milestones logged.</em></p>')

            # 7. Governance: Identified Risks (Placed before Remark)
            if rec.risk_line_ids:
                parts.append('<h4 style="font-weight: 700; color: #dc3545; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #dc3545; padding-bottom: 4px;">7. Identified Risks</h4>')
                parts.append('<table style="width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 13px;">')
                parts.append('<tr style="background-color: #f8d7da;"><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Risk Description</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Category</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Severity</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Mitigation Strategy</th></tr>')
                for r in rec.risk_line_ids:
                    cat_name = dict(r._fields["category"].selection).get(r.category, r.category or "-")
                    sev_name = dict(r._fields["severity"].selection).get(r.severity, r.severity or "")
                    parts.append(f'<tr><td style="border: 1px solid #dee2e6; padding: 6px 10px; font-weight: bold;">{r.name}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{cat_name}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{sev_name}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{r.mitigation or "-"}</td></tr>')
                parts.append('</table>')
            else:
                parts.append('<h4 style="font-weight: 700; color: #dc3545; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #dc3545; padding-bottom: 4px;">7. Identified Risks</h4>')
                parts.append('<p style="color: #6c757d; margin-left: 20px;"><em>No major risks logged for this period.</em></p>')

            # 8. Governance: Challenges (Placed before Remark)
            if rec.challenge_line_ids:
                parts.append('<h4 style="font-weight: 700; color: #fd7e14; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #fd7e14; padding-bottom: 4px;">8. Challenges</h4>')
                parts.append('<table style="width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 13px;">')
                parts.append('<tr style="background-color: #ffe8cc;"><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Challenge Description</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Category</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Impact</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Action Plan</th></tr>')
                for c in rec.challenge_line_ids:
                    cat_name = dict(c._fields["category"].selection).get(c.category, c.category or "-")
                    parts.append(f'<tr><td style="border: 1px solid #dee2e6; padding: 6px 10px; font-weight: bold;">{c.name}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{cat_name}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{c.impact or "-"}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{c.action_plan or "-"}</td></tr>')
                parts.append('</table>')
            else:
                parts.append('<h4 style="font-weight: 700; color: #fd7e14; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #fd7e14; padding-bottom: 4px;">8. Challenges</h4>')
                parts.append('<p style="color: #6c757d; margin-left: 20px;"><em>No operational challenges reported for this period.</em></p>')

            # 9. Governance: Issues (Placed before Remark)
            if rec.issue_line_ids:
                parts.append('<h4 style="font-weight: 700; color: #d63384; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #d63384; padding-bottom: 4px;">9. Issues &amp; Decisions Needed</h4>')
                parts.append('<table style="width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 13px;">')
                parts.append('<tr style="background-color: #f8d7da;"><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Issue Description</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Severity</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Owner</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Decision Needed</th><th style="border: 1px solid #dee2e6; padding: 6px 10px; text-align: left;">Status</th></tr>')
                for i in rec.issue_line_ids:
                    sev_name = dict(i._fields["severity"].selection).get(i.severity, i.severity or "")
                    stat_name = dict(i._fields["status"].selection).get(i.status, i.status or "")
                    parts.append(f'<tr><td style="border: 1px solid #dee2e6; padding: 6px 10px; font-weight: bold;">{i.name}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{sev_name}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{i.owner_id.name if i.owner_id else "-"}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{i.decision_needed or "-"}</td><td style="border: 1px solid #dee2e6; padding: 6px 10px;">{stat_name}</td></tr>')
                parts.append('</table>')
            else:
                parts.append('<h4 style="font-weight: 700; color: #d63384; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #d63384; padding-bottom: 4px;">9. Issues &amp; Decisions Needed</h4>')
                parts.append('<p style="color: #6c757d; margin-left: 20px;"><em>No critical issues requiring executive escalation.</em></p>')

            # 10. Remark (Final concluding wrap-up)
            parts.append('<h4 style="font-weight: 700; color: #0d6efd; margin-top: 15px; margin-bottom: 8px; border-bottom: 2px solid #0d6efd; padding-bottom: 4px;">10. Remark</h4>')
            if rec.remark:
                parts.append(f'<div style="background-color: #f8f9fa; border-left: 4px solid #198754; padding: 8px 12px; margin-bottom: 12px;">{rec.remark}</div>')
            else:
                parts.append('<p style="color: #6c757d; margin-left: 20px;"><em>Project progress remark.</em></p>')

            parts.append('</div>')
            rec.consolidated_preview_html = Markup("".join(parts))

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if not self.project_id:
            return
        p = self.project_id
        if not self.name:
            self.name = f"Progress update as on {fields.Date.today().strftime('%d-%m-%Y')}"

        if not self.date_from:
            self.date_from = fields.Date.today().replace(day=1)
        if not self.date_to:
            self.date_to = fields.Date.today()

        self.manager_id = p.manager_id
        self.project_status = p.status
        self.health_state = p.health_state
        self.progress_rate = p.progress_rate
        self.project_date_start = p.date_start
        self.project_date_end = p.date_end

        m_total = len(p.milestone_ids)
        m_reached = len(p.milestone_ids.filtered(lambda m: m.progress_rate >= 100.0 or m.state == 'completed'))
        self.milestones_summary = f"{m_reached} / {m_total} reached"

        d_total = len(p.deliverable_ids)
        d_reached = len(p.deliverable_ids.filtered(lambda d: d.progress_rate >= 100.0 or d.state == 'completed'))
        self.deliverables_summary = f"{d_reached} / {d_total} reached"

        self._populate_lines_from_project(p)

    def action_refresh_from_project(self):
        self.ensure_one()
        if not self.project_id:
            return
        p = self.project_id
        self.manager_id = p.manager_id
        self.project_status = p.status
        self.health_state = p.health_state
        self.progress_rate = p.progress_rate
        self.project_date_start = p.date_start
        self.project_date_end = p.date_end

        m_total = len(p.milestone_ids)
        m_reached = len(p.milestone_ids.filtered(lambda m: m.progress_rate >= 100.0 or m.state == 'completed'))
        self.milestones_summary = f"{m_reached} / {m_total} reached"

        d_total = len(p.deliverable_ids)
        d_reached = len(p.deliverable_ids.filtered(lambda d: d.progress_rate >= 100.0 or d.state == 'completed'))
        self.deliverables_summary = f"{d_reached} / {d_total} reached"

        self._populate_lines_from_project(p, clear_existing=True)

    def _populate_lines_from_project(self, p, clear_existing=False):
        currency_symbol = p.currency_id.symbol if p.currency_id else "Br"
        budget_str = f"{currency_symbol} {p.estimated_cost:,.2f}" if p.estimated_cost else "Not Specified"
        start_str = p.date_start.strftime('%d/%m/%Y') if p.date_start else "N/A"
        end_str = p.date_end.strftime('%d/%m/%Y') if p.date_end else "N/A"
        schedule_str = f"{start_str} to {end_str}"
        risk_count = len(p.risk_ids)
        open_risks = len(p.risk_ids.filtered(lambda r: getattr(r, 'status', '') != 'closed'))
        risk_str = f"{open_risks} active / {risk_count} total risks" if risk_count else "No major risks logged"
        scope_str = dict(p._fields['status'].selection).get(p.status, p.status or 'Planning')
        health_dict = dict(p._fields['health_state'].selection) if 'health_state' in p._fields else {}
        health_str = health_dict.get(p.health_state, p.health_state or 'On Track')
        sponsor_str = p.lead_office_id.name if getattr(p, 'lead_office_id', False) else (p.customer_id.name if p.customer_id else 'Enterprise Banking')

        # 1. Project Information Lines (1 column)
        info_cmds = [(5, 0, 0)] if clear_existing else []
        if not self.info_line_ids or clear_existing:
            info_cmds.extend([
                (0, 0, {'name': f"line 1: Project Name: {p.name} ({p.code or 'N/A'})"}),
                (0, 0, {'name': f"line 2: Project Manager: {p.manager_id.name if p.manager_id else 'Unassigned'}"}),
                (0, 0, {'name': f"line 3: Timeline: {schedule_str}"}),
                (0, 0, {'name': f"line 4: Strategic Issue / Initiative: {p.initiative_id.name if p.initiative_id else 'Direct Corporate Alignment'}"}),
                (0, 0, {'name': f"line 5: Sponsor / Lead Office: {sponsor_str}"}),
            ])
            self.info_line_ids = info_cmds

        # 2. Executive Summary
        if not self.executive_summary or clear_existing:
            self.executive_summary = (
                f"How's the project going? Project execution is currently {health_str.upper()} with an overall progress "
                f"rate of {p.progress_rate:.1f}%. Major work packages are proceeding in accordance with the established schedule."
            )

        # 3. Overall Project Status Lines
        status_cmds = [(5, 0, 0)] if clear_existing else []
        if not self.status_line_ids or clear_existing:
            status_cmds.extend([
                (0, 0, {'name': 'Budget', 'value': budget_str, 'health': 'on_track', 'notes': 'Baselined cost tracking within approved limit'}),
                (0, 0, {'name': 'Scope', 'value': scope_str, 'health': 'on_track', 'notes': 'Scope baseline locked, change requests monitored'}),
                (0, 0, {'name': 'schedule', 'value': schedule_str, 'health': 'on_track' if p.health_state != 'off_track' else 'off_track', 'notes': 'Milestones tracking on agreed dates'}),
                (0, 0, {'name': 'Risk', 'value': risk_str, 'health': 'at_risk' if open_risks > 2 else 'on_track', 'notes': 'Periodic risk assessment completed'}),
                (0, 0, {'name': 'Overall progress', 'value': f"{p.progress_rate:.1f}%", 'health': 'on_track' if p.progress_rate > 50 else 'at_risk', 'notes': 'Weighted completion rate rollup'}),
            ])
            self.status_line_ids = status_cmds

        # 4. Major Activities / Deliverables Reached Lines
        deliv_cmds = [(5, 0, 0)] if clear_existing else []
        if not self.deliverable_line_ids or clear_existing:
            # Strictly load only reached / completed deliverables (100% or completed status)
            completed_delivs = p.deliverable_ids.filtered(lambda d: d.progress_rate >= 100.0 or d.state == 'completed')
            for d in completed_delivs:
                deliv_cmds.append((0, 0, {
                    'deliverable_id': d.id,
                    'name': d.name,
                    'date_deadline': d.date_deadline,
                    'progress_rate': d.progress_rate,
                    'state': 'completed',
                    'notes': 'Delivered and accepted',
                }))
            if deliv_cmds:
                self.deliverable_line_ids = deliv_cmds
            elif clear_existing:
                self.deliverable_line_ids = [(5, 0, 0)]

        # 5. Task / Activities Completed Lines (Period-filtered)
        task_cmds = [(5, 0, 0)] if clear_existing else []
        if not self.task_line_ids or clear_existing:
            # Strictly load only completed tasks (state == 'done' or progress_rate >= 100.0)
            completed_tasks = p.task_ids.filtered(lambda t: t.state in ('done', 'completed') or t.progress_rate >= 100.0)
            if self.date_from and self.date_to and completed_tasks:
                period_tasks = completed_tasks.filtered(lambda t: t.date_deadline and self.date_from <= t.date_deadline <= self.date_to)
                if period_tasks:
                    completed_tasks = period_tasks
            for t in completed_tasks:
                task_cmds.append((0, 0, {
                    'task_id': t.id,
                    'name': t.name,
                    'user_id': t.user_ids[0].id if t.user_ids else False,
                    'date_deadline': t.date_deadline,
                    'progress_rate': t.progress_rate,
                    'state': 'done',
                    'notes': 'Completed within schedule',
                }))
            if task_cmds:
                self.task_line_ids = task_cmds
            elif clear_existing:
                self.task_line_ids = [(5, 0, 0)]

        # 6. Milestones Lines
        milestone_cmds = [(5, 0, 0)] if clear_existing else []
        if not self.milestone_line_ids or clear_existing:
            for m in p.milestone_ids:
                is_reached = (m.progress_rate >= 100.0 or m.state == 'completed')
                reached_date = m.date_deadline if is_reached and m.date_deadline else (fields.Date.today() if is_reached else False)
                delay_status = 'pending'
                if is_reached:
                    if m.date_deadline and reached_date and reached_date > m.date_deadline:
                        delay_status = 'delayed'
                    else:
                        delay_status = 'on_time'
                else:
                    if m.date_deadline and m.date_deadline < fields.Date.today():
                        delay_status = 'overdue'
                    else:
                        delay_status = 'pending'

                milestone_cmds.append((0, 0, {
                    'milestone_id': m.id,
                    'name': m.name,
                    'date_deadline': m.date_deadline,
                    'date_reached': reached_date,
                    'is_reached': is_reached,
                    'delay_status': delay_status,
                    'progress_rate': m.progress_rate,
                    'status_note': "Completed on time" if delay_status == 'on_time' else ("Delayed milestone" if delay_status == 'delayed' else "In progress"),
                }))
            if milestone_cmds:
                self.milestone_line_ids = milestone_cmds

        # 7. Remark
        if not self.remark or clear_existing:
            self.remark = "Project progress remark: Execution is proceeding satisfactorily. No major blockers requiring executive escalation at this time."

        # Governance: Risks (with proper category mapping & score conversion)
        risk_cmds = [(5, 0, 0)] if clear_existing else []
        if not self.risk_line_ids or clear_existing:
            for r in p.risk_ids.filtered(lambda r: getattr(r, 'status', '') != 'closed'):
                cat_code = r.category if getattr(r, 'category', False) in ('technical', 'resource', 'schedule', 'budget', 'external', 'compliance') else 'operational'
                sev_score = getattr(r, 'severity', 1) or 1
                if sev_score >= 12:
                    sev_choice = 'critical'
                elif sev_score >= 9:
                    sev_choice = 'high'
                elif sev_score >= 4:
                    sev_choice = 'medium'
                else:
                    sev_choice = 'low'
                risk_cmds.append((0, 0, {
                    'risk_id': r.id,
                    'name': r.name,
                    'category': cat_code,
                    'severity': sev_choice,
                    'mitigation': r.mitigation or 'Ongoing monitoring and control',
                }))
            if risk_cmds:
                self.risk_line_ids = risk_cmds

        # Governance: Challenges (auto-populate blocked tasks as challenges)
        challenge_cmds = [(5, 0, 0)] if clear_existing else []
        if not self.challenge_line_ids or clear_existing:
            blocked_tasks = p.task_ids.filtered(lambda t: t.is_blocked and not t.is_closed)
            for bt in blocked_tasks:
                challenge_cmds.append((0, 0, {
                    'name': f"Operational block on '{bt.name}'",
                    'category': 'dependency',
                    'impact': f"Task progress halted ({int(bt.progress_rate)}%) due to blocking constraints.",
                    'action_plan': 'Expedite blocking dependency resolution and review resource availability.',
                }))
            if challenge_cmds:
                self.challenge_line_ids = challenge_cmds

        # Governance: Issues (auto-populate blocked tasks requiring management decisions)
        issue_cmds = [(5, 0, 0)] if clear_existing else []
        if not self.issue_line_ids or clear_existing:
            blocked_tasks = p.task_ids.filtered(lambda t: t.is_blocked and not t.is_closed)
            for bt in blocked_tasks:
                is_overdue = bt.date_deadline and bt.date_deadline < fields.Date.today()
                issue_cmds.append((0, 0, {
                    'name': f"Blocked Task: {bt.name}",
                    'severity': 'critical' if is_overdue else 'high',
                    'owner_id': bt.user_ids[0].id if bt.user_ids else (p.manager_id.id if p.manager_id else False),
                    'decision_needed': 'Steering committee / PMO decision needed to remove blockers.',
                    'status': 'open',
                }))
            if issue_cmds:
                self.issue_line_ids = issue_cmds

    def action_submit(self):
        for rec in self:
            rec.state = 'submitted'
            if rec.project_id:
                # Permanently freeze snapshot KPIs for auditability
                rec.progress_rate = rec.project_id.progress_rate
                rec.health_state = rec.project_id.health_state
                rec.project_status = rec.project_id.status
                m_total = len(rec.project_id.milestone_ids)
                m_reached = len(rec.project_id.milestone_ids.filtered(lambda m: m.progress_rate >= 100.0 or m.state == 'completed'))
                rec.milestones_summary = f"{m_reached} / {m_total} reached"
                d_total = len(rec.project_id.deliverable_ids)
                d_reached = len(rec.project_id.deliverable_ids.filtered(lambda d: d.progress_rate >= 100.0 or d.state == 'completed'))
                rec.deliverables_summary = f"{d_reached} / {d_total} reached"
            rec.message_post(body=_("Progress report submitted to stakeholders."))

    def action_review(self):
        for rec in self:
            rec.state = 'reviewed'
            rec.message_post(body=_("Progress report marked as reviewed by management."))

    def action_set_draft(self):
        for rec in self:
            rec.state = 'draft'


# -------------------------------------------------------------------------
# Sub-Models for the 7 Sections & Governance Tabs
# -------------------------------------------------------------------------

class PmProjectUpdateInfoLine(models.Model):
    _name = 'pm.project.update.info.line'
    _description = 'Project Update Information Line'
    _order = 'id asc'

    update_id = fields.Many2one('pm.project.progress.update', string='Update Report', required=True, ondelete='cascade')
    name = fields.Char(string='Information Line', required=True)


class PmProjectUpdateStatusLine(models.Model):
    _name = 'pm.project.update.status.line'
    _description = 'Overall Project Status Parameter Line'
    _order = 'id asc'

    update_id = fields.Many2one('pm.project.progress.update', string='Update Report', required=True, ondelete='cascade')
    name = fields.Char(string='Parameter', required=True)
    value = fields.Char(string='Status / Value', required=True)
    health = fields.Selection([
        ('on_track', 'On Track'),
        ('at_risk', 'At Risk'),
        ('off_track', 'Off Track'),
        ('on_hold', 'On Hold')
    ], string='Health', default='on_track')
    notes = fields.Char(string='Notes / Assessment')


class PmProjectUpdateDeliverableLine(models.Model):
    _name = 'pm.project.update.deliverable.line'
    _description = 'Deliverables & Major Activities Line'
    _order = 'id asc'

    update_id = fields.Many2one('pm.project.progress.update', string='Update Report', required=True, ondelete='cascade')
    deliverable_id = fields.Many2one('pm.deliverable', string='Deliverable', ondelete='set null')
    name = fields.Char(string='Deliverable / Major Activity Title', required=True)
    date_deadline = fields.Date(string='Target Deadline')
    progress_rate = fields.Float(string='Progress (%)', default=0.0)
    state = fields.Selection([
        ('draft', 'Planned'),
        ('in_progress', 'In Progress'),
        ('at_risk', 'At Risk'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='completed')
    notes = fields.Char(string='Remark')

    @api.onchange('deliverable_id')
    def _onchange_deliverable_id(self):
        if self.deliverable_id:
            d = self.deliverable_id
            self.name = d.name
            self.date_deadline = d.date_deadline
            self.progress_rate = d.progress_rate
            self.state = d.state if d.state in dict(self._fields['state'].selection) else 'completed'


class PmProjectUpdateTaskLine(models.Model):
    _name = 'pm.project.update.task.line'
    _description = 'Completed Task / Activity Line'
    _order = 'id asc'

    update_id = fields.Many2one('pm.project.progress.update', string='Update Report', required=True, ondelete='cascade')
    task_id = fields.Many2one('pm.task', string='Task', ondelete='set null')
    name = fields.Char(string='Task Name', required=True)
    user_id = fields.Many2one('res.users', string='Assignee')
    date_deadline = fields.Date(string='Deadline')
    progress_rate = fields.Float(string='Progress (%)', default=100.0)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('blocked', 'Blocked'),
        ('done', 'Done'),
        ('canceled', 'Canceled')
    ], string='State', default='done')
    notes = fields.Char(string='Notes')

    @api.onchange('task_id')
    def _onchange_task_id(self):
        if self.task_id:
            t = self.task_id
            self.name = t.name
            self.user_id = t.user_ids[0].id if t.user_ids else False
            self.date_deadline = t.date_deadline
            self.progress_rate = t.progress_rate
            self.state = t.state if t.state in dict(self._fields['state'].selection) else 'done'


class PmProjectUpdateMilestoneLine(models.Model):
    _name = 'pm.project.update.milestone.line'
    _description = 'Milestone Line with Delay Tracking'
    _order = 'id asc'

    update_id = fields.Many2one('pm.project.progress.update', string='Update Report', required=True, ondelete='cascade')
    milestone_id = fields.Many2one('pm.milestone', string='Milestone', ondelete='set null')
    name = fields.Char(string='Milestone Phase', required=True)
    date_deadline = fields.Date(string='Due Date')
    date_reached = fields.Date(string='Reached On')
    is_reached = fields.Boolean(string='Reached', default=False)
    delay_status = fields.Selection([
        ('on_time', 'On Time 🟢'),
        ('delayed', 'Delayed 🔴'),
        ('overdue', 'Overdue 🔴'),
        ('pending', 'Pending ⏳')
    ], string='Schedule Status', default='pending')
    progress_rate = fields.Float(string='Progress (%)', default=0.0)
    status_note = fields.Char(string='Notes / Remark')

    @api.onchange('milestone_id')
    def _onchange_milestone_id(self):
        if self.milestone_id:
            m = self.milestone_id
            self.name = m.name
            self.date_deadline = m.date_deadline
            self.progress_rate = m.progress_rate
            is_reached = (m.progress_rate >= 100.0 or m.state == 'completed')
            self.is_reached = is_reached
            self.date_reached = m.date_deadline if is_reached and m.date_deadline else (fields.Date.today() if is_reached else False)
            if is_reached:
                if m.date_deadline and self.date_reached and self.date_reached > m.date_deadline:
                    self.delay_status = 'delayed'
                else:
                    self.delay_status = 'on_time'
            else:
                if m.date_deadline and m.date_deadline < fields.Date.today():
                    self.delay_status = 'overdue'
                else:
                    self.delay_status = 'pending'

    @api.onchange('date_deadline', 'date_reached', 'is_reached')
    def _onchange_delay_calculation(self):
        for rec in self:
            if rec.is_reached:
                if rec.date_deadline and rec.date_reached and rec.date_reached > rec.date_deadline:
                    rec.delay_status = 'delayed'
                else:
                    rec.delay_status = 'on_time'
            else:
                if rec.date_deadline and rec.date_deadline < fields.Date.today():
                    rec.delay_status = 'overdue'
                else:
                    rec.delay_status = 'pending'


class PmProjectUpdateRiskLine(models.Model):
    _name = 'pm.project.update.risk.line'
    _description = 'Project Update Identified Risk Line'
    _order = 'id asc'

    update_id = fields.Many2one('pm.project.progress.update', string='Update Report', required=True, ondelete='cascade')
    risk_id = fields.Many2one('pm.project.risk', string='Project Risk', ondelete='set null')
    name = fields.Char(string='Risk Description', required=True)
    category = fields.Selection([
        ('technical', 'Technical / Architecture'),
        ('resource', 'Resource / Staffing'),
        ('schedule', 'Schedule / Timeline'),
        ('budget', 'Budget / Cost'),
        ('external', 'External / Vendor'),
        ('compliance', 'Regulatory & Compliance'),
        ('operational', 'Operational & Process'),
    ], string='Category', default='operational')
    severity = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical')
    ], string='Severity', default='medium')
    mitigation = fields.Char(string='Mitigation Strategy')

    @api.onchange('risk_id')
    def _onchange_risk_id(self):
        if self.risk_id:
            r = self.risk_id
            self.name = r.name
            if r.category and r.category in dict(self._fields['category'].selection):
                self.category = r.category
            else:
                self.category = 'operational'
            sev_score = getattr(r, 'severity', 1) or 1
            if sev_score >= 12:
                self.severity = 'critical'
            elif sev_score >= 9:
                self.severity = 'high'
            elif sev_score >= 4:
                self.severity = 'medium'
            else:
                self.severity = 'low'
            self.mitigation = r.mitigation or 'Ongoing monitoring and control'


class PmProjectUpdateChallengeLine(models.Model):
    _name = 'pm.project.update.challenge.line'
    _description = 'Project Update Challenge Line'
    _order = 'id asc'

    update_id = fields.Many2one('pm.project.progress.update', string='Update Report', required=True, ondelete='cascade')
    name = fields.Char(string='Challenge Description', required=True)
    category = fields.Selection([
        ('operational', 'Operational & Process'),
        ('technical', 'Technical & Infrastructure'),
        ('resource', 'Resource & Skill Shortage'),
        ('dependency', 'Dependency & External Blocker'),
        ('schedule', 'Schedule & Timeline Pressure'),
        ('procurement', 'Procurement & Logistics'),
        ('governance', 'Governance & Stakeholder'),
    ], string='Category', default='operational')
    impact = fields.Char(string='Impact on Project')
    action_plan = fields.Char(string='Action Plan / Resolution')


class PmProjectUpdateIssueLine(models.Model):
    _name = 'pm.project.update.issue.line'
    _description = 'Project Update Issue Line'
    _order = 'id asc'

    update_id = fields.Many2one('pm.project.progress.update', string='Update Report', required=True, ondelete='cascade')
    name = fields.Char(string='Issue Description', required=True)
    severity = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical')
    ], string='Severity', default='medium')
    owner_id = fields.Many2one('res.users', string='Owner')
    decision_needed = fields.Char(string='Decision / Action Needed')
    status = fields.Selection([
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved')
    ], string='Status', default='open')
