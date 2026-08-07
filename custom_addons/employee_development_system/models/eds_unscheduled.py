# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsUnscheduledRequest(models.Model):
    """Ad-hoc / unscheduled training request (FREDS075/076, FREDS026).

    Classroom training must originate from the approved TNA; any unscheduled request
    is the documented exception - it requires a mandatory justification and L&D
    approval. Once approved, the request is appended to the target annual plan as an
    authorized addendum line (FREDS026), creating a session for delivery.
    """
    _name = 'eds.unscheduled.request'
    _description = 'Unscheduled Training Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Requested By', tracking=True)
    work_unit_id = fields.Many2one('operating.unit', string='Work Unit')
    department_id = fields.Many2one('hr.department', string='Department')
    course_id = fields.Many2one('eds.course', string='Training Program',
                                domain=[('status', 'in', ('draft', 'active'))])
    program_name = fields.Char(string='Program Name',
                               help='Free-text program when it is not in the course catalog.')
    justification = fields.Text(string='Justification', required=True,
                                help='Mandatory - ad-hoc requests must be justified and approved '
                                     'by L&D (business rule / FREDS075).')
    reason = fields.Selection([
        ('urgent_operational', 'Urgent Operational Need'),
        ('regulatory', 'New Regulatory Requirement'),
        ('emergency_gap', 'Emergency Competency Gap'),
        ('opportunity', 'Time-Bound Opportunity'),
        ('other', 'Other'),
    ], string='Reason', default='urgent_operational', required=True)
    requested_date_start = fields.Date(string='Requested Start Date')
    requested_date_end = fields.Date(string='Requested End Date')
    estimated_cost = fields.Monetary(string='Estimated Cost',
                                     currency_field='company_currency_id')
    delivery_mode = fields.Selection([
        ('classroom', 'Classroom'),
        ('e_learning', 'E-Learning'),
        ('blended', 'Blended'),
    ], string='Delivery Mode', default='classroom', required=True)
    annual_plan_id = fields.Many2one(
        'eds.annual.plan', string='Annual Plan',
        domain="[('state', 'in', ('draft', 'published', 'amended'))]",
        help='Target annual plan the approved request is appended to as an addendum '
             '(FREDS026).')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('lnd_approved', 'L&D Approved'),
        ('director_approved', 'Director PPDD Approved'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, tracking=True)
    rejected_reason = fields.Text(string='Rejection Reason')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    company_currency_id = fields.Many2one('res.currency', related='company_id.currency_id',
                                          readonly=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.onchange('course_id')
    def _onchange_course_id(self):
        if self.course_id:
            self.program_name = self.course_id.name

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.department_id = self.employee_id.department_id
            if not self.work_unit_id and hasattr(self.employee_id, 'default_operating_unit_id'):
                self.work_unit_id = self.employee_id.default_operating_unit_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.unscheduled.request') or _('New')
        return super().create(vals_list)

    # ── Workflow (FREDS075/076) ──────────────────────────────────────────────
    def action_submit(self):
        """Draft -> Submitted: request enters the approval chain."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            if not rec.justification:
                raise UserError(_('A justification is mandatory for unscheduled training '
                                  'requests (FREDS075).'))
            rec.state = 'submitted'
            rec.message_post(body=_('Unscheduled request %s submitted for L&D approval '
                                    '(FREDS075).') % rec.name)

    def action_lnd_approve(self):
        """Submitted -> L&D Approved."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'submitted':
                raise UserError(_('Only submitted requests can be approved by L&D.'))
            rec.state = 'lnd_approved'
            rec.message_post(body=_('Unscheduled request %s approved by L&D.') % rec.name)

    def action_director_approve(self):
        """L&D Approved -> Director PPDD Approved."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'lnd_approved':
                raise UserError(_('Only L&D-approved requests can move to Director PPDD.'))
            rec.state = 'director_approved'
            rec.message_post(body=_('Unscheduled request %s approved by Director PPDD.')
                             % rec.name)

    def action_approve(self):
        """Director PPDD Approved -> Approved: append the addendum line to the annual plan
        and create its draft session (FREDS026/076)."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'director_approved':
                raise UserError(_('Only Director-approved requests can be finally approved.'))
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec._append_addendum()
            rec.message_post(body=_('Unscheduled request %s approved - appended to the annual '
                                    'plan as an addendum (FREDS076).') % rec.name)

    def _append_addendum(self):
        """Create an addendum plan line (and its session) on the target annual plan."""
        self.ensure_one()
        plan = self.annual_plan_id
        if not plan:
            return
        if plan.state == 'published':
            plan.action_amend()
        line = self.env['eds.annual.plan.line'].create({
            'plan_id': plan.id,
            'course_id': self.course_id.id if self.course_id else False,
            'program_name': self.program_name or (self.course_id.name if self.course_id else ''),
            'delivery_method': 'internal' if self.delivery_mode == 'classroom' else 'local_external',
            'budget_allocated': self.estimated_cost or 0.0,
            'is_addendum': True,
        })
        line._create_default_session()

    def action_reject(self):
        """Submitted -> Rejected (with mandatory reason)."""
        for rec in self:
            if rec.state not in ('submitted', 'lnd_approved', 'director_approved'):
                raise UserError(_('Only pending requests can be rejected.'))
            if not rec.rejected_reason:
                raise UserError(_('A rejection reason is required (FREDS075).'))
            rec.state = 'rejected'
            rec.message_post(body=_('Unscheduled request %s rejected: %s')
                             % (rec.name, rec.rejected_reason))

    def _require_manager(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This approval step requires L&D Manager authority (FREDS075).'))
