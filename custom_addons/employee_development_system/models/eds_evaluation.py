# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

from .eds_action_notification import clear_action_activities, notify_action
from datetime import timedelta
from dateutil.relativedelta import relativedelta

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

    session_id = fields.Many2one('eds.session', string='Training Session', required=True, ondelete='cascade', index=True, tracking=True)
    course_id = fields.Many2one('eds.course', related='session_id.course_id', string='Course', store=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True, index=True, tracking=True)
    instrument_id = fields.Many2one('eds.evaluation.instrument', string='Evaluation Instrument')
    submitted_date = fields.Date(string='Submission Date', readonly=True)
    report_sla_deadline = fields.Date(string='Report SLA Deadline (7 Days)', compute='_compute_sla_deadline', store=True)
    overall_score = fields.Float(string='Overall Score (%)', compute='_compute_overall_score', store=True)
    state = fields.Selection([
        ('distributed', 'Draft'),
        ('submitted', 'Submitted'),
        ('consolidated', 'Consolidated'),
    ], string='Status', default='distributed', required=True, tracking=True)
    line_ids = fields.One2many('eds.evaluation.level1.line', 'evaluation_id', string='Question Responses')
    general_comments = fields.Text(string='General Comments & Suggestions')
    recommend_to_others = fields.Selection([('yes', 'Yes'), ('no', 'No'), ('maybe', 'Maybe')], string='Would recommend course?')
    
    # Standard Form Fields
    most_valuable_feedback = fields.Text(string='What was most valuable about this program?')
    improvement_suggestions = fields.Text(string='What should be improved? Suggested future training topics?')
    score_content = fields.Float(string='Content Score (%)', compute='_compute_category_scores', store=True)
    score_trainer = fields.Float(string='Trainer Score (%)', compute='_compute_category_scores', store=True)
    score_venue = fields.Float(string='Venue & Food Score (%)', compute='_compute_category_scores', store=True)
    score_objective = fields.Float(string='Objectives & Overall Score (%)', compute='_compute_category_scores', store=True)
    is_anonymous = fields.Boolean(string='Submit Anonymously', default=False, help='If checked, participant name and badge are suppressed on reports.')

    @api.model_create_multi
    def create(self, vals_list):
        evaluations = super().create(vals_list)
        self.env['eds.trainer.feedback'].sync_from_level1(evaluations)
        return evaluations

    def write(self, vals):
        result = super().write(vals)
        if {'state', 'submitted_date', 'session_id', 'employee_id', 'is_anonymous'} & vals.keys():
            self.env['eds.trainer.feedback'].sync_from_level1(self)
        return result

    @api.constrains('session_id', 'employee_id')
    def _check_unique_session_participant(self):
        for rec in self:
            if rec.session_id and rec.employee_id:
                domain = [('session_id', '=', rec.session_id.id), ('employee_id', '=', rec.employee_id.id), ('id', '!=', rec.id)]
                if self.search_count(domain) > 0:
                    raise ValidationError(_("A Level 1 evaluation already exists for participant %s in session %s.") % (
                        rec.employee_id.name, rec.session_id.name
                    ))

    @api.depends('session_id.date_end')
    def _compute_sla_deadline(self):
        for rec in self:
            if rec.session_id and rec.session_id.date_end:
                rec.report_sla_deadline = rec.session_id.date_end + timedelta(days=7)
            else:
                rec.report_sla_deadline = False

    @api.depends('line_ids.score_pct', 'line_ids.question_id.question_type')
    def _compute_overall_score(self):
        for rec in self:
            scorable_lines = rec.line_ids.filtered(
                lambda l: l.question_id.question_type in ('scale_1_5', 'scale_1_10', 'yes_no')
            )
            if scorable_lines:
                rec.overall_score = round(sum(scorable_lines.mapped('score_pct')) / len(scorable_lines), 2)
            else:
                rec.overall_score = 0.0

    @api.depends('line_ids.score_pct', 'line_ids.question_id.category')
    def _compute_category_scores(self):
        for rec in self:
            def avg_cat(categories):
                lines = rec.line_ids.filtered(
                    lambda l: l.question_id.category in categories and l.question_id.question_type in ('scale_1_5', 'scale_1_10', 'yes_no')
                )
                return round(sum(lines.mapped('score_pct')) / len(lines), 2) if lines else 0.0
            rec.score_content = avg_cat(['content'])
            rec.score_trainer = avg_cat(['trainer'])
            rec.score_venue = avg_cat(['venue'])
            rec.score_objective = avg_cat(['objective', 'impact'])

    def action_generate_questions(self):
        """Load the published questionnaire without replacing existing answers."""
        for rec in self:
            if rec.state != 'distributed':
                raise ValidationError(_("Questions can only be generated for draft feedback."))
            instrument = (rec.instrument_id
                          or rec.line_ids[:1].question_id.instrument_id
                          or rec.session_id.course_id.level1_instrument_id
                          or self.env.ref('employee_development_system.inst_level1_standard',
                                          raise_if_not_found=False))
            if not instrument or instrument.state != 'published' or not instrument.question_ids:
                raise ValidationError(_(
                    "No published feedback questionnaire is available for this course. "
                    "Ask L&D to configure one."))
            existing_question_ids = set(rec.line_ids.mapped('question_id').ids)
            missing = instrument.question_ids.filtered(
                lambda question: question.id not in existing_question_ids)
            if missing:
                rec.write({
                    'instrument_id': instrument.id,
                    'line_ids': [(0, 0, {'question_id': question.id}) for question in missing],
                })

    def action_submit_feedback(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_("Please fill in responses before submitting."))
            for line in rec.line_ids:
                answer_type = line.question_id.question_type
                if answer_type in ('scale_1_5', 'scale_1_10') and not line.rating_val:
                    raise ValidationError(_("Answer every rating question before submitting."))
                if answer_type == 'yes_no' and not line.yes_no_val:
                    raise ValidationError(_("Answer every yes/no question before submitting."))
                if answer_type == 'text' and not line.text_val:
                    raise ValidationError(_("Answer every text question before submitting."))
            rec.state = 'submitted'
            rec.submitted_date = fields.Date.context_today(self)
            clear_action_activities(rec)
            rec.message_post(body=_("Level 1 feedback submitted by %s with score %.1f%%.") % (rec.employee_id.name, rec.overall_score))

    def action_print_form(self):
        """Prints official Form Reaction Survey PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_level1').report_action(self)

class EdsEvaluationLevel1Line(models.Model):
    _name = 'eds.evaluation.level1.line'
    _description = 'EDS Level 1 Response Line'

    evaluation_id = fields.Many2one('eds.evaluation.level1', string='Level 1 Evaluation', ondelete='cascade')
    question_id = fields.Many2one('eds.evaluation.instrument.question', string='Question', required=True)
    rating_val = fields.Integer(string='Rating Value', default=0)
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

    session_id = fields.Many2one('eds.session', string='Training Session', required=True, ondelete='cascade', index=True, tracking=True)
    course_id = fields.Many2one('eds.course', related='session_id.course_id', string='Course', store=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True, index=True, tracking=True)
    pre_assessment_id = fields.Many2one('eds.assessment', string='Pre-Assessment', domain="[('session_id', '=', session_id), ('employee_id', '=', employee_id), ('assessment_type', '=', 'pre')]")
    post_assessment_id = fields.Many2one('eds.assessment', string='Post-Assessment', domain="[('session_id', '=', session_id), ('employee_id', '=', employee_id), ('assessment_type', '=', 'post')]")
    pre_score = fields.Float(string='Pre Score (%)', related='pre_assessment_id.score', store=True)
    post_score = fields.Float(string='Post Score (%)', related='post_assessment_id.score', store=True)
    
    # Standard Pre/Post Scoring & Signatories
    total_marks = fields.Float(string='Total Marks (Test)', default=100.0)
    pre_test_score = fields.Float(string='Pre-test Raw Score', default=0.0)
    post_test_score = fields.Float(string='Post-test Raw Score', default=0.0)
    pre_test_pct = fields.Float(string='Pre-test (%)', compute='_compute_test_percentages', store=True)
    post_test_pct = fields.Float(string='Post-test (%)', compute='_compute_test_percentages', store=True)
    learning_gain = fields.Float(string='Knowledge Gain (%)', compute='_compute_learning_gain', store=True)
    passing_score = fields.Float(string='Passing Score (%)', default=60.0)
    passed = fields.Boolean(string='Level 2 Passed', compute='_compute_passed', store=True)
    objective_achieved = fields.Boolean(string='Learning Objective Achieved', compute='_compute_passed', store=True)
    remarks = fields.Char(string='Remarks')

    trainer_assessor_name = fields.Char(string='Trainer / Assessor')
    training_coordinator_name = fields.Char(string='Training Coordinator (L&D)')
    approved_by_tl_name = fields.Char(string='Team Leader, L&D')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('evaluated', 'Evaluated'),
    ], string='Status', default='draft', required=True, tracking=True)

    @api.constrains('session_id', 'employee_id')
    def _check_unique_session_participant_l2(self):
        for rec in self:
            if rec.session_id and rec.employee_id:
                domain = [('session_id', '=', rec.session_id.id), ('employee_id', '=', rec.employee_id.id), ('id', '!=', rec.id)]
                if self.search_count(domain) > 0:
                    raise ValidationError(_("A Level 2 evaluation already exists for participant %s in session %s.") % (
                        rec.employee_id.name, rec.session_id.name
                    ))

    @api.depends('pre_test_score', 'post_test_score', 'total_marks', 'pre_score',
                 'post_score', 'pre_assessment_id', 'post_assessment_id')
    def _compute_test_percentages(self):
        for rec in self:
            tm = rec.total_marks or 100.0
            # A linked assessment is the official result whether its answers
            # were entered by the employee, by L&D, or through the template.
            # Keep raw marks as a fallback for older Level-2-only records.
            if rec.pre_assessment_id:
                rec.pre_test_pct = rec.pre_score
            elif rec.pre_test_score > 0:
                rec.pre_test_pct = round((rec.pre_test_score / tm) * 100.0, 2)
            else:
                rec.pre_test_pct = 0.0

            if rec.post_assessment_id:
                rec.post_test_pct = rec.post_score
            elif rec.post_test_score > 0:
                rec.post_test_pct = round((rec.post_test_score / tm) * 100.0, 2)
            else:
                rec.post_test_pct = 0.0

    @api.depends('pre_test_pct', 'post_test_pct')
    def _compute_learning_gain(self):
        for rec in self:
            rec.learning_gain = round(rec.post_test_pct - rec.pre_test_pct, 2)

    @api.depends('post_test_pct', 'passing_score')
    def _compute_passed(self):
        for rec in self:
            rec.passed = rec.post_test_pct >= rec.passing_score
            rec.objective_achieved = rec.passed

    def action_evaluate(self):
        for rec in self:
            if not rec.pre_assessment_id or not rec.post_assessment_id:
                raise ValidationError(_(
                    "Record and grade both the pre- and post-assessment questions "
                    "before completing the Level 2 evaluation."
                ))
            pending = (rec.pre_assessment_id | rec.post_assessment_id).filtered(
                lambda assessment: assessment.entry_method != 'score_only'
                and assessment.state != 'graded'
            )
            if pending:
                raise ValidationError(_(
                    "Grade every answer in the pre- and post-assessments "
                    "before completing the Level 2 evaluation."
                ))
            rec.state = 'evaluated'
            rec.message_post(body=_("Level 2 evaluation completed: Pre %.1f%%, Post %.1f%%, Gain %.1f%%, Passed: %s.") % (
                rec.pre_test_pct, rec.post_test_pct, rec.learning_gain, rec.passed
            ))
            # Trigger low-score flag for next cycle TNA if post score is below threshold
            if not rec.passed and rec.course_id:
                rec._flag_tna_gap_candidate()

    def action_print_form(self):
        """Prints official Form Assessment Sheet PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_level2').report_action(self)

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

    session_id = fields.Many2one('eds.session', string='Training Session', required=True, ondelete='cascade', index=True, tracking=True)
    course_id = fields.Many2one('eds.course', related='session_id.course_id', string='Course', store=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True, index=True, tracking=True)
    manager_id = fields.Many2one('hr.employee', string='Line Manager / Assessor', required=True, tracking=True)
    due_date = fields.Date(string='Assessment Due Date', required=True, tracking=True)
    notification_at = fields.Datetime(
        string='Manager Notification At', index=True, readonly=True, copy=False,
        help='The manager is notified when this time is reached. Set when the session is completed.')
    notification_sent_at = fields.Datetime(
        string='Manager Notified At', readonly=True, copy=False)
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

    # Standard Form Fields
    evaluation_period = fields.Selection([
        ('30_days', '30 Days'),
        ('60_days', '60 Days'),
        ('90_days', '90 Days'),
        ('custom', 'Configured Interval'),
    ], string='Evaluation Period', default='60_days', required=True, tracking=True)
    overall_result = fields.Selection([
        ('significant_improvement', 'Significant Improvement'),
        ('some_improvement', 'Some Improvement'),
        ('no_change', 'No Change'),
        ('decline', 'Decline'),
    ], string='Overall Result', default='some_improvement', tracking=True)
    business_impact_observed = fields.Text(
        string='Business Impact Observed',
        help='Observed impact on productivity, quality, customer service, or risk/compliance.')
    recommended_support = fields.Text(
        string='Further Support / Development Needs Recommended')
    sign_manager_name = fields.Char(string='Line Manager')
    sign_trainee_name = fields.Char(string='Trainee Acknowledgement')
    sign_officer_name = fields.Char(string='L&D Officer (Received)')

    @api.model
    def _configured_notification_time(self, completed_at=None):
        """Return the review reminder time from the EDS delay settings."""
        params = self.env['ir.config_parameter'].sudo()
        try:
            value = int(params.get_param('eds.level3_delay_value', '60'))
        except (TypeError, ValueError):
            value = 60
        unit = params.get_param('eds.level3_delay_unit', 'days')
        if value < 1 or unit not in ('minutes', 'hours', 'days', 'weeks', 'months'):
            value, unit = 60, 'days'
        completed_at = fields.Datetime.to_datetime(completed_at or fields.Datetime.now())
        delay = relativedelta(months=value) if unit == 'months' else timedelta(**{unit: value})
        return completed_at + delay, ('60_days' if (value, unit) == (60, 'days') else 'custom')

    @api.model
    def _cron_notify_due_level3(self, batch_size=200):
        """Send each due manager review once; leave older, already-alerted rows alone."""
        due = self.sudo().search([
            ('notification_at', '!=', False),
            ('notification_at', '<=', fields.Datetime.now()),
            ('notification_sent_at', '=', False),
            ('status', 'in', ('pending', 'in_progress')),
            ('manager_id.user_id', '!=', False),
            ('manager_id.user_id.active', '=', True),
        ], order='notification_at, id', limit=batch_size)
        for review in due:
            user = review.manager_id.user_id
            if not user or not user.active:
                continue
            message = _('Please review %s’s on-the-job application of %s.') % (
                review.employee_id.name, review.session_id.name)
            if notify_action(review, user, _('Review training impact'), message):
                review.notification_sent_at = fields.Datetime.now()

    @api.depends('line_ids.score_pct')
    def _compute_behavior_score(self):
        for rec in self:
            if rec.line_ids:
                rec.behavior_score = round(sum(rec.line_ids.mapped('score_pct')) / len(rec.line_ids), 2)
            else:
                rec.behavior_score = 0.0

    def action_submit_level3(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_("Please score at least one target competency observation line."))
            rec.status = 'completed'
            rec.completed_date = fields.Date.context_today(self)
            clear_action_activities(rec)
            rec.message_post(body=_("Level 3 behavioral evaluation completed by manager %s with score %.1f%%.") % (rec.manager_id.name, rec.behavior_score))

    def action_print_form(self):
        """Prints official Form Behavioral Evaluation PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_level3').report_action(self)

class EdsEvaluationLevel3Line(models.Model):
    _name = 'eds.evaluation.level3.line'
    _description = 'EDS Level 3 Competency Observation Line'

    evaluation_id = fields.Many2one('eds.evaluation.level3', string='Level 3 Evaluation', ondelete='cascade')
    competency_id = fields.Many2one('competency.competency', string='Target Competency', required=True)
    behavior_description = fields.Char(string='Observable On-the-Job Behavior')
    frequency_rating = fields.Selection([
        ('1', '1 - Never'),
        ('2', '2 - Rarely'),
        ('3', '3 - Sometimes'),
        ('4', '4 - Often'),
        ('5', '5 - Always'),
    ], string='Frequency Rating', default='4')
    observed_level = fields.Selection([
        ('1', 'Level 1: Basic'),
        ('2', 'Level 2: Intermediate'),
        ('3', 'Level 3: Advanced'),
        ('4', 'Level 4: Expert'),
    ], string='Observed Proficiency Level', default='2')
    score_pct = fields.Float(string='Score (%)', compute='_compute_score_pct', store=True)
    comment = fields.Text(string='Workplace Evidence / Comment')

    @api.depends('observed_level', 'frequency_rating')
    def _compute_score_pct(self):
        for rec in self:
            if rec.frequency_rating:
                rec.score_pct = (int(rec.frequency_rating) / 5.0) * 100.0
            else:
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

    session_id = fields.Many2one('eds.session', string='Training Session', tracking=True)
    evaluator_id = fields.Many2one('res.users', string='Evaluated by', default=lambda self: self.env.user)
    sign_tl_lnd = fields.Char(string='Team Leader, L&D Signoff')
    sign_director_ppdd = fields.Char(string='Director, PPDD Approval')
    sign_executive = fields.Char(string='Executive Management Sign-Off')

    def action_print_form(self):
        """Prints official Form Level 4 Impact & ROI Assessment PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_level4').report_action(self)

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
