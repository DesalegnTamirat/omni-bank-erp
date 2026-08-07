# -*- coding: utf-8 -*-
import logging
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EdsCurriculum(models.Model):
    """Curriculum / course design document (FREDS014-019, FR-EDS-011...013).

    Approval chain: L&D Quality Review -> Director PPDD -> CPCO Approval (FREDS016).
    Revision returns the curriculum to the originating officer for update and
    resubmission with comment history (FREDS017). Editing an approved curriculum
    creates a new version and archives the previous one (FREDS019).
    """
    _name = 'eds.curriculum'
    _description = 'Curriculum / Course Design'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    course_id = fields.Many2one('eds.course', string='Course', required=True, ondelete='cascade',
                                tracking=True)
    version = fields.Char(string='Version', default='v1.0', required=True, tracking=True)
    learning_objectives = fields.Text(string='Learning Objectives', required=True)
    assessment_method = fields.Text(string='Assessment Method')
    # copy=True: a new version must deep-copy its modules (FREDS019)
    module_ids = fields.One2many('eds.curriculum.module', 'curriculum_id', string='Modules', copy=True)
    sme_ids = fields.Many2many(
        'res.users', string='Subject Matter Experts', tracking=True)
    review_sla_deadline = fields.Date(
        string='Review SLA Deadline', compute='_compute_review_sla', store=True,
        help='Computed from the curriculum SLA in settings (default 10 working days, FREDS014).')
    sla_breached = fields.Boolean(
        string='SLA Breached', compute='_compute_sla_breached', store=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('quality_review', 'L&D Quality Review'),
        ('director_validation', 'Director PPDD Validation'),
        ('cpco_approval', 'CPCO Approval'),
        ('approved', 'Approved'),
        ('revision', 'Revision'),
    ], string='Status', default='draft', required=True, tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    revision_comment = fields.Text(string='Revision Comment')
    approval_history_ids = fields.One2many(
        'eds.approval.history', 'curriculum_id', string='Approval History',
        domain=[('model', '=', 'eds.curriculum')])
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    active = fields.Boolean(string='Active', default=True,
                            help='Archived when superseded by a newer version (FREDS019).')

    _sql_constraints = [
        ('course_version_uniq', 'unique(course_id, version)',
         'A curriculum version already exists for this course!'),
    ]

    @api.depends('create_date')
    def _compute_review_sla(self):
        for rec in self:
            if rec.create_date:
                days = rec._get_int_param('eds.curriculum_sla_days', 10)
                rec.review_sla_deadline = self.env['eds.tna.cycle']._add_working_days(
                    rec.create_date.date(), days)
            else:
                rec.review_sla_deadline = False

    @api.depends('review_sla_deadline', 'state')
    def _compute_sla_breached(self):
        today = date.today()
        for rec in self:
            rec.sla_breached = bool(
                rec.review_sla_deadline and rec.review_sla_deadline < today
                and rec.state in ('draft', 'quality_review', 'director_validation', 'cpco_approval'))

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.curriculum') or _('New')
        return super().create(vals_list)

    # ── Approval chain (FREDS016) ────────────────────────────────────────────
    def _log_approval_step(self, state_from, state_to, comment=''):
        self.env['eds.approval.history'].create({
            'curriculum_id': self.id,
            'state_from': state_from,
            'state_to': state_to,
            'comment': comment or _('Moved %s -> %s') % (state_from, state_to),
        })

    def action_submit_quality_review(self):
        """Draft -> L&D Quality Review (FREDS016 step 1)."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft curricula can be submitted to quality review.'))
            if not rec.module_ids:
                raise UserError(_('Add at least one curriculum module before submitting.'))
            rec.state = 'quality_review'
            rec._log_approval_step('draft', 'quality_review')
            rec.message_post(body=_('Curriculum %s submitted to L&D Quality Review. SLA: %s (FREDS014).')
                             % (rec.name, rec.review_sla_deadline))

    def action_quality_approve(self):
        """L&D Quality Review -> Director PPDD Validation."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'quality_review':
                raise UserError(_('Only curricula under quality review can move to Director validation.'))
            rec.state = 'director_validation'
            rec._log_approval_step('quality_review', 'director_validation')
            rec.message_post(body=_('Curriculum %s approved by L&D Quality Review, sent to Director PPDD validation.')
                             % rec.name)

    def action_director_validate(self):
        """Director PPDD Validation -> CPCO Approval."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'director_validation':
                raise UserError(_('Only curricula under Director validation can move to CPCO approval.'))
            rec.state = 'cpco_approval'
            rec._log_approval_step('director_validation', 'cpco_approval')
            rec.message_post(body=_('Curriculum %s validated by Director PPDD, sent to CPCO for approval.')
                             % rec.name)

    def action_cpco_approve(self):
        """CPCO Approval -> Approved. On approval: sync course version, insert into the
        draft annual plan (FREDS018) and route e-learning needs to the LMS (Task 13)."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'cpco_approval':
                raise UserError(_('Only curricula under CPCO approval can be approved.'))
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec._log_approval_step('cpco_approval', 'approved', _('Approved by CPCO'))
            rec.message_post(body=_('Curriculum %s approved by CPCO (FREDS016).') % rec.name)
            rec._on_curriculum_approved()

    def _on_curriculum_approved(self):
        """FREDS018 + Task 13 contract hooks, defensive against modules not yet installed."""
        self.ensure_one()
        # Sync the course current version + activate it
        self.course_id.write({'version': self.version, 'status': 'active'})
        # (a) Insert into the draft annual plan - eds.annual.plan arrives in Task 5.
        plan_model = self.env.registry.get('eds.annual.plan')
        if plan_model and hasattr(plan_model, '_add_approved_curriculum'):
            try:
                self.env['eds.annual.plan']._add_approved_curriculum(self)
            except Exception as exc:
                _logger.warning('Annual plan insert failed for curriculum %s: %s', self.name, exc)
        # (b) e-learning / blended needs -> LMS routing shell (Task 13 contract)
        e_learning = self.course_id.development_request_ids.mapped('tna_entry_ids').filtered(
            lambda e: e.delivery_mode in ('e_learning', 'blended') and e.state != 'excluded')
        if e_learning:
            routing_model = self.env.registry.get('eds.lms.routing')
            if routing_model:
                try:
                    self.env['eds.lms.routing'].create({
                        'curriculum_id': self.id,
                        'source': 'curriculum',
                    })
                except Exception as exc:
                    _logger.warning('LMS routing creation failed for curriculum %s: %s', self.name, exc)

    def action_request_revision(self):
        """Approved -> Revision (FREDS017): return to the originating officer for update,
        then create a new version (FREDS019) archived from the old one."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'approved':
                raise UserError(_('Only approved curricula can be sent for revision.'))
            if not rec.revision_comment:
                raise UserError(_('A revision comment is required before returning the curriculum (FREDS017).'))
            # Version control (FREDS019): copy to a new version, archive the previous
            new_version = rec._bump_version(rec.version)
            new_curriculum = rec.copy(default={
                'version': new_version,
                'state': 'revision',
                'revision_comment': rec.revision_comment,
                'approved_by_id': False,
                'approval_date': False,
                'course_id': rec.course_id.id,
            })
            rec.write({'active': False})
            rec._log_approval_step('approved', 'revision', rec.revision_comment)
            rec.message_post(body=_('Curriculum %s returned for revision (FREDS017). New version %s created.')
                             % (rec.name, new_version))
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'eds.curriculum',
                'res_id': new_curriculum.id,
                'view_mode': 'form',
            }

    def action_resubmit_revision(self):
        """Revision -> Quality Review: the officer updates and resubmits (FREDS017)."""
        for rec in self:
            if rec.state != 'revision':
                raise UserError(_('Only curricula under revision can be resubmitted.'))
            rec.state = 'quality_review'
            rec._log_approval_step('revision', 'quality_review', _('Resubmitted after revision'))
            rec.message_post(body=_('Revised curriculum %s resubmitted to L&D Quality Review.') % rec.name)

    def _require_manager(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This approval step requires L&D Manager authority (FREDS016).'))

    @staticmethod
    def _bump_version(version):
        try:
            major, minor = version.lower().lstrip('v').split('.')
            return 'v%s.%s' % (major, int(minor) + 1)
        except Exception:
            return 'v1.1'


class EdsCurriculumModule(models.Model):
    """One module inside a curriculum design (FREDS015)."""
    _name = 'eds.curriculum.module'
    _description = 'Curriculum Module'
    _order = 'sequence, id'

    curriculum_id = fields.Many2one('eds.curriculum', string='Curriculum', required=True,
                                    ondelete='cascade')
    sequence = fields.Integer(string='Order', default=10)
    name = fields.Char(string='Module Name', required=True)
    duration_hours = fields.Float(string='Duration (Hours)', default=1.0)
    content_ids = fields.Many2many(
        'ir.attachment', string='Content / Materials',
        help='Module content attachments (slides, manuals, exercises).')
