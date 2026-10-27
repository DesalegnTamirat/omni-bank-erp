# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .eds_currency_policy import currency_for_delivery, validate_delivery_currency
from .eds_action_notification import clear_action_activities, notify_action


class EdsUnscheduledRequest(models.Model):
    """Ad-hoc / unscheduled training request.

    Classroom training must originate from the approved TNA; any unscheduled request
    is the documented exception - it requires a mandatory justification and L&D
    approval. Once approved, the request is appended to the target annual plan as an
    authorized addendum line, creating a session for delivery.
    """
    _name = 'eds.unscheduled.request'
    _description = 'Unscheduled Training Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Requested By', tracking=True)
    contact_phone_email = fields.Char(string='Contact Phone / Email')
    work_unit_id = fields.Many2one('operating.unit', string='Work Unit')
    department_id = fields.Many2one('hr.department', string='Department')
    job_position_id = fields.Many2one('hr.job', string='Job Position')
    unit_head_id = fields.Many2one('hr.employee', string='Unit Head')

    course_id = fields.Many2one('eds.course', string='Training Program',
                                domain=[('status', 'in', ('draft', 'active'))])
    program_name = fields.Char(string='Program Name',
                               readonly=True, help='Catalog course name retained for reports.')
    plan_line_ids = fields.One2many(
        'eds.annual.plan.line', 'unscheduled_request_id',
        string='Approved Addendum Programs', readonly=True)
    proposed_dates_text = fields.Char(string='Proposed Dates Text')
    participant_count = fields.Integer(string='No. of Participants', default=1)
    preferred_provider = fields.Char(string='Preferred Provider')
    duration_text = fields.Char(string='Duration (Days / Hours)')
    urgency_category = fields.Selection([
        ('urgent_2weeks', 'Urgent (Within 2 Weeks)'),
        ('high_1month', 'High (Within 1 Month)'),
        ('other', 'Other Timeframe'),
    ], string='Urgency Category', default='urgent_2weeks', tracking=True)
    urgency_other = fields.Char(string='Other Urgency Specification')

    justification = fields.Text(string='Justification', required=True,
                                help='Mandatory - ad-hoc requests must be justified and approved '
                                     'by L&D (business rule / ).')
    reason = fields.Selection([
        ('urgent_operational', 'Urgent Operational Need'),
        ('regulatory', 'New Regulatory Requirement'),
        ('emergency_gap', 'Emergency Competency Gap'),
        ('opportunity', 'Time-Bound Opportunity'),
        ('other', 'Other'),
    ], string='Reason', default='urgent_operational', required=True)

    # Risk Checkboxes of NOT Conducting
    risk_regulatory = fields.Boolean(string='Regulatory / Compliance Risk')
    risk_operational = fields.Boolean(string='Operational Risk')
    risk_financial = fields.Boolean(string='Financial Loss Risk')
    risk_customer = fields.Boolean(string='Customer Service Impact')
    risk_reputation = fields.Boolean(string='Reputational Risk')
    risk_other = fields.Boolean(string='Other Risk')
    risk_details = fields.Text(string='Risk of NOT Conducting Details')

    requested_date_start = fields.Date(string='Requested Start Date')
    requested_date_end = fields.Date(string='Requested End Date')
    delivery_method = fields.Selection([
        ('internal', 'Internal Delivery'),
        ('local_external', 'Local External'),
        ('international', 'International'),
    ], string='Delivery Source', default='internal', required=True)
    currency_id = fields.Many2one(
        'res.currency', string='Cost Currency', required=True,
        default=lambda self: currency_for_delivery(self.env, 'internal'))
    estimated_cost = fields.Monetary(string='Estimated Cost',
                                     currency_field='currency_id')
    cost_per_participant = fields.Monetary(
        string='Cost per Participant',
        currency_field='currency_id',
        compute='_compute_cost_per_participant',
        store=True)

    @api.depends('estimated_cost', 'participant_count')
    def _compute_cost_per_participant(self):
        for rec in self:
            if rec.participant_count and rec.participant_count > 0:
                rec.cost_per_participant = rec.estimated_cost / rec.participant_count
            else:
                rec.cost_per_participant = 0.0
    budget_source = fields.Selection([
        ('unit_budget', 'Requesting Unit Budget'),
        ('training_budget', 'Training Department Budget'),
        ('contingency', 'Contingency / Reallocation'),
        ('other', 'Other Source'),
    ], string='Budget Source', default='training_budget')
    budget_source_other = fields.Char(string='Other Budget Source Specification')
    cost_centre_code = fields.Char(string='Cost Centre / Budget Code')

    delivery_mode = fields.Selection([
        ('classroom', 'Classroom'),
        ('e_learning', 'E-Learning'),
        ('blended', 'Blended'),
    ], string='Delivery Mode', default='classroom', required=True)
    annual_plan_id = fields.Many2one(
        'eds.annual.plan', string='Annual Plan',
        domain="[('state', 'in', ('draft', 'published', 'amended'))]",
        help='Target annual plan the approved request is appended to as an addendum '
             '().')

    # Approval Signatories & Decision
    sign_unit_head = fields.Char(string='Requesting Unit Head Signoff')
    sign_tl_lnd = fields.Char(string='Team Leader, L&D (Verified)')
    sign_finance = fields.Char(string='Finance (Budget Confirmed)')
    sign_director = fields.Char(string='Director, PPDD (Approved)')
    decision_type = fields.Selection([
        ('approved', 'Approved'),
        ('approved_with_changes', 'Approved with Changes'),
        ('rejected', 'Rejected'),
    ], string='Final Committee Decision', default='approved', tracking=True)
    decision_comments = fields.Text(string='Committee / Approver Comments')

    def action_print_form(self):
        """Prints official Form Unscheduled Training Request PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_unscheduled').report_action(self)

    def action_open_provider_sourcing(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Approve the unscheduled request before sourcing a provider.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Training Provider Sourcing'),
            'res_model': 'eds.course.vendor.selection',
            'view_mode': 'list,form',
            'domain': [('unscheduled_request_id', '=', self.id)],
            'context': {'default_source_type': 'unscheduled',
                        'default_unscheduled_request_id': self.id},
        }

    def action_open_hotel_sourcing(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Approve the unscheduled request before sourcing a hotel.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Hotel / Venue Sourcing'),
            'res_model': 'eds.hotel.selection',
            'view_mode': 'list,form',
            'domain': [('unscheduled_request_id', '=', self.id)],
            'context': {'default_source_type': 'unscheduled',
                        'default_unscheduled_request_id': self.id},
        }
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
    lnd_reviewer_id = fields.Many2one('res.users', string='L&D Reviewer', readonly=True)
    director_reviewer_id = fields.Many2one('res.users', string='Director Reviewer', readonly=True)
    company_currency_id = fields.Many2one('res.currency', related='company_id.currency_id',
                                          readonly=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.onchange('course_id')
    def _onchange_course_id(self):
        if self.course_id:
            self.program_name = self.course_id.name
            self.delivery_method = self.course_id.recommended_source or 'internal'
            self._onchange_delivery_currency()

    @api.onchange('delivery_method')
    def _onchange_delivery_currency(self):
        if self.delivery_method != 'international' or not self.currency_id or self.currency_id.name == 'ETB':
            self.currency_id = currency_for_delivery(self.env, self.delivery_method)

    @api.onchange('department_id')
    def _onchange_department_id(self):
        """Top of hierarchy: Department -> Operating Unit -> Job Position.
        - If department selected:
          work_unit_id domain restricted to operating units belonging to this department.
          If selected work_unit_id doesn't belong to the department, clear it.
          job_position_id and employee_id restricted to the department.
        - If no department selected:
          All operating units and jobs are available.
        """
        ou_domain = self.env['eds.hr.compat'].get_operating_unit_domain(departments=self.department_id)
        if self.department_id:
            if self.work_unit_id and not self.env['eds.hr.compat'].is_operating_unit_in_departments(self.work_unit_id, self.department_id):
                self.work_unit_id = False
            if self.job_position_id and self.job_position_id.department_id and self.job_position_id.department_id != self.department_id:
                self.job_position_id = False
            if self.employee_id and self.employee_id.department_id != self.department_id:
                self.employee_id = False
        job_domain = self.env['eds.hr.compat'].get_job_domain(
            departments=self.department_id, operating_units=self.work_unit_id)
        emp_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id, job=self.job_position_id)
        return {'domain': {'work_unit_id': ou_domain, 'job_position_id': job_domain, 'employee_id': emp_domain}}

    @api.onchange('work_unit_id')
    def _onchange_work_unit_id(self):
        """Middle of hierarchy: Operating Unit -> Job Position.
        Filter job position and employee based on selected work unit and department.
        """
        if self.work_unit_id and not self.department_id:
            if hasattr(self.work_unit_id, 'department') and self.work_unit_id.department:
                self.department_id = self.work_unit_id.department
            elif 'operating_unit_id' in self.env['hr.department']._fields:
                linked_dept = self.env['hr.department'].search([('operating_unit_id', '=', self.work_unit_id.id)], limit=1)
                if linked_dept:
                    self.department_id = linked_dept

        if self.work_unit_id:
            if self.employee_id:
                emp_ou = self.env['eds.hr.compat'].get_employee_operating_unit(self.employee_id)
                if emp_ou and emp_ou != self.work_unit_id:
                    self.employee_id = False
        job_domain = self.env['eds.hr.compat'].get_job_domain(
            departments=self.department_id, operating_units=self.work_unit_id)
        emp_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id, job=self.job_position_id)
        return {'domain': {'job_position_id': job_domain, 'employee_id': emp_domain}}

    @api.onchange('job_position_id')
    def _onchange_job_position_id(self):
        if self.job_position_id and self.job_position_id.department_id:
            if not self.department_id:
                self.department_id = self.job_position_id.department_id
            if self.department_id.operating_unit_id and not self.work_unit_id:
                self.work_unit_id = self.department_id.operating_unit_id
        if self.job_position_id and self.employee_id:
            emp_job = self.env['eds.hr.compat'].get_employee_job(self.employee_id)
            if emp_job and emp_job != self.job_position_id:
                self.employee_id = False
        emp_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id, job=self.job_position_id)
        return {'domain': {'employee_id': emp_domain}}

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            job = self.env['eds.hr.compat'].get_employee_job(self.employee_id)
            if job:
                self.job_position_id = job
            if self.employee_id.department_id:
                self.department_id = self.employee_id.department_id
            ou = self.env['eds.hr.compat'].get_employee_operating_unit(self.employee_id)
            if ou:
                self.work_unit_id = ou

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if vals.get('course_id'):
                vals['program_name'] = self.env['eds.course'].browse(vals['course_id']).name
            method = vals.get('delivery_method') or 'internal'
            if vals.get('currency_id'):
                validate_delivery_currency(self.env, method, vals['currency_id'])
            else:
                vals['currency_id'] = currency_for_delivery(self.env, method).id
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.unscheduled.request') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if 'course_id' in vals:
            vals['program_name'] = (
                self.env['eds.course'].browse(vals['course_id']).name
                if vals['course_id'] else False)
        else:
            vals.pop('program_name', None)
        if 'delivery_method' in vals and 'currency_id' not in vals:
            vals['currency_id'] = currency_for_delivery(self.env, vals['delivery_method']).id
        if {'delivery_method', 'currency_id'} & vals.keys():
            for rec in self:
                validate_delivery_currency(
                    self.env, vals.get('delivery_method', rec.delivery_method),
                    vals.get('currency_id', rec.currency_id.id))
        return super().write(vals)

    # ── Workflow ──────────────────────────────────────────────
    def _notify_review_role(self, role, title, message):
        self.ensure_one()
        group = self.env.ref('employee_development_system.' + role)
        recipients = group.sudo().user_ids.filtered(
            lambda user: user.active and not user.share and self.company_id in user.company_ids
            and user.id != self.env.user.id)
        if not recipients:
            raise UserError(_('No eligible reviewer is assigned to the EDS role for %s.') % title)
        clear_action_activities(self)
        notify_action(self, recipients, title, message)

    def action_submit(self):
        """Draft -> Submitted: request enters the approval chain."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            if not rec.justification:
                raise UserError(_('A justification is mandatory for unscheduled training '
                                  'requests.'))
            rec.state = 'submitted'
            rec.message_post(body=_('Unscheduled request %s submitted for L&D approval '
                                    'review.') % rec.name)
            rec._notify_review_role(
                'group_eds_team_leader', _('Review unplanned training'),
                _('Unplanned training request %s needs Team Leader review.') % rec.name)

    def action_lnd_approve(self):
        """Submitted -> L&D Approved."""
        for rec in self:
            rec._require_approval_role('group_eds_team_leader', _('Team Leader'))
            if rec.state != 'submitted':
                raise UserError(_('Only submitted requests can be approved by L&D.'))
            rec.state = 'lnd_approved'
            rec.lnd_reviewer_id = self.env.user
            rec.message_post(body=_('Unscheduled request %s approved by L&D.') % rec.name)
            rec._notify_review_role(
                'group_eds_director', _('Review unplanned training'),
                _('Unplanned training request %s needs Director review.') % rec.name)

    def action_director_approve(self):
        """L&D Approved -> Director PPDD Approved."""
        for rec in self:
            rec._require_approval_role('group_eds_director', _('Director PPDD'))
            if rec.state != 'lnd_approved':
                raise UserError(_('Only L&D-approved requests can move to Director PPDD.'))
            rec.state = 'director_approved'
            rec.director_reviewer_id = self.env.user
            rec.message_post(body=_('Unscheduled request %s approved by Director PPDD.')
                             % rec.name)
            rec._notify_review_role(
                'group_eds_chief', _('Approve unplanned training'),
                _('Unplanned training request %s needs final approval.') % rec.name)

    def action_approve(self):
        """Director PPDD Approved -> Approved: append the addendum line to the annual plan
        and create its draft session."""
        for rec in self:
            rec._require_approval_role('group_eds_chief', _('Chief'))
            if rec.state != 'director_approved':
                raise UserError(_('Only Director-approved requests can be finally approved.'))
            if not rec.course_id:
                raise UserError(_(
                    'Add the training program to the course catalog and select it before approving this request.'))
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec._append_addendum()
            clear_action_activities(rec)
            rec.message_post(body=_('Unscheduled request %s approved - appended to the annual '
                                    'plan as an addendum.') % rec.name)
            notify_action(
                rec, rec.create_uid | rec.director_reviewer_id | rec.lnd_reviewer_id,
                _('Unplanned training approved'),
                _('Unplanned training request %s was approved and added to the annual plan.') % rec.name,
                action_required=False)

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
            'course_id': self.course_id.id,
            'program_name': self.course_id.name,
            'unscheduled_request_id': self.id,
            'delivery_method': self.delivery_method,
            'budget_currency_id': self.currency_id.id,
            'budget_allocated': self.estimated_cost or 0.0,
            'is_addendum': True,
        })
        line._create_default_session()

    def action_reject(self):
        """Submitted -> Rejected (with mandatory reason)."""
        for rec in self:
            if rec.state not in ('submitted', 'lnd_approved', 'director_approved'):
                raise UserError(_('Only pending requests can be rejected.'))
            role = {
                'submitted': ('group_eds_team_leader', _('Team Leader')),
                'lnd_approved': ('group_eds_director', _('Director PPDD')),
                'director_approved': ('group_eds_chief', _('Chief')),
            }[rec.state]
            rec._require_approval_role(*role)
            if not rec.rejected_reason:
                raise UserError(_('A rejection reason is required.'))
            rec.state = 'rejected'
            clear_action_activities(rec)
            rec.message_post(body=_('Unscheduled request %s rejected: %s')
                             % (rec.name, rec.rejected_reason))
            notify_action(
                rec, rec.create_uid | rec.director_reviewer_id | rec.lnd_reviewer_id,
                _('Unplanned training rejected'),
                _('Unplanned training request %s was rejected: %s') % (rec.name, rec.rejected_reason),
                action_required=False)

    def _require_approval_role(self, role_xml_id, role_name):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + role_xml_id)):
            raise UserError(_('This approval step requires the EDS %s role.') % role_name)
