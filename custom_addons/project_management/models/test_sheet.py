# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PmTestCaseLine(models.Model):
    _name = 'pm.test.case.line'
    _description = 'Test Case Specification Line'
    _order = 'sequence, id'

    document_id = fields.Many2one('pm.project.document', string='Source Document', ondelete='cascade')
    project_id = fields.Many2one('pm.project', string='Project', ondelete='cascade', store=True)
    milestone_id = fields.Many2one('pm.milestone', string='Milestone', ondelete='set null', store=True)
    deliverable_id = fields.Many2one('pm.deliverable', string='Deliverable / Activity', ondelete='set null', store=True)

    sequence = fields.Integer(string='Sequence', default=10)
    code = fields.Char(string='Test ID', required=True, default='TC-001')
    name = fields.Char(string='Test Case Name', required=True)

    category = fields.Selection([
        ('functional', 'Functional'),
        ('ui_ux', 'UI / UX'),
        ('api_integration', 'API / Integration'),
        ('security', 'Security & Access'),
        ('performance', 'Performance'),
        ('other', 'Other'),
    ], string='Category', default='functional', required=True)

    severity = fields.Selection([
        ('critical', 'Critical / Blocker'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ], string='Severity', default='medium', required=True)

    preconditions = fields.Text(string='Preconditions / Setup')
    steps = fields.Text(string='Test Steps')
    expected_result = fields.Text(string='Expected Result')


class PmTestExecution(models.Model):
    _name = 'pm.test.execution'
    _description = 'Test Execution & Results Evaluation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Execution Title', required=True, tracking=True)
    code = fields.Char(string='Execution ID', readonly=True, copy=False, default=lambda self: _('New'))

    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade', tracking=True)
    milestone_id = fields.Many2one('pm.milestone', string='Milestone', ondelete='set null',
                                  domain="[('project_id', '=', project_id)]", tracking=True)
    deliverable_id = fields.Many2one('pm.deliverable', string='Deliverable / Major Activity', ondelete='set null',
                                    domain="milestone_id and [('milestone_id', '=', milestone_id)] or [('project_id', '=', project_id)]", tracking=True)

    test_round = fields.Char(string='Test Round', default='Round 1', required=True, tracking=True)
    tester_id = fields.Many2one('res.users', string='Evaluator / Tester', default=lambda self: self.env.user, tracking=True)
    execution_date = fields.Date(string='Execution Date', default=fields.Date.context_today, required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'Under Testing'),
        ('completed', 'Completed'),
        ('sign_off', 'Approved / Signed Off'),
    ], string='Status', default='in_progress', required=True, tracking=True)

    notes = fields.Text(string='Scope & Evaluation Observations')
    sign_off_notes = fields.Text(string='Sign-Off Remarks & Executive Summary')

    execution_line_ids = fields.One2many('pm.test.execution.line', 'execution_id', string='Test Evaluation Results')

    # Computed KPI Metrics
    total_cases = fields.Integer(string='Total Cases', compute='_compute_metrics', store=True)
    executed_cases = fields.Integer(string='Executed Cases', compute='_compute_metrics', store=True)
    passed_count = fields.Integer(string='Passed', compute='_compute_metrics', store=True)
    failed_count = fields.Integer(string='Failed', compute='_compute_metrics', store=True)
    indifferent_count = fields.Integer(string='Indifferent', compute='_compute_metrics', store=True)
    pass_rate = fields.Float(string='Pass Rate (%)', compute='_compute_metrics', store=True)

    active = fields.Boolean(string='Active', default=True)

    @api.depends('execution_line_ids', 'execution_line_ids.status', 'execution_line_ids.result')
    def _compute_metrics(self):
        for rec in self:
            rec.total_cases = len(rec.execution_line_ids)
            rec.executed_cases = len(rec.execution_line_ids.filtered(lambda e: e.status == 'tested'))
            rec.passed_count = len(rec.execution_line_ids.filtered(lambda e: e.result == 'pass'))
            rec.failed_count = len(rec.execution_line_ids.filtered(lambda e: e.result == 'fail'))
            rec.indifferent_count = len(rec.execution_line_ids.filtered(lambda e: e.result == 'indifferent'))
            if rec.total_cases > 0:
                rec.pass_rate = round((rec.passed_count / rec.total_cases) * 100.0, 1)
            else:
                rec.pass_rate = 0.0

    @api.onchange('project_id')
    def _onchange_project_id(self):
        domain = {
            'milestone_id': [],
            'deliverable_id': [],
        }
        if self.project_id:
            if self.milestone_id and self.milestone_id.project_id != self.project_id:
                self.milestone_id = False
            if self.deliverable_id and self.deliverable_id.project_id != self.project_id:
                self.deliverable_id = False
            domain['milestone_id'] = [('project_id', '=', self.project_id.id)]
            if self.milestone_id:
                domain['deliverable_id'] = [('milestone_id', '=', self.milestone_id.id)]
            else:
                domain['deliverable_id'] = [('project_id', '=', self.project_id.id)]
        else:
            self.milestone_id = False
            self.deliverable_id = False
        return {'domain': domain}

    @api.onchange('milestone_id')
    def _onchange_milestone_id(self):
        if self.milestone_id:
            if not self.project_id or self.project_id != self.milestone_id.project_id:
                self.project_id = self.milestone_id.project_id
            if self.deliverable_id and self.deliverable_id.milestone_id != self.milestone_id:
                self.deliverable_id = False
            return {'domain': {'deliverable_id': [('milestone_id', '=', self.milestone_id.id)]}}
        elif self.project_id:
            return {'domain': {'deliverable_id': [('project_id', '=', self.project_id.id)]}}
        else:
            return {'domain': {'deliverable_id': []}}

    @api.onchange('deliverable_id')
    def _onchange_deliverable_id(self):
        if self.deliverable_id:
            if self.deliverable_id.milestone_id:
                self.milestone_id = self.deliverable_id.milestone_id
            if self.deliverable_id.project_id:
                self.project_id = self.deliverable_id.project_id

    # -------------------------------------------------------------------------
    # AUTOMATIC POPULATION OF TEST CASES
    # -------------------------------------------------------------------------
    @api.onchange('project_id', 'milestone_id', 'deliverable_id')
    def _onchange_scope_load_test_cases(self):
        if not self.project_id:
            self.execution_line_ids = [(5, 0, 0)]
            return

        domain = [('project_id', '=', self.project_id.id)]
        if self.milestone_id:
            domain.append(('milestone_id', '=', self.milestone_id.id))
        if self.deliverable_id:
            domain.append(('deliverable_id', '=', self.deliverable_id.id))

        cases = self.env['pm.test.case.line'].search(domain, order='sequence, id')
        if not cases:
            self.execution_line_ids = [(5, 0, 0)]
            return

        # Retain existing evaluations if any
        existing_cases = {}
        for line in self.execution_line_ids:
            cid = line.test_case_id.id or (line.test_case_id._origin.id if hasattr(line.test_case_id, '_origin') else False)
            if cid:
                existing_cases[cid] = line

        lines_to_keep = []
        for case in cases:
            if case.id in existing_cases:
                existing_line = existing_cases[case.id]
                lines_to_keep.append((0, 0, {
                    'test_case_id': case.id,
                    'status': existing_line.status or 'not_tested',
                    'result': existing_line.result or False,
                    'remark': existing_line.remark or '',
                }))
            else:
                lines_to_keep.append((0, 0, {
                    'test_case_id': case.id,
                    'status': 'not_tested',
                }))
        self.execution_line_ids = [(5, 0, 0)] + lines_to_keep

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pm.test.execution') or _('New')
        records = super().create(vals_list)
        for rec in records:
            if rec.project_id and not rec.execution_line_ids:
                rec._load_test_cases_from_project()
        return records

    def _load_test_cases_from_project(self):
        self.ensure_one()
        if not self.project_id or self.execution_line_ids:
            return

        domain = [('project_id', '=', self.project_id.id)]
        if self.milestone_id:
            domain.append(('milestone_id', '=', self.milestone_id.id))
        if self.deliverable_id:
            domain.append(('deliverable_id', '=', self.deliverable_id.id))

        cases = self.env['pm.test.case.line'].search(domain, order='sequence, id')
        lines = []
        for case in cases:
            lines.append({
                'execution_id': self.id,
                'test_case_id': case.id,
                'status': 'not_tested',
            })
        if lines:
            self.env['pm.test.execution.line'].create(lines)

    def action_complete_testing(self):
        self.ensure_one()
        self.state = 'completed'

    def action_sign_off(self):
        self.ensure_one()
        self.state = 'sign_off'

    def action_reset_draft(self):
        self.ensure_one()
        self.state = 'draft'

    def action_reload_test_cases(self):
        self.ensure_one()
        domain = [('project_id', '=', self.project_id.id)]
        if self.milestone_id:
            domain.append(('milestone_id', '=', self.milestone_id.id))
        if self.deliverable_id:
            domain.append(('deliverable_id', '=', self.deliverable_id.id))

        cases = self.env['pm.test.case.line'].search(domain, order='sequence, id')
        existing_case_ids = set(self.execution_line_ids.mapped('test_case_id.id'))
        new_lines = []
        for case in cases:
            if case.id not in existing_case_ids:
                new_lines.append({
                    'execution_id': self.id,
                    'test_case_id': case.id,
                    'status': 'not_tested',
                })
        if new_lines:
            self.env['pm.test.execution.line'].create(new_lines)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Test Cases Loaded'),
                    'message': _('Added %d test cases to this evaluation.') % len(new_lines),
                    'type': 'success',
                }
            }


class PmTestExecutionLine(models.Model):
    _name = 'pm.test.execution.line'
    _description = 'Test Execution Evaluation Line'
    _order = 'id asc'

    execution_id = fields.Many2one('pm.test.execution', string='Execution Run', required=True, ondelete='cascade')
    test_case_id = fields.Many2one('pm.test.case.line', string='Test Case', ondelete='cascade')

    case_code = fields.Char(string='Test ID', related='test_case_id.code', readonly=True, store=True)
    case_title = fields.Char(string='Test Case Name', related='test_case_id.name', readonly=True, store=True)
    case_category = fields.Selection(string='Category', related='test_case_id.category', readonly=True)
    case_severity = fields.Selection(string='Severity', related='test_case_id.severity', readonly=True)
    steps = fields.Text(string='Test Steps', related='test_case_id.steps', readonly=True)
    expected_result = fields.Text(string='Expected Result', related='test_case_id.expected_result', readonly=True)

    status = fields.Selection([
        ('not_tested', 'Not Tested'),
        ('tested', 'Tested'),
    ], string='Status', default='not_tested', required=True)

    result = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('indifferent', 'Indifferent'),
    ], string='Result')

    remark = fields.Text(string='Remark')

    @api.onchange('result')
    def _onchange_result(self):
        if self.result and self.status == 'not_tested':
            self.status = 'tested'

    @api.onchange('status')
    def _onchange_status(self):
        if self.status == 'not_tested':
            self.result = False
