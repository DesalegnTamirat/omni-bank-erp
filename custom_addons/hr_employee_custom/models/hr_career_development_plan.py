# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

class HrCareerIdp(models.Model):
    """
    Individual Career Development Plan (ICDP).
    Automatically generated when a career aspiration is approved (FR-IDP-001).
    """
    _name = 'hr.career.idp'
    _description = 'Individual Career Development Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    active = fields.Boolean(string='Active', default=True, tracking=True)
    is_succession_idp = fields.Boolean(
        string='Is Succession IDP',
        default=False,
        index=True,
        copy=False,
        help='Indicates whether this Individual Development Plan belongs to Succession Planning.')
    def _default_target_job_id(self):
        emp = self.env.user.employee_id or self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        if emp:
            job = emp.job_id or emp.job_position
            return job.id if job else False
        return False

    name = fields.Char(string='IDP Reference', required=True, copy=False, readonly=True, default='New')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True,
        default=lambda self: self.env.user.employee_id or self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1))
        
    aspiration_id = fields.Many2one('hr.career.aspiration', string='Source Aspiration', domain="[('employee_id', '=', employee_id)]")
    target_job_id = fields.Many2one('hr.job', string='Current Role', tracking=True, required=True, default=_default_target_job_id)
    
    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            job = self.employee_id.job_id or self.employee_id.job_position
            if job:
                self.target_job_id = job.id
            # Auto-populate with the employee's latest active aspiration
            aspiration = self.env['hr.career.aspiration'].search([
                ('employee_id', '=', self.employee_id.id)
            ], limit=1, order='id desc')
            
            if aspiration:
                self.aspiration_id = aspiration.id
            else:
                self.aspiration_id = False
        else:
            self.aspiration_id = False
            self.target_job_id = False

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Review'),
        ('active', 'Active / In Progress'),
        ('extension_requested', 'Extension Requested'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    
    start_date = fields.Date(string='Start Date', required=True, default=fields.Date.context_today)
    target_completion_date = fields.Date(string='Target Completion Date')

    # --- Extension Governance ---
    extension_count = fields.Integer(string='Extensions Granted', default=0, readonly=True, tracking=True)
    proposed_completion_date = fields.Date(string='Proposed Completion Date', readonly=True, copy=False, tracking=True)
    extension_reason = fields.Text(string='Extension Justification', readonly=True, copy=False)
    extension_request_date = fields.Date(string='Extension Request Date', readonly=True, copy=False)
    extension_history_ids = fields.One2many(
        'hr.career.idp.extension.log', 'idp_id', string='Extension History'
    )
    
    line_ids = fields.One2many('hr.career.idp.line', 'idp_id', string='Development Activities')
    
    manager_id = fields.Many2one('hr.employee', string='Approving Manager', related='employee_id.parent_id', readonly=True)
    notes = fields.Text(string='General Notes')

    # --- Employee Commitment (FR-IDP-003) ---
    employee_commitment = fields.Text(
        string='Employee Commitment Statement', tracking=True,
        help='Statement confirming employee dedication to achieving the milestones set in this development plan.')
    employee_commitment_date = fields.Date(string='Commitment Sign-Off Date', tracking=True)

    # --- Supervisor Review & Feedback (FR-IDP-004) ---
    supervisor_feedback = fields.Text(
        string='Supervisor Review & Feedback', tracking=True,
        help="Manager's overall review, developmental recommendations, and feedback for the employee.")
    supervisor_feedback_date = fields.Date(string='Supervisor Review Date', tracking=True)

    # Computed fields to control form access
    is_owner = fields.Boolean(compute='_compute_is_owner', string='Is Owner')
    is_manager_user = fields.Boolean(compute='_compute_is_manager_user', string='Is Manager User')

    @api.depends('employee_id')
    @api.depends_context('uid')
    def _compute_is_owner(self):
        for rec in self:
            current_emp = self.env.user.employee_id
            rec.is_owner = bool(
                (rec.employee_id and rec.sudo().employee_id.user_id == self.env.user) or
                (rec.employee_id and current_emp and rec.employee_id.id == current_emp.id) or
                (not rec.employee_id and not rec.id)
            )

    @api.depends('manager_id', 'employee_id')
    @api.depends_context('uid')
    def _compute_is_manager_user(self):
        is_admin = self.env.is_superuser() or self.env.user._is_admin() or self.env.user.id in (1, 2)
        is_hr = (
            self.env.user.has_group('hr_employee_custom.group_career_path_admin') or
            self.env.user.has_group('hr_employee_custom.group_career_path_officer') or
            self.env.user.has_group('hr.group_hr_manager')
        )
        for rec in self:
            current_emp = self.env.user.employee_id
            is_self = bool(
                (rec.employee_id and rec.sudo().employee_id.user_id == self.env.user) or
                (rec.employee_id and current_emp and rec.employee_id.id == current_emp.id) or
                (not rec.employee_id and not rec.id)
            )
            if is_self:
                rec.is_manager_user = False
                continue

            mgr_emp = rec.sudo().manager_id or (rec.employee_id and rec.sudo().employee_id.parent_id)
            is_mgr = bool(mgr_emp and mgr_emp.user_id == self.env.user)
            is_coach = bool(rec.employee_id and rec.sudo().employee_id.coach_id and rec.sudo().employee_id.coach_id.user_id == self.env.user)
            is_line_mgr_group = self.env.user.has_group('hr_employee_custom.group_career_path_manager')
            rec.is_manager_user = bool(is_mgr or is_coach or is_hr or is_admin or is_line_mgr_group)

    competency_gap_html = fields.Html(string='Competency Gap Analysis', compute='_compute_competency_gap_html')

    @api.depends('target_job_id', 'employee_id')
    def _compute_competency_gap_html(self):
        for rec in self:
            html = '<div class="text-muted p-4 text-center">Please select a Target Role and Employee to generate gap analysis.</div>'
            if rec.target_job_id and rec.employee_id:
                job = rec.target_job_id
                emp = rec.employee_id
                
                # Helper to get current employee score
                def get_emp_score(comp_id):
                    assessment = self.env['competency.assessment'].search([
                        ('employee_id', '=', emp.id),
                        ('state', 'in', ['approved', 'locked']),
                    ], order='id desc', limit=1)
                    if assessment:
                        match = assessment.line_ids.filtered(lambda c: c.competency_id.id == comp_id)
                        if match and match[0].current_level:
                            try:
                                return float(match[0].current_level)
                            except:
                                pass
                    return 0.0
                    
                mapping = self.env['competency.role.mapping'].sudo().search([('job_position_id', '=', job.id)], limit=1) if 'competency.role.mapping' in self.env else False
                
                if mapping and mapping.line_ids:
                    # Using standard Odoo list table styling
                    html = '<div class="table-responsive"><table class="table table-sm table-hover" style="margin-bottom: 0;">'
                    html += '<thead><tr style="border-bottom: 2px solid #dee2e6;">'
                    html += '<th>Competency</th>'
                    html += '<th>Pillar</th>'
                    html += '<th class="text-end">Weight</th>'
                    html += '<th class="text-end">Assessment Score</th>'
                    html += '<th class="text-end">Required Score</th>'
                    html += '<th class="text-end">Gap Size</th>'
                    html += '<th class="text-center">Status</th>'
                    html += '</tr></thead><tbody>'
                    
                    for line in mapping.line_ids:
                        req_lvl = float(line.required_proficiency) if hasattr(line, 'required_proficiency') and line.required_proficiency else 0.0
                        comp = line.competency_id
                        if not comp: continue
                        
                        curr_lvl = get_emp_score(comp.id)
                        
                        gap = req_lvl - curr_lvl
                        
                        if curr_lvl >= req_lvl:
                            # Meets or Exceeds (Green)
                            row_class = 'table-success'
                            badge_class = 'text-bg-success'
                            status_text = 'Meets' if curr_lvl == req_lvl else 'Exceeds'
                            gap_display = "0.00" if curr_lvl == req_lvl else f"+{curr_lvl - req_lvl:.2f}"
                        else:
                            # Gap (Red)
                            row_class = 'table-danger'
                            badge_class = 'text-bg-danger'
                            status_text = 'Gap Detected'
                            gap_display = f"{gap:.2f}"
                            
                        # Format scores to 2 decimals like in the screenshot
                        req_str = f"{req_lvl:.2f}"
                        curr_str = f"{curr_lvl:.2f}"
                        weight_str = f"{line.weight:.2f}" if hasattr(line, 'weight') and line.weight else "0.00"
                        pillar_str = dict(comp._fields['pillar'].selection).get(comp.pillar, '') if hasattr(comp, 'pillar') and comp.pillar else ''
                        
                        c_display = getattr(comp, 'display_name', False) or getattr(comp, 'competency', '') or str(comp.id)
                        html += f'<tr class="{row_class}">'
                        html += f'<td><span class="text-primary">{c_display}</span></td>'
                        html += f'<td>{pillar_str}</td>'
                        html += f'<td class="text-end">{weight_str}</td>'
                        html += f'<td class="text-end">{curr_str}</td>'
                        html += f'<td class="text-end">{req_str}</td>'
                        html += f'<td class="text-end">{gap_display}</td>'
                        html += f'<td class="text-center"><span class="badge rounded-pill {badge_class}">{status_text}</span></td>'
                        html += '</tr>'
                        
                    html += '</tbody></table></div>'
                else:
                    html = '<div class="alert alert-info" role="alert"><i class="fa fa-info-circle me-2"></i>No competency mapping found for the Target Role.</div>'
            rec.competency_gap_html = html

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') in ('New', 'IDP-New', False, ''):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('hr.career.idp') or ('BB-IDP-%05d' % (self.search_count([]) + 1))
            if not vals.get('target_job_id'):
                emp_id = vals.get('employee_id')
                if emp_id:
                    emp = self.env['hr.employee'].browse(emp_id)
                    job = emp.job_id or emp.job_position if emp else False
                    if job:
                        vals['target_job_id'] = job.id
                else:
                    emp = self.env.user.employee_id or self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
                    job = emp.job_id or emp.job_position if emp else False
                    if job:
                        vals['target_job_id'] = job.id
        return super().create(vals_list)

    # =========================================================================
    # SUDO OVERRIDES — allow all employees to read IDP records
    # without being blocked by hr.employee record rules on related fields.
    # =========================================================================

    def read(self, fields=None, load='_classic_read'):
        return super(HrCareerIdp, self.sudo()).read(fields, load)

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None, **kwargs):
        return super(HrCareerIdp, self.sudo()).search_read(
            domain=domain, fields=fields, offset=offset, limit=limit, order=order, **kwargs)

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        return super(HrCareerIdp, self.sudo()).web_search_read(
            domain=domain, specification=specification,
            offset=offset, limit=limit, order=order, count_limit=count_limit)

    def write(self, vals):
        if ('supervisor_feedback' in vals or 'supervisor_feedback_date' in vals) and not self.env.su:
            is_admin = self.env.is_superuser() or self.env.user._is_admin() or self.env.user.id in (1, 2)
            if not is_admin:
                for rec in self:
                    if not rec.is_manager_user:
                        raise ValidationError(_("Only reviewing managers and HR administrators can record or update Supervisor Feedback."))
        return super().write(vals)

    def _get_plan_date_error(self):
        """Return validation message if plan Start/Target Completion dates are inconsistent."""
        self.ensure_one()
        if self.start_date and self.target_completion_date and self.target_completion_date < self.start_date:
            return _(
                "Target Completion Date (%(end)s) cannot be earlier than Start Date (%(start)s)."
            ) % {'end': self.target_completion_date, 'start': self.start_date}
        return False

    def _get_line_timeline_error(self, line):
        """Return validation message if an activity line's Timeline violates plan bounds."""
        self.ensure_one()
        if not line.target_date:
            return False
        activity_label = line.name or _('New Activity')
        if not self.start_date or not self.target_completion_date:
            return _(
                "Please set both Start Date and Target Completion Date on the Development Plan "
                "before setting a Timeline for '%(activity)s'."
            ) % {'activity': activity_label}
        if line.target_date < self.start_date:
            return _(
                "Timeline (%(timeline)s) for '%(activity)s' cannot be backdated before the Plan Start Date (%(start)s)."
            ) % {
                'timeline': line.target_date,
                'activity': activity_label,
                'start': self.start_date,
            }
        if line.target_date > self.target_completion_date:
            return _(
                "Timeline (%(timeline)s) for '%(activity)s' must be between Start Date (%(start)s) "
                "and Target Completion Date (%(end)s)."
            ) % {
                'timeline': line.target_date,
                'activity': activity_label,
                'start': self.start_date,
                'end': self.target_completion_date,
            }
        return False

    def _validate_timeline_dates(self, require_dates=False):
        """Validate IDP header date bounds and all activity line timelines."""
        for rec in self:
            if require_dates:
                if not rec.start_date:
                    raise ValidationError(_("Start Date is mandatory on the Development Plan."))
                if not rec.target_completion_date:
                    raise ValidationError(_("Target Completion Date is mandatory on the Development Plan."))
            plan_err = rec._get_plan_date_error()
            if plan_err:
                raise ValidationError(plan_err)
            for line in rec.line_ids:
                if not line.target_date:
                    if require_dates:
                        raise ValidationError(_(
                            "Timeline is mandatory for all Development Activities (missing on '%s')."
                        ) % (line.name or _('New Activity')))
                    continue
                line_err = rec._get_line_timeline_error(line)
                if line_err:
                    raise ValidationError(line_err)

    @api.onchange('start_date', 'target_completion_date')
    def _onchange_plan_dates(self):
        for rec in self:
            err = rec._get_plan_date_error()
            if err:
                rec.target_completion_date = False
                return {
                    'warning': {
                        'title': _('Invalid Plan Date Range'),
                        'message': err,
                    }
                }

    @api.constrains('start_date', 'target_completion_date', 'line_ids')
    def _check_timeline_dates(self):
        self._validate_timeline_dates(require_dates=False)

    @api.constrains('line_ids', 'state')
    def _check_development_activities(self):
        for rec in self:
            if rec.state != 'draft' and not rec.line_ids:
                raise ValidationError(_("Development Activities are mandatory. Please add at least one Development Activity to the Individual Career Development Plan."))

    def action_generate_gaps(self):
        """Automatically identify competency gaps and recommend development lines (FR-IDP-002)."""
        for rec in self:
            if not rec.target_job_id or not rec.employee_id:
                raise ValidationError(_("Please ensure both an Employee and Target Role are selected."))
                
            job = rec.target_job_id
            emp = rec.employee_id
            
            # Helper to get current employee score
            def get_emp_score(comp_id):
                assessment = self.env['competency.assessment'].search([
                    ('employee_id', '=', emp.id),
                    ('state', 'in', ['approved', 'locked']),
                ], order='id desc', limit=1)
                if assessment:
                    match = assessment.line_ids.filtered(lambda c: c.competency_id.id == comp_id)
                    if match and match[0].current_level:
                        try:
                            return float(match[0].current_level)
                        except:
                            pass
                return 0.0
                
            new_lines = []
            mapping = self.env['competency.role.mapping'].sudo().search([('job_position_id', '=', job.id)], limit=1) if 'competency.role.mapping' in self.env else False
            
            if mapping:
                for line in mapping.line_ids:
                    req_lvl = float(line.required_proficiency) if hasattr(line, 'required_proficiency') and line.required_proficiency else 0.0
                    comp = line.competency_id
                    if not comp: continue
                    
                    curr_lvl = get_emp_score(comp.id)
                    if curr_lvl < req_lvl:
                        c_name = getattr(comp, 'display_name', False) or getattr(comp, 'competency', '') or str(comp.id)
                        new_lines.append((0, 0, {
                            'competency_id': comp.id,
                            'target_gap': c_name,
                            'name': f"Improve {c_name}",
                            'activity_type': 'training_program',
                            'target_outcome': f"Achieve proficiency benchmark ({req_lvl:.1f})",
                            'resource_support': 'Internal Training / Mentorship / LMS',
                        }))
                        
            if new_lines:
                rec.with_context(skip_timeline_required_check=True).write({'line_ids': new_lines})
                rec.message_post(body=_("Gap Analysis generated %d recommended development activities.") % len(new_lines))
            else:
                rec.message_post(body=_("No competency gaps found for the Target Role."))

    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_("Development Activities are mandatory. Please add at least one Development Activity before submitting your Development Plan to your manager."))
            rec._validate_timeline_dates(require_dates=True)
            if not rec.employee_commitment_date:
                rec.employee_commitment_date = fields.Date.today()
        self.write({'state': 'submitted'})
        for rec in self:
            rec.message_post(body=_("IDP submitted to Manager for review."))

    def action_activate(self):
        is_admin = self.env.is_superuser() or self.env.user._is_admin() or self.env.user.id in (1, 2)
        current_emp = self.env.user.employee_id
        for rec in self:
            # Maker-Checker Rule: Employee cannot self-approve their own IDP
            is_self = bool(
                (rec.employee_id and rec.sudo().employee_id.user_id == self.env.user) or
                (rec.employee_id and current_emp and rec.employee_id.id == current_emp.id)
            )
            if is_self and not is_admin:
                raise ValidationError(_("Maker-Checker Violation: You cannot approve or activate your own Individual Development Plan. It must be reviewed and approved by your Direct Supervisor / Line Manager."))
            if not rec.line_ids:
                raise ValidationError(_("Development Activities are mandatory. An Individual Career Development Plan must have at least one Development Activity before it can be approved and activated."))
            if not rec.supervisor_feedback or not rec.supervisor_feedback.strip():
                raise ValidationError(_("Supervisor Review & Feedback is mandatory. Please provide your review and development feedback before approving and activating this plan."))
            if not rec.supervisor_feedback_date:
                rec.supervisor_feedback_date = fields.Date.today()
        self.write({'state': 'active'})
        for rec in self:
            rec.line_ids.filtered(lambda l: l.status in ('pending', False)).write({'status': 'in_progress'})
            rec.message_post(body=_("IDP Approved and Activated by Manager. All activities are now In Progress."))

    def action_complete(self):
        is_admin = self.env.is_superuser() or self.env.user._is_admin() or self.env.user.id in (1, 2)
        current_emp = self.env.user.employee_id
        for rec in self:
            # Maker-Checker Rule: Employee cannot self-complete their own IDP
            is_self = bool(
                (rec.employee_id and rec.sudo().employee_id.user_id == self.env.user) or
                (rec.employee_id and current_emp and rec.employee_id.id == current_emp.id)
            )
            if is_self and not is_admin:
                raise ValidationError(_("Maker-Checker Violation: You cannot mark your own Individual Development Plan as Completed. Only your Direct Supervisor / Line Manager or HR can verify and complete your IDP."))
            if not rec.supervisor_feedback or not rec.supervisor_feedback.strip():
                raise ValidationError(_("Supervisor Review & Feedback is mandatory. Please provide supervisor feedback before completing this development plan."))
            rec.line_ids.filtered(lambda l: l.status != 'completed').write({
                'status': 'completed',
                'completion_date': fields.Date.context_today(self)
            })
            rec.write({'state': 'completed'})
            rec.message_post(body=_("IDP successfully completed. All underlying activities have been marked as Completed."))
            
            # Automatically update the linked Career Aspiration to "Achieved"
            if rec.aspiration_id and rec.aspiration_id.state == 'approved':
                rec.aspiration_id.with_context(force_write=True).write({'state': 'achieved'})
                rec.aspiration_id.message_post(
                    body=_('Congratulations! Your Development Plan has been completed, and this Career Aspiration is now officially Achieved.')
                )
        
    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_request_extension_wizard(self):
        """Open the extension request wizard for the employee."""
        self.ensure_one()
        return {
            'name': _('Request Completion Date Extension'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.career.idp.extension.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_idp_id': self.id,
            }
        }

    def action_approve_extension(self):
        """Manager approves the proposed completion date extension."""
        is_admin = self.env.is_superuser() or self.env.user._is_admin() or self.env.user.id in (1, 2)
        current_emp = self.env.user.employee_id
        for rec in self:
            # Maker-Checker Rule: Employee cannot self-approve their own extension request
            is_self = bool(
                (rec.employee_id and rec.sudo().employee_id.user_id == self.env.user) or
                (rec.employee_id and current_emp and rec.employee_id.id == current_emp.id)
            )
            if is_self and not is_admin:
                raise ValidationError(_("Maker-Checker Violation: You cannot approve your own completion date extension request. It must be approved by your Direct Supervisor / Line Manager or HR."))

            if not rec.proposed_completion_date:
                raise ValidationError(_("No proposed completion date found to approve."))

            old_date = rec.target_completion_date
            new_date = rec.proposed_completion_date
            days_added = (new_date - (old_date or fields.Date.today())).days
            new_count = rec.extension_count + 1

            # Log to extension history
            self.env['hr.career.idp.extension.log'].create({
                'idp_id': rec.id,
                'previous_date': old_date,
                'new_date': new_date,
                'days_added': days_added,
                'reason': rec.extension_reason or '',
                'requested_by_id': rec.employee_id.user_id.id if rec.employee_id and rec.employee_id.user_id else self.env.user.id,
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })

            rec.write({
                'target_completion_date': new_date,
                'proposed_completion_date': False,
                'extension_reason': False,
                'extension_count': new_count,
                'state': 'active',
            })

            rec.message_post(
                body=_("<b>IDP Date Extension Approved by %s:</b><br/>"
                       "• Revised Target Completion Date: %s (+%d days)<br/>"
                       "• Extension Cycle: #%d<br/>"
                       "The plan continues as Active / In Progress.") % (
                    self.env.user.name, new_date, days_added, new_count)
            )

            if rec.employee_id and rec.employee_id.user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('IDP Date Extension Approved!'),
                    note=_('Your completion date extension request has been approved by your manager. '
                           'Your new Target Completion Date is %s.') % new_date,
                    user_id=rec.employee_id.user_id.id,
                )

    def action_reject_extension_wizard(self):
        """Open the extension rejection wizard for the reviewing manager."""
        self.ensure_one()
        return {
            'name': _('Reject Extension Request'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.career.idp.extension.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_idp_id': self.id,
            }
        }

    def unlink(self):
        is_admin = self.env.is_admin() or self.env.user.has_group('base.group_system') or self.env.user.has_group('hr.group_hr_manager')
        for rec in self:
            rec_sudo = rec.sudo()
            if rec_sudo.state == 'draft':
                if not (rec_sudo.create_uid == self.env.user or is_admin):
                    raise UserError(_(
                        "Draft IDP '%s' can only be deleted by its creator (%s) or an HR Administrator."
                    ) % (rec_sudo.name, rec_sudo.create_uid.name or 'unknown'))
            else:
                state_label = dict(rec_sudo._fields['state'].selection).get(rec_sudo.state, rec_sudo.state)
                raise UserError(_(
                    "IDP record '%s' in status '%s' cannot be permanently deleted. "
                    "Please archive this IDP (Action > Archive) to retain historical development records."
                ) % (rec_sudo.name, state_label))
        return super(HrCareerIdp, self.sudo()).unlink()


class HrCareerIdpLine(models.Model):
    """
    A specific development activity within an IDP to close a competency gap.
    """
    _name = 'hr.career.idp.line'
    _description = 'IDP Activity Line'

    idp_id = fields.Many2one('hr.career.idp', string='IDP Reference', required=True, ondelete='cascade')
    target_gap = fields.Char(string='Target Gap / Competency')
    
    # 1. Goal/Competency
    #competency_id = fields.Many2one('recruitment.competency', string='Goal / Competency')
    # 1. Goal/Competency
    competency_id = fields.Many2one('competency.competency', string='Goal / Competency', ondelete='set null')
    # 2. Development Methods
    activity_type = fields.Selection([
        ('coaching', 'Coaching'),
        ('mentoring', 'Mentoring'),
        ('job_rotation', 'Job Rotation'),
        ('acting_assignment', 'Acting Assignment'),
        ('stretch_assignment', 'Stretch Assignment'),
        ('training_program', 'Formal Training Program'),
        ('certification', 'Certification'),
        ('learning_activity', 'General Learning Activity'),
    ], string='Development Method', required=True, default='training_program')
    
    # 3. Milestone / Activity
    name = fields.Char(string='Milestone / Activity', required=True)
    
    # 4. Target
    target_outcome = fields.Char(string='Target', help='Target outcome, objective, or measure of success')
    
    # 5. Timeline
    target_date = fields.Date(string='Timeline')
    
    # 6. Resource / Support
    resource_support = fields.Char(string='Resource / Support', help='Resources, budget, systems, or mentor support required')
    
    # 7. Progress / Status
    status = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed')
    ], string='Progress / Status', default='pending')
    
    # 8. Employee Commitment
    employee_commitment = fields.Text(string='Employee Commitment', help='Employee personal commitment, planned approach, and reflections')
    employee_comment = fields.Text(string='Employee Comment')
    
    # 9. Supervisor Feedback
    supervisor_feedback = fields.Text(string='Supervisor Feedback', help="Manager's evaluation and milestone feedback")
    
    completion_date = fields.Date(string='Completion Date')
    notes = fields.Text(string='Notes/Details')

    idp_state = fields.Selection(related='idp_id.state', string="IDP Status")
    is_manager = fields.Boolean(compute='_compute_is_manager', string="Is Manager")

    # IDs of competencies where the employee has a gap vs the target role —
    # used as a domain on competency_id so the dropdown only shows gap items.
    gap_competency_ids = fields.Many2many(
        'competency.competency',
        compute='_compute_gap_competency_ids',
        string='Gap Competencies',
    )

    @api.depends('idp_id.target_job_id', 'idp_id.employee_id')
    def _compute_gap_competency_ids(self):
        for rec in self:
            gap_ids = []
            idp = rec.idp_id
            if idp and idp.target_job_id and idp.employee_id and 'competency.role.mapping' in self.env:
                mapping = self.env['competency.role.mapping'].sudo().search(
                    [('job_position_id', '=', idp.target_job_id.id)], limit=1
                )
                if mapping and mapping.line_ids:
                    # Get the latest approved/locked assessment for the employee
                    assessment = self.env['competency.assessment'].search([
                        ('employee_id', '=', idp.employee_id.id),
                        ('state', 'in', ['approved', 'locked']),
                    ], order='id desc', limit=1)

                    for line in mapping.line_ids:
                        comp = line.competency_id
                        if not comp:
                            continue
                        req_lvl = float(line.required_proficiency) if getattr(line, 'required_proficiency', False) else 0.0
                        curr_lvl = 0.0
                        if assessment:
                            match = assessment.line_ids.filtered(lambda c: c.competency_id.id == comp.id)
                            if match and match[0].current_level:
                                try:
                                    curr_lvl = float(match[0].current_level)
                                except Exception:
                                    pass
                        if curr_lvl < req_lvl:
                            gap_ids.append(comp.id)
            rec.gap_competency_ids = [(6, 0, gap_ids)]

    @api.depends('idp_id.is_manager_user')
    def _compute_is_manager(self):
        for rec in self:
            rec.is_manager = bool(rec.idp_id and rec.idp_id.is_manager_user)

    @api.onchange('target_date')
    def _onchange_target_date(self):
        for rec in self:
            if not rec.target_date or not rec.idp_id:
                continue
            err = rec.idp_id._get_line_timeline_error(rec)
            if err:
                rec.target_date = False
                return {
                    'warning': {
                        'title': _('Invalid Timeline Date'),
                        'message': err,
                    }
                }

    @api.constrains('target_date', 'idp_id')
    def _check_target_date(self):
        skip_required = self.env.context.get('skip_timeline_required_check')
        for rec in self:
            if not rec.target_date:
                if skip_required:
                    continue
                raise ValidationError(_(
                    "Timeline is mandatory for Development Activity '%s'."
                ) % (rec.name or _('New Activity')))
            if rec.idp_id:
                err = rec.idp_id._get_line_timeline_error(rec)
                if err:
                    raise ValidationError(err)


class HrCareerIdpExtensionLog(models.Model):
    """
    Audit log tracking all approved date extensions on an Individual Development Plan.
    """
    _name = 'hr.career.idp.extension.log'
    _description = 'IDP Extension Audit Log'
    _order = 'approval_date desc, id desc'

    idp_id = fields.Many2one(
        'hr.career.idp', string='Development Plan',
        required=True, ondelete='cascade', index=True
    )
    previous_date = fields.Date(string='Previous Target Date', readonly=True)
    new_date = fields.Date(string='Extended Target Date', readonly=True)
    days_added = fields.Integer(string='Days Added', readonly=True)
    reason = fields.Text(string='Justification', readonly=True)
    requested_by_id = fields.Many2one('res.users', string='Requested By', readonly=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)

