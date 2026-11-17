# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .eds_currency_policy import currency_for_delivery, validate_delivery_currency
from .eds_action_notification import clear_action_activities, notify_action
from .eds_employee_projection import safe_employee_web_read


class EdsUnscheduledRequest(models.Model):
    """Ad-hoc / unscheduled training request.

    Classroom training must originate from the approved TNA; any unscheduled request
    is the documented exception - it requires a mandatory justification and L&D
    approval. L&D may attach it to a published annual plan as an addendum, but
    Director approval and direct sourcing do not require an annual plan.
    """
    _name = 'eds.unscheduled.request'
    _description = 'Unscheduled Training Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read,
            ('employee_id', 'unit_head_id'))

    def _default_requesting_employee(self):
        return self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.env.user.id)], limit=1)

    def _is_lnd_staff(self):
        return self.env.su or self.env.user.has_group(
            'employee_development_system.group_eds_officer')

    def _check_requesting_unit_scope(self, work_unit_id, employee_id):
        """Enforce the HR-managed unit boundary for non-L&D requesters."""
        if self._is_lnd_staff():
            return
        employee = self._default_requesting_employee()
        managed_units = self.env['eds.hr.compat'].get_managed_operating_units()
        if (not employee or not work_unit_id or work_unit_id not in managed_units.ids
                or employee_id != employee.id):
            raise AccessError(_(
                'Only a work unit leader may request unscheduled training for a unit '
                'they manage, and Requested By must be their employee record.'))

    @api.depends_context('uid')
    def _compute_request_access(self):
        staff = self._is_lnd_staff()
        units = (self.env['operating.unit'].sudo().search([('active', '=', True)])
                 if staff else self.env['eds.hr.compat'].get_managed_operating_units().filtered('active'))
        for rec in self:
            rec.is_lnd_staff = staff
            rec.allowed_work_unit_ids = units

    @api.depends('state')
    @api.depends_context('uid')
    def _compute_can_reject(self):
        for rec in self:
            role = (
                'group_eds_team_leader' if rec.state in ('submitted', 'team_leader_review') else
                'group_eds_director' if rec.state in ('director_review', 'lnd_approved', 'director_approved') else
                'group_eds_chief' if rec.state == 'chief_approval' else False
            )
            rec.can_reject = bool(role and (self.env.su or self.env.user.has_group(
                'employee_development_system.' + role) or self.env.user.has_group(
                'employee_development_system.group_eds_admin')))

    request_source = fields.Selection([
        ('work_unit', 'Work Unit Request'),
        ('hr', 'HR / L&D Initiative'),
    ], string='Request Source', default='work_unit', required=True, tracking=True)

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    employee_id = fields.Many2one(
        'hr.employee', string='Requested By', tracking=True,
        default=_default_requesting_employee)
    is_lnd_staff = fields.Boolean(compute='_compute_request_access')
    can_reject = fields.Boolean(compute='_compute_can_reject')
    allowed_work_unit_ids = fields.Many2many(
        'operating.unit', compute='_compute_request_access',
        string='Work Units Available to Request')
    contact_phone_email = fields.Char(string='Contact Phone / Email')
    work_unit_id = fields.Many2one(
        'operating.unit', string='Work Unit',
        default=lambda self: self.env['eds.hr.compat'].get_employee_operating_unit(
            self._default_requesting_employee()))
    department_id = fields.Many2one(
        'hr.department', string='Department',
        default=lambda self: self._default_requesting_employee().department_id)
    job_position_id = fields.Many2one(
        'hr.job', string='Job Position',
        default=lambda self: self.env['eds.hr.compat'].get_employee_job(
            self._default_requesting_employee()))
    unit_head_id = fields.Many2one('hr.employee', string='Unit Head')

    course_id = fields.Many2one('eds.course', string='Training Program',
                                domain=[('status', 'in', ('draft', 'active'))])
    program_name = fields.Char(string='Program Name',
                               readonly=True, help='Catalog course name retained for reports.')
    plan_line_ids = fields.One2many(
        'eds.annual.plan.line', 'unscheduled_request_id',
        string='Approved Addendum Programs', readonly=True)
    proposed_dates_text = fields.Char(string='Proposed Dates Text')
    employee_ids = fields.Many2many(
        'hr.employee', 'eds_unscheduled_request_employee_rel',
        'request_id', 'employee_id', string='Target Participants')
    participant_count = fields.Integer(
        string='No. of Participants', default=1,
        compute='_compute_participant_count', store=True, readonly=False)
    session_count = fields.Integer(string='Sessions Count', compute='_compute_session_count')
    preferred_provider = fields.Char(string='Preferred Provider')

    @api.depends('employee_ids')
    def _compute_participant_count(self):
        for rec in self:
            if rec.employee_ids:
                rec.participant_count = len(rec.employee_ids)
            elif not rec.participant_count:
                rec.participant_count = 1

    @api.onchange('employee_ids')
    def _onchange_employee_ids(self):
        if self.employee_ids:
            self.participant_count = len(self.employee_ids)

    def _compute_session_count(self):
        session_data = self.env['eds.session'].sudo().read_group(
            [('unscheduled_request_id', 'in', self.ids)],
            ['unscheduled_request_id'],
            ['unscheduled_request_id']
        )
        mapped = {row['unscheduled_request_id'][0]: row['unscheduled_request_id_count'] for row in session_data}
        for rec in self:
            rec.session_count = mapped.get(rec.id, 0)

    def action_open_sessions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Training Sessions'),
            'res_model': 'eds.session',
            'view_mode': 'list,form',
            'domain': [('unscheduled_request_id', '=', self.id)],
            'context': {
                'default_source_type': 'unscheduled',
                'default_unscheduled_request_id': self.id,
                'default_course_id': self.course_id.id if self.course_id else False,
                'default_delivery_method': self.delivery_method or 'internal',
                'default_company_id': self.company_id.id,
            },
        }
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
    risk_details = fields.Text(string='Risk of Not Conducting')

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
        'eds.annual.plan', string='Annual Plan', tracking=True,
        domain="[('state', '=', 'published')]",
        help='Optional published annual plan for recording this request as an addendum.')

    # Approval Signatories & Decision
    sign_unit_head = fields.Char(string='Requesting Unit Head Signoff')
    sign_tl_lnd = fields.Char(string='Team Leader, L&D (Verified)')
    sign_finance = fields.Char(string='Legacy Finance Signoff')
    sign_director = fields.Char(string='Director, PPDD (Approved)')
    decision_type = fields.Selection([
        ('approved', 'Approved'),
        ('approved_with_changes', 'Approved with Changes'),
        ('rejected', 'Rejected'),
    ], string='Final Decision', tracking=True)
    decision_comments = fields.Text(string='Reviewer / Approver Remarks', tracking=True)

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
        ('draft', 'Draft (Creation)'),
        ('team_leader_review', 'Team Leader Review (Checker)'),
        ('director_review', 'Director Review'),
        ('chief_approval', 'Chief Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('submitted', 'Team Leader Review (Checker)'),
        ('lnd_approved', 'Director Review'),
        ('director_approved', 'Chief Approval'),
    ], string='Status', default='draft', required=True, tracking=True)
    rejected_reason = fields.Text(string='Rejection Reason', tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    team_leader_id = fields.Many2one('res.users', string='Team Leader Reviewer', readonly=True)
    lnd_reviewer_id = fields.Many2one('res.users', string='L&D Reviewer', readonly=True)
    director_reviewer_id = fields.Many2one('res.users', string='Director Reviewer', readonly=True)
    chief_id = fields.Many2one('res.users', string='Chief Approver', readonly=True)
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
            if self.employee_id and self.employee_id.sudo().department_id != self.department_id:
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
            if self.employee_id.sudo().department_id:
                self.department_id = self.employee_id.sudo().department_id
            ou = self.env['eds.hr.compat'].get_employee_operating_unit(self.employee_id)
            if ou:
                self.work_unit_id = ou

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        requester = self._default_requesting_employee()
        for vals in vals_list:
            if not self.env.su and vals.get('state', 'draft') != 'draft':
                raise AccessError(_('Submit the request through the approval actions.'))
            if not self._is_lnd_staff():
                vals.setdefault('employee_id', requester.id)
                if not vals.get('work_unit_id'):
                    vals['work_unit_id'] = self.env['eds.hr.compat'].get_employee_operating_unit(
                        requester).id or False
                self._check_requesting_unit_scope(
                    vals.get('work_unit_id'), vals.get('employee_id'))
                if vals.get('unit_head_id') and vals['unit_head_id'] != requester.id:
                    raise AccessError(_('The work unit requester must sign for their own request.'))
                vals['unit_head_id'] = requester.id
                vals['sign_unit_head'] = requester.name
                unit = self.env['operating.unit'].sudo().browse(vals['work_unit_id'])
                department = unit.department or requester.department_id
                if vals.get('department_id') and vals['department_id'] != (department.id or False):
                    raise AccessError(_('The request department must match the work unit.'))
                vals['department_id'] = department.id or False
                if vals.get('annual_plan_id'):
                    raise AccessError(_('L&D assigns the annual plan for an unscheduled request.'))
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
        records = super().create(vals_list)
        for record in records:
            if record.employee_ids:
                super(EdsUnscheduledRequest, record).write({'participant_count': len(record.employee_ids)})
        return records

    def write(self, vals):
        vals = dict(vals)
        if not self.env.su:
            workflow_fields = {
                'state', 'approved_by_id', 'approval_date',
                'team_leader_id', 'lnd_reviewer_id', 'director_reviewer_id', 'chief_id',
                'sign_tl_lnd', 'sign_director', 'sign_finance', 'decision_type',
            }
            if workflow_fields & vals.keys():
                raise AccessError(_('Use the unscheduled request approval actions to change its decision.'))
        core_request_fields = {
            'employee_id', 'contact_phone_email', 'work_unit_id', 'department_id',
            'job_position_id', 'unit_head_id', 'course_id', 'proposed_dates_text',
            'preferred_provider', 'duration_text', 'urgency_category', 'urgency_other',
            'justification', 'reason', 'risk_regulatory', 'risk_operational',
            'risk_financial', 'risk_customer', 'risk_reputation', 'risk_other',
            'risk_details', 'requested_date_start', 'requested_date_end',
            'company_id', 'sign_unit_head', 'employee_ids',
        }
        if core_request_fields & vals.keys() and any(rec.state != 'draft' for rec in self):
            raise UserError(_('Request details cannot change after submission.'))

        budget_review_fields = {
            'delivery_method', 'delivery_mode', 'currency_id',
            'estimated_cost', 'budget_source', 'budget_source_other',
            'cost_centre_code', 'participant_count',
        }
        if budget_review_fields & vals.keys():
            if not self._is_lnd_staff() and any(rec.state != 'draft' for rec in self):
                raise AccessError(_('Only L&D staff may review or adjust budget and delivery details.'))
            if any(rec.state in ('approved', 'rejected') for rec in self):
                raise UserError(_('Budget and delivery details cannot change after final approval or rejection.'))

        if 'annual_plan_id' in vals and not self.env.su:
            if not self._is_lnd_staff() or any(
                    rec.state in ('approved', 'rejected') for rec in self):
                raise AccessError(_(
                    'Only L&D may assign an annual plan before the final decision.'))
            if vals['annual_plan_id']:
                plan = self.env['eds.annual.plan'].browse(vals['annual_plan_id'])
                if any(plan.company_id != rec.company_id for rec in self):
                    raise UserError(_('The annual plan must belong to the request company.'))
                if plan.state != 'published':
                    raise UserError(_('Select a published annual plan for an unscheduled request.'))
        if {'rejected_reason', 'decision_comments'} & vals.keys() and not self.env.su \
                and any(not rec.can_reject for rec in self):
            raise AccessError(_('Only the reviewer at the current stage may record decision remarks.'))
        if not self._is_lnd_staff():
            for rec in self:
                if rec.create_uid != self.env.user:
                    raise AccessError(_('Only the requester may edit their draft.'))
                self._check_requesting_unit_scope(
                    vals.get('work_unit_id', rec.work_unit_id.id),
                    vals.get('employee_id', rec.employee_id.id))
                if 'unit_head_id' in vals and vals['unit_head_id'] != rec.employee_id.id:
                    raise AccessError(_('The work unit requester must sign for their own request.'))
                if 'sign_unit_head' in vals and vals['sign_unit_head'] != rec.employee_id.sudo().name:
                    raise AccessError(_('The work unit requester must sign for their own request.'))
                if 'department_id' in vals:
                    unit = self.env['operating.unit'].sudo().browse(
                        vals.get('work_unit_id', rec.work_unit_id.id))
                    department = unit.department or rec.employee_id.sudo().department_id
                    if vals['department_id'] != (department.id or False):
                        raise AccessError(_('The request department must match the work unit.'))
                elif 'work_unit_id' in vals:
                    unit = self.env['operating.unit'].sudo().browse(vals['work_unit_id'])
                    department = unit.department or rec.employee_id.sudo().department_id
                    if department:
                        vals['department_id'] = department.id
            if vals.get('annual_plan_id'):
                raise AccessError(_('L&D assigns the annual plan for an unscheduled request.'))
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
        res = super().write(vals)
        if 'employee_ids' in vals:
            for rec in self:
                if rec.employee_ids:
                    super(EdsUnscheduledRequest, rec).write({'participant_count': len(rec.employee_ids)})
        return res

    def _write_workflow_values(self, vals):
        """Only approval actions call this server-side transition helper."""
        return super(EdsUnscheduledRequest, self).write(vals)

    def _lock_current_state(self):
        """Serialize transitions so two reviewers cannot finalize one request twice."""
        self.ensure_one()
        self.flush_recordset(['state'])
        self.env.cr.execute(
            'SELECT state FROM eds_unscheduled_request WHERE id = %s FOR UPDATE',
            [self.id])
        return self.env.cr.fetchone()[0]

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
        """Draft -> Team Leader Review: request enters the approval chain."""
        for rec in self.sorted('id'):
            if rec._lock_current_state() != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            if not rec.justification:
                raise UserError(_('A justification is mandatory for unscheduled training requests.'))
            if not rec.course_id:
                raise UserError(_('Select a catalog training program before submitting the request.'))
            if not rec._is_lnd_staff():
                rec._check_requesting_unit_scope(rec.work_unit_id.id, rec.employee_id.id)
            if rec.employee_ids:
                rec.participant_count = len(rec.employee_ids)
            rec._write_workflow_values({'state': 'team_leader_review'})
            rec.message_post(body=_('Unscheduled request %s submitted for Team Leader review.') % rec.name)
            rec._notify_review_role(
                'group_eds_team_leader', _('Review unplanned training'),
                _('Unplanned training request %s needs Team Leader review.') % rec.name)

    def action_team_leader_forward(self):
        """Team Leader (Checker) verifies and forwards to Director."""
        for rec in self.sorted('id'):
            rec._require_approval_role('group_eds_team_leader', _('Team Leader'))
            if rec._lock_current_state() not in ('team_leader_review', 'submitted'):
                raise UserError(_('Only requests under Team Leader review can be forwarded.'))
            rec._write_workflow_values({
                'state': 'director_review',
                'team_leader_id': self.env.user.id,
                'lnd_reviewer_id': self.env.user.id,
                'sign_tl_lnd': self.env.user.name,
            })
            rec.message_post(body=_('Unscheduled request %s verified by Team Leader %s and forwarded to Director.')
                             % (rec.name, self.env.user.name))
            rec._notify_review_role(
                'group_eds_director', _('Review unplanned training'),
                _('Unplanned training request %s needs Director review.') % rec.name)

    def action_lnd_approve(self):
        """Compatibility alias for Team Leader forward."""
        return self.action_team_leader_forward()

    def action_director_forward(self):
        """Director reviews and forwards to Chief."""
        for rec in self.sorted('id'):
            rec._require_approval_role('group_eds_director', _('Director PPDD'))
            if rec._lock_current_state() not in ('director_review', 'lnd_approved', 'director_approved'):
                raise UserError(_('Only requests under Director review can be forwarded to Chief.'))
            rec._write_workflow_values({
                'state': 'chief_approval',
                'director_reviewer_id': self.env.user.id,
                'sign_director': self.env.user.name,
            })
            rec.message_post(body=_('Unscheduled request %s endorsed by Director %s and forwarded to Chief.')
                             % (rec.name, self.env.user.name))
            rec._notify_review_role(
                'group_eds_chief', _('Review unplanned training'),
                _('Unplanned training request %s requires Chief approval.') % rec.name)

    def action_chief_approve(self):
        """Chief final approval."""
        for rec in self.sorted('id'):
            rec._require_approval_role('group_eds_chief', _('Chief Approver'))
            if rec._lock_current_state() != 'chief_approval':
                raise UserError(_('Only requests pending Chief approval can receive final approval.'))
            if not rec.course_id:
                raise UserError(_('Add the training program to the course catalog and select it before approving.'))
            rec._write_workflow_values({
                'state': 'approved',
                'chief_id': self.env.user.id,
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
                'sign_director': rec.sign_director or self.env.user.name,
                'decision_type': 'approved',
            })
            clear_action_activities(rec)
            rec.message_post(body=_('Unscheduled request %s received final approval by Chief (%s).')
                             % (rec.name, self.env.user.name))
            recipients = rec.create_uid | rec.employee_id.sudo().user_id | rec.lnd_reviewer_id | rec.director_reviewer_id
            notify_action(
                rec, recipients,
                _('Unplanned training approved'),
                _('Unplanned training request %s was approved by the Chief.') % rec.name,
                action_required=False)

    def action_director_approve(self):
        """Compatibility entry point."""
        return self.action_director_forward()

    def action_approve(self):
        return self.action_chief_approve()

    def _append_addendum(self):
        """Create an addendum plan line (and its session) on the target annual plan."""
        self.ensure_one()
        if self.plan_line_ids:
            return self.plan_line_ids[:1]
        plan = self._require_published_plan()
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
        plan.action_re_publish()
        return line

    def _require_published_plan(self):
        self.ensure_one()
        plan = self.annual_plan_id
        if not plan or plan.state != 'published':
            raise UserError(_(
                'Assign a published annual plan before the Director approves '
                'this unscheduled training request.'))
        if plan.company_id != self.company_id:
            raise UserError(_('The annual plan must belong to the request company.'))
        return plan

    def action_reject(self):
        """Open rejection wizard to capture rejection reason."""
        self.ensure_one()
        state = self._lock_current_state()
        if state not in ('team_leader_review', 'submitted', 'director_review', 'lnd_approved', 'director_approved', 'chief_approval'):
            raise UserError(_('Only pending requests can be rejected.'))
        role = {
            'team_leader_review': ('group_eds_team_leader', _('Team Leader')),
            'submitted': ('group_eds_team_leader', _('Team Leader')),
            'director_review': ('group_eds_director', _('Director PPDD')),
            'lnd_approved': ('group_eds_director', _('Director PPDD')),
            'director_approved': ('group_eds_director', _('Director PPDD')),
            'chief_approval': ('group_eds_chief', _('Chief Approver')),
        }[state]
        self._require_approval_role(*role)
        if self.rejected_reason:
            return self.action_confirm_rejection(self.rejected_reason)
        return {
            'name': _('Reject Unscheduled Training Request'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.unscheduled.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_request_id': self.id,
            },
        }

    def action_confirm_rejection(self, reason):
        """Confirm rejection with the given reason."""
        for rec in self.sorted('id'):
            state = rec._lock_current_state()
            if state not in ('team_leader_review', 'submitted', 'director_review', 'lnd_approved', 'director_approved', 'chief_approval'):
                raise UserError(_('Only pending requests can be rejected.'))
            role = {
                'team_leader_review': ('group_eds_team_leader', _('Team Leader')),
                'submitted': ('group_eds_team_leader', _('Team Leader')),
                'director_review': ('group_eds_director', _('Director PPDD')),
                'lnd_approved': ('group_eds_director', _('Director PPDD')),
                'director_approved': ('group_eds_director', _('Director PPDD')),
                'chief_approval': ('group_eds_chief', _('Chief Approver')),
            }[state]
            rec._require_approval_role(*role)
            rec._write_workflow_values({
                'state': 'rejected',
                'decision_type': 'rejected',
                'rejected_reason': reason,
            })
            clear_action_activities(rec)
            rec.message_post(body=_('Unscheduled request %s rejected: %s')
                             % (rec.name, reason))
            notify_action(
                rec, rec.create_uid | rec.director_reviewer_id | rec.lnd_reviewer_id,
                _('Unplanned training rejected'),
                _('Unplanned training request %s was rejected: %s') % (rec.name, reason),
                action_required=False)
        return True

    def _require_approval_role(self, role_xml_id, role_name):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + role_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This approval step requires the EDS %s role.') % role_name)
