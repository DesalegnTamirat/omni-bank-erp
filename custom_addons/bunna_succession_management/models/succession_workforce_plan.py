# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SuccessionManagerCareerDiscussion(models.Model):
    """
    Structured Career Discussion Record (FR-MHT-003).
    Managers document career discussions, guidance, agreed development
    actions, employee aspirations, and follow-up commitments.
    """
    _name = 'succession.career.discussion'
    _description = 'Manager Career Discussion Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'discussion_date desc'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Discussion', compute='_compute_display_name', store=True)

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        tracking=True, ondelete='restrict')
    manager_id = fields.Many2one(
        'hr.employee', string='Manager',
        default=lambda self: self.env.user.employee_id.parent_id,
        tracking=True)
    discussion_date = fields.Date(
        string='Discussion Date', required=True,
        default=fields.Date.today, tracking=True)
    discussion_type = fields.Selection([
        ('career_review', 'Career Development Review'),
        ('aspiration_alignment', 'Aspiration Alignment'),
        ('readiness_discussion', 'Readiness Discussion'),
        ('performance_career', 'Performance & Career Link'),
        ('succession_nomination', 'Succession Nomination Discussion'),
        ('annual_pdp', 'Annual PDP Review'),
    ], string='Discussion Type', required=True,
       default='career_review', tracking=True)

    # --- Discussion Content ---
    career_interests = fields.Text(
        string='Employee Career Interests & Aspirations',
        help="Record the employee's stated career interests discussed in this session.")
    manager_guidance = fields.Text(
        string='Manager Guidance & Expectations')
    strengths_discussed = fields.Text(string='Key Strengths Discussed')
    development_areas = fields.Text(string='Development Areas Identified')

    # --- Action Commitments ---
    agreed_actions = fields.Html(
        string='Agreed Development Actions',
        help='What actions were agreed upon (employee and manager commitments)?')
    follow_up_date = fields.Date(string='Follow-Up Review Date', tracking=True)
    follow_up_notes = fields.Text(string='Follow-Up Notes')

    # --- Outcome ---
    outcome = fields.Selection([
        ('on_track', 'On Track for Progression'),
        ('needs_development', 'Needs Further Development'),
        ('ready_for_promotion', 'Ready for Promotion / Succession'),
        ('change_of_direction', 'Career Direction Change Recommended'),
    ], string='Discussion Outcome', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed / Signed Off'),
    ], string='Status', default='draft', tracking=True)

    employee_acknowledgement = fields.Boolean(
        string='Employee Acknowledges This Record', default=False)

    @api.depends('employee_id', 'discussion_date', 'discussion_type')
    def _compute_display_name(self):
        for rec in self:
            emp = rec.employee_id.name if rec.employee_id else '?'
            dtype = dict(rec._fields['discussion_type'].selection).get(
                rec.discussion_type, '') if rec.discussion_type else ''
            date = rec.discussion_date.strftime('%d %b %Y') if rec.discussion_date else ''
            rec.display_name = '%s — %s (%s)' % (emp, dtype, date)

    def action_confirm(self):
        self.write({'state': 'confirmed'})
        self.message_post(body=_('Career discussion confirmed and signed off by %s.') % self.env.user.name)
