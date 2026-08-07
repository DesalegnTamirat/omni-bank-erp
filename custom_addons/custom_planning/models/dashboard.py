# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PlanningDashboard(models.Model):
    _name = 'planning.dashboard'
    _description = 'Planning Dashboard'

    name = fields.Char(default='Planning Dashboard')
    note = fields.Html(readonly=True)

    fiscal_year_id = fields.Many2one(
        'planning.fiscal.year', string='Fiscal Year',
        help="Filter the summary below by Fiscal Year. Leave empty to show all Fiscal Years.")

    total_plans = fields.Integer(string='Total Plans', compute='_compute_summary')
    draft_count = fields.Integer(string='Draft', compute='_compute_summary')
    initiated_count = fields.Integer(string='Initiated', compute='_compute_summary')
    approved_count = fields.Integer(string='Approved', compute='_compute_summary')
    rejected_count = fields.Integer(string='Rejected', compute='_compute_summary')
    total_headcount = fields.Integer(string='Approved Head Count', compute='_compute_summary')
    work_unit_count = fields.Integer(string='Work Units with Plans', compute='_compute_summary')

    def _get_manpower_domain(self):
        self.ensure_one()
        domain = [('del_flg', '!=', 'Y')]
        if self.fiscal_year_id:
            domain.append(('fiscal_year_id', '=', self.fiscal_year_id.id))
        return domain

    @api.depends('fiscal_year_id')
    def _compute_summary(self):
        Manpower = self.env['planning.work.unit.manpower']
        for rec in self:
            active_plans = Manpower.search(rec._get_manpower_domain())
            approved_plans = active_plans.filtered(lambda r: r.state == 'approved')

            rec.total_plans = len(active_plans)
            rec.draft_count = len(active_plans.filtered(lambda r: r.state == 'draft'))
            rec.initiated_count = len(active_plans.filtered(lambda r: r.state == 'initiated'))
            rec.approved_count = len(approved_plans)
            rec.rejected_count = len(active_plans.filtered(lambda r: r.state == 'rejected'))
            rec.total_headcount = sum(approved_plans.mapped('total_headcount'))
            rec.work_unit_count = len(active_plans.mapped('work_unit_id'))

    def _action_open_manpower(self, extra_domain=None):
        action = self.env['ir.actions.act_window']._for_xml_id(
            'custom_planning.action_planning_work_unit_manpower')
        domain = list(extra_domain or [])
        if self.fiscal_year_id:
            domain.append(('fiscal_year_id', '=', self.fiscal_year_id.id))
        if domain:
            action['domain'] = domain
        return action

    def action_open_all(self):
        return self._action_open_manpower()

    def action_open_draft(self):
        return self._action_open_manpower([('state', '=', 'draft')])

    def action_open_initiated(self):
        return self._action_open_manpower([('state', '=', 'initiated')])

    def action_open_approved(self):
        return self._action_open_manpower([('state', '=', 'approved')])

    def action_open_rejected(self):
        return self._action_open_manpower([('state', '=', 'rejected')])

    def _action_graph_analysis(self, name, graph_type, group_by):
        self.ensure_one()
        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': 'planning.work.unit.manpower',
            'view_mode': 'graph,pivot,list',
            'domain': self._get_manpower_domain(),
            'context': {
                'group_by': group_by,
                'graph_measure': 'total_headcount',
                'graph_mode': graph_type,
            },
        }

    def action_open_status_analysis(self):
        """Bar chart: number of plans grouped by Status."""
        return self._action_graph_analysis(
            'Plans by Status', 'bar', ['state'])

    def action_open_workunit_analysis(self):
        """Bar chart: head count grouped by Work Unit."""
        return self._action_graph_analysis(
            'Head Count by Work Unit', 'bar', ['work_unit_id'])

    def action_open_full_analysis(self):
        """Opens a full graph/pivot/list analysis view over all Manpower
        plans, still respecting the selected fiscal year."""
        return self._action_graph_analysis(
            'Manpower Analysis', 'bar', ['work_unit_id'])