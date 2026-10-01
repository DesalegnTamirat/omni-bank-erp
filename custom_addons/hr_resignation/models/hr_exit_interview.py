# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class HrExitInterviewTemplate(models.Model):
    _name = 'hr.exit.interview.template'
    _description = 'Exit Interview Template'
    _order = 'name'

    name = fields.Char(string='Template Name', required=True, translate=True)
    active = fields.Boolean(default=True)

    # Dynamic Questions list
    question_ids = fields.One2many('hr.exit.interview.question', 'template_id', string='Questions')

    # Configurable Question Labels (Deprecated - kept for fallback/migration compatibility)
    rating_label = fields.Char(string='Rating Question (Deprecated)', default='Work Environment Rating')
    recommend_label = fields.Char(string='Boolean Question (Deprecated)', default='Would Recommend the Bank to Others?')
    text_1_label = fields.Char(string='Text Question 1 (Deprecated)', default='PRIMARY REASON FOR LEAVING')
    text_2_label = fields.Char(string='Text Question 2 (Deprecated)', default='FEEDBACK ON MANAGEMENT AND WORK EXPERIENCE')
    text_3_label = fields.Char(string='Text Question 3 (Deprecated)', default='SUGGESTIONS FOR IMPROVEMENT')


class HrExitInterviewQuestion(models.Model):
    _name = 'hr.exit.interview.question'
    _description = 'Exit Interview Question'
    _order = 'sequence, id'

    template_id = fields.Many2one('hr.exit.interview.template', string='Template', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Question Text', required=True, translate=True)
    question_type = fields.Selection([
        ('rating',       'Rating'),
        ('satisfaction', 'Satisfaction'),
        ('agreement',    'Agreement'),
        ('boolean',      'Yes / No'),
        ('boolean_agree','Agree / Disagree'),
        ('custom',       'Custom Choices'),
        ('checkbox',     'Multiple Choices'),
        ('text',         'Open-ended Text'),
    ], string='Type', default='text', required=True)

    preview_text = fields.Text(string='Preview Text', compute='_compute_preview_text')

    @api.depends('question_type', 'option_ids')
    def _compute_preview_text(self):
        for rec in self:
            if rec.question_type == 'text':
                rec.preview_text = "Example: [Employee enters their detailed text response here...]"
            else:
                rec.preview_text = ""
    section = fields.Char(string='Section', help='Group heading for the portal form', translate=True)

    option_ids = fields.One2many(
        'hr.exit.interview.question.option', 'question_id',
        string='Options',
        help='Define selectable options for Custom/Multiple Choice types.')
    is_mandatory = fields.Boolean(string='Mandatory', default=False)
    active = fields.Boolean(string='Active', default=True)

    def action_delete_question(self):
        self.ensure_one()
        self.write({'active': False})
        return {'type': 'ir.actions.act_window_close'}

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)

    def write(self, vals):
        return super().write(vals)


class HrExitInterviewQuestionOption(models.Model):
    _name = 'hr.exit.interview.question.option'
    _description = 'Exit Interview Question Option'
    _order = 'sequence, id'

    question_id = fields.Many2one('hr.exit.interview.question', string='Question', ondelete='cascade', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Option Text', required=True, translate=True)



class HrExitInterview(models.Model):
    _name = 'hr.exit.interview'
    _description = 'Exit Interview'
    _rec_name = 'employee_id'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    resignation_id = fields.Many2one('hr.resignation', ondelete='cascade')
    employee_id    = fields.Many2one('hr.employee', required=True)
    interview_date = fields.Date(default=fields.Date.context_today)
    template_id    = fields.Many2one('hr.exit.interview.template', string='Template', required=True)
    
    interviewer_id = fields.Many2one('res.users', string='Conducted By', default=lambda self: self.env.user)

    # Dynamic Response Lines
    line_ids = fields.One2many('hr.exit.interview.line', 'interview_id', string='Response Lines')

    # Specific fields matching user mockup exactly (Deprecated - kept for legacy data/view compilation compatibility)
    work_environment_rating = fields.Selection([
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor')
    ], string='Work Environment Rating (Deprecated)')
    
    would_recommend = fields.Boolean(string='Would Recommend (Deprecated)')
    
    primary_reason = fields.Text(string='Primary Reason (Deprecated)')
    feedback_management = fields.Text(string='Feedback on Management (Deprecated)')
    suggestions = fields.Text(string='Suggestions (Deprecated)')

    # Related Labels from Template (Deprecated)
    rating_label = fields.Char(related='template_id.rating_label')
    recommend_label = fields.Char(related='template_id.recommend_label')
    text_1_label = fields.Char(related='template_id.text_1_label')
    text_2_label = fields.Char(related='template_id.text_2_label')
    text_3_label = fields.Char(related='template_id.text_3_label')

    # Legacy fields to prevent OwlError for users with cached/zombie views
    answered_count = fields.Integer(string='Answered (Legacy)')
    total_count = fields.Integer(string='Total (Legacy)')
    progress_pct = fields.Float(string='Progress (Legacy)')
    notes = fields.Text(string='Interviewer Notes (Legacy)')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('completed',  'Submitted'),
    ], default='draft', tracking=True)

    can_edit = fields.Boolean(compute='_compute_can_edit')

    @api.depends_context('uid')
    def _compute_can_edit(self):
        for rec in self:
            is_employee = (rec.employee_id.user_id == self.env.user)
            rec.can_edit = is_employee and rec.state == 'draft'

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            lines = []
            for question in self.template_id.question_ids:
                lines.append((0, 0, {
                    'question_id': question.id,
                    'sequence': question.sequence,
                    'question_name': question.name,
                    'question_type': question.question_type,
                    'section': question.section,
                    'is_mandatory': question.is_mandatory,
                }))
            self.line_ids = [(5, 0, 0)] + lines

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('template_id') and not vals.get('line_ids'):
                template = self.env['hr.exit.interview.template'].browse(vals['template_id'])
                lines = []
                for question in template.question_ids:
                    lines.append((0, 0, {
                        'question_id': question.id,
                        'sequence': question.sequence,
                        'question_name': question.name,
                        'question_type': question.question_type,
                        'section': question.section,
                        'is_mandatory': question.is_mandatory,
                    }))
                vals['line_ids'] = lines
        return super().create(vals_list)

    def write(self, vals):
        if 'template_id' in vals and 'line_ids' not in vals:
            template = self.env['hr.exit.interview.template'].browse(vals['template_id'])
            lines = [(5, 0, 0)]
            for question in template.question_ids:
                lines.append((0, 0, {
                    'question_id': question.id,
                    'sequence': question.sequence,
                    'question_name': question.name,
                    'question_type': question.question_type,
                    'section': question.section,
                    'is_mandatory': question.is_mandatory,
                }))
            vals['line_ids'] = lines
        return super().write(vals)

    def init(self):
        super().init()
        # Ensure SQL tables are created before running migration
        self.env.cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'hr_exit_interview_question'")
        if self.env.cr.fetchone():
            # 1. Create questions for templates that don't have questions yet (exclude default template which is handled by data XML)
            templates = self.env['hr.exit.interview.template'].search([])
            default_template = self.env.ref('hr_resignation.default_exit_interview_template', raise_if_not_found=False)
            for template in templates:
                if (default_template and template.id == default_template.id) or template.name == 'Standard Exit Interview':
                    continue
                if not template.question_ids:
                    self.env['hr.exit.interview.question'].create([
                        {
                            'template_id': template.id,
                            'sequence': 10,
                            'name': template.rating_label or 'Work Environment Rating',
                            'question_type': 'rating',
                        },
                        {
                            'template_id': template.id,
                            'sequence': 20,
                            'name': template.recommend_label or 'Would Recommend the Bank to Others?',
                            'question_type': 'boolean',
                        },
                        {
                            'template_id': template.id,
                            'sequence': 30,
                            'name': template.text_1_label or 'PRIMARY REASON FOR LEAVING',
                            'question_type': 'text',
                        },
                        {
                            'template_id': template.id,
                            'sequence': 40,
                            'name': template.text_2_label or 'FEEDBACK ON MANAGEMENT AND WORK EXPERIENCE',
                            'question_type': 'text',
                        },
                        {
                            'template_id': template.id,
                            'sequence': 50,
                            'name': template.text_3_label or 'SUGGESTIONS FOR IMPROVEMENT',
                            'question_type': 'text',
                        },
                    ])

            # 2. Clean up duplicate questions that don't have XML IDs on the default template to heal database duplicates using SQL
            self.env.cr.execute("""
                WITH ranked_questions AS (
                    SELECT q.id,
                           ROW_NUMBER() OVER (
                               PARTITION BY q.template_id, q.name 
                               ORDER BY CASE WHEN m.id IS NOT NULL THEN 1 ELSE 0 END DESC, q.id ASC
                           ) as rn
                    FROM hr_exit_interview_question q
                    JOIN hr_exit_interview_template t ON q.template_id = t.id
                    LEFT JOIN ir_model_data m ON m.model = 'hr.exit.interview.question' AND m.res_id = q.id AND m.module = 'hr_resignation'
                    WHERE t.name->>'en_US' = 'Standard Exit Interview'
                       OR t.name->>'en' = 'Standard Exit Interview'
                       OR t.name->>'' = 'Standard Exit Interview'
                )
                DELETE FROM hr_exit_interview_question
                WHERE id IN (SELECT id FROM ranked_questions WHERE rn > 1);
            """)

        self.env.cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'hr_exit_interview_line'")
        if self.env.cr.fetchone():
            # Check if 'answer' column exists before doing ORM actions on hr.exit.interview.line
            self.env.cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'hr_exit_interview_line' AND column_name = 'answer';")
            has_answer_column = bool(self.env.cr.fetchone())

            # 3. Populate response lines for exit interviews that have no lines yet (migration from old columns)
            if has_answer_column:
                interviews = self.env['hr.exit.interview'].search([('line_ids', '=', False)])
                for interview in interviews:
                    template = interview.template_id
                    if not template:
                        template = self.env['hr.exit.interview.template'].search([], limit=1)
                    
                    if template:
                        lines = []
                        for question in template.question_ids:
                            val_dict = {
                                'interview_id': interview.id,
                                'question_id': question.id,
                                'sequence': question.sequence,
                                'question_name': question.name,
                                'question_type': question.question_type,
                                'section': question.section,
                            }
                            if question.question_type == 'rating':
                                val_dict['rating_value'] = interview.work_environment_rating
                            elif question.question_type == 'boolean':
                                val_dict['boolean_value'] = 'yes' if interview.would_recommend else 'no'
                            elif question.question_type == 'text':
                                if question.sequence == 30:
                                    val_dict['text_value'] = interview.primary_reason
                                elif question.sequence == 40:
                                    val_dict['text_value'] = interview.feedback_management
                                elif question.sequence == 50:
                                    val_dict['text_value'] = interview.suggestions
                                else:
                                    val_dict['text_value'] = ''
                            lines.append(val_dict)
                        if lines:
                            self.env['hr.exit.interview.line'].create(lines)

            # 4. Clean up duplicate lines in existing interviews to fix historical duplicate issues via SQL (ORM-safe)
            self.env.cr.execute("""
                WITH ranked_lines AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY interview_id, question_name 
                               ORDER BY CASE WHEN rating_value IS NOT NULL 
                                                OR boolean_value IS NOT NULL 
                                                OR text_value IS NOT NULL THEN 1 ELSE 0 END DESC, id ASC
                           ) as rn
                    FROM hr_exit_interview_line
                )
                DELETE FROM hr_exit_interview_line 
                WHERE id IN (SELECT id FROM ranked_lines WHERE rn > 1);
            """)

    def action_open_portal_interview(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/exit_interview/{self.id}',
            'target': 'new',
        }

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('This interview has already been submitted.'))
            
            unanswered_mandatory = rec.line_ids.filtered(lambda l: l.is_mandatory and not l.answer)
            if unanswered_mandatory:
                questions = ', '.join(unanswered_mandatory.mapped('question_name'))
                raise UserError(_('Please answer the following mandatory questions:\n\n%s') % questions)
                
            rec.state = 'completed'
            if rec.resignation_id and rec.resignation_id.state == 'last_day_recorded':
                rec.resignation_id.state = 'exit_interviewed'
                rec.resignation_id._check_and_advance_cleared()

            # Notify HR and the employee via Discuss popup — no chatter clutter.
            resignation = rec.resignation_id
            if resignation:
                notify_partners = set()

                emp_user = resignation.employee_id.sudo().user_id
                if emp_user and emp_user.active:
                    notify_partners.add(emp_user.partner_id.id)

                hr_group = self.env.ref('hr.group_hr_user', raise_if_not_found=False)
                if hr_group:
                    for u in hr_group.sudo().all_user_ids.filtered(lambda u: u.active):
                        notify_partners.add(u.partner_id.id)

                if notify_partners:
                    resignation.message_notify(
                        partner_ids=list(notify_partners),
                        subject=_('Exit Interview Submitted: %s') % resignation.name,
                        body=_(
                            'The exit interview for <strong>%s</strong> (%s) has been submitted '
                            'by %s. The case is now proceeding to Clearance.'
                        ) % (
                            resignation.employee_id.sudo().name,
                            resignation.name,
                            self.env.user.name,
                        ),
                    )

    def action_reset_to_draft(self):
        for rec in self:
            rec.state = 'draft'
            rec.message_post(body=_('Exit Interview reset to draft.'))

    def action_open_interview(self):
        self.ensure_one()
        return {
            'name':      _('Exit Interview'),
            'type':      'ir.actions.act_window',
            'res_model': 'hr.exit.interview',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
            'context':   {'dialog_size': 'extra-large'},
        }

    @api.model
    def get_dashboard_data(self):
        """ Fetch and aggregate exit interview data for the advanced HR dashboard. """
        from datetime import date
        import re
        from collections import Counter

        interviews_done = self.env['hr.exit.interview'].search([('state', '=', 'completed')])
        lines = self.env['hr.exit.interview.line'].search([('interview_id', 'in', interviews_done.ids)])

        total = len(interviews_done)
        today = date.today()
        this_month = len(interviews_done.filtered(
            lambda i: i.interview_date and i.interview_date.month == today.month and i.interview_date.year == today.year
        ))
        dept_ids = interviews_done.mapped('employee_id.department_id').ids
        dept_count = len(set(dept_ids))

        questions = {}
        for line in lines:
            if not line.question_id:
                continue
            qid = line.question_id.id
            if qid not in questions:
                questions[qid] = {
                    'question_name': line.question_name.strip() if line.question_name else '',
                    'question_type': line.question_type,
                    'lines': [],
                }
            questions[qid]['lines'].append(line)

        charts = []
        likerts = []
        all_text = []
        all_rating_scores = []

        for idx, (qid, q_data) in enumerate(questions.items()):
            q_type = q_data['question_type']
            q_lines = q_data['lines']
            q_name = q_data['question_name']

            if q_type in ('custom', 'checkbox', 'boolean', 'boolean_agree'):
                options_counts = {}
                for line in q_lines:
                    selected = []
                    if q_type == 'custom' and line.choice_id:
                        selected.append(line.choice_id.name)
                    elif q_type == 'checkbox' and line.choice_ids:
                        selected.extend(line.choice_ids.mapped('name'))
                    elif q_type == 'boolean':
                        selected.append('Yes' if line.boolean_value else 'No')
                    elif q_type == 'boolean_agree':
                        label_map = {'yes': 'Agree', 'no': 'Disagree', True: 'Yes', False: 'No'}
                        v = line.boolean_value
                        selected.append(label_map.get(v, str(v)))
                    for s in selected:
                        if s:
                            options_counts[s] = options_counts.get(s, 0) + 1

                if options_counts:
                    sorted_opts = sorted(options_counts.items(), key=lambda x: x[1], reverse=True)
                    labels = [x[0] for x in sorted_opts]
                    data_vals = [x[1] for x in sorted_opts]
                    chart_type = 'doughnut' if len(labels) <= 4 else 'bar'
                    title = q_name if len(q_name) <= 50 else q_name[:47] + '...'
                    charts.append({
                        'id': str(idx),
                        'title': title,
                        'subtitle': f"{q_type.replace('_', ' ').title()} · {sum(data_vals)} responses",
                        'labels': labels,
                        'data': data_vals,
                        'type': chart_type,
                    })

            elif q_type in ('rating', 'satisfaction', 'agreement'):
                total_score = 0
                count = 0
                for line in q_lines:
                    val = (line.rating_value if q_type == 'rating' else
                           (line.satisfaction_value if q_type == 'satisfaction' else line.agreement_value))
                    if val:
                        try:
                            total_score += int(val)
                            count += 1
                        except (ValueError, TypeError):
                            pass
                if count > 0:
                    avg = round(total_score / count, 2)
                    all_rating_scores.append(avg)
                    likerts.append({'label': q_name, 'v': avg})

            elif q_type == 'text':
                for ln in q_lines:
                    if ln.text_value and ln.text_value.strip():
                        all_text.append(ln.text_value.strip())

        # NLP Simulation for Themes
        themes = []
        if all_text:
            stop_words = {'the', 'a', 'to', 'and', 'was', 'is', 'in', 'of', 'for', 'it', 'my', 'i', 'with', 'that', 'this', 'on', 'not', 'have', 'be', 'as', 'but', 'are', 'at', 'very', 'they'}
            words = []
            for text in all_text:
                # clean and split
                cleaned = re.sub(r'[^a-zA-Z\s]', '', text).lower()
                for w in cleaned.split():
                    if w not in stop_words and len(w) > 3:
                        words.append(w.capitalize())
            
            # Count common meaningful words
            word_counts = Counter(words)
            for w, c in word_counts.most_common(12):
                if c >= 1:
                    themes.append({'t': w, 'n': c})

        avg_rating_raw = round(sum(all_rating_scores) / len(all_rating_scores), 1) if all_rating_scores else 0
        avg_rating_display = str(avg_rating_raw) if avg_rating_raw else '–'

        return {
            'meta': {
                'total': total,
                'this_month': this_month,
                'dept_count': dept_count,
                'avg_rating': avg_rating_display,
                'avg_rating_raw': avg_rating_raw,
            },
            'charts': charts,
            'likerts': likerts,
            'themes': themes,
        }

class HrExitInterviewLine(models.Model):
    _name = 'hr.exit.interview.line'
    _description = 'Exit Interview Response Line'
    _order = 'sequence, id'

    interview_id = fields.Many2one('hr.exit.interview', string='Exit Interview', required=True, ondelete='cascade')
    question_id = fields.Many2one('hr.exit.interview.question', string='Question Template', ondelete='set null')
    available_option_ids = fields.One2many(related='question_id.option_ids')
    sequence = fields.Integer(string='Sequence', default=10)
    section = fields.Char(string='Section', translate=True)
    question_name = fields.Char(string='Question', required=True, translate=True)
    is_mandatory = fields.Boolean(string='Mandatory', default=False)
    question_type = fields.Selection([
        ('rating',       'Rating'),
        ('satisfaction', 'Satisfaction'),
        ('agreement',    'Agreement'),
        ('boolean',      'Yes / No'),
        ('boolean_agree','Agree / Disagree'),
        ('custom',       'Custom Choices'),
        ('checkbox',     'Multiple Choices'),
        ('text',         'Open-ended Text'),
    ], string='Question Type', required=True)

    rating_value = fields.Selection([
        ('excellent', 'Excellent'),
        ('good',      'Good'),
        ('fair',      'Fair'),
        ('poor',      'Poor'),
    ], string='Rating')

    satisfaction_value = fields.Selection([
        ('very_satisfied',    'Very Satisfied'),
        ('satisfied',         'Satisfied'),
        ('neutral',           'Neutral'),
        ('dissatisfied',      'Dissatisfied'),
        ('very_dissatisfied', 'Very Dissatisfied'),
    ], string='Satisfaction')

    agreement_value = fields.Selection([
        ('strongly_agree',    'Strongly Agree'),
        ('agree',             'Agree'),
        ('disagree',          'Disagree'),
        ('strongly_disagree', 'Strongly Disagree'),
    ], string='Agreement')

    boolean_value = fields.Selection([
        ('yes', 'Yes'),
        ('no',  'No'),
    ], string='Yes / No')

    boolean_agree_value = fields.Selection([
        ('agree',    'Agree'),
        ('disagree', 'Disagree'),
    ], string='Agree / Disagree')

    choice_id = fields.Many2one(
        'hr.exit.interview.question.option',
        string='Selected Option',
        domain="[('question_id', '=', question_id)]")

    choice_ids = fields.Many2many(
        'hr.exit.interview.question.option',
        'exit_interview_line_option_rel',
        'line_id', 'option_id',
        string='Selected Options',
        domain="[('question_id', '=', question_id)]")

    text_value = fields.Text(string='Response')

    answer = fields.Char(string='Answer', compute='_compute_answer', store=True)

    @api.depends('question_type', 'rating_value', 'satisfaction_value',
                 'agreement_value', 'boolean_value', 'boolean_agree_value',
                 'choice_id', 'choice_ids', 'choice_ids.name', 'text_value')
    def _compute_answer(self):
        for rec in self:
            if rec.question_type == 'rating':
                rec.answer = dict(rec._fields['rating_value'].selection).get(rec.rating_value, '')
            elif rec.question_type == 'satisfaction':
                rec.answer = dict(rec._fields['satisfaction_value'].selection).get(rec.satisfaction_value, '')
            elif rec.question_type == 'agreement':
                rec.answer = dict(rec._fields['agreement_value'].selection).get(rec.agreement_value, '')
            elif rec.question_type == 'boolean':
                rec.answer = dict(rec._fields['boolean_value'].selection).get(rec.boolean_value, '')
            elif rec.question_type == 'boolean_agree':
                rec.answer = dict(rec._fields['boolean_agree_value'].selection).get(rec.boolean_agree_value, '')
            elif rec.question_type == 'custom':
                rec.answer = rec.choice_id.name or ''
            elif rec.question_type == 'checkbox':
                rec.answer = ', '.join(rec.choice_ids.mapped('name'))
            elif rec.question_type == 'text':
                rec.answer = rec.text_value or ''
            else:
                rec.answer = ''
