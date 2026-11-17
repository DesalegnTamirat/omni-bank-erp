# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class SuccessionAutoMatchWizard(models.TransientModel):
    _name = 'succession.auto.match.wizard'
    _description = 'Succession Auto-Match Candidates Wizard'

    critical_position_id = fields.Many2one(
        'succession.critical.position',
        string='Critical Position',
        domain=[('state', '=', 'approved')],
        required=True,
        index=True
    )
    job_id = fields.Many2one('hr.job', related='critical_position_id.job_id', string='Job Position', readonly=True, index=True)
    search_employee_id = fields.Many2one(
        'hr.employee',
        string='Search Employee to Invite',
        index=True,
        help='Search any bank employee to verify recruitment promotion criteria and send succession invitation.'
    )
    manual_employee_id = fields.Many2one(
        'hr.employee',
        string='Select Employee to Send Succession Invitation',
        index=True
    )
    eligibility_feedback_html = fields.Html(
        string='Eligibility Evaluation Feedback',
        readonly=True
    )
    eligibility_is_eligible = fields.Boolean(
        string='Is Eligible',
        default=False
    )
    match_line_ids = fields.One2many('succession.auto.match.line', 'wizard_id', string='Matched Candidates')
    selected_count = fields.Integer(string='Selected Count', compute='_compute_selected_count')
    total_eligible_count = fields.Integer(string='Total Matched', compute='_compute_counts')
    not_invited_count = fields.Integer(string='Not Invited', compute='_compute_counts')
    invited_count = fields.Integer(string='Invited (Pending)', compute='_compute_counts')
    accepted_count = fields.Integer(string='Accepted / Applied', compute='_compute_counts')
    declined_count = fields.Integer(string='Declined', compute='_compute_counts')
    expired_count = fields.Integer(string='Expired', compute='_compute_counts')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'match_line_ids' in vals:
                cleaned = []
                for cmd in vals['match_line_ids']:
                    if isinstance(cmd, (list, tuple)) and len(cmd) == 3 and cmd[0] == 0:
                        if cmd[2] and cmd[2].get('employee_id'):
                            cleaned.append(cmd)
                    else:
                        cleaned.append(cmd)
                vals['match_line_ids'] = cleaned
        return super().create(vals_list)

    def write(self, vals):
        if 'match_line_ids' in vals:
            cleaned = []
            for cmd in vals['match_line_ids']:
                if isinstance(cmd, (list, tuple)) and len(cmd) == 3 and cmd[0] == 0:
                    if cmd[2] and cmd[2].get('employee_id'):
                        cleaned.append(cmd)
                else:
                    cleaned.append(cmd)
            vals['match_line_ids'] = cleaned
        return super().write(vals)

    @api.depends('match_line_ids.is_selected', 'match_line_ids.employee_id')
    def _compute_selected_count(self):
        for rec in self:
            rec.selected_count = len(rec.match_line_ids.filtered(lambda l: l.is_selected and bool(l.employee_id)))

    @api.depends('match_line_ids.invitation_status', 'match_line_ids.already_nominated', 'match_line_ids.employee_id')
    def _compute_counts(self):
        for rec in self:
            valid_lines = rec.match_line_ids.filtered(lambda l: bool(l.employee_id))
            rec.total_eligible_count = len(valid_lines)
            rec.not_invited_count = len(valid_lines.filtered(lambda l: l.invitation_status == 'none' and not l.already_nominated))
            rec.invited_count = len(valid_lines.filtered(lambda l: l.invitation_status == 'invited' and not l.already_nominated))
            rec.accepted_count = len(valid_lines.filtered(lambda l: l.invitation_status == 'accepted' and not l.already_nominated))
            rec.declined_count = len(valid_lines.filtered(lambda l: l.invitation_status == 'declined' and not l.already_nominated))
            rec.expired_count = len(valid_lines.filtered(lambda l: l.invitation_status == 'expired' and not l.already_nominated))

    def action_open_accepted_nominations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nominate Accepted Candidates'),
            'res_model': 'succession.candidate.invitation',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('critical_position_id', '=', self.critical_position_id.id), ('state', '=', 'accepted')],
            'context': {'default_critical_position_id': self.critical_position_id.id, 'search_default_filter_accepted': 1},
            'target': 'current',
        }

    @api.onchange('critical_position_id')
    def _onchange_critical_position_id(self):
        if self.critical_position_id:
            # If match lines are already loaded (e.g. populated when opening action), avoid redundant expensive re-scan
            origin_cp = getattr(self, '_origin', False) and getattr(self._origin, 'critical_position_id', False)
            if self.match_line_ids and (not origin_cp or origin_cp == self.critical_position_id):
                return
            match_lines_data = self.critical_position_id.get_auto_match_candidates_data()
            valid_lines = [l for l in match_lines_data if l.get('employee_id')]
            self.match_line_ids = [(5, 0, 0)] + [(0, 0, line) for line in valid_lines]
            if not valid_lines:
                return {
                    'warning': {
                        'title': _('No Matching Candidates'),
                        'message': _('No eligible candidates met the matching criteria for %s.') % self.critical_position_id.display_name,
                    }
                }
        else:
            self.match_line_ids = [(5, 0, 0)]

    def action_run_auto_match(self):
        """Manually trigger or refresh the auto-match candidate pool."""
        self.ensure_one()
        if not self.critical_position_id:
            raise ValidationError(_('Please select an approved Critical Position first.'))
        self.match_line_ids.unlink()
        match_lines_data = self.critical_position_id.get_auto_match_candidates_data()
        valid_lines = [l for l in match_lines_data if l.get('employee_id')]
        self.write({'match_line_ids': [(0, 0, line) for line in valid_lines]})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Auto-Match Scan Complete'),
                'message': _('Scan completed: %d eligible candidate(s) found.') % len(valid_lines),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': self._name,
                    'res_id': self.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'target': 'new',
                }
            }
        }

    def action_select_all(self):
        self.ensure_one()
        phantom = self.match_line_ids.filtered(lambda l: not l.employee_id)
        if phantom:
            phantom.unlink()
        available = self.match_line_ids.filtered(lambda l: bool(l.employee_id) and not l.already_nominated)
        available.write({'is_selected': True})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_deselect_all(self):
        self.ensure_one()
        self.match_line_ids.write({'is_selected': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_select_top_3(self):
        self.ensure_one()
        phantom = self.match_line_ids.filtered(lambda l: not l.employee_id)
        if phantom:
            phantom.unlink()
        self.match_line_ids.write({'is_selected': False})
        available = self.match_line_ids.filtered(lambda l: bool(l.employee_id) and not l.already_nominated)
        top_lines = available.sorted(lambda l: (l.service_in_company, l.total_experience), reverse=True)[:3]
        top_lines.write({'is_selected': True})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_select_top_5(self):
        self.ensure_one()
        phantom = self.match_line_ids.filtered(lambda l: not l.employee_id)
        if phantom:
            phantom.unlink()
        self.match_line_ids.write({'is_selected': False})
        available = self.match_line_ids.filtered(lambda l: bool(l.employee_id) and not l.already_nominated)
        top_lines = available.sorted(lambda l: (l.service_in_company, l.total_experience), reverse=True)[:5]
        top_lines.write({'is_selected': True})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_select_accepted(self):
        self.ensure_one()
        phantom = self.match_line_ids.filtered(lambda l: not l.employee_id)
        if phantom:
            phantom.unlink()
        self.match_line_ids.write({'is_selected': False})
        accepted_lines = self.match_line_ids.filtered(
            lambda l: bool(l.employee_id) and not l.already_nominated and l.invitation_status == 'accepted'
        )
        if not accepted_lines:
            raise ValidationError(_('No candidates with "Accepted" status found. Candidates must first accept the succession invitation before they can be checked and nominated.'))
        accepted_lines.write({'is_selected': True})
        msg = _('Successfully checked %d candidate(s) who accepted/applied the succession invitation.') % len(accepted_lines)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Accepted Candidates Checked'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': self._name,
                    'res_id': self.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'target': 'new',
                }
            }
        }

    def action_send_invitations(self):
        self.ensure_one()
        phantom = self.match_line_ids.filtered(lambda l: not l.employee_id)
        if phantom:
            phantom.unlink()

        # If user checked specific lines, invite those lines; otherwise invite ALL eligible uninvited candidates directly!
        selected_lines = self.match_line_ids.filtered(
            lambda l: l.is_selected and bool(l.employee_id) and not l.already_nominated and l.invitation_status in ('none', 'declined', 'expired')
        )
        if not selected_lines:
            selected_lines = self.match_line_ids.filtered(
                lambda l: bool(l.employee_id) and not l.already_nominated and l.invitation_status in ('none', 'declined', 'expired')
            )
        if not selected_lines:
            raise ValidationError(_('No uninvited candidates found to send invitations to. All eligible candidates have either already been invited or nominated.'))

        Invitation = self.env['succession.candidate.invitation']
        policy = self.env['succession.governance.policy'].get_policy()
        expiry_days = policy.invitation_expiry_days or 3
        deadline = fields.Date.today() + timedelta(days=expiry_days)

        # Prefetch existing invitations in a single batch query for instant performance
        candidate_emp_ids = selected_lines.mapped('employee_id.id')
        existing_invs = Invitation.search([
            ('critical_position_id', '=', self.critical_position_id.id),
            ('employee_id', 'in', candidate_emp_ids),
        ])
        inv_by_emp = {inv.employee_id.id: inv for inv in existing_invs}

        invitations_to_notify = Invitation.browse()
        for line in selected_lines:
            emp = line.employee_id
            vals = {
                'critical_position_id': self.critical_position_id.id,
                'employee_id': emp.id,
                'grade_name': line.grade_name,
                'tenure_years': line.service_in_company or line.tenure_years,
                'last_promotion_months': line.last_promotion_months,
                'total_exp_years': line.total_experience or line.total_exp_years,
                'qualification_desc': line.educational_qualification or line.qualification_desc,
                'sent_date': fields.Date.today(),
                'deadline_date': deadline,
                'state': 'invited',
            }
            inv = inv_by_emp.get(emp.id)
            if inv:
                inv.write(vals)
            else:
                inv = Invitation.create(vals)
                inv_by_emp[emp.id] = inv
            invitations_to_notify |= inv
            line.invitation_id = inv.id

        # Batch update all selected lines at once
        selected_lines.write({
            'invitation_status': 'invited',
            'acceptance_end_date': deadline,
            'app_date': deadline,
            'is_selected': False,
        })

        # Asynchronously dispatch notifications (Discuss, activity, email) without blocking web UI
        invitations_to_notify.send_notification_message(async_send=True)

        sent_count = len(selected_lines)
        msg = _('Succession invitations successfully sent to %d candidate(s).') % sent_count
        self.critical_position_id.message_post(body=msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Invitations Sent Successfully'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_nominate_accepted(self):
        self.ensure_one()
        accepted_lines = self.match_line_ids.filtered(
            lambda l: bool(l.employee_id) and not l.already_nominated and l.invitation_status == 'accepted'
        )
        if not accepted_lines:
            raise ValidationError(_('No candidates with "Accepted" status found. Candidates must first accept their invitation before they can be nominated via this button.'))
        self.match_line_ids.write({'is_selected': False})
        accepted_lines.write({'is_selected': True})
        return self.action_nominate_selected()

    def action_nominate_selected(self):
        self.ensure_one()
        phantom = self.match_line_ids.filtered(lambda l: not l.employee_id)
        if phantom:
            phantom.unlink()

        selected_lines = self.match_line_ids.filtered(lambda l: l.is_selected and bool(l.employee_id))
        if not selected_lines:
            raise ValidationError(_('Please check at least one candidate who has accepted/applied the invitation before clicking "Nominate Selected Candidates".'))

        # Check candidate acceptance: only employees who accepted the invitation can be nominated
        unaccepted_lines = selected_lines.filtered(
            lambda l: l.invitation_status != 'accepted' and not l.already_nominated and l.career_proximity != 'Manual Nomination'
        )
        if unaccepted_lines:
            unaccepted_names = [f"• {l.employee_id.name} (Status: {l.invitation_status})" for l in unaccepted_lines]
            raise ValidationError(_(
                'The following employee(s) cannot be nominated because they have not applied/accepted the succession invitation yet:\n\n'
                '%s\n\n'
                'In accordance with Bunna Bank promotion and recruitment policy, only employees who have accepted the succession invitation can be nominated.\n'
                'Please click "Check Accepted Candidates" to select only candidates who accepted the invitation.'
            ) % '\n'.join(unaccepted_names))

        critical_pos = self.critical_position_id
        if not critical_pos:
            raise ValidationError(_('Please select a Critical Position.'))

        existing_emp_ids = set(self.env['succession.candidate'].search([
            ('critical_position_id', '=', critical_pos.id),
            ('employee_id', 'in', selected_lines.mapped('employee_id').ids)
        ]).mapped('employee_id.id'))

        created_candidates = self.env['succession.candidate']
        skipped_names = []

        for line in selected_lines:
            emp = line.employee_id
            if not emp:
                continue

            if emp.id in existing_emp_ids:
                skipped_names.append(emp.name)
                continue

            role_str = line.job_title or (line.job_id.name if line.job_id else (emp.job_id.name if emp.job_id else 'N/A'))
            justification = (
                _('Discretionary nomination added manually.')
                if line.career_proximity == 'Manual Nomination'
                else _('Auto-Nominated based on Recruitment Promotion Criteria: Position: %s, Grade: %s, Bank Service: %.2f yrs, Total Exp: %.2f yrs.') % (
                    role_str,
                    line.grade_name or 'N/A',
                    line.service_in_company or line.tenure_years or 0.0,
                    line.total_experience or line.total_exp_years or 0.0)
            )
            cfg = self.env['succession.assessment.config'].get_config()
            candidate = self.env['succession.candidate'].with_context(skip_plan_validation=True).create({
                'critical_position_id': critical_pos.id,
                'employee_id': emp.id,
                'nominated_by_id': self.env.user.id,
                'manager_justification': justification,
                'plan_include_exam': True,
                'plan_include_pms': True,
                'plan_include_manager': bool(critical_pos.plan_include_manager),
                'plan_include_self': False,  # Self-assessment disabled
                'plan_include_spmc': bool(critical_pos.plan_include_spmc),
                'spmc_assessor_ids': [(6, 0, critical_pos.spmc_assessor_ids.ids)],
            })
            try:
                candidate.action_nominate()
            except Exception:
                pass
            if candidate.critical_position_id.sudo().required_role_mapping_line_ids and not candidate.competency_gap_ids:
                try:
                    candidate.action_compute_gap_analysis()
                except Exception:
                    pass

            # Sync invitation state if exists
            inv = line.invitation_id or self.env['succession.candidate.invitation'].search([
                ('critical_position_id', '=', critical_pos.id),
                ('employee_id', '=', emp.id),
            ], limit=1)
            if inv:
                inv.write({
                    'state': 'nominated',
                    'nominated_candidate_id': candidate.id,
                })

            created_candidates |= candidate

        # Remove nominated lines from wizard so they are GONE from Auto-Match!
        selected_lines.unlink()

        cand_names = ", ".join(created_candidates.mapped('employee_id.name'))
        msg = _('Successfully nominated %d candidate(s) (%s) to the Succession Pipeline! Assessment scorecards have been initialized.') % (
            len(created_candidates), cand_names
        )
        if skipped_names:
            msg += _(' (%d candidate(s) were already in pipeline: %s)') % (len(skipped_names), ', '.join(skipped_names))

        critical_pos.message_post(body=msg)

        remaining = self.match_line_ids.filtered(lambda l: bool(l.employee_id))
        next_act = {'type': 'ir.actions.act_window_close'} if not remaining else {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidate(s) Successfully Nominated'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': next_act,
            }
        }

    @api.onchange('search_employee_id', 'manual_employee_id')
    def _onchange_search_employee_id(self):
        emp = self.search_employee_id or self.manual_employee_id
        if not emp or not self.critical_position_id:
            self.eligibility_feedback_html = False
            self.eligibility_is_eligible = False
            return

        res = self.critical_position_id.evaluate_employee_eligibility(emp)
        emp_name = emp.name
        pos_title = self.critical_position_id.job_id.name if self.critical_position_id.job_id else self.critical_position_id.display_name

        if not res['is_eligible']:
            self.eligibility_is_eligible = False
            reasons_html = ''.join([f'<li style="margin-bottom: 5px;">{reason}</li>' for reason in res['failure_reasons']])
            self.eligibility_feedback_html = f"""
                <div class="alert alert-danger d-flex align-items-start mt-2 mb-0 shadow-sm border border-danger" role="alert" style="background-color: #f8d7da; border-color: #f5c2c7; color: #842029; padding: 12px; border-radius: 6px;">
                    <i class="fa fa-times-circle fa-2x me-3 text-danger mt-1" style="font-size: 1.8rem; margin-right: 12px;"></i>
                    <div class="flex-grow-1">
                        <strong class="fs-6 text-danger d-block mb-1">Employee Does NOT Meet Recruitment &amp; Promotion Criteria</strong>
                        <p class="mb-1 small" style="color: #495057;">
                            <strong>{emp_name}</strong> cannot be invited or nominated for <strong>{pos_title}</strong> because the employee does not meet the following criteria:
                        </p>
                        <ul class="mb-0 small ps-3" style="color: #b02a37;">
                            {reasons_html}
                        </ul>
                    </div>
                </div>
            """
        else:
            self.eligibility_is_eligible = True
            if res['is_already_nominated']:
                self.eligibility_feedback_html = f"""
                    <div class="alert alert-primary d-flex align-items-start mt-2 mb-0 shadow-sm" role="alert" style="background-color: #cff4fc; border-color: #b6effb; color: #055160; padding: 12px; border-radius: 6px;">
                        <i class="fa fa-info-circle fa-2x me-3 text-primary mt-1" style="font-size: 1.8rem; margin-right: 12px;"></i>
                        <div>
                            <strong class="fs-6 text-primary d-block mb-1">Already Nominated into Pipeline</strong>
                            <p class="mb-0 small text-dark">
                                <strong>{emp_name}</strong> meets all promotion criteria and is <strong>already nominated</strong> in the succession pipeline for <strong>{pos_title}</strong>.
                            </p>
                        </div>
                    </div>
                """
            elif res['invitation']:
                inv = res['invitation']
                status_label = dict(inv._fields['state'].selection).get(inv.state, inv.state)
                self.eligibility_feedback_html = f"""
                    <div class="alert alert-info d-flex align-items-start mt-2 mb-0 shadow-sm" role="alert" style="background-color: #e2e3e5; border-color: #d3d6d8; color: #41464b; padding: 12px; border-radius: 6px;">
                        <i class="fa fa-envelope-o fa-2x me-3 text-info mt-1" style="font-size: 1.8rem; margin-right: 12px;"></i>
                        <div>
                            <strong class="fs-6 text-info d-block mb-1">Succession Invitation Already Sent</strong>
                            <p class="mb-0 small text-dark">
                                <strong>{emp_name}</strong> meets all criteria. An invitation was already sent on <strong>{inv.sent_date}</strong> (Current Status: <strong>{status_label}</strong>, Response Deadline: <strong>{inv.deadline_date or 'N/A'}</strong>).
                            </p>
                        </div>
                    </div>
                """
            else:
                self.eligibility_feedback_html = f"""
                    <div class="alert alert-success d-flex align-items-start mt-2 mb-0 shadow-sm border border-success" role="alert" style="background-color: #d1e7dd; border-color: #badbcc; color: #0f5132; padding: 12px; border-radius: 6px;">
                        <i class="fa fa-check-circle fa-2x me-3 text-success mt-1" style="font-size: 1.8rem; margin-right: 12px;"></i>
                        <div>
                            <strong class="fs-6 text-success d-block mb-1">Employee Meets All Criteria!</strong>
                            <p class="mb-0 small text-dark">
                                <strong>{emp_name}</strong> satisfies all official feeder position, grade, tenure, experience, and educational requirements. Click <strong>"Send Succession Invitation"</strong> to send the invitation and notification directly to this candidate.
                            </p>
                        </div>
                    </div>
                """

    def action_send_single_invitation_searched(self):
        self.ensure_one()
        emp = self.search_employee_id or self.manual_employee_id
        if not emp:
            raise ValidationError(_('Please select an employee first.'))
        if not self.critical_position_id:
            raise ValidationError(_('Please select a Critical Position first.'))

        res = self.critical_position_id.evaluate_employee_eligibility(emp)
        emp_name = emp.name

        if not res['is_eligible']:
            bullet_reasons = '\n• '.join(res['failure_reasons'])
            raise ValidationError(_(
                'Cannot send succession invitation to %s!\n\n'
                'The employee does NOT meet Bunna Bank\'s official promotion criteria:\n• %s'
            ) % (emp_name, bullet_reasons))

        if res['is_already_nominated']:
            raise ValidationError(_(
                '%s is already nominated in the succession pipeline for this position.'
            ) % emp_name)

        critical_pos = self.critical_position_id
        Invitation = self.env['succession.candidate.invitation']
        policy = self.env['succession.governance.policy'].get_policy()
        expiry_days = policy.invitation_expiry_days or 3
        deadline = fields.Date.today() + timedelta(days=expiry_days)

        inv = Invitation.search([
            ('critical_position_id', '=', critical_pos.id),
            ('employee_id', '=', emp.id),
        ], limit=1)

        match_data = res['match_data']
        vals = {
            'critical_position_id': critical_pos.id,
            'employee_id': emp.id,
            'grade_name': match_data.get('grade_name'),
            'tenure_years': match_data.get('service_in_company') or match_data.get('tenure_years'),
            'last_promotion_months': match_data.get('last_promotion_months'),
            'total_exp_years': match_data.get('total_experience') or match_data.get('total_exp_years'),
            'qualification_desc': match_data.get('educational_qualification') or match_data.get('qualification_desc'),
            'sent_date': fields.Date.today(),
            'deadline_date': deadline,
            'state': 'invited',
        }
        if inv:
            inv.write(vals)
        else:
            inv = Invitation.create(vals)

        inv.send_notification_message()

        # Synchronize candidate row in match_line_ids
        existing_line = self.match_line_ids.filtered(lambda l: l.employee_id.id == emp.id)
        if existing_line:
            existing_line.write({
                'invitation_id': inv.id,
                'invitation_status': 'invited',
                'acceptance_end_date': deadline,
                'app_date': deadline,
                'is_selected': False,
            })
        else:
            line_vals = dict(match_data)
            line_vals.update({
                'invitation_id': inv.id,
                'invitation_status': 'invited',
                'acceptance_end_date': deadline,
                'app_date': deadline,
                'is_selected': False,
            })
            self.write({'match_line_ids': [(0, 0, line_vals)]})

        critical_pos.message_post(
            body=_('Succession invitation directly sent to candidate %s (Response Deadline: %s).') % (emp_name, deadline)
        )

        self.search_employee_id = False
        self.manual_employee_id = False
        self.eligibility_feedback_html = False
        self.eligibility_is_eligible = False

        msg = _('Succession invitation successfully sent to %s (Response Deadline: %s).') % (emp_name, deadline)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Invitation Sent'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_add_searched_candidate(self):
        """Alias to action_send_single_invitation_searched."""
        return self.action_send_single_invitation_searched()

    def action_nominate_manual(self):
        """Redirect manual nomination to action_send_single_invitation_searched."""
        if self.manual_employee_id and not self.search_employee_id:
            self.search_employee_id = self.manual_employee_id
        return self.action_send_single_invitation_searched()


class SuccessionAutoMatchLine(models.TransientModel):
    _name = 'succession.auto.match.line'
    _description = 'Succession Auto-Match Candidate Line'
    _order = 'service_in_company desc, total_experience desc, employee_id'

    wizard_id = fields.Many2one('succession.auto.match.wizard', string='Wizard', ondelete='cascade', index=True)
    is_selected = fields.Boolean(string=' ', default=False)
    already_nominated = fields.Boolean(string='Already in Pipeline', default=False)

    # ── Fields matching Image 1 (Internal Recruitment Eligible Employees) ──
    employee_id = fields.Many2one('hr.employee', string='Name', required=False, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        cleaned_vals = [v for v in vals_list if v.get('employee_id')]
        if not cleaned_vals:
            return self.browse()
        return super().create(cleaned_vals)
    acceptance_end_date = fields.Date(string='Acceptance End Date')
    app_date = fields.Date(string='Match / Application Date')
    grade_name = fields.Char(string='Grade')
    job_title = fields.Char(string='Position')
    category = fields.Char(string='Category')
    employment_type = fields.Char(string='Employment Type')
    gender = fields.Char(string='Gender')
    current_location = fields.Char(string='Current Location')
    current_department = fields.Char(string='Current Department')
    educational_qualification = fields.Char(string='Educational Qualification')
    service_in_company = fields.Float(string='Service in Company', digits=(16, 2))
    relevant_experience = fields.Float(string='Relevant Exp', digits=(16, 2))
    employment_experience = fields.Float(string='Employment Experience', digits=(16, 2))
    total_experience = fields.Float(string='Total Experience', digits=(16, 2))

    # ── Succession Workflow & Tracking Fields ──
    invitation_id = fields.Many2one('succession.candidate.invitation', string='Invitation', readonly=True, index=True)
    latest_pms_score = fields.Float(string='Latest PMS Score', digits=(16, 2))
    invitation_status = fields.Selection([
        ('none', 'Not Invited'),
        ('invited', 'Invitation Sent'),
        ('accepted', 'Invitation Accepted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
        ('already_in_pipeline', 'In Pipeline'),
    ], string='Status', default='none', readonly=True, index=True)

    # Legacy / helper aliases for compatibility
    job_id = fields.Many2one('hr.job', string='Current Position Job', compute='_compute_job_dept', store=True, index=True)
    department_id = fields.Many2one('hr.department', string='Department Rec', compute='_compute_job_dept', store=True, index=True)
    tenure_years = fields.Float(string='Bank Service (Years)', compute='_compute_legacy_exp', store=True)
    total_exp_years = fields.Float(string='Total Experience (Years)', compute='_compute_legacy_exp', store=True)
    last_promotion_months = fields.Float(string='Months Since Last Promotion', digits=(16, 1))
    qualification_desc = fields.Char(string='Educational Qualification & CGPA')
    eligibility_status = fields.Char(string='Eligibility Status', default='Eligible - Meets Promotion Criteria')
    career_proximity = fields.Char(string='Role Alignment')
    grade_match_desc = fields.Char(string='Grade Match')
    title_match_desc = fields.Char(string='Position Alignment')
    criteria_match_desc = fields.Char(string='Experience & Qualification')
    composite_score = fields.Float(string='Recruitment Match Score (%)')
    grade_pts = fields.Float(string='Grade Pts')
    career_pts = fields.Float(string='Position Pts')
    tenure_pts = fields.Float(string='Exp Pts')
    edu_pts = fields.Float(string='Edu Pts')

    @api.depends('employee_id')
    def _compute_job_dept(self):
        for rec in self:
            if rec.employee_id:
                rec.job_id = rec.employee_id.job_id or getattr(rec.employee_id, 'job_position', False)
                rec.department_id = rec.employee_id.department_id
            else:
                rec.job_id = False
                rec.department_id = False

    @api.depends('service_in_company', 'total_experience')
    def _compute_legacy_exp(self):
        for rec in self:
            rec.tenure_years = rec.service_in_company
            rec.total_exp_years = rec.total_experience

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            emp = self.employee_id
            emp_job = emp.job_id or getattr(emp, 'job_position', False)
            emp_grade = emp.job_grade or getattr(emp, 'grade_id', False)
            self.job_title = emp.job_id.name or emp.job_title or (emp_job.name if emp_job else '')
            self.grade_name = emp_grade.grade_code if emp_grade and getattr(emp_grade, 'grade_code', False) else (emp_grade.display_name if emp_grade else '')
            self.category = emp_job.employee_category if emp_job and hasattr(emp_job, 'employee_category') else 'Non Managerial'
            self.employment_type = emp_job.type_of_employment if emp_job and hasattr(emp_job, 'type_of_employment') else 'Permanent'
            self.gender = emp.gender or ''
            self.current_location = emp.default_operating_unit_id.name if emp.default_operating_unit_id else ''
            self.current_department = emp.department_id.name if emp.department_id else ''
            self.career_proximity = 'Manual Nomination'
            self.composite_score = 50.0

    def action_send_single_invitation(self):
        self.ensure_one()
        if not self.employee_id:
            raise ValidationError(_('Please select an employee.'))
        if self.already_nominated:
            raise ValidationError(_('This candidate is already nominated in the succession pipeline.'))

        critical_pos = self.wizard_id.critical_position_id
        Invitation = self.env['succession.candidate.invitation']
        inv = Invitation.search([
            ('critical_position_id', '=', critical_pos.id),
            ('employee_id', '=', self.employee_id.id),
        ], limit=1)

        policy = self.env['succession.governance.policy'].get_policy()
        expiry_days = policy.invitation_expiry_days or 3
        deadline = fields.Date.today() + timedelta(days=expiry_days)

        vals = {
            'critical_position_id': critical_pos.id,
            'employee_id': self.employee_id.id,
            'grade_name': self.grade_name,
            'tenure_years': self.service_in_company or self.tenure_years,
            'last_promotion_months': self.last_promotion_months,
            'total_exp_years': self.total_experience or self.total_exp_years,
            'qualification_desc': self.educational_qualification or self.qualification_desc,
            'sent_date': fields.Date.today(),
            'deadline_date': deadline,
            'state': 'invited',
        }
        if inv:
            inv.write(vals)
        else:
            inv = Invitation.create(vals)

        inv.send_notification_message()
        self.write({
            'invitation_id': inv.id,
            'invitation_status': 'invited',
            'acceptance_end_date': deadline,
            'app_date': deadline,
            'is_selected': False,
        })
        msg = _('Succession invitation successfully sent to %s directly from Auto Match.') % self.employee_id.name
        critical_pos.message_post(body=msg)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Invitation Sent'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_nominate(self):
        self.ensure_one()
        critical_pos = self.wizard_id.critical_position_id
        if not self.employee_id:
            raise ValidationError(_('Please select an employee before nominating.'))

        # Check acceptance before nomination
        if self.invitation_status != 'accepted' and self.career_proximity != 'Manual Nomination':
            raise ValidationError(_(
                'Candidate %s has not applied/accepted the succession invitation yet (Status: %s).\n\n'
                'In accordance with Bunna Bank promotion criteria, candidates must confirm acceptance of the succession invitation before they can be nominated into the pipeline.'
            ) % (self.employee_id.name, self.invitation_status))
        
        # Check if already a candidate
        existing = self.env['succession.candidate'].search([
            ('critical_position_id', '=', critical_pos.id),
            ('employee_id', '=', self.employee_id.id)
        ])
        if existing:
            raise ValidationError(_('%s is already nominated for this position.') % self.employee_id.name)
            
        role_str = self.job_title or (self.job_id.name if self.job_id else (self.employee_id.job_id.name if self.employee_id.job_id else 'N/A'))
        justification = (
            _('Discretionary nomination added manually.')
            if self.career_proximity == 'Manual Nomination'
            else _('Auto-Nominated based on Recruitment Promotion Criteria: Position: %s, Grade: %s, Bank Service: %.2f yrs, Total Exp: %.2f yrs.') % (
                role_str,
                self.grade_name or 'N/A',
                self.service_in_company or self.tenure_years or 0.0,
                self.total_experience or self.total_exp_years or 0.0)
        )
        cfg = self.env['succession.assessment.config'].get_config()
        candidate = self.env['succession.candidate'].with_context(skip_plan_validation=True).create({
            'critical_position_id': critical_pos.id,
            'employee_id': self.employee_id.id,
            'nominated_by_id': self.env.user.id,
            'manager_justification': justification,
            'plan_include_exam': True,
            'plan_include_pms': True,
            'plan_include_manager': bool(critical_pos.plan_include_manager),
            'plan_include_self': False,  # Self-assessment disabled
            'plan_include_spmc': bool(critical_pos.plan_include_spmc),
            'spmc_assessor_ids': [(6, 0, critical_pos.spmc_assessor_ids.ids)],
        })
        try:
            candidate.action_nominate()
        except Exception:
            pass
        if candidate.critical_position_id.sudo().required_role_mapping_line_ids and not candidate.competency_gap_ids:
            try:
                candidate.action_compute_gap_analysis()
            except Exception:
                pass

        # Sync invitation state if exists
        inv = self.invitation_id or self.env['succession.candidate.invitation'].search([
            ('critical_position_id', '=', critical_pos.id),
            ('employee_id', '=', self.employee_id.id),
        ], limit=1)
        if inv:
            inv.write({
                'state': 'nominated',
                'nominated_candidate_id': candidate.id,
            })
        emp_name = self.employee_id.name
        wizard = self.wizard_id
        # Delete line so candidate is immediately gone from the Auto-Match table
        self.unlink()

        remaining = wizard.match_line_ids.filtered(lambda l: bool(l.employee_id))
        next_act = {'type': 'ir.actions.act_window_close'} if not remaining else {
            'type': 'ir.actions.act_window',
            'res_model': wizard._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidate Successfully Nominated'),
                'message': _('Candidate %s was successfully nominated to the Succession Pipeline! Assessment scorecards and evaluation plan has been initialized.') % emp_name,
                'type': 'success',
                'sticky': False,
                'next': next_act,
            }
        }
