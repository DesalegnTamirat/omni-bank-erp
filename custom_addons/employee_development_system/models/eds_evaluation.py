# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta

class EdsEvaluationInstrument(models.Model):
    _name = 'eds.evaluation.instrument'
    _description = 'EDS Evaluation Instrument / Questionnaire Template'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name, version desc'

    name = fields.Char(string='Instrument Name', required=True, tracking=True)
    instrument_type = fields.Selection([
        ('level1', 'Level 1: Participant Reaction & Satisfaction'),
        ('level2', 'Level 2: Learning & Knowledge Retention'),
        ('level3', 'Level 3: Behavioral Application (Job Level)'),
        ('level4', 'Level 4: Business Results & Organizational Impact'),
    ], string='Evaluation Level', required=True, tracking=True)
    version = fields.Char(string='Version', default='v1.0', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ], string='Status', default='draft', required=True, tracking=True)
    question_ids = fields.One2many('eds.evaluation.instrument.question', 'instrument_id', string='Questions', copy=True)
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Description / Instructions')

    def action_publish(self):
        for rec in self:
            if not rec.question_ids:
                raise ValidationError(_("Cannot publish an evaluation instrument without questions."))
            rec.state = 'published'
            rec.message_post(body=_("Evaluation instrument %s version %s published.") % (rec.name, rec.version))

    def action_archive(self):
        for rec in self:
            rec.state = 'archived'

    def action_create_new_version(self):
        for rec in self:
            v_parts = rec.version.replace('v', '').split('.')
            new_v = f"v{int(v_parts[0]) + 1}.0" if len(v_parts) > 0 and v_parts[0].isdigit() else 'v2.0'
            new_inst = rec.copy({'version': new_v, 'state': 'draft', 'name': f"{rec.name} ({new_v})"})
            return {
                'name': _('New Instrument Version'),
                'view_mode': 'form',
                'res_model': 'eds.evaluation.instrument',
                'res_id': new_inst.id,
                'type': 'ir.actions.act_window',
            }

class EdsEvaluationInstrumentQuestion(models.Model):
    _name = 'eds.evaluation.instrument.question'
    _description = 'EDS Evaluation Question'
    _order = 'sequence, id'

    instrument_id = fields.Many2one('eds.evaluation.instrument', string='Instrument', ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Question Prompt', required=True)
    category = fields.Selection([
        ('content', 'Course Content & Relevance'),
        ('trainer', 'Trainer Delivery & Expertise'),
        ('venue', 'Facilities, Venue & Materials'),
        ('objective', 'Learning Objectives Achievement'),
        ('impact', 'Workplace Impact Expectation'),
    ], string='Category', default='content', required=True)
    question_type = fields.Selection([
        ('scale_1_5', '5-Point Rating Scale (1-Poor to 5-Excellent)'),
        ('scale_1_10', '10-Point Rating Scale'),
        ('yes_no', 'Yes / No'),
        ('text', 'Open Text'),
    ], string='Answer Format', default='scale_1_5', required=True)
    weight = fields.Float(string='Weight (%)', default=1.0)

class EdsEvaluationLevel1(models.Model):
    _name = 'eds.evaluation.level1'
    _description = 'EDS Level 1 Reaction & Satisfaction Feedback'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    session_id = fields.Many2one('eds.session', string='Training Session', required=True, ondelete='cascade', tracking=True)
    course_id = fields.Many2one('eds.course', related='session_id.course_id', string='Course', store=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True, tracking=True)
    instrument_id = fields.Many2one('eds.evaluation.instrument', string='Evaluation Instrument')
    submitted_date = fields.Date(string='Submission Date', default=fields.Date.context_today)
    report_sla_deadline = fields.Date(string='Report SLA Deadline (7 Days)', compute='_compute_sla_deadline', store=True)
    overall_score = fields.Float(string='Overall Score (%)', compute='_compute_overall_score', store=True)
    state = fields.Selection([
        ('distributed', 'Distributed'),
        ('submitted', 'Submitted'),
        ('consolidated', 'Consolidated'),
    ], string='Status', default='distributed', required=True, tracking=True)
    line_ids = fields.One2many('eds.evaluation.level1.line', 'evaluation_id', string='Question Responses')
    general_comments = fields.Text(string='General Comments & Suggestions')
    recommend_to_others = fields.Selection([('yes', 'Yes'), ('no', 'No'), ('maybe', 'Maybe')], string='Would recommend course?')

    _sql_constraints = [
        ('unique_session_participant_l1', 'unique(session_id, employee_id)', 'A Level 1 evaluation already exists for this participant in this session.')
    ]

    @api.depends('session_id.date_end')
    def _compute_sla_deadline(self):
        for rec in self:
            if rec.session_id and rec.session_id.date_end:
                rec.report_sla_deadline = rec.session_id.date_end + timedelta(days=7)
            else:
                rec.report_sla_deadline = False

    @api.depends('line_ids.score_pct')
    def _compute_overall_score(self):
        for rec in self:
            valid_lines = rec.line_ids.filtered(lambda l: l.score_pct > 0)
            if valid_lines:
                rec.overall_score = sum(valid_lines.mapped('score_pct')) / len(valid_lines)
            else:
                rec.overall_score = 0.0

    def action_submit_feedback(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_("Please fill in responses before submitting."))
            rec.state = 'submitted'
            rec.submitted_date = fields.Date.context_today(self)
            rec.message_post(body=_("Level 1 feedback submitted by %s with score %.1f%%.") % (rec.employee_id.name, rec.overall_score))

class EdsEvaluationLevel1Line(models.Model):
    _name = 'eds.evaluation.level1.line'
    _description = 'EDS Level 1 Response Line'

    evaluation_id = fields.Many2one('eds.evaluation.level1', string='Level 1 Evaluation', ondelete='cascade')
    question_id = fields.Many2one('eds.evaluation.instrument.question', string='Question', required=True)
    rating_val = fields.Integer(string='Rating Value (1-5)', default=5)
    yes_no_val = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Yes/No Response')
    text_val = fields.Text(string='Comments')
    score_pct = fields.Float(string='Score (%)', compute='_compute_score_pct', store=True)

    @api.depends('rating_val', 'yes_no_val', 'question_id.question_type')
    def _compute_score_pct(self):
        for rec in self:
            if rec.question_id.question_type == 'scale_1_5':
                rec.score_pct = (rec.rating_val / 5.0) * 100.0 if rec.rating_val else 0.0
            elif rec.question_id.question_type == 'scale_1_10':
                rec.score_pct = (rec.rating_val / 10.0) * 100.0 if rec.rating_val else 0.0
            elif rec.question_id.question_type == 'yes_no':
                rec.score_pct = 100.0 if rec.yes_no_val == 'yes' else 0.0
            else:
                rec.score_pct = 0.0

class EdsEvaluationLevel2(models.Model):
    _name = 'eds.evaluation.level2'
    _description = 'EDS Level 2 Learning Evaluation (Pre vs Post Gain)'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    session_id = fields.Many2one('eds.session', string='Training Session', required=True, ondelete='cascade', tracking=True)
    course_id = fields.Many2one('eds.course', related='session_id.course_id', string='Course', store=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True, tracking=True)
    pre_assessment_id = fields.Many2one('eds.assessment', string='Pre-Assessment', domain="[('session_id', '=', session_id), ('employee_id', '=', employee_id), ('assessment_type', '=', 'pre')]")
    post_assessment_id = fields.Many2one('eds.assessment', string='Post-Assessment', domain="[('session_id', '=', session_id), ('employee_id', '=', employee_id), ('assessment_type', '=', 'post')]")
    pre_score = fields.Float(string='Pre Score (%)', related='pre_assessment_id.score', store=True)
    post_score = fields.Float(string='Post Score (%)', related='post_assessment_id.score', store=True)
    learning_gain = fields.Float(string='Knowledge Gain (%)', compute='_compute_learning_gain', store=True)
    passing_score = fields.Float(string='Passing Score (%)', default=60.0)
    passed = fields.Boolean(string='Level 2 Passed', compute='_compute_passed', store=True)
    objective_achieved = fields.Boolean(string='Learning Objective Achieved', compute='_compute_passed', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('evaluated', 'Evaluated'),
    ], string='Status', default='draft', required=True, tracking=True)

    _sql_constraints = [
        ('unique_session_emp_l2', 'unique(session_id, employee_id)', 'A Level 2 evaluation already exists for this participant in this session.')
    ]

    @api.depends('pre_score', 'post_score')
    def _compute_learning_gain(self):
        for rec in self:
            rec.learning_gain = rec.post_score - rec.pre_score

    @api.depends('post_score', 'passing_score')
    def _compute_passed(self):
        for rec in self:
            rec.passed = rec.post_score >= rec.passing_score
            rec.objective_achieved = rec.passed

    def action_evaluate(self):
        for rec in self:
            rec.state = 'evaluated'
            rec.message_post(body=_("Level 2 evaluation completed: Pre %.1f%%, Post %.1f%%, Gain %.1f%%, Passed: %s.") % (
                rec.pre_score, rec.post_score, rec.learning_gain, rec.passed
            ))
            # Trigger low-score flag for next cycle TNA if post score is below threshold
            if not rec.passed and rec.course_id:
                rec._flag_tna_gap_candidate()

    def _flag_tna_gap_candidate(self):
        # Implementation of feedback loop to TNA for low Level-2 scores
        for comp in self.course_id.competency_line_ids.mapped('competency_id'):
            self.env['eds.tna.entry'].create({
                'cycle_id': self.env['eds.tna.cycle'].search([('state', '=', 'collecting')], limit=1).id or False,
                'work_unit_id': self.employee_id.operating_unit_id.id if hasattr(self.employee_id, 'operating_unit_id') else False,
                'employee_id': self.employee_id.id,
                'competency_id': comp.id,
                'gap_severity': 'high',
                'source': 'pms',
                'delivery_mode': 'classroom',
                'justification': _("Auto-flagged from Level 2 post-assessment failure in course %s (Post score: %.1f%%).") % (self.course_id.name, self.post_score),
            })

class EdsEvaluationLevel3(models.Model):
    _name = 'eds.evaluation.level3'
    _description = 'EDS Level 3 Behavioral Application Assessment (Post 30-90 Days)'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    session_id = fields.Many2one('eds.session', string='Training Session', required=True, ondelete='cascade', tracking=True)
    course_id = fields.Many2one('eds.course', related='session_id.course_id', string='Course', store=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True, tracking=True)
    manager_id = fields.Many2one('hr.employee', string='Line Manager / Assessor', required=True, tracking=True)
    due_date = fields.Date(string='Assessment Due Date', required=True, tracking=True)
    completed_date = fields.Date(string='Completion Date')
    behavior_score = fields.Float(string='Behavioral Application Score (%)', compute='_compute_behavior_score', store=True)
    status = fields.Selection([
        ('pending', 'Pending (Scheduled)'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('overdue', 'Overdue'),
    ], string='Status', default='pending', required=True, tracking=True)
    line_ids = fields.One2many('eds.evaluation.level3.line', 'evaluation_id', string='Competency Observations')
    observation_notes = fields.Text(string='Manager Behavioral Observation & Evidence')

    @api.depends('line_ids.score_pct')
    def _compute_behavior_score(self):
        for rec in self:
            if rec.line_ids:
                rec.behavior_score = sum(rec.line_ids.mapped('score_pct')) / len(rec.line_ids)
            else:
                rec.behavior_score = 0.0

    def action_submit_level3(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_("Please score at least one target competency observation line."))
            rec.status = 'completed'
            rec.completed_date = fields.Date.context_today(self)
            rec.message_post(body=_("Level 3 behavioral evaluation completed by manager %s with score %.1f%%.") % (rec.manager_id.name, rec.behavior_score))

class EdsEvaluationLevel3Line(models.Model):
    _name = 'eds.evaluation.level3.line'
    _description = 'EDS Level 3 Competency Observation Line'

    evaluation_id = fields.Many2one('eds.evaluation.level3', string='Level 3 Evaluation', ondelete='cascade')
    competency_id = fields.Many2one('competency.competency', string='Target Competency', required=True)
    observed_level = fields.Selection([
        ('1', 'Level 1: Basic'),
        ('2', 'Level 2: Intermediate'),
        ('3', 'Level 3: Advanced'),
        ('4', 'Level 4: Expert'),
    ], string='Observed Proficiency Level', required=True, default='2')
    score_pct = fields.Float(string='Score (%)', compute='_compute_score_pct', store=True)
    comment = fields.Text(string='Workplace Evidence / Comment')

    @api.depends('observed_level')
    def _compute_score_pct(self):
        for rec in self:
            val = int(rec.observed_level) if rec.observed_level else 1
            rec.score_pct = (val / 4.0) * 100.0

class EdsEvaluationLevel4(models.Model):
    _name = 'eds.evaluation.level4'
    _description = 'EDS Level 4 Organizational Impact & ROI Assessment'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Impact Assessment Reference', required=True, default=lambda self: _('New'))
    course_id = fields.Many2one('eds.course', string='Training Program / Course', required=True, tracking=True)
    measurement_date = fields.Date(string='Measurement Date', default=fields.Date.context_today, required=True)
    roi_percentage = fields.Float(string='Calculated ROI (%)', compute='_compute_roi', store=True)
    total_program_cost = fields.Monetary(string='Total Program Cost', currency_field='currency_id')
    estimated_financial_benefit = fields.Monetary(string='Estimated Financial Benefit', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)
    kpi_ids = fields.One2many('eds.evaluation.level4.kpi', 'level4_id', string='Business KPIs Evaluated')
    impact_summary = fields.Text(string='Organizational Impact & Summary Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('evaluated', 'Evaluated & Published'),
    ], string='Status', default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.level4.evaluation') or _('New')
        return super(EdsEvaluationLevel4, self).create(vals_list)

    @api.depends('total_program_cost', 'estimated_financial_benefit')
    def _compute_roi(self):
        for rec in self:
            if rec.total_program_cost > 0:
                net_benefit = rec.estimated_financial_benefit - rec.total_program_cost
                rec.roi_percentage = (net_benefit / rec.total_program_cost) * 100.0
            else:
                rec.roi_percentage = 0.0

    def action_evaluate(self):
        for rec in self:
            rec.state = 'evaluated'
            rec.message_post(body=_("Level 4 ROI assessment completed: ROI %.1f%%.") % rec.roi_percentage)

class EdsEvaluationLevel4Kpi(models.Model):
    _name = 'eds.evaluation.level4.kpi'
    _description = 'EDS Level 4 Business KPI Indicator'

    level4_id = fields.Many2one('eds.evaluation.level4', string='Level 4 Assessment', ondelete='cascade')
    kpi_name = fields.Char(string='KPI Indicator Name', required=True)
    baseline_value = fields.Float(string='Baseline (Pre-Training)')
    target_value = fields.Float(string='Target Value')
    achieved_value = fields.Float(string='Achieved Post-Training')
    improvement_pct = fields.Float(string='Improvement (%)', compute='_compute_improvement', store=True)

    @api.depends('baseline_value', 'achieved_value')
    def _compute_improvement(self):
        for rec in self:
            if rec.baseline_value > 0:
                rec.improvement_pct = ((rec.achieved_value - rec.baseline_value) / rec.baseline_value) * 100.0
            else:
                rec.improvement_pct = 0.0
