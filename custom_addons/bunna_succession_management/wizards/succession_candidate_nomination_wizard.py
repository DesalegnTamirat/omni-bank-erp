# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SuccessionCandidateNominationWizard(models.TransientModel):
    _name = 'succession.candidate.nomination.wizard'
    _description = 'Succession Candidate Sourcing & Nomination Wizard'

    critical_position_id = fields.Many2one(
        'succession.critical.position',
        string='Target Critical Position',
        domain=[('state', '=', 'approved')],
        required=True,
        index=True,
        help='Select an approved critical position to review & invite/nominate candidates.'
    )
    job_id = fields.Many2one('hr.job', related='critical_position_id.job_id', string='Job Position', readonly=True, index=True)
    search_employee_id = fields.Many2one(
        'hr.employee',
        string='Search Candidate',
        index=True,
        help='Search any candidate or bank employee by name.'
    )
    line_ids = fields.One2many(
        'succession.candidate.nomination.line',
        'wizard_id',
        string='Candidates'
    )
    selected_count = fields.Integer(string='Selected Count', compute='_compute_counts')
    accepted_count = fields.Integer(string='Accepted Ready', compute='_compute_counts')
    total_count = fields.Integer(string='Total Candidates', compute='_compute_counts')

    def check_access(self, operation: str) -> None:
        return None

    def check_access_rule(self, operation):
        return None

    def read(self, fields=None, load='_classic_read'):
        return super(SuccessionCandidateNominationWizard, self.sudo()).read(fields=fields, load=load)

    def web_read(self, specification):
        return super(SuccessionCandidateNominationWizard, self.sudo()).web_read(specification)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        pos_id = self.env.context.get('default_critical_position_id')
        if not pos_id and self.env.context.get('active_model') == 'succession.critical.position':
            pos_id = self.env.context.get('active_id')

        # By default, leave critical_position_id and lines completely empty
        if pos_id:
            res['critical_position_id'] = pos_id
            pos = self.env['succession.critical.position'].sudo().browse(pos_id)
            if pos.exists():
                line_vals = self._prepare_nomination_lines_data(pos)
                res['line_ids'] = [(0, 0, v) for v in line_vals]
        return res

    @api.depends('line_ids', 'line_ids.is_selected', 'line_ids.invitation_status')
    def _compute_counts(self):
        for rec in self:
            valid = rec.line_ids.filtered(lambda l: bool(l.employee_id))
            rec.total_count = len(valid)
            rec.selected_count = len(valid.filtered(lambda l: l.is_selected))
            rec.accepted_count = len(valid.filtered(lambda l: l.invitation_status == 'accepted'))

    @api.model
    def _extract_employee_grade_name(self, emp, inv=None):
        """Extract a clean, user-friendly grade code or name (e.g. 'VI', 'Grade VI')
        from an employee or invitation record, avoiding any stringified recordset reprs.
        """
        if inv and inv.grade_name and not inv.grade_name.startswith('employee.'):
            return inv.grade_name
        if not emp:
            return ''
        emp_grade = emp.job_grade or getattr(emp, 'grade_id', False)
        if not emp_grade:
            return ''
        return getattr(emp_grade, 'grade_code', False) or getattr(emp_grade, 'grade_name', False) or emp_grade.display_name or ''

    def _prepare_nomination_lines_data(self, position):
        if not position:
            return []
        # Execute recruitment matching criteria identical to Auto-Match Candidates
        # Sudo is enforced so PPDD Officers and Committee members do not require HR Admin roles
        match_data = position.sudo().get_auto_match_candidates_data()
        lines = []
        seen_emp_ids = set()
        for d in match_data:
            emp_id = d.get('employee_id')
            if not emp_id:
                continue
            seen_emp_ids.add(emp_id)
            inv_st = d.get('invitation_status', 'none')
            if inv_st == 'already_in_pipeline':
                inv_st = 'already_in_pipeline'
            lines.append({
                'invitation_id': d.get('invitation_id', False),
                'employee_id': emp_id,
                'grade_name': d.get('grade_name', ''),
                'job_title': d.get('job_title', ''),
                'category': d.get('category', ''),
                'employment_type': d.get('employment_type', ''),
                'gender': d.get('gender', ''),
                'current_location': d.get('current_location', ''),
                'current_department': d.get('current_department', ''),
                'educational_qualification': d.get('educational_qualification', ''),
                'service_in_company': d.get('service_in_company', 0.0),
                'total_experience': d.get('total_experience', 0.0),
                'acceptance_end_date': d.get('acceptance_end_date', False),
                'already_nominated': d.get('already_nominated', False),
                'composite_score': d.get('composite_score', 0.0),
                'latest_pms_score': d.get('latest_pms_score', 0.0),
                'invitation_status': inv_st,
                'is_selected': False,
            })

        return lines

    @api.onchange('critical_position_id')
    def _onchange_critical_position_id(self):
        if self.critical_position_id:
            lines_data = self._prepare_nomination_lines_data(self.critical_position_id.sudo())
            self.line_ids = [(5, 0, 0)] + [(0, 0, l) for l in lines_data]
            self.search_employee_id = False
        else:
            self.line_ids = [(5, 0, 0)]

    @api.onchange('search_employee_id')
    def _onchange_search_employee_id(self):
        if self.search_employee_id and self.critical_position_id:
            emp = self.search_employee_id.sudo()
            res = self.critical_position_id.evaluate_employee_eligibility(emp)
            if not res['is_eligible']:
                bullet_reasons = '\n• '.join(res['failure_reasons'])
                self.search_employee_id = False
                return {
                    'warning': {
                        'title': _('Candidate Ineligible - Recruitment Criteria Not Met'),
                        'message': _(
                            'Employee %s does NOT meet Bunna Bank\'s official recruitment criteria for this position:\n\n• %s'
                        ) % (emp.name, bullet_reasons),
                    }
                }
            found = False
            for line in self.line_ids:
                if line.employee_id.id == self.search_employee_id.id:
                    line.is_selected = True
                    found = True
            if not found:
                inv = res.get('invitation') or self.env['succession.candidate.invitation'].sudo().search([
                    ('critical_position_id', '=', self.critical_position_id.id),
                    ('employee_id', '=', emp.id)
                ], limit=1)
                grade = self._extract_employee_grade_name(emp, inv=inv)
                job_title = (inv and inv.employee_job_id and inv.employee_job_id.name) or (emp.job_id.name if emp.job_id else '')
                cat = (getattr(emp.job_id, 'category', False) and emp.job_id.category) or (getattr(emp, 'category', False) and emp.category) or ''
                dept = (inv and inv.department_id and inv.department_id.name) or (emp.department_id.name if emp.department_id else '')
                service_years = 0.0
                if inv and inv.tenure_years:
                    service_years = inv.tenure_years
                elif getattr(emp, 'service_in_company', False):
                    service_years = emp.service_in_company
                elif getattr(emp, 'joining_date', False):
                    service_years = round((fields.Date.today() - emp.joining_date).days / 365.25, 2)
                
                total_exp = (inv and inv.total_exp_years) or getattr(emp, 'total_experience', 0.0) or service_years

                self.line_ids = [(0, 0, {
                    'invitation_id': inv.id if inv else False,
                    'employee_id': emp.id,
                    'grade_name': grade,
                    'job_title': job_title,
                    'category': cat,
                    'gender': emp.gender,
                    'current_department': dept,
                    'service_in_company': service_years,
                    'total_experience': total_exp,
                    'invitation_status': inv.state if inv else 'none',
                    'is_selected': True,
                })]

    def action_refresh_candidates(self):
        self.ensure_one()
        self.sudo().line_ids.unlink()
        lines_data = self._prepare_nomination_lines_data(self.critical_position_id.sudo())
        self.sudo().write({
            'line_ids': [(0, 0, l) for l in lines_data],
            'search_employee_id': False,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidates Refreshed'),
                'message': _('%d candidate(s) loaded.') % len(lines_data),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': self._name,
                    'res_id': self.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'target': 'new',
                    'context': {
                        'default_critical_position_id': self.critical_position_id.id,
                        'active_model': 'succession.candidate.nomination.wizard',
                        'succession_sudo_search': True,
                        'succession_employee_select': True,
                        'dialog_size': 'extra-large',
                    },
                }
            }
        }

    def _reload_lines(self):
        self.ensure_one()
        self.sudo().line_ids.unlink()
        lines_data = self._prepare_nomination_lines_data(self.critical_position_id.sudo())
        self.sudo().write({'line_ids': [(0, 0, l) for l in lines_data]})

    def action_send_single_invitation_searched(self):
        self.ensure_one()
        if not self.search_employee_id:
            raise UserError(_('Please select an employee to send a succession invitation.'))
        if not self.critical_position_id:
            raise UserError(_('Please select a Target Critical Position first.'))

        emp = self.search_employee_id.sudo()
        res = self.critical_position_id.evaluate_employee_eligibility(emp)
        if not res['is_eligible']:
            bullet_reasons = '\n• '.join(res['failure_reasons'])
            raise UserError(_(
                'Cannot send succession invitation to %s!\n\n'
                'The employee does NOT meet Bunna Bank\'s official recruitment criteria for this position:\n• %s'
            ) % (emp.name, bullet_reasons))

        Invitation = self.env['succession.candidate.invitation'].sudo()
        inv = Invitation.search([
            ('critical_position_id', '=', self.critical_position_id.id),
            ('employee_id', '=', emp.id),
        ], limit=1)

        if inv and inv.state == 'nominated':
            raise UserError(_('Employee %s is already nominated into the succession pipeline for this position.') % emp.name)

        policy = self.env['succession.governance.policy'].sudo().get_policy()
        expiry_days = policy.invitation_expiry_days or 3
        deadline = fields.Date.today() + timedelta(days=expiry_days)

        grade = self._extract_employee_grade_name(emp, inv=inv)
        service_years = 0.0
        if getattr(emp, 'service_in_company', False):
            service_years = emp.service_in_company
        elif getattr(emp, 'joining_date', False):
            service_years = round((fields.Date.today() - emp.joining_date).days / 365.25, 2)
        total_exp = getattr(emp, 'total_experience', 0.0) or service_years

        vals = {
            'critical_position_id': self.critical_position_id.id,
            'employee_id': emp.id,
            'grade_name': grade,
            'tenure_years': service_years,
            'total_exp_years': total_exp,
            'sent_date': fields.Date.today(),
            'deadline_date': deadline,
            'state': 'invited',
        }
        if inv:
            inv.write(vals)
        else:
            inv = Invitation.create(vals)

        inv.send_notification_message()
        msg = _('Succession nomination invitation sent to employee %s (deadline: %s).') % (emp.name, deadline)
        self.critical_position_id.sudo().message_post(body=msg)
        self._reload_lines()
        self.sudo().write({'search_employee_id': False})

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

    def action_send_invitations(self):
        self.ensure_one()
        selected = self.line_ids.filtered(lambda l: l.is_selected and bool(l.employee_id))
        if not selected:
            # If nothing checked, default to all uninvited, expired, or declined candidates
            selected = self.line_ids.filtered(
                lambda l: bool(l.employee_id) and l.invitation_status in ('none', 'expired', 'declined')
            )
        if not selected:
            raise UserError(_('Please select at least one candidate checkbox to send succession invitations.'))

        # Check if user selected already nominated candidates
        already_nom = selected.filtered(lambda l: l.invitation_status == 'nominated')
        if already_nom:
            names = ", ".join(already_nom.sudo().mapped('employee_id.name'))
            raise UserError(_('The following candidate(s) are already nominated into the succession pipeline: %s.') % names)

        Invitation = self.env['succession.candidate.invitation'].sudo()
        policy = self.env['succession.governance.policy'].sudo().get_policy()
        expiry_days = policy.invitation_expiry_days or 3
        deadline = fields.Date.today() + timedelta(days=expiry_days)

        emp_ids = selected.mapped('employee_id.id')
        existing_invs = Invitation.search([
            ('critical_position_id', '=', self.critical_position_id.id),
            ('employee_id', 'in', emp_ids),
        ])
        inv_by_emp = {inv.employee_id.id: inv for inv in existing_invs}

        invitations_to_notify = Invitation.browse()
        for line in selected:
            emp = line.employee_id.sudo()
            inv = line.invitation_id or inv_by_emp.get(emp.id)

            vals = {
                'critical_position_id': self.critical_position_id.id,
                'employee_id': emp.id,
                'grade_name': line.grade_name or '',
                'tenure_years': line.service_in_company or 0.0,
                'total_exp_years': line.total_experience or 0.0,
                'sent_date': fields.Date.today(),
                'deadline_date': deadline,
                'state': 'invited',
            }
            if inv:
                inv.write(vals)
            else:
                inv = Invitation.create(vals)
                inv_by_emp[emp.id] = inv

            invitations_to_notify |= inv
            line.invitation_id = inv.id

        selected.sudo().write({
            'invitation_status': 'invited',
            'is_selected': False,
        })

        invitations_to_notify.send_notification_message(async_send=True)
        sent_count = len(selected)

        msg = _('Succession invitations successfully sent to %d candidate(s).') % sent_count
        self.critical_position_id.sudo().message_post(body=msg)
        self._reload_lines()

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

    def action_nominate_selected(self):
        self.ensure_one()
        selected = self.line_ids.filtered(lambda l: l.is_selected)
        if not selected:
            raise UserError(_('Please select at least one candidate checkbox to nominate.'))

        non_accepted = selected.filtered(lambda l: l.invitation_status != 'accepted')
        if non_accepted:
            names = ", ".join(non_accepted.sudo().mapped('employee_id.name'))
            raise UserError(_(
                'The following candidate(s) cannot be nominated because they have not confirmed interest: %s. '
                'Only candidates with status "Accepted" can be nominated into the succession pipeline.'
            ) % names)

        invitations = selected.mapped('invitation_id')
        if not invitations:
            raise UserError(_('No valid invitations found for the selected candidate(s).'))

        invitations.sudo().action_nominate_to_pipeline()

        cand_names = ", ".join(selected.sudo().mapped('employee_id.name'))
        count = len(selected)
        self._reload_lines()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidate Successfully Nominated') if count == 1 else _('Candidates Successfully Nominated'),
                'message': _('Successfully nominated %d candidate(s) (%s) into the Succession Pipeline! Assessment scorecards have been synchronized.') % (count, cand_names),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_select_all(self):
        self.ensure_one()
        self.line_ids.filtered(lambda l: bool(l.employee_id) and not l.already_nominated).sudo().write({'is_selected': True})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context, dialog_size='extra-large', succession_sudo_search=True, succession_employee_select=True),
        }

    def action_deselect_all(self):
        self.ensure_one()
        self.line_ids.sudo().write({'is_selected': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context, dialog_size='extra-large', succession_sudo_search=True, succession_employee_select=True),
        }

    def action_select_accepted(self):
        self.ensure_one()
        self.line_ids.sudo().write({'is_selected': False})
        self.line_ids.filtered(lambda l: bool(l.employee_id) and l.invitation_status == 'accepted').sudo().write({'is_selected': True})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context, dialog_size='extra-large', succession_sudo_search=True, succession_employee_select=True),
        }


class SuccessionCandidateNominationLine(models.TransientModel):
    _name = 'succession.candidate.nomination.line'
    _description = 'Succession Candidate Nomination Line'
    _order = 'service_in_company desc, total_experience desc, employee_id'

    wizard_id = fields.Many2one('succession.candidate.nomination.wizard', ondelete='cascade', index=True)
    invitation_id = fields.Many2one('succession.candidate.invitation', string='Invitation', index=True)
    employee_id = fields.Many2one('hr.employee', string='Candidate Name', required=False, index=True)

    def check_access(self, operation: str) -> None:
        return None

    def check_access_rule(self, operation):
        return None

    def read(self, fields=None, load='_classic_read'):
        return super(SuccessionCandidateNominationLine, self.sudo()).read(fields=fields, load=load)

    def web_read(self, specification):
        return super(SuccessionCandidateNominationLine, self.sudo()).web_read(specification)

    @api.model_create_multi
    def create(self, vals_list):
        cleaned_vals = [v for v in vals_list if v.get('employee_id')]
        if not cleaned_vals:
            return self.browse()
        return super().create(cleaned_vals)

    # ── Core display fields ──────────────────────────────────────────
    grade_name = fields.Char(string='Grade')
    job_title = fields.Char(string='Current Position')
    category = fields.Char(string='Category')
    employment_type = fields.Char(string='Employment Type')
    gender = fields.Char(string='Gender')
    current_location = fields.Char(string='Current Location')
    current_department = fields.Char(string='Department')
    educational_qualification = fields.Char(string='Education')
    service_in_company = fields.Float(string='Bank Service (Yrs)', digits=(16, 2))
    total_experience = fields.Float(string='Total Exp (Yrs)', digits=(16, 2))
    acceptance_end_date = fields.Date(string='Deadline')
    already_nominated = fields.Boolean(string='Already in Pipeline', default=False)
    composite_score = fields.Float(string='Match Score (%)')

    invitation_status = fields.Selection([
        ('none', 'Not Invited'),
        ('invited', 'Invitation Sent'),
        ('accepted', 'Invitation Accepted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
        ('nominated', 'Nominated'),
        ('already_in_pipeline', 'In Pipeline'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='none')
    is_selected = fields.Boolean(string='', default=False)
    latest_pms_score = fields.Float(string='Latest PMS', digits=(16, 2))

    def action_nominate(self):
        return self.action_nominate_single()
    can_nominate = fields.Boolean(string='Can Nominate', compute='_compute_can_nominate')

    @api.depends('invitation_status')
    def _compute_can_nominate(self):
        for rec in self:
            rec.can_nominate = (rec.invitation_status == 'accepted')

    def action_send_single_invite(self):
        self.ensure_one()
        wizard = self.wizard_id
        emp = self.employee_id.sudo()
        if self.invitation_status == 'nominated':
            raise UserError(_('Candidate %s is already nominated into the succession pipeline.') % emp.name)

        Invitation = self.env['succession.candidate.invitation'].sudo()
        inv = self.invitation_id or Invitation.search([
            ('critical_position_id', '=', wizard.critical_position_id.id),
            ('employee_id', '=', emp.id),
        ], limit=1)

        policy = self.env['succession.governance.policy'].sudo().get_policy()
        expiry_days = policy.invitation_expiry_days or 3
        deadline = fields.Date.today() + timedelta(days=expiry_days)

        clean_grade = self.grade_name if (self.grade_name and not self.grade_name.startswith('employee.')) else wizard._extract_employee_grade_name(emp, inv=inv)
        vals = {
            'critical_position_id': wizard.critical_position_id.id,
            'employee_id': emp.id,
            'grade_name': clean_grade or '',
            'tenure_years': self.service_in_company or 0.0,
            'total_exp_years': self.total_experience or 0.0,
            'sent_date': fields.Date.today(),
            'deadline_date': deadline,
            'state': 'invited',
        }
        if inv:
            inv.write(vals)
        else:
            inv = Invitation.create(vals)

        inv.send_notification_message()
        msg = _('Succession invitation sent to %s.') % emp.name
        wizard.critical_position_id.sudo().message_post(body=msg)
        wizard._reload_lines()

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

    def action_nominate_single(self):
        self.ensure_one()
        if self.invitation_status != 'accepted':
            raise UserError(_(
                'Candidate %s has status "%s". Only candidates who have accepted their succession invitations can be nominated into the pipeline.'
            ) % (self.sudo().employee_id.name, dict(self._fields['invitation_status'].selection).get(self.invitation_status, self.invitation_status)))

        wizard = self.wizard_id
        emp_name = self.sudo().employee_id.name
        if self.invitation_id:
            self.invitation_id.sudo().action_nominate_to_pipeline()

        wizard._reload_lines()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidate Successfully Nominated'),
                'message': _('Candidate %s was successfully nominated into the Succession Pipeline! Assessment scorecards have been synchronized.') % emp_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
