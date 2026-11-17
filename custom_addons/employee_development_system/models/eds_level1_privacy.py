"""Level 1 completion tracking without exposing participant answers to staff."""

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


_ROSTER_GROUPS = (
    'employee_development_system.group_eds_team_leader',
    'employee_development_system.group_eds_director',
    'employee_development_system.group_eds_chief',
    'employee_development_system.group_eds_cpco',
    'employee_development_system.group_eds_smc',
    'employee_development_system.group_eds_admin',
    'employee_development_system.group_eds_executive',
)
_ROSTER_FIELD_GROUPS = ','.join(_ROSTER_GROUPS)


class EdsLevel1Notification(models.Model):
    _inherit = 'eds.evaluation.level1'

    notification_sent_at = fields.Datetime(
        string='Survey Notice Sent', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        # Staff must not become followers of a survey they distribute.
        return super(EdsLevel1Notification, self.with_context(
            tracking_disable=True)).create(vals_list)

    def write(self, vals):
        # State tracking would tell an L&D follower who submitted feedback.
        return super(EdsLevel1Notification, self.with_context(
            tracking_disable=True)).write(vals)

    def message_post(self, *args, **kwargs):
        # Notifications go only to the explicit recipient of a survey notice.
        kwargs['notify_skip_followers'] = True
        return super().message_post(*args, **kwargs)


class EdsSessionLevel1Privacy(models.Model):
    _inherit = 'eds.session'

    level1_received_count = fields.Integer(
        string='Surveys Sent', compute='_compute_level1_completion_counts')
    level1_submitted_count = fields.Integer(
        string='Filled', compute='_compute_level1_completion_counts')
    level1_pending_count = fields.Integer(
        string='Not Filled', compute='_compute_level1_completion_counts')
    level1_completion_roster_ids = fields.One2many(
        'eds.enrollment', 'session_id', string='Survey Completion Roster',
        domain=[('state', 'in', ('completed', 'incomplete'))],
        groups=_ROSTER_FIELD_GROUPS, readonly=True)

    @api.depends('level1_feedback_ids.state')
    def _compute_level1_completion_counts(self):
        counts = {session.id: [0, 0] for session in self}
        if counts:
            # The user sees only totals. The privileged read never returns
            # answer rows, respondent IDs, or per-person scores to the client.
            surveys = self.env['eds.evaluation.level1'].sudo().search([
                ('session_id', 'in', list(counts)),
            ])
            for survey in surveys:
                values = counts.get(survey.session_id.id)
                if values is not None:
                    values[0] += 1
                    if survey.state in ('submitted', 'consolidated'):
                        values[1] += 1
        for session in self:
            sent, filled = counts.get(session.id, (0, 0))
            session.level1_received_count = sent
            session.level1_submitted_count = filled
            session.level1_pending_count = sent - filled

    @api.depends('level1_feedback_ids')
    def _compute_level1_questions_locked(self):
        Survey = self.env['eds.evaluation.level1'].sudo()
        for session in self:
            session.level1_questions_locked = bool(Survey.search_count([
                ('session_id', '=', session.id),
            ]))

    def action_prepare_level1_questions(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        if self.env['eds.evaluation.level1'].sudo().search_count([
            ('session_id', '=', self.id),
        ]):
            raise UserError(_(
                'Level 1 feedback has already been sent. Open the questions '
                'in view mode to see their original wording.'))
        return super().action_prepare_level1_questions()

    def _require_level1_completion_roster_access(self):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            if not any(self.env.user.has_group(group) for group in _ROSTER_GROUPS):
                raise AccessError(_(
                    'Only the Team Leader and higher review roles may see '
                    'who completed Level 1 feedback.'))
        self.check_access('read')

    def action_open_level1_completion_roster(self):
        self.ensure_one()
        self._require_level1_completion_roster_access()
        view = self.env.ref(
            'employee_development_system.view_eds_level1_completion_roster')
        return {
            'name': _('Level 1 Completion Roster'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.enrollment',
            'view_mode': 'list',
            'views': [(view.id, 'list')],
            'domain': [
                ('session_id', '=', self.id),
                ('state', 'in', ('completed', 'incomplete')),
            ],
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    def action_open_level1_feedback(self):
        """Retain the old button API without revealing answer records."""
        return self.action_open_level1_completion_roster()


class EdsEnrollmentLevel1Completion(models.Model):
    _inherit = 'eds.enrollment'

    level1_completion_status = fields.Selection([
        ('not_sent', 'Not Sent'),
        ('pending', 'Not Filled'),
        ('submitted', 'Filled'),
    ], string='Level 1 Feedback', compute='_compute_level1_completion_status',
        groups=_ROSTER_FIELD_GROUPS)

    @api.depends('session_id', 'employee_id', 'session_id.level1_feedback_ids.state')
    def _compute_level1_completion_status(self):
        pairs = {(row.session_id.id, row.employee_id.id) for row in self
                 if row.session_id and row.employee_id}
        statuses = {}
        if pairs:
            surveys = self.env['eds.evaluation.level1'].sudo().search([
                ('session_id', 'in', list({pair[0] for pair in pairs})),
                ('employee_id', 'in', list({pair[1] for pair in pairs})),
            ])
            statuses = {
                (survey.session_id.id, survey.employee_id.id):
                    ('submitted' if survey.state in ('submitted', 'consolidated')
                     else 'pending')
                for survey in surveys
            }
        for row in self:
            row.level1_completion_status = statuses.get(
                (row.session_id.id, row.employee_id.id), 'not_sent')


class EdsLevel1PrivateReport(models.AbstractModel):
    _name = 'report.employee_development_system.report_eds_level1_document'
    _description = 'Private Level 1 Reaction Survey Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        surveys = self.env['eds.evaluation.level1'].browse(docids).exists()
        if not self.env.su:
            surveys.check_access('read')
            if any(survey.employee_id.sudo().user_id != self.env.user
                   for survey in surveys):
                raise AccessError(_(
                    'Only the respondent can print a Level 1 reaction survey.'))
        return {
            'doc_ids': surveys.ids,
            'doc_model': 'eds.evaluation.level1',
            'docs': surveys,
        }
