# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsUnscheduledRequest(models.Model):
    """Ad-hoc / unscheduled training request (/076, ).

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
                               help='Free-text program when it is not in the course catalog.')
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
    estimated_cost = fields.Monetary(string='Estimated Cost',
                                     currency_field='company_currency_id')
    cost_per_participant = fields.Monetary(
        string='Cost per Participant',
        currency_field='company_currency_id',
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
        """Prints official Form EDS-F-09 Unscheduled Training Request PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_unscheduled').report_action(self)
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
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.unscheduled.request') or _('New')
        return super().create(vals_list)

    # ── Workflow (/076) ──────────────────────────────────────────────
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
                                    '().') % rec.name)

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
        and create its draft session (/076)."""
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
                                    'plan as an addendum.') % rec.name)

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
                raise UserError(_('A rejection reason is required.'))
            rec.state = 'rejected'
            rec.message_post(body=_('Unscheduled request %s rejected: %s')
                             % (rec.name, rec.rejected_reason))

    def _require_manager(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This approval step requires L&D Manager authority.'))
