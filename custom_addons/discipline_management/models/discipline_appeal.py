# -*- coding: utf-8 -*-
from datetime import timedelta
from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DisciplineAppeal(models.Model):
    _name = 'discipline.appeal'
    _description = 'Disciplinary Appeal Record'
    _inherit = ['mail.thread']
    _order = 'submission_date desc, id desc'

    name = fields.Char(
        string='Appeal Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    
    # Required inverse field for discipline.case appeal_ids (One2many)
    case_id = fields.Many2one(
        'discipline.case',
        string='Original Case',
        required=True,
        ondelete='cascade',
        tracking=True
    )

    allowed_case_ids = fields.Many2many(
        'discipline.case',
        compute='_compute_allowed_case_ids',
        string='Eligible Cases for Appeal'
    )

    is_case_readonly = fields.Boolean(
        string='Is Case Readonly',
        compute='_compute_is_case_readonly',
    )

    @api.depends_context('default_case_id')
    @api.depends('state', 'case_id')
    def _compute_is_case_readonly(self):
        for rec in self:
            is_from_case = bool(self.env.context.get('default_case_id'))
            rec.is_case_readonly = bool(
                is_from_case or
                rec.state != 'draft' or
                (rec.id and rec.case_id)
            )


    @api.depends_context('uid')
    def _compute_allowed_case_ids(self):
        user = self.env.user
        is_hr = (
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_admin') or
            user._is_superuser()
        )
        current_emp = user.sudo().employee_id

        domain = [('state', 'in', ['enforced', 'closed', 'appealed'])]
        if not is_hr:
            emp_ids = set()
            if current_emp:
                emp_ids.add(current_emp.id)
            if hasattr(user, 'employee_ids') and user.employee_ids:
                emp_ids.update(user.employee_ids.ids)
            linked_emps = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)])
            if linked_emps:
                emp_ids.update(linked_emps.ids)
            if emp_ids:
                domain.append(('employee_id', 'in', list(emp_ids)))
            else:
                domain.append(('id', '=', 0))

        all_cases = self.env['discipline.case'].search(domain)
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()

        for rec in self:
            eligible_cases = self.env['discipline.case']
            current_appeal_id = rec._origin.id if rec._origin else (rec.id if isinstance(rec.id, int) else False)

            for case in all_cases:
                # 1. Skip if case state is not in enforced / closed / appealed
                if case.state not in ('enforced', 'closed', 'appealed'):
                    continue

                # 2. Skip if case itself was exonerated with no punishment
                if (case.punishment_type == 'exonerate' or
                    case.decided_punishment_type == 'exonerate' or
                    getattr(case, 'is_exonerated_case', False)):
                    continue

                case_appeals = case.appeal_ids
                if current_appeal_id:
                    case_appeals = case_appeals.filtered(lambda a: a.id != current_appeal_id)

                # 3. Skip if case already has an accepted appeal or window closed
                has_accepted = any(a.acceptance_state in ('accepted', 'window_closed') for a in case_appeals)
                if has_accepted:
                    continue

                # 4. Skip if case already has an active appeal in progress
                active_appeals = case_appeals.filtered(lambda a: a.state in ('draft', 'submitted', 'under_review'))
                if active_appeals:
                    continue

                # 5. Skip if prior appeal exonerated or reached CEO / 4th level
                decided_appeals = case_appeals.filtered(lambda a: a.state == 'decided')
                has_final = False
                for dec in decided_appeals:
                    is_ceo = bool(
                        (ceo_user and (dec.reviewer_id == ceo_user or dec.designated_reviewer_id == ceo_user)) or
                        dec.appeal_target_authority == 'ceo' or
                        (dec.reviewer_id and dec.reviewer_id.has_group('discipline_management.group_discipline_ceo'))
                    )
                    is_exon = bool(
                        dec.decision_outcome == 'overturned' or
                        dec.revised_punishment_type == 'exonerate' or
                        (dec.decision_outcome == 'penalty_reduced' and dec.revised_penalty_percentage == 0.0 and dec.revised_fine_days == 0.0)
                    )
                    if is_exon or is_ceo or dec.appeal_level == 'fourth':
                        has_final = True
                        break

                if has_final:
                    continue

                # 6. If no prior appeals exist, ensure appeal window is open (within statutory deadline)
                if not case_appeals and not case.is_appeal_window_open:
                    continue

                eligible_cases |= case

            if rec.case_id:
                eligible_cases |= rec.case_id

            rec.allowed_case_ids = eligible_cases

    
    employee_id = fields.Many2one(
        'hr.employee',
        string='Appellant Employee',
        related='case_id.employee_id',
        store=True,
        readonly=True
    )
    original_offense_id = fields.Many2one(
        'discipline.offense',
        string='Original Offense',
        related='case_id.offense_id',
        readonly=True
    )
    original_decision_date = fields.Date(
        string='Original Decision Date',
        related='case_id.final_decision_date',
        readonly=True
    )
    case_article_id = fields.Many2one(
        'discipline.article',
        string='Governing Article',
        related='case_id.article_id',
        readonly=True
    )
    case_sub_article_code = fields.Char(
        string='Sub-Article / Clause',
        related='case_id.sub_article_code',
        readonly=True
    )
    case_legal_article_display = fields.Char(
        string='Legal Article / Citation',
        related='case_id.legal_article_display',
        readonly=True
    )
    case_severity_level_id = fields.Many2one(
        'discipline.severity.level',
        string='Severity Classification',
        related='case_id.severity_level_id',
        readonly=True
    )
    case_incident_date = fields.Date(
        string='Misconduct Incident Date',
        related='case_id.incident_date',
        readonly=True
    )
    case_occurrence_count = fields.Integer(
        string='Breach Occurrence (Tier)',
        related='case_id.occurrence_count',
        readonly=True
    )
    case_description = fields.Text(
        string='Summary of Case Facts / Details',
        related='case_id.description',
        readonly=True
    )
    case_initiator_id = fields.Many2one(
        'res.users',
        string='Reporting Manager / Initiator',
        related='case_id.initiator_id',
        readonly=True
    )
    case_action_track = fields.Selection(
        related='case_id.case_action_track',
        string='Disciplinary Action Track',
        readonly=True
    )
    original_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Written Warning + Penalty'),
        ('second_warning_penalty', 'Second Written Warning + Penalty'),
        ('first_warning_penalty', 'First Written Warning + Penalty'),
        ('fine', 'Salary Fine Deduction'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('exonerate', 'Exonerated / No Action'),
    ], string='Original Punishment', compute='_compute_original_penalty_details', store=True, readonly=True)

    original_penalty_percentage = fields.Float(
        string='Original Penalty Percentage (%)',
        compute='_compute_original_penalty_details',
        store=True,
        readonly=True
    )
    original_fine_days = fields.Float(
        string='Original Salary Fine (Days)',
        compute='_compute_original_penalty_details',
        store=True,
        readonly=True
    )

    @api.depends('case_id', 'case_id.punishment_type', 'case_id.penalty_percentage', 'case_id.fine_days',
                 'parent_appeal_id', 'parent_appeal_id.revised_punishment_type', 'parent_appeal_id.revised_penalty_percentage', 'parent_appeal_id.revised_fine_days')
    def _compute_original_penalty_details(self):
        for rec in self:
            if rec.parent_appeal_id and rec.parent_appeal_id.state == 'decided':
                rec.original_punishment_type = rec.parent_appeal_id.revised_punishment_type or False
                rec.original_penalty_percentage = rec.parent_appeal_id.revised_penalty_percentage
                rec.original_fine_days = rec.parent_appeal_id.revised_fine_days
            elif rec.case_id:
                case_sudo = rec.case_id.sudo()
                # If appeal already has locked baseline values and is active/decided, preserve them
                if rec.state in ('under_review', 'decided') and rec.original_punishment_type:
                    continue
                rec.original_punishment_type = case_sudo.punishment_type or case_sudo.decided_punishment_type
                rec.original_penalty_percentage = case_sudo.penalty_percentage if case_sudo.penalty_percentage > 0 else case_sudo.decided_penalty_percentage
                rec.original_fine_days = case_sudo.fine_days if case_sudo.fine_days > 0 else case_sudo.decided_fine_days
            else:
                rec.original_punishment_type = False
                rec.original_penalty_percentage = 0.0
                rec.original_fine_days = 0.0

    # Multi-Tier Appeal Structure
    appeal_level = fields.Selection([
        ('first', '1st Level Appeal'),
        ('second', '2nd Level Appeal'),
        ('third', '3rd Level Appeal'),
        ('fourth', '4th Level Appeal (Final to CEO)'),
    ], string='Appeal Stage', default='first', required=True, tracking=True)

    parent_appeal_id = fields.Many2one('discipline.appeal', string='Prior Appeal Reference', tracking=True)
    child_appeal_ids = fields.One2many('discipline.appeal', 'parent_appeal_id', string='Subsequent Escalated Appeals')

    decision_source_display = fields.Char(
        string='Decision Source',
        compute='_compute_decision_source_display',
        store=True,
        help='Displays the specific prior authority person whose decision is currently under appeal.'
    )

    designated_appeal_authority_display = fields.Char(
        string='Designated Appeal Authority',
        compute='_compute_designated_appeal_authority_display',
        store=True,
        help='Displays the name of the designated authority responsible for reviewing this appeal.'
    )

    case_origin_type = fields.Selection([
        ('manager', 'Appeal on Line Manager / Coach Decision'),
        ('director', 'Appeal on Directorate Director Decision'),
        ('chief', 'Appeal on Chief Officer Decision'),
        ('committee', 'Appeal on Disciplinary Committee Decision'),
    ], string='Decision Source Type', compute='_compute_case_origin_type', store=True)

    is_direct_enforce_case = fields.Boolean(
        string='Is Direct Coach Enforcement Case',
        compute='_compute_is_direct_enforce_case',
        store=True,
        help='Indicates if this appeal stems from a Direct Coach / Line Manager enforcement case.'
    )

    @api.depends('case_id', 'case_id.case_action_track', 'case_origin_type')
    def _compute_is_direct_enforce_case(self):
        for rec in self:
            rec.is_direct_enforce_case = bool(
                (rec.case_id and rec.case_id.case_action_track == 'direct_enforce') or
                rec.case_origin_type in ('manager', 'director')
            )

    appeal_target_authority = fields.Selection([
        ('directorate', 'Respective Directorate Director (Coach of Manager)'),
        ('chief', 'Respective Chief Officer / CPCO (Coach of Director)'),
        ('secretary', 'Disciplinary Committee Secretary (POMD)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Designated Appeal Authority Type', compute='_compute_appeal_target_authority', store=True, tracking=True)

    auto_escalated_authority = fields.Selection([
        ('chief', 'Respective Chief Officer / CPCO (Coach of Director)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Auto-Escalated Target Authority', tracking=True)
    is_auto_escalated = fields.Boolean(string='Auto-Escalated due to SLA', default=False, tracking=True)

    acceptance_state = fields.Selection([
        ('pending', 'Pending Appellant Acceptance'),
        ('accepted', 'Accepted by Appellant'),
        ('appealed_further', 'Escalated to Next Appeal Level'),
        ('window_closed', 'Window Closed (Deemed Accepted)'),
        ('not_applicable', 'Not Applicable (Exonerated / Final)'),
    ], string='Appellant Acceptance Status', default='pending', tracking=True)

    appeal_window_deadline = fields.Date(
        string='Acceptance / Re-appeal Deadline',
        compute='_compute_appeal_window_deadline',
        store=True,
        tracking=True,
        help='10 calendar days window from the appeal decision date.'
    )
    held_refund_amount = fields.Float(
        string='Held Payroll Refund Amount',
        tracking=True,
        help='Reimbursement amount held until appellant acceptance or appeal window closure.'
    )
    sla_review_deadline = fields.Date(
        string='SLA Review Deadline',
        compute='_compute_sla_review_deadline',
        store=True,
        tracking=True,
        help='Review SLA deadline for the assigned appeal authority (5 working days).'
    )
    is_sla_overdue = fields.Boolean(
        string='Review Overdue',
        compute='_compute_is_sla_overdue',
        help='Indicates if appeal authority has exceeded review SLA.'
    )

    is_submitted_on_behalf = fields.Boolean(
        string='Submitted on Behalf of Employee',
        default=False,
        help='Submitted by POMD or Committee Secretary on behalf of deactivated or suspended employee.'
    )
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', default=lambda self: self.env.user, tracking=True)

    @api.onchange('case_id')
    def _onchange_case_id_auto_level(self):
        """Auto-detect existing decided appeals on the selected case and configure appeal level, parent appeal, and baseline."""
        if not self.case_id:
            return

        case_sudo = self.case_id.sudo()
        all_case_appeals = case_sudo.appeal_ids.filtered(lambda a: a.id != (self._origin.id if self._origin else False))
        decided_appeals = all_case_appeals.filtered(lambda a: a.state == 'decided').sorted(
            lambda a: (a.review_date or (a.write_date.date() if a.write_date else fields.Date.today()), a.id or 0),
            reverse=True
        )
        active_appeals = all_case_appeals.filtered(lambda a: a.state in ('draft', 'submitted', 'under_review'))
        if active_appeals:
            case_name = case_sudo.name
            self.case_id = False
            return {
                'warning': {
                    'title': _('Active Appeal in Progress'),
                    'message': _('Case %s already has an active appeal (%s) in progress with state %s. Under Bank Disciplinary Policy, only one active appeal can exist at a time.') % (case_name, active_appeals[0].name, active_appeals[0].state)
                }
            }

        if (case_sudo.punishment_type == 'exonerate' or
            case_sudo.decided_punishment_type == 'exonerate' or
            getattr(case_sudo, 'is_exonerated_case', False)):
            case_name = case_sudo.name
            self.case_id = False
            return {
                'warning': {
                    'title': _('No Sanctions to Appeal'),
                    'message': _('Case %s was exonerated with no disciplinary sanctions. No appeal is necessary.') % case_name
                }
            }

        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        for dec in decided_appeals:
            is_ceo = bool(
                (ceo_user and (dec.reviewer_id == ceo_user or dec.designated_reviewer_id == ceo_user)) or
                dec.appeal_target_authority == 'ceo' or
                (dec.reviewer_id and dec.reviewer_id.has_group('discipline_management.group_discipline_ceo'))
            )
            is_exon = bool(
                dec.decision_outcome == 'overturned' or
                dec.revised_punishment_type == 'exonerate' or
                (dec.decision_outcome == 'penalty_reduced' and dec.revised_penalty_percentage == 0.0 and dec.revised_fine_days == 0.0)
            )
            if is_exon:
                case_name = case_sudo.name
                self.case_id = False
                return {
                    'warning': {
                        'title': _('Appeal Already Concluded'),
                        'message': _('Prior appeal %s for Case %s resulted in full exoneration / reversal of sanctions. No further appeals can be submitted.') % (dec.name, case_name)
                    }
                }
            if is_ceo or dec.appeal_level == 'fourth':
                case_name = case_sudo.name
                self.case_id = False
                return {
                    'warning': {
                        'title': _('Final Appeal Concluded'),
                        'message': _('Case %s has reached the final appeal stage (decided by CEO / 4th Level). No further appeals can be submitted.') % case_name
                    }
                }

        num_decided = len(decided_appeals)
        if num_decided == 0:
            self.appeal_level = 'first'
            self.parent_appeal_id = False
            self.original_punishment_type = case_sudo.punishment_type or case_sudo.decided_punishment_type
            self.original_penalty_percentage = case_sudo.penalty_percentage if case_sudo.penalty_percentage > 0 else case_sudo.decided_penalty_percentage
            self.original_fine_days = case_sudo.fine_days if case_sudo.fine_days > 0 else case_sudo.decided_fine_days
        elif num_decided == 1:
            self.appeal_level = 'second'
            parent = decided_appeals[0]
            self.parent_appeal_id = parent.id
            if parent.decision_outcome == 'penalty_reduced':
                self.original_punishment_type = parent.revised_punishment_type or parent.original_punishment_type
                self.original_penalty_percentage = parent.revised_penalty_percentage
                self.original_fine_days = parent.revised_fine_days
            else:
                self.original_punishment_type = parent.original_punishment_type
                self.original_penalty_percentage = parent.original_penalty_percentage
                self.original_fine_days = parent.original_fine_days
        elif num_decided == 2:
            self.appeal_level = 'third'
            parent = decided_appeals[0]
            self.parent_appeal_id = parent.id
            if parent.decision_outcome == 'penalty_reduced':
                self.original_punishment_type = parent.revised_punishment_type or parent.original_punishment_type
                self.original_penalty_percentage = parent.revised_penalty_percentage
                self.original_fine_days = parent.revised_fine_days
            else:
                self.original_punishment_type = parent.original_punishment_type
                self.original_penalty_percentage = parent.original_penalty_percentage
                self.original_fine_days = parent.original_fine_days
        else:
            self.appeal_level = 'fourth'
            parent = decided_appeals[0]
            self.parent_appeal_id = parent.id
            if parent.decision_outcome == 'penalty_reduced':
                self.original_punishment_type = parent.revised_punishment_type or parent.original_punishment_type
                self.original_penalty_percentage = parent.revised_penalty_percentage
                self.original_fine_days = parent.revised_fine_days
            else:
                self.original_punishment_type = parent.original_punishment_type
                self.original_penalty_percentage = parent.original_penalty_percentage
                self.original_fine_days = parent.original_fine_days

    @api.depends('appeal_level', 'parent_appeal_id', 'parent_appeal_id.reviewer_id', 'parent_appeal_id.designated_reviewer_id', 'case_id', 'case_id.reported_by_id', 'case_id.approver_id', 'case_id.case_action_track')
    def _compute_decision_source_display(self):
        for rec in self:
            if rec.parent_appeal_id:
                parent = rec.parent_appeal_id
                rev_user = parent.reviewer_id or parent.designated_reviewer_id
                rec.decision_source_display = rev_user.name if rev_user else _('Prior Appeal Reviewer')
            elif rec.case_id:
                if rec.case_id.case_action_track == 'committee_escalation' or rec.case_id.initiator_type == 'audit':
                    rec.decision_source_display = _("Disciplinary Committee")
                else:
                    init_name = (rec.case_id.reported_by_id and rec.case_id.reported_by_id.name) or (rec.case_id.approver_id and rec.case_id.approver_id.name) or _('Line Manager')
                    rec.decision_source_display = init_name
            else:
                rec.decision_source_display = False

    @api.depends('appeal_level', 'appeal_target_authority', 'designated_reviewer_id', 'case_id', 'case_id.reported_by_id', 'case_id.employee_id', 'case_id.director_id', 'case_id.chief_id')
    def _compute_designated_appeal_authority_display(self):
        EmpModel = self.env['hr.employee'].sudo()
        for rec in self:
            if rec.designated_reviewer_id:
                rec.designated_appeal_authority_display = rec.designated_reviewer_id.name
                continue
            case = rec.case_id.sudo() if rec.case_id else False
            target = rec.appeal_target_authority
            auth_name = False

            if target == 'directorate':
                if case and case.director_id:
                    auth_name = case.director_id.name
                if not auth_name:
                    auth_name = _("Directorate Director")
            elif target == 'chief':
                if case and case.chief_id:
                    auth_name = case.chief_id.name
                else:
                    cpco_u = EmpModel.get_cpco_user()
                    auth_name = cpco_u.name if cpco_u else _("Chief People & Culture Officer")
            elif target == 'ceo':
                ceo_u = EmpModel.get_ceo_user()
                auth_name = ceo_u.name if ceo_u else _("Chief Executive Officer")
            elif target == 'secretary':
                sec_u = EmpModel.get_secretary_user()
                auth_name = sec_u.name if sec_u else _("Disciplinary Committee Secretary")
            else:
                auth_name = False

            rec.designated_appeal_authority_display = auth_name

    @api.depends('case_id', 'case_id.initiator_type', 'case_id.case_action_track', 'case_id.reported_by_id', 'case_id.employee_id')
    def _compute_case_origin_type(self):
        for rec in self:
            case = rec.case_id.sudo()
            if not case:
                rec.case_origin_type = 'manager'
                continue
            if case.initiator_type == 'audit' or case.case_action_track == 'committee_escalation':
                rec.case_origin_type = 'committee'
            else:
                initiator_emp = case.reported_by_id.sudo() if case.reported_by_id else False
                if not initiator_emp and case.employee_id:
                    initiator_emp = case.employee_id.sudo().coach_id or case.employee_id.sudo().parent_id
                
                level = getattr(initiator_emp, 'executive_level', False) if initiator_emp else False
                if not level and initiator_emp:
                    job_name = (initiator_emp.job_id.sudo().name or '').lower() if initiator_emp.job_id else ''
                    if any(k in job_name for k in ['chief', 'cpco', 'cfo', 'cio', 'cdo', 'coo', 'vp']):
                        level = 'chief'
                    elif any(k in job_name for k in ['director', 'directorate']):
                        level = 'director'
                    else:
                        level = 'manager'
                
                if level == 'chief':
                    rec.case_origin_type = 'chief'
                elif level == 'director':
                    rec.case_origin_type = 'director'
                else:
                    rec.case_origin_type = 'manager'

    submission_date = fields.Date(
        string='Appeal Submission Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )
    appeal_grounds = fields.Text(string='Grounds for Appeal & Justification', required=True)
    supporting_document = fields.Binary(string='Supporting Appeal Document', attachment=True)
    document_filename = fields.Char(string='Document Filename')

    def _get_superior_coach_chain(self, start_emp):
        """Returns ordered list of superior hr.employee records going up the coach/manager chain."""
        chain = []
        curr = start_emp.sudo() if start_emp else False
        visited = {curr.id} if curr else set()
        while curr:
            sup = curr.coach_id or curr.parent_id or (curr.department_id and curr.department_id.manager_id)
            if not sup or sup.id in visited:
                break
            visited.add(sup.id)
            chain.append(sup)
            curr = sup
        return chain

    @api.depends('parent_appeal_id', 'parent_appeal_id.reviewer_id', 'parent_appeal_id.designated_reviewer_id', 'appeal_level', 'case_id', 'case_id.reported_by_id', 'case_id.approver_id', 'case_id.employee_id', 'case_id.case_action_track', 'case_id.chief_id', 'case_id.director_id', 'auto_escalated_authority')
    def _compute_designated_reviewer_id(self):
        EmpModel = self.env['hr.employee'].sudo()
        cpco_user = EmpModel.get_cpco_user()
        ceo_user = EmpModel.get_ceo_user()
        sec_user = EmpModel.get_secretary_user()

        for rec in self:
            case = rec.case_id.sudo() if rec.case_id else False
            if not case:
                rec.designated_reviewer_id = False
                continue

            # Auto-escalated authority override
            if rec.auto_escalated_authority == 'chief':
                rec.designated_reviewer_id = cpco_user or (case.chief_id.user_id if case.chief_id else False)
                continue
            elif rec.auto_escalated_authority == 'ceo':
                rec.designated_reviewer_id = ceo_user
                continue

            # 1. Committee Escalation Track
            if case.case_action_track == 'committee_escalation' or case.initiator_type == 'audit':
                # Committee cases are approved and enforced by the CEO. Appeals route directly to the CEO.
                rec.designated_reviewer_id = ceo_user
                continue

            # 2. Hierarchical Manager/Coach Chain Traversal
            next_reviewer_emp = False
            if rec.parent_appeal_id:
                prior_user = rec.parent_appeal_id.reviewer_id or rec.parent_appeal_id.designated_reviewer_id
                prior_emp = prior_user.sudo().employee_id if prior_user else False
                if prior_emp:
                    next_reviewer_emp = prior_emp.coach_id or prior_emp.parent_id or (prior_emp.department_id and prior_emp.department_id.manager_id)
            else:
                enforcer = case.reported_by_id.sudo() or (case.approver_id and case.approver_id.sudo().employee_id) or (case.create_uid and case.create_uid.sudo().employee_id)
                if not enforcer and case.employee_id:
                    enforcer = case.employee_id.sudo().coach_id or case.employee_id.sudo().parent_id
                if enforcer:
                    next_reviewer_emp = enforcer.coach_id or enforcer.parent_id or (enforcer.department_id and enforcer.department_id.manager_id)

            if next_reviewer_emp and next_reviewer_emp.user_id:
                rec.designated_reviewer_id = next_reviewer_emp.user_id
            else:
                # Fallback to ordered chain from enforcer
                enforcer = case.reported_by_id.sudo() or (case.approver_id and case.approver_id.sudo().employee_id) or (case.create_uid and case.create_uid.sudo().employee_id)
                if not enforcer and case.employee_id:
                    enforcer = case.employee_id.sudo().coach_id or case.employee_id.sudo().parent_id

                chain = rec._get_superior_coach_chain(enforcer)
                reviewer_emp = False
                if rec.appeal_level == 'first':
                    reviewer_emp = chain[0] if len(chain) > 0 else False
                elif rec.appeal_level == 'second':
                    reviewer_emp = chain[1] if len(chain) > 1 else (chain[0] if len(chain) > 0 else False)
                elif rec.appeal_level == 'third':
                    reviewer_emp = chain[2] if len(chain) > 2 else (chain[-1] if chain else False)
                else:
                    reviewer_emp = chain[-1] if chain else False

                if reviewer_emp and reviewer_emp.user_id:
                    rec.designated_reviewer_id = reviewer_emp.user_id
                elif rec.appeal_level in ('third', 'fourth') and len(chain) <= 3:
                    rec.designated_reviewer_id = ceo_user
                elif rec.appeal_level == 'second':
                    rec.designated_reviewer_id = case.chief_id or cpco_user
                elif rec.appeal_level == 'first':
                    rec.designated_reviewer_id = case.director_id
                else:
                    rec.designated_reviewer_id = ceo_user

    @api.depends('case_id', 'case_origin_type', 'appeal_level', 'designated_reviewer_id', 'parent_appeal_id', 'auto_escalated_authority')
    def _compute_appeal_target_authority(self):
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        cpco_user = EmpModel.get_cpco_user()
        for rec in self:
            if rec.auto_escalated_authority:
                rec.appeal_target_authority = rec.auto_escalated_authority
                continue

            case = rec.case_id.sudo() if rec.case_id else False
            if case and (case.case_action_track == 'committee_escalation' or case.initiator_type == 'audit'):
                rec.appeal_target_authority = 'ceo'
                continue

            reviewer = rec.designated_reviewer_id
            if reviewer:
                if (ceo_user and reviewer.id == ceo_user.id) or reviewer.has_group('discipline_management.group_discipline_ceo'):
                    rec.appeal_target_authority = 'ceo'
                    continue
                if (cpco_user and reviewer.id == cpco_user.id) or reviewer.has_group('discipline_management.group_discipline_cpco'):
                    rec.appeal_target_authority = 'chief'
                    continue
                emp = reviewer.sudo().employee_id
                exec_lvl = getattr(emp, 'executive_level', False) if emp else False

                if exec_lvl == 'ceo':
                    rec.appeal_target_authority = 'ceo'
                elif exec_lvl in ('chief', 'deputy_chief'):
                    rec.appeal_target_authority = 'chief'
                else:
                    rec.appeal_target_authority = 'directorate'
            else:
                if rec.appeal_level == 'first':
                    rec.appeal_target_authority = 'directorate'
                elif rec.appeal_level == 'second':
                    rec.appeal_target_authority = 'chief'
                else:
                    rec.appeal_target_authority = 'ceo'

    @api.depends('decision_date', 'state')
    def _compute_appeal_window_deadline(self):
        for rec in self:
            base = rec.decision_date or rec.review_date
            if base and rec.state in ('decided', 'closed'):
                rec.appeal_window_deadline = base + timedelta(days=10)
            else:
                rec.appeal_window_deadline = False

    @api.depends('submission_date', 'create_date', 'state')
    def _compute_sla_review_deadline(self):
        for rec in self:
            base = rec.submission_date or (rec.create_date.date() if rec.create_date else False)
            if base and rec.state in ('submitted', 'under_review'):
                day_count = 0
                curr = base
                while day_count < 5:
                    curr += timedelta(days=1)
                    if curr.weekday() < 5:  # Monday to Friday
                        day_count += 1
                rec.sla_review_deadline = curr
            else:
                rec.sla_review_deadline = False

    @api.depends('sla_review_deadline', 'state')
    def _compute_is_sla_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state in ('submitted', 'under_review') and rec.sla_review_deadline:
                rec.is_sla_overdue = today > rec.sla_review_deadline
            else:
                rec.is_sla_overdue = False

    designated_reviewer_id = fields.Many2one(
        'res.users',
        string='Designated Appeal Reviewer',
        compute='_compute_designated_reviewer_id',
        store=True,
        recursive=True,
        tracking=True
    )
    reviewer_id = fields.Many2one('res.users', string='Appeal Authority / Chair', tracking=True)
    review_date = fields.Date(string='Review Date', tracking=True)
    decision_date = fields.Date(string='Decision Date', related='review_date', store=True, readonly=True)

    @api.model
    def _default_reviewer_signature(self):
        user = self.env.user
        sig = getattr(user, 'discipline_digital_signature', False) or getattr(user, 'digital_signature', False)
        if not sig:
            prev_case = self.env['discipline.case'].sudo().search([
                ('signatory_signature', '!=', False),
                '|', ('initiator_id', '=', user.id), ('create_uid', '=', user.id)
            ], order='id desc', limit=1)
            if prev_case and prev_case.signatory_signature:
                sig = prev_case.signatory_signature
        return sig or False

    reviewer_signature = fields.Binary(
        string='Appellate Reviewer Signature',
        default=_default_reviewer_signature,
        copy=False,
        help='Authorized appellate authority digital signature rendered on the final appeal decision notice.'
    )

    # Appeal Tracking & Decision Outcome
    decision_outcome = fields.Selection([
        ('upheld', 'Original Decision Upheld (Appeal Rejected)'),
        ('overturned', 'Decision Overturned (Exonerated)'),
        ('penalty_reduced', 'Penalty / Action Reduced'),
    ], string='Appeal Decision Outcome', tracking=True)

    revised_penalty_percentage = fields.Float(string='Revised Penalty Percentage (%)', tracking=True)
    revised_fine_days = fields.Float(string='Revised Salary Fine (Days)', tracking=True)
    revised_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('final_warning_penalty', 'Final Written Warning + Penalty'),
        ('second_warning_penalty', 'Second Written Warning + Penalty'),
        ('first_warning_penalty', 'First Written Warning + Penalty'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('exonerate', 'Exonerated / No Action'),
    ], string='Revised Punishment', tracking=True)

    appeal_decision_notes = fields.Text(string='Appeal Board Decision Rationale', tracking=True)

    def _compute_and_set_revised_penalties(self, punishment_type):
        """Helper to auto-compute and populate default revised penalty percentages or fine days."""
        if not punishment_type or punishment_type in ['exonerate', 'verbal_warning', 'dismissal']:
            self.revised_penalty_percentage = 0.0
            self.revised_fine_days = 0.0
            return

        emp = self.sudo().employee_id or (self.case_id and self.case_id.sudo().employee_id)
        job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
        is_managerial = (self.case_id.staff_category == 'managerial') if (self.case_id and self.case_id.staff_category) else (
            getattr(emp, 'is_managerial', False) or any(kw in job_name for kw in ['manager', 'director', 'chief', 'team leader', 'head', 'vp', 'supervisor'])
        )

        type_to_level_code = {
            'final_warning_penalty': 'level_2',
            'second_warning_penalty': 'level_3',
            'first_warning_penalty': 'level_4',
        }
        target_code = type_to_level_code.get(punishment_type)

        severity_level = False
        if target_code:
            severity_level = self.env['discipline.severity.level'].search([('code', '=', target_code)], limit=1)

        if is_managerial:
            self.revised_penalty_percentage = 0.0
            if severity_level:
                self.revised_fine_days = getattr(severity_level, 'default_managerial_fine_days', 0.0) or getattr(severity_level, 'default_fine_days', 0.0) or (3.0 if target_code == 'level_2' else (2.0 if target_code == 'level_3' else 1.0))
            else:
                self.revised_fine_days = 3.0 if punishment_type == 'final_warning_penalty' else (2.0 if punishment_type == 'second_warning_penalty' else 1.0)
        else:
            self.revised_fine_days = 0.0
            if severity_level:
                self.revised_penalty_percentage = getattr(severity_level, 'default_non_managerial_penalty_pct', 0.0) or getattr(severity_level, 'default_penalty_percentage', 0.0) or (20.0 if target_code == 'level_2' else (10.0 if target_code == 'level_3' else 5.0))
            else:
                self.revised_penalty_percentage = 20.0 if punishment_type == 'final_warning_penalty' else (10.0 if punishment_type == 'second_warning_penalty' else 5.0)

    @api.onchange('decision_outcome')
    def _onchange_decision_outcome(self):
        """Automatically set revised punishment and clear penalties if decision is overturned,
        upheld, or reduced."""
        if self.decision_outcome == 'overturned':
            self.revised_punishment_type = 'exonerate'
            self.revised_penalty_percentage = 0.0
            self.revised_fine_days = 0.0
        elif self.decision_outcome == 'upheld':
            self.revised_punishment_type = self.original_punishment_type or (self.case_id and (self.case_id.decided_punishment_type or self.case_id.punishment_type))
            self.revised_penalty_percentage = self.original_penalty_percentage if self.original_penalty_percentage > 0 else (self.case_id.penalty_percentage if self.case_id else 0.0)
            self.revised_fine_days = self.original_fine_days if self.original_fine_days > 0 else (self.case_id.fine_days if self.case_id else 0.0)
        elif self.decision_outcome == 'penalty_reduced':
            orig = self.original_punishment_type or (self.case_id and (self.case_id.decided_punishment_type or self.case_id.punishment_type))
            reduction_defaults = {
                'dismissal': 'final_warning_penalty',
                'demotion': 'final_warning_penalty',
                'final_warning_penalty': 'second_warning_penalty',
                'second_warning_penalty': 'first_warning_penalty',
                'first_warning_penalty': 'verbal_warning',
                'verbal_warning': 'exonerate',
                'exonerate': 'exonerate',
            }
            default_lower = reduction_defaults.get(orig, 'exonerate')
            self.revised_punishment_type = default_lower
            self._compute_and_set_revised_penalties(default_lower)

    @api.onchange('revised_punishment_type')
    def _onchange_revised_punishment_type(self):
        """Auto-populate default penalty percentage and salary fine days based on severity policy matrix,
        and validate that revised punishment does not exceed original punishment when reducing penalty."""
        if not self.revised_punishment_type:
            return

        punishment_rank = {
            'dismissal': 6,
            'demotion': 5,
            'final_warning_penalty': 4,
            'second_warning_penalty': 3,
            'first_warning_penalty': 2,
            'verbal_warning': 1,
            'exonerate': 0,
            False: 0,
        }
        reduction_defaults = {
            'dismissal': 'final_warning_penalty',
            'demotion': 'final_warning_penalty',
            'final_warning_penalty': 'second_warning_penalty',
            'second_warning_penalty': 'first_warning_penalty',
            'first_warning_penalty': 'verbal_warning',
            'verbal_warning': 'exonerate',
            'exonerate': 'exonerate',
        }

        # Severity filtering & enforcement when penalty is reduced
        if self.decision_outcome == 'penalty_reduced':
            orig_punish = self.original_punishment_type or (self.case_id and (self.case_id.decided_punishment_type or self.case_id.punishment_type))
            orig_rank = punishment_rank.get(orig_punish, 0)
            rev_rank = punishment_rank.get(self.revised_punishment_type, 0)

            if rev_rank > orig_rank:
                default_lower = reduction_defaults.get(orig_punish, 'exonerate')
                orig_label = dict(self._fields['original_punishment_type'].selection).get(orig_punish, orig_punish or 'None')
                attempted_label = dict(self._fields['revised_punishment_type'].selection).get(self.revised_punishment_type, self.revised_punishment_type or 'None')
                reset_label = dict(self._fields['revised_punishment_type'].selection).get(default_lower, default_lower)

                self.revised_punishment_type = default_lower
                self._compute_and_set_revised_penalties(default_lower)

                return {
                    'warning': {
                        'title': _('Invalid Disciplinary Sanction Selection'),
                        'message': _(
                            "When selecting 'Penalty / Action Reduced', the revised punishment cannot be more severe than "
                            "the original baseline penalty ('%s').\n\n"
                            "Attempted selection '%s' has been automatically reset to allowable reduced sanction '%s'."
                        ) % (orig_label, attempted_label, reset_label)
                    }
                }

        self._compute_and_set_revised_penalties(self.revised_punishment_type)

    @api.onchange('revised_penalty_percentage', 'revised_fine_days')
    def _onchange_revised_penalty_amounts(self):
        """Ensure revised monetary deductions do not exceed original baseline values when reducing penalty."""
        if self.decision_outcome == 'penalty_reduced':
            punishment_rank = {
                'dismissal': 6,
                'demotion': 5,
                'final_warning_penalty': 4,
                'second_warning_penalty': 3,
                'first_warning_penalty': 2,
                'verbal_warning': 1,
                'exonerate': 0,
                False: 0,
            }
            orig_punish = self.original_punishment_type or (self.case_id and (self.case_id.original_punishment_type or self.case_id.punishment_type))
            orig_rank = punishment_rank.get(orig_punish, 0)
            rev_rank = punishment_rank.get(self.revised_punishment_type, 0)

            orig_pct = self.original_penalty_percentage
            orig_days = self.original_fine_days

            if orig_punish in ('demotion', 'dismissal') and rev_rank < orig_rank:
                # Structural reduction down to warning/fine: allowable
                return

            if self.revised_penalty_percentage > orig_pct and orig_pct > 0:
                self.revised_penalty_percentage = orig_pct
                return {
                    'warning': {
                        'title': _('Invalid Penalty Percentage'),
                        'message': _("Under 'Penalty Reduced', revised penalty percentage cannot exceed the original baseline (%s%%).") % orig_pct
                    }
                }

            if self.revised_fine_days > orig_days and orig_days > 0:
                self.revised_fine_days = orig_days
                return {
                    'warning': {
                        'title': _('Invalid Fine Days'),
                        'message': _("Under 'Penalty Reduced', revised salary fine days cannot exceed the original baseline (%s days).") % orig_days
                    }
                }

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Appeal Submitted'),
        ('under_review', 'Under Review'),
        ('committee_review', 'Under Committee Review'),
        ('decided', 'Final Decision Rendered'),
        ('rejected_expired', 'Rejected (Window Expired)'),
    ], string='Status', default='draft', required=True, tracking=True)

    committee_appeal_recommendation = fields.Text(
        string='Committee Deliberation & Recommendation',
        tracking=True,
        help="Deliberations and recommended decision by the Disciplinary Committee when an appeal is referred by the CEO."
    )

    is_appeal_reviewer_or_admin = fields.Boolean(
        string='Is Appeal Reviewer or Admin',
        compute='_compute_is_appeal_reviewer_or_admin'
    )

    can_user_review_current_stage = fields.Boolean(
        string='Can User Review Current Stage',
        compute='_compute_can_user_review_current_stage'
    )

    is_appellant_employee = fields.Boolean(
        string='Is Appellant Employee',
        compute='_compute_is_appellant_employee'
    )

    is_managerial = fields.Boolean(
        string='Is Managerial Staff',
        compute='_compute_staff_category_flags',
        store=True,
        help="Indicates whether the appellant employee is in a managerial position (fine days vs penalty percentage)."
    )

    @api.depends('case_id', 'case_id.staff_category', 'case_id.employee_id', 'employee_id', 'employee_id.job_id')
    def _compute_staff_category_flags(self):
        for rec in self:
            if rec.case_id and rec.case_id.staff_category:
                rec.is_managerial = (rec.case_id.staff_category == 'managerial')
            else:
                emp = rec.employee_id or (rec.case_id and rec.case_id.employee_id)
                job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
                rec.is_managerial = getattr(emp, 'is_managerial', False) or any(kw in job_name for kw in ['manager', 'director', 'chief', 'team leader', 'head', 'vp', 'supervisor'])

    @api.depends_context('uid')
    def _compute_is_appeal_reviewer_or_admin(self):
        user = self.env.user
        is_reviewer = (
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_pomd_director') or
            user.has_group('discipline_management.group_discipline_cpco') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('discipline_management.group_discipline_admin') or
            user._is_superuser()
        )
        for rec in self:
            rec.is_appeal_reviewer_or_admin = is_reviewer or bool(rec.designated_reviewer_id and rec.designated_reviewer_id.id == user.id)

    @api.depends_context('uid')
    @api.depends('designated_reviewer_id', 'appeal_target_authority', 'appeal_level', 'case_origin_type', 'case_id', 'case_id.reported_by_id', 'case_id.employee_id', 'state')
    def _compute_can_user_review_current_stage(self):
        user = self.env.user
        EmpModel = self.env['hr.employee'].sudo()
        cpco_user = EmpModel.get_cpco_user()
        sec_user = EmpModel.get_secretary_user()
        ceo_user = EmpModel.get_ceo_user()
        is_admin = user.has_group('discipline_management.group_discipline_admin') or user._is_superuser()
        is_ceo = bool((ceo_user and user.id == ceo_user.id) or user.has_group('discipline_management.group_discipline_ceo'))
        is_chief_corp = bool((cpco_user and user.id == cpco_user.id) or user.has_group('discipline_management.group_discipline_cpco'))
        is_pomd = bool((sec_user and user.id == sec_user.id) or user.has_group('discipline_management.group_discipline_pomd_director') or user.has_group('discipline_management.group_discipline_pomd'))
        emp = user.sudo().employee_id

        for rec in self:
            if is_admin:
                rec.can_user_review_current_stage = True
                continue

            if rec.state == 'committee_review':
                # During committee review, Committee Secretary, CPCO Chair, or Admin can deliberate and submit recommendation
                rec.can_user_review_current_stage = bool(is_pomd or is_chief_corp)
                continue

            target = rec.appeal_target_authority
            case_sudo = rec.case_id.sudo() if rec.case_id else False
            if target == 'ceo':
                rec.can_user_review_current_stage = is_ceo
            elif target == 'secretary':
                rec.can_user_review_current_stage = is_pomd
            elif rec.designated_reviewer_id and rec.designated_reviewer_id.id == user.id:
                # User is the designated reviewer in the coach hierarchy
                rec.can_user_review_current_stage = True
            elif target == 'directorate' and case_sudo and case_sudo.director_id and case_sudo.director_id.id == user.id:
                rec.can_user_review_current_stage = True
            elif target == 'chief' and ((case_sudo and case_sudo.chief_id and case_sudo.chief_id.id == user.id) or is_chief_corp):
                rec.can_user_review_current_stage = True
            elif emp and rec.designated_reviewer_id and rec.designated_reviewer_id.sudo().employee_id:
                # Superior coach above designated reviewer can also review / oversee
                sup_chain = rec._get_superior_coach_chain(rec.designated_reviewer_id.sudo().employee_id)
                rec.can_user_review_current_stage = bool(any(s.id == emp.id for s in sup_chain))
            else:
                rec.can_user_review_current_stage = False

    @api.depends_context('uid')
    @api.depends('case_id', 'case_id.employee_id', 'employee_id')
    def _compute_is_appellant_employee(self):
        current_user = self.env.user
        current_emp = current_user.sudo().employee_id
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system')
        for rec in self:
            emp = rec.sudo().employee_id or (rec.case_id and rec.case_id.sudo().employee_id)
            if not emp and current_emp:
                emp = current_emp
            is_emp = bool(
                emp and (
                    (emp.user_id and emp.user_id.id == current_user.id) or
                    (current_emp and current_emp.id == emp.id) or
                    (hasattr(current_user, 'employee_ids') and emp.id in current_user.sudo().employee_ids.ids)
                )
            )
            # Default to True for new/unsaved records
            if not rec.id:
                is_emp = True
            rec.is_appellant_employee = is_emp or is_admin

    can_submit_next_appeal = fields.Boolean(
        string='Can Submit Next Appeal',
        compute='_compute_can_submit_next_appeal'
    )
    next_appeal_button_label = fields.Char(
        string='Next Appeal Button Label',
        compute='_compute_can_submit_next_appeal'
    )

    # Backward compatibility alias
    can_submit_second_appeal = fields.Boolean(
        string='Can Submit 2nd Appeal',
        related='can_submit_next_appeal'
    )

    @api.depends_context('uid')
    @api.depends('state', 'acceptance_state', 'decision_outcome', 'revised_punishment_type', 'revised_penalty_percentage', 'revised_fine_days', 'employee_id', 'case_id', 'appeal_level')
    def _compute_can_submit_next_appeal(self):
        current_user = self.env.user
        is_pomd = current_user.has_group('discipline_management.group_discipline_pomd') or current_user.has_group('discipline_management.group_discipline_admin')
        for rec in self:
            emp = rec.sudo().employee_id
            is_emp = bool(
                emp and (
                    (emp.user_id and emp.user_id.id == current_user.id) or
                    (current_user.sudo().employee_id and current_user.sudo().employee_id.id == emp.id) or
                    (hasattr(current_user, 'employee_ids') and emp.id in current_user.sudo().employee_ids.ids)
                )
            )
            is_dismissal_inactive = bool(
                rec.case_id and
                (rec.case_id.severity_level == 'level_1' or rec.case_id.punishment_type == 'dismissal') and
                emp and (not emp.active or (emp.user_id and not emp.user_id.active))
            )
            eligible_user = is_emp or (is_pomd and is_dismissal_inactive)

            is_fully_cleared = (
                rec.decision_outcome == 'overturned' or
                rec.revised_punishment_type == 'exonerate' or
                (rec.decision_outcome == 'penalty_reduced' and rec.revised_penalty_percentage == 0.0 and rec.revised_fine_days == 0.0 and rec.revised_punishment_type in ('exonerate', False))
            )

            # Check if record is decided and outcome has remaining penalty to appeal
            is_decided_with_penalty = (
                rec.state == 'decided' and
                rec.decision_outcome in ('upheld', 'penalty_reduced') and
                rec.acceptance_state == 'pending' and
                not is_fully_cleared
            )

            # Check if next level is available: appeals continue until decided by the CEO
            actual_reviewer = rec.reviewer_id or rec.designated_reviewer_id
            EmpModel = self.env['hr.employee'].sudo()
            ceo_user = EmpModel.get_ceo_user()
            is_ceo_decision = bool(
                (ceo_user and actual_reviewer and actual_reviewer.id == ceo_user.id) or
                (actual_reviewer and actual_reviewer.has_group('discipline_management.group_discipline_ceo')) or
                rec.appeal_target_authority == 'ceo'
            )
            has_next_level = not is_ceo_decision
            label = _('Submit Appeal')

            # Check if child appeal is already created
            has_child = bool(rec.child_appeal_ids)

            # Check if case currently has any active appeal in progress
            case_has_active = bool(rec.case_id and any(
                a.id != rec.id and a.state in ('draft', 'submitted', 'under_review')
                for a in rec.case_id.appeal_ids
            ))

            rec.can_submit_next_appeal = (
                eligible_user and
                is_decided_with_penalty and
                has_next_level and
                not has_child and
                not case_has_active
            )
            rec.next_appeal_button_label = label

    can_employee_accept_decision = fields.Boolean(
        string='Can Employee Accept Decision',
        compute='_compute_can_employee_accept_decision'
    )

    @api.depends_context('uid')
    @api.depends(
        'state', 'acceptance_state', 'decision_outcome', 'revised_punishment_type',
        'revised_penalty_percentage', 'revised_fine_days', 'appeal_target_authority',
        'appeal_level', 'employee_id', 'reviewer_id', 'designated_reviewer_id',
        'case_id.punishment_type', 'case_id.state', 'case_id.is_exonerated_case'
    )
    def _compute_can_employee_accept_decision(self):
        current_user = self.env.user
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        for rec in self:
            emp = rec.sudo().employee_id
            is_emp = bool(
                emp and (
                    (emp.user_id and emp.user_id.id == current_user.id) or
                    (current_user.sudo().employee_id and current_user.sudo().employee_id.id == emp.id) or
                    (hasattr(current_user, 'employee_ids') and emp.id in current_user.sudo().employee_ids.ids)
                )
            )
            is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system')
            eligible_user = is_emp or is_admin

            # 1. Exonerated check: If exonerated, employee is fully cleared; no sanction to accept.
            is_exonerated = bool(
                rec.decision_outcome == 'overturned' or
                rec.revised_punishment_type == 'exonerate' or
                (rec.decision_outcome == 'penalty_reduced' and rec.revised_penalty_percentage == 0.0 and rec.revised_fine_days == 0.0 and rec.revised_punishment_type in ('exonerate', False)) or
                (rec.case_id and (rec.case_id.punishment_type == 'exonerate' or rec.case_id.is_exonerated_case))
            )

            # 2. Last Authority check: If decided by the CEO or 4th stage, the decision is final and binding immediately.
            actual_reviewer = rec.reviewer_id or rec.designated_reviewer_id
            is_last_authority = bool(
                (ceo_user and actual_reviewer and actual_reviewer.id == ceo_user.id) or
                (actual_reviewer and actual_reviewer.has_group('discipline_management.group_discipline_ceo')) or
                rec.appeal_target_authority == 'ceo' or
                rec.appeal_level == 'fourth'
            )

            rec.can_employee_accept_decision = bool(
                eligible_user and
                rec.state in ('decided', 'closed') and
                rec.acceptance_state == 'pending' and
                not is_exonerated and
                not is_last_authority
            )

    # Case Completed / Enforced Validation
    @api.constrains('case_id')
    def _check_case_enforced_for_appeal(self):
        for rec in self:
            if rec.case_id and rec.case_id.state not in ('enforced', 'closed', 'appealed'):
                case_status = dict(rec.case_id._fields['state'].selection).get(rec.case_id.state, rec.case_id.state)
                raise ValidationError(_(
                    'Invalid Appeal Request: An appeal cannot be requested before the disciplinary case is completed and enforced. '
                    'Case "%s" is currently in "%s" state.'
                ) % (rec.case_id.name, case_status))

    # Appeal Window Enforcement (10 Calendar Days for 1st level appeal)
    @api.constrains('submission_date', 'case_id')
    def _check_appeal_window(self):
        for rec in self:
            if rec.appeal_level != 'first':
                continue
            if rec.case_id:
                base_date = rec.case_id.final_decision_date or rec.case_id.delivery_receipt_date
                if base_date:
                    deadline = rec.case_id.appeal_deadline
                    if not deadline:
                        ICP = self.env['ir.config_parameter'].sudo()
                        val = ICP.get_param('discipline_management.appeal_window_days') or ICP.get_param('discipline.appeal_window_days')
                        try:
                            appeal_days = int(val) if val else 5
                        except (ValueError, TypeError):
                            appeal_days = 5
                        deadline = base_date + timedelta(days=appeal_days)
                    if rec.submission_date > deadline:
                        raise ValidationError(_(
                            'Appeal Window Expired: Policy restricts appeal submission to the configured appeal window '
                            'from the decision date (%s). Deadline was %s.'
                        ) % (base_date, deadline))

    # Duplicate & Active Appeal Validation for Same Case
    @api.constrains('case_id', 'appeal_level', 'state')
    def _check_duplicate_appeals(self):
        """Validate that:
        1. Only ONE active appeal (draft, submitted, under_review) can exist per case at any given time.
        2. Only one appeal can exist per case at the same appeal level.
        3. A higher-level appeal cannot be lodged before prior levels are decided.
        4. No subsequent appeal can be lodged if a prior level fully exonerated the employee or was decided by the CEO.
        """
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()

        def _is_ceo_decision(app):
            act_rev = app.reviewer_id or app.designated_reviewer_id
            return bool(
                (ceo_user and act_rev and act_rev.id == ceo_user.id) or
                (act_rev and act_rev.has_group('discipline_management.group_discipline_ceo')) or
                app.appeal_target_authority == 'ceo'
            )

        def _is_exonerated(app):
            return bool(
                app.decision_outcome == 'overturned' or
                app.revised_punishment_type == 'exonerate' or
                (app.decision_outcome == 'penalty_reduced' and app.revised_penalty_percentage == 0.0 and app.revised_fine_days == 0.0 and app.revised_punishment_type in ('exonerate', False))
            )

        for rec in self:
            if not rec.case_id:
                continue

            rec_id = rec._origin.id if rec._origin else (rec.id if isinstance(rec.id, int) else 0)

            # 0. Check if any prior appeal on this case was already accepted by the appellant or window closed
            accepted_appeal = self.search([
                ('id', '!=', rec_id),
                ('case_id', '=', rec.case_id.id),
                ('acceptance_state', 'in', ('accepted', 'window_closed')),
            ], limit=1)
            if accepted_appeal:
                status_label = 'accepted by the appellant' if accepted_appeal.acceptance_state == 'accepted' else 'finalized (window closed)'
                raise ValidationError(_(
                    'Appeal Already Finalized: Disciplinary Case "%(case)s" was already %(status)s '
                    '(Appeal Ref: %(ref)s). Under Bank Disciplinary Policy, no further appeals can be lodged for this case.'
                ) % {
                    'case': rec.case_id.name,
                    'status': status_label,
                    'ref': accepted_appeal.name,
                })

            # Check if case itself was originally exonerated with no sanction (only applies when lodging appeal)
            if rec.state in ('draft', 'submitted') and (
                rec.original_punishment_type == 'exonerate' or
                (not rec.original_punishment_type and (
                    rec.case_id.punishment_type == 'exonerate' or
                    rec.case_id.decided_punishment_type == 'exonerate' or
                    getattr(rec.case_id, 'is_exonerated_case', False)
                ))
            ):
                raise ValidationError(_(
                    'Cannot Appeal Exonerated Case: Disciplinary Case "%s" has no active disciplinary sanction or was exonerated. '
                    'Appeals can only be lodged against cases with active penalties.'
                ) % rec.case_id.name)

            # 1. Enforce ONLY ONE active appeal per case at any given time
            if rec.state in ('draft', 'submitted', 'under_review'):
                other_active = self.search([
                    ('id', '!=', rec_id),
                    ('case_id', '=', rec.case_id.id),
                    ('state', 'in', ('draft', 'submitted', 'under_review')),
                ], limit=1)
                if other_active:
                    other_state = dict(self._fields['state'].selection).get(other_active.state, other_active.state)
                    other_level = dict(self._fields['appeal_level'].selection).get(other_active.appeal_level, other_active.appeal_level)
                    raise ValidationError(_(
                        'Active Appeal in Progress: Disciplinary Case "%(case)s" already has an active appeal (Ref: %(ref)s, %(level)s Stage) '
                        'currently in "%(state)s" status.\n\n'
                        'Under Bank Disciplinary Policy, a case can have ONLY ONE active appeal at any time. '
                        'The ongoing appeal must be formally reviewed and decided before any subsequent appeal can be lodged.'
                    ) % {
                        'case': rec.case_id.name,
                        'ref': other_active.name,
                        'level': other_level,
                        'state': other_state,
                    })

            # 2. Prevent duplicate appeals for the same case and same appeal level
            duplicate_same_level = self.search([
                ('id', '!=', rec_id),
                ('case_id', '=', rec.case_id.id),
                ('appeal_level', '=', rec.appeal_level),
            ], limit=1)
            if duplicate_same_level:
                stage_name = dict(self._fields['appeal_level'].selection).get(rec.appeal_level, rec.appeal_level)
                raise ValidationError(_(
                    'Duplicate Appeal Error: An appeal record (%s) already exists for Case "%s" at the "%s" level. '
                    'You cannot create duplicate appeals for the same case at the same level.'
                ) % (duplicate_same_level.name, rec.case_id.name, stage_name))

            # 3. Prevent creating 2nd level appeal without a completed 1st level appeal
            if rec.appeal_level == 'second':
                first_appeal = self.search([
                    ('id', '!=', rec.id),
                    ('case_id', '=', rec.case_id.id),
                    ('appeal_level', '=', 'first'),
                ], limit=1)
                if not first_appeal:
                    raise ValidationError(_(
                        'Invalid Appeal Stage: A 2nd Level Appeal cannot be created for Case "%s" without an existing 1st Level Appeal.'
                    ) % rec.case_id.name)
                if first_appeal.state != 'decided':
                    raise ValidationError(_(
                        'Pending Appeal in Progress: Cannot lodge a 2nd Level Appeal because the 1st Level Appeal (%s) is still pending review (%s).'
                    ) % (first_appeal.name, first_appeal.state))
                if _is_exonerated(first_appeal):
                    raise ValidationError(_(
                        'Appeal Already Concluded: The 1st Level Appeal (%s) resulted in full exoneration / reversal of sanctions. No further appeals can be submitted.'
                    ) % first_appeal.name)
                if _is_ceo_decision(first_appeal):
                    raise ValidationError(_(
                        'Final Decision Reached: The 1st Level Appeal (%s) was decided by the Chief Executive Officer (CEO), which is the final appeal authority. No further appeals can be submitted.'
                    ) % first_appeal.name)

            # 4. Prevent creating 3rd level appeal without completed 1st and 2nd level appeals
            elif rec.appeal_level == 'third':
                second_appeal = self.search([
                    ('id', '!=', rec.id),
                    ('case_id', '=', rec.case_id.id),
                    ('appeal_level', '=', 'second'),
                ], limit=1)
                if not second_appeal:
                    raise ValidationError(_(
                        'Invalid Appeal Stage: A 3rd Level Appeal cannot be created for Case "%s" without an existing 2nd Level Appeal.'
                    ) % rec.case_id.name)
                if second_appeal.state != 'decided':
                    raise ValidationError(_(
                        'Pending Appeal in Progress: Cannot lodge a 3rd Level Appeal because the 2nd Level Appeal (%s) is still pending review (%s).'
                    ) % (second_appeal.name, second_appeal.state))
                if _is_exonerated(second_appeal):
                    raise ValidationError(_(
                        'Appeal Already Concluded: The 2nd Level Appeal (%s) resulted in full exoneration / reversal of sanctions. No further appeals can be submitted.'
                    ) % second_appeal.name)
                if _is_ceo_decision(second_appeal):
                    raise ValidationError(_(
                        'Final Decision Reached: The 2nd Level Appeal (%s) was decided by the Chief Executive Officer (CEO), which is the final appeal authority. No further appeals can be submitted.'
                    ) % second_appeal.name)

            # 5. Prevent creating 4th level appeal without completed 1st, 2nd, and 3rd level appeals
            elif rec.appeal_level == 'fourth':
                third_appeal = self.search([
                    ('id', '!=', rec.id),
                    ('case_id', '=', rec.case_id.id),
                    ('appeal_level', '=', 'third'),
                ], limit=1)
                if not third_appeal:
                    raise ValidationError(_(
                        'Invalid Appeal Stage: A 4th Level Appeal cannot be created for Case "%s" without an existing 3rd Level Appeal.'
                    ) % rec.case_id.name)
                if third_appeal.state != 'decided':
                    raise ValidationError(_(
                        'Pending Appeal in Progress: Cannot lodge a 4th Level Appeal because the 3rd Level Appeal (%s) is still pending review (%s).'
                    ) % (third_appeal.name, third_appeal.state))
                if _is_exonerated(third_appeal):
                    raise ValidationError(_(
                        'Appeal Already Concluded: The 3rd Level Appeal (%s) resulted in full exoneration / reversal of sanctions. No further appeals can be submitted.'
                    ) % third_appeal.name)
                if _is_ceo_decision(third_appeal):
                    raise ValidationError(_(
                        'Final Decision Reached: The 3rd Level Appeal (%s) was decided by the Chief Executive Officer (CEO), which is the final appeal authority. No further appeals can be submitted.'
                    ) % third_appeal.name)

    # Appeal Decision Outcome & Penalty Reduction Order Validation
    @api.constrains('decision_outcome', 'revised_punishment_type', 'revised_penalty_percentage', 'revised_fine_days', 'state')
    def _check_decision_outcome_validity(self):
        """Validate that the appeal decision outcome strictly complies with penalty hierarchy rules:
        1. 'penalty_reduced' must strictly reduce punishment severity or monetary deductions compared to baseline.
        2. 'upheld' must maintain the baseline penalty without modification.
        3. 'overturned' must fully exonerate the employee (zero penalty).
        """
        punishment_rank = {
            'dismissal': 6,
            'demotion': 5,
            'final_warning_penalty': 4,
            'second_warning_penalty': 3,
            'first_warning_penalty': 2,
            'verbal_warning': 1,
            'exonerate': 0,
            False: 0,
        }
        for rec in self:
            if rec.state not in ('under_review', 'decided') or not rec.decision_outcome:
                continue

            orig_punish = rec.original_punishment_type
            rev_punish = rec.revised_punishment_type
            orig_rank = punishment_rank.get(orig_punish, 0)
            rev_rank = punishment_rank.get(rev_punish, 0)

            orig_pct = round(rec.original_penalty_percentage, 2)
            rev_pct = round(rec.revised_penalty_percentage, 2)
            orig_days = round(rec.original_fine_days, 2)
            rev_days = round(rec.revised_fine_days, 2)

            if rec.decision_outcome == 'penalty_reduced':
                # Rule A: Cannot increase punishment severity rank
                if rev_rank > orig_rank:
                    orig_label = dict(self._fields['original_punishment_type'].selection).get(orig_punish, orig_punish or 'None')
                    rev_label = dict(self._fields['revised_punishment_type'].selection).get(rev_punish, rev_punish or 'None')
                    raise ValidationError(_(
                        "Invalid Appeal Decision: You selected 'Penalty / Action Reduced', but the revised punishment ('%s') "
                        "is more severe than the baseline penalty ('%s'). An appeal cannot increase penalty severity."
                    ) % (rev_label, orig_label))

                # Rule B: Cannot increase monetary deductions
                # Demotion/Dismissal is a severe structural sanction where fine days/percentage are 0.
                # Reducing Demotion down to a Warning (rank 1-4) is a significant reduction in sanction severity.
                # In such cases, the warning's standard fine days / penalty percentage are allowed.
                is_structural_reduction = (orig_punish in ('demotion', 'dismissal') and rev_rank < orig_rank)
                if not is_structural_reduction:
                    if rev_pct > orig_pct or rev_days > orig_days:
                        raise ValidationError(_(
                            "Invalid Appeal Decision: You selected 'Penalty / Action Reduced', but the revised penalty (%s%%, %s fine days) "
                            "is greater than the baseline penalty (%s%%, %s fine days)."
                        ) % (rev_pct, rev_days, orig_pct, orig_days))

                # Rule C: If punishment rank is identical, monetary deductions MUST be strictly reduced
                if rev_rank == orig_rank and rev_pct == orig_pct and rev_days == orig_days:
                    orig_label = dict(self._fields['original_punishment_type'].selection).get(orig_punish, orig_punish or 'None')
                    raise ValidationError(_(
                        "Invalid Appeal Decision: You selected 'Penalty / Action Reduced', but the revised punishment and penalties "
                        "are identical to the baseline penalty (%s, %s%%, %s fine days).\n\n"
                        "• To maintain the exact same penalty, please select 'Original Decision Upheld (Appeal Rejected)'.\n"
                        "• To reduce the penalty, select a lower severity punishment or decrease the penalty percentage / fine days."
                    ) % (orig_label, orig_pct, orig_days))

            elif rec.decision_outcome == 'upheld':
                # Upheld maintains the exact original penalty
                if rev_punish and (rev_rank != orig_rank or rev_pct != orig_pct or rev_days != orig_days):
                    orig_label = dict(self._fields['original_punishment_type'].selection).get(orig_punish, orig_punish or 'None')
                    raise ValidationError(_(
                        "Invalid Appeal Decision: You selected 'Original Decision Upheld (Appeal Rejected)', but modified the punishment "
                        "or penalty values. When upholding a decision, the baseline penalty (%s, %s%%, %s fine days) must remain unchanged."
                    ) % (orig_label, orig_pct, orig_days))

            elif rec.decision_outcome == 'overturned':
                # Overturned requires zero penalty
                if (rev_punish and rev_punish != 'exonerate') or rev_pct > 0 or rev_days > 0:
                    raise ValidationError(_(
                        "Invalid Appeal Decision: You selected 'Decision Overturned (Exonerated)'. "
                        "All penalties must be cleared to 0.00 and punishment set to 'Exonerated / No Action'."
                    ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.appeal') or _('New')

            case_id = vals.get('case_id')
            if case_id:
                active_existing = self.search([
                    ('case_id', '=', case_id),
                    ('state', 'in', ('draft', 'submitted', 'under_review')),
                ], limit=1)
                if active_existing:
                    case_rec = self.env['discipline.case'].browse(case_id)
                    act_state = dict(self._fields['state'].selection).get(active_existing.state, active_existing.state)
                    act_level = dict(self._fields['appeal_level'].selection).get(active_existing.appeal_level, active_existing.appeal_level)
                    raise ValidationError(_(
                        'Active Appeal in Progress: Case "%(case)s" already has an active appeal (Ref: %(ref)s, %(level)s Stage) '
                        'in "%(state)s" status.\n\n'
                        'Under Bank Disciplinary Policy, a case can have ONLY ONE active appeal at any given time. '
                        'The ongoing appeal must be formally decided before lodging another appeal.'
                    ) % {
                        'case': case_rec.name,
                        'ref': active_existing.name,
                        'level': act_level,
                        'state': act_state,
                    })

        appeals = super().create(vals_list)
        for app in appeals:
            if app.parent_appeal_id:
                app.parent_appeal_id.write({'acceptance_state': 'appealed_further'})
            if app.case_id and not self.env.su:
                current_user = self.env.user
                emp = app.sudo().employee_id
                is_self = bool(
                    (emp and emp.user_id and emp.user_id.id == current_user.id) or
                    (current_user.sudo().employee_id and current_user.sudo().employee_id.id == emp.id)
                )
                is_dismissal = bool(
                    app.case_id.punishment_type == 'dismissal' or
                    app.case_id.severity_level == 'level_1' or
                    app.case_id.decided_punishment_type == 'dismissal' or
                    app.original_punishment_type == 'dismissal'
                )
                is_auth_third_party = (
                    current_user.has_group('discipline_management.group_discipline_pomd') or
                    current_user.has_group('discipline_management.group_discipline_admin') or
                    current_user.has_group('base.group_system')
                )
                if not is_self and not (is_dismissal and is_auth_third_party):
                    raise ValidationError(_(
                        "Appeal Access Denied: Disciplinary appeals must be submitted directly by the employee (%s). "
                        "Submissions on behalf by HR / POMD are permitted solely for Dismissal / Separation cases."
                    ) % (emp.name if emp else 'Employee'))

            if app.state == 'submitted' and app.case_id:
                app.case_id.sudo().with_context(force_write=True).write({'state': 'appealed'})
                app.case_id.sudo().message_post(body=_('Appeal %s (%s) submitted against Case decision.') % (app.name, app.appeal_level))
                app._send_appeal_submission_notifications()
        return appeals

    def action_submit_appeal(self):
        """Explicitly submit draft appeal and transition parent case to appealed state."""
        for rec in self:
            if not rec.appeal_grounds:
                raise UserError(_('Please provide the grounds and justification for your appeal before submitting.'))
            if rec.case_id and rec.case_id.state not in ('enforced', 'closed', 'appealed'):
                raise UserError(_('An appeal can only be submitted for a disciplinary case that has been finalized and enforced.'))

            # Ensure no OTHER appeal is currently submitted or under review for this case
            if rec.case_id:
                other_active = self.search([
                    ('id', '!=', rec.id),
                    ('case_id', '=', rec.case_id.id),
                    ('state', 'in', ('submitted', 'under_review')),
                ], limit=1)
                if other_active:
                    raise UserError(_(
                        'Active Appeal in Progress: Case "%(case)s" already has an active appeal (Ref: %(ref)s) in "%(state)s" status. '
                        'The pending appeal must be formally decided before submitting another appeal.'
                    ) % {
                        'case': rec.case_id.name,
                        'ref': other_active.name,
                        'state': dict(self._fields['state'].selection).get(other_active.state, other_active.state),
                    })
            
            # Submission access check
            current_user = self.env.user
            emp = rec.sudo().employee_id
            is_self = bool(
                (emp and emp.user_id and emp.user_id.id == current_user.id) or
                (current_user.sudo().employee_id and current_user.sudo().employee_id.id == emp.id)
            )
            is_dismissal = bool(
                rec.case_id and (
                    rec.case_id.punishment_type == 'dismissal' or
                    rec.case_id.severity_level == 'level_1' or
                    rec.case_id.decided_punishment_type == 'dismissal' or
                    rec.original_punishment_type == 'dismissal'
                )
            )
            is_auth_third_party = (
                current_user.has_group('discipline_management.group_discipline_pomd') or
                current_user.has_group('discipline_management.group_discipline_admin') or
                current_user.has_group('base.group_system')
            )
            if not is_self and not (is_dismissal and is_auth_third_party):
                raise UserError(_(
                    "Appeal Access Denied: Disciplinary appeals must be submitted directly by the employee (%s). "
                    "Submissions on behalf by HR / POMD are permitted solely for Dismissal / Separation cases."
                ) % (emp.name if emp else 'Employee'))

            if rec.appeal_level == 'first' and rec.case_id:
                rec._check_appeal_window()
            rec.write({'state': 'submitted'})
            if rec.case_id:
                rec.case_id.sudo().with_context(force_write=True).write({'state': 'appealed'})
                # Place pending payroll deductions on appeal hold
                pending_pens = self.env['discipline.payroll.penalty'].sudo().search([
                    ('case_id', '=', rec.case_id.id),
                    ('state', '=', 'pending'),
                    ('transaction_type', '=', 'deduction'),
                ])
                if pending_pens:
                    pending_pens.write({'is_appeal_held': True})
                rec.case_id.sudo().message_post(body=_(
                    'Appeal %s (%s) submitted against Case decision. Pending payroll penalty deductions placed on appeal hold.'
                ) % (rec.name, rec.appeal_level))
            rec._send_appeal_submission_notifications()
        return {'type': 'ir.actions.act_window_close'}

    def _send_appeal_submission_notifications(self):
        """Send official notifications to the case initiator, prior reviewers, and designated appeal reviewer."""
        for rec in self:
            case = rec.case_id.sudo() if rec.case_id else False
            appellant_name = rec.sudo().employee_id.name if rec.sudo().employee_id else _('Employee')
            case_name = case.name if case else _('Disciplinary Case')
            appeal_lvl_label = dict(rec._fields['appeal_level'].selection).get(rec.appeal_level, rec.appeal_level)
            target_label = dict(rec._fields['appeal_target_authority'].selection).get(rec.appeal_target_authority, rec.appeal_target_authority)
            EmpModel = self.env['hr.employee'].sudo()

            # 1. Notify Case Initiator / Reporting Manager (Eyob)
            initiator_user = (case.reported_by_id and case.reported_by_id.user_id) or (case.create_uid if case else False)
            if initiator_user and initiator_user.partner_id:
                rec.sudo().message_subscribe(partner_ids=[initiator_user.partner_id.id])
                if case:
                    case.sudo().message_subscribe(partner_ids=[initiator_user.partner_id.id])
                
                try:
                    channel = self.env['discuss.channel'].with_user(rec.env.user)._get_or_create_chat(
                        partners_to=[initiator_user.partner_id.id]
                    )
                    if channel:
                        msg_body = Markup(_(
                            '<p><strong>Disciplinary Appeal Notice (%s Level)</strong></p>'
                            '<p>Dear %s,</p>'
                            '<p>Employee <strong>%s</strong> has submitted an appeal (Ref: <strong>%s</strong>, %s Level) against disciplinary case <strong>%s</strong>.</p>'
                            '<p><strong>Grounds for Appeal:</strong> <em>%s</em></p>'
                            '<p>The appeal has been routed to <strong>%s</strong> for official review.</p>'
                        ) % (
                            appeal_lvl_label,
                            initiator_user.name,
                            appellant_name,
                            rec.name,
                            appeal_lvl_label,
                            case_name,
                            rec.appeal_grounds or _('Not specified'),
                            target_label,
                        ))
                        channel.message_post(
                            body=msg_body,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment',
                            author_id=rec.env.user.partner_id.id,
                        )
                except Exception:
                    pass

            # 2. Notify Previous Stage Reviewer (e.g., Directorate Director Derese) if escalated
            if rec.parent_appeal_id and rec.parent_appeal_id.reviewer_id and rec.parent_appeal_id.reviewer_id.partner_id:
                prev_reviewer_user = rec.parent_appeal_id.reviewer_id
                rec.sudo().message_subscribe(partner_ids=[prev_reviewer_user.partner_id.id])
                try:
                    channel = self.env['discuss.channel'].with_user(rec.env.user)._get_or_create_chat(
                        partners_to=[prev_reviewer_user.partner_id.id]
                    )
                    if channel:
                        msg_body = Markup(_(
                            '<p><strong>Disciplinary Appeal Escalation Notice</strong></p>'
                            '<p>Dear %s,</p>'
                            '<p>Employee <strong>%s</strong> has escalated their appeal (Ref: <strong>%s</strong>, %s Level) against disciplinary case <strong>%s</strong> to <strong>%s</strong> following previous review decision on %s.</p>'
                            '<p><strong>Grounds for Appeal:</strong> <em>%s</em></p>'
                        ) % (
                            prev_reviewer_user.name,
                            appellant_name,
                            rec.name,
                            appeal_lvl_label,
                            case_name,
                            target_label,
                            rec.parent_appeal_id.name,
                            rec.appeal_grounds or _('Not specified'),
                        ))
                        channel.message_post(
                            body=msg_body,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment',
                            author_id=rec.env.user.partner_id.id,
                        )
                except Exception:
                    pass

            # 3. Resolve and Notify Designated Appeal Reviewer (e.g. Yeshanew for Chief level)
            reviewer_user = rec.reviewer_id
            if not reviewer_user:
                rep_emp = case.reported_by_id.sudo() if case and case.reported_by_id else False
                subj_emp = case.employee_id.sudo() if case and case.employee_id else False
                if rec.appeal_target_authority == 'directorate':
                    if case:
                        reviewer_user = (
                            case.director_id or
                            (rep_emp and (rep_emp.coach_id.user_id or rep_emp.parent_id.user_id)) or
                            (subj_emp and (subj_emp.coach_id.coach_id.user_id or subj_emp.parent_id.parent_id.user_id))
                        )
                elif rec.appeal_target_authority == 'chief':
                    if case:
                        reviewer_user = (
                            case.chief_id or
                            (rep_emp and (rep_emp.coach_id.coach_id.user_id or rep_emp.parent_id.parent_id.user_id)) or
                            (subj_emp and (subj_emp.coach_id.coach_id.coach_id.user_id or subj_emp.parent_id.parent_id.parent_id.user_id)) or
                            EmpModel.get_cpco_user()
                        )
                    else:
                        reviewer_user = EmpModel.get_cpco_user()
                elif rec.appeal_target_authority == 'secretary':
                    reviewer_user = EmpModel.get_secretary_user()
                elif rec.appeal_target_authority == 'ceo':
                    reviewer_user = EmpModel.get_ceo_user()

            if reviewer_user and reviewer_user.partner_id:
                rec.sudo().message_subscribe(partner_ids=[reviewer_user.partner_id.id])
                if case:
                    case.sudo().message_subscribe(partner_ids=[reviewer_user.partner_id.id])
                
                try:
                    channel = self.env['discuss.channel'].with_user(rec.env.user)._get_or_create_chat(
                        partners_to=[reviewer_user.partner_id.id]
                    )
                    if channel:
                        msg_body = Markup(_(
                            '<p><strong>Action Required: Disciplinary Appeal Submitted (%s Level)</strong></p>'
                            '<p>Dear %s,</p>'
                            '<p>A formal %s level disciplinary appeal (Ref: <strong>%s</strong>) has been submitted by <strong>%s</strong> regarding case <strong>%s</strong> and is awaiting your review as <strong>%s</strong>.</p>'
                            '<p><strong>Grounds for Appeal:</strong> <em>%s</em></p>'
                            '<p>Please review the appeal in Bunna Bank ERP under <strong>Discipline Operations &gt; Appeals</strong> to render your formal decision.</p>'
                        ) % (
                            appeal_lvl_label,
                            reviewer_user.name,
                            appeal_lvl_label,
                            rec.name,
                            appellant_name,
                            case_name,
                            target_label,
                            rec.appeal_grounds or _('Not specified'),
                        ))
                        channel.message_post(
                            body=msg_body,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment',
                            author_id=rec.env.user.partner_id.id,
                        )
                except Exception:
                    pass

    def write(self, vals):
        # Decision outcome and revised action fields can only be modified by designated stage authority or admin
        outcome_fields = {
            'decision_outcome', 'revised_punishment_type', 'revised_penalty_percentage',
            'revised_fine_days', 'appeal_decision_notes', 'review_date'
        }
        if not self.env.su and any(f in vals for f in outcome_fields):
            for rec in self:
                if not rec.can_user_review_current_stage:
                    target_label = dict(self._fields['appeal_target_authority'].selection).get(rec.appeal_target_authority, rec.appeal_target_authority)
                    raise UserError(_('Permission Denied: Decision outcome and revised action fields can only be modified by the designated appeal authority (%s) or HR Administrator.') % target_label)

        # Supporting document can only be uploaded / modified by the employee or POMD/Admin on behalf
        doc_fields = {'supporting_document', 'document_filename'}
        if not self.env.su and any(f in vals for f in doc_fields):
            for rec in self:
                current_user = self.env.user
                emp = rec.sudo().employee_id
                is_emp = bool(
                    emp and (
                        (emp.user_id and emp.user_id.id == current_user.id) or
                        (current_user.sudo().employee_id and current_user.sudo().employee_id.id == emp.id) or
                        (hasattr(current_user, 'employee_ids') and emp.id in current_user.sudo().employee_ids.ids)
                    )
                )
                is_pomd_on_behalf = rec.is_submitted_on_behalf and (
                    current_user.has_group('discipline_management.group_discipline_pomd') or
                    current_user.has_group('discipline_management.group_discipline_admin') or
                    current_user.has_group('base.group_system')
                )
                if not (is_emp or is_pomd_on_behalf):
                    raise UserError(_('Permission Denied: Only the appellant employee can attach or modify supporting appeal documents.'))

        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state in ('decided', 'rejected_expired'):
                raise UserError(_('Preservation Policy Violation: Decided or finalized appeal decisions cannot be deleted.'))
            user = self.env.user
            is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system')
            is_creator = bool(rec.create_uid and rec.create_uid.id == user.id)
            if not (is_admin or is_creator or self.env.su):
                raise UserError(_('Permission Denied: You are not authorized to delete appeal %s.') % rec.name)
        cases = self.mapped('case_id')
        res = super().unlink()
        for case in cases:
            if case.exists():
                active_appeals = case.appeal_ids.filtered(lambda a: a.state in ('submitted', 'under_review', 'committee_review'))
                if not active_appeals and case.state == 'appealed':
                    case.sudo().with_context(force_write=True).write({'state': 'enforced'})
                case._compute_appeal_outcome()
                case._compute_appeal_stats()
        return res

    def action_start_review(self):
        for rec in self:
            if not rec.can_user_review_current_stage:
                target_label = dict(self._fields['appeal_target_authority'].selection).get(rec.appeal_target_authority, rec.appeal_target_authority)
                raise UserError(_('Authority Restriction: You do not have the required authority role (%s) to start review for this appeal stage.') % target_label)
            rec.write({
                'reviewer_id': self.env.user.id,
                'state': 'under_review'
            })
            if rec.case_id:
                rec.case_id.sudo().message_post(
                    body=_('Appeal %s review initiated by %s (%s).') % (rec.name, self.env.user.name, rec.appeal_target_authority or 'Review Authority')
                )

    def action_ceo_refer_to_committee(self):
        """CEO refers an appeal on a committee-decided sanction back to the Disciplinary Committee for further review / re-deliberation."""
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        user = self.env.user
        is_ceo = bool((ceo_user and user.id == ceo_user.id) or user.has_group('discipline_management.group_discipline_ceo'))
        is_admin = user.has_group('discipline_management.group_discipline_admin') or user._is_superuser()
        if not (is_ceo or is_admin):
            raise UserError(_("Only the Chief Executive Officer (CEO) can refer this appeal to the Disciplinary Committee."))

        for rec in self:
            if rec.is_direct_enforce_case:
                raise UserError(_("Referral Restriction: Direct Coach / Line Manager enforcement cases cannot be referred to the Disciplinary Committee."))
            if rec.state != 'under_review':
                raise UserError(_("The appeal must be Under Review to refer it to the Disciplinary Committee."))

            rec.write({
                'state': 'committee_review',
            })

            msg = _("Appeal %s has been referred to the Disciplinary Committee by CEO %s for further review and recommendations.") % (rec.name, user.name)
            rec.message_post(body=msg)
            if rec.case_id:
                rec.case_id.sudo().message_post(body=msg)

            cpco_user = EmpModel.get_cpco_user()
            sec_user = EmpModel.get_secretary_user()
            recipients = self.env['res.users']
            if cpco_user:
                recipients |= cpco_user
            if sec_user:
                recipients |= sec_user
            for u in recipients:
                rec._send_direct_discuss_msg(
                    u,
                    _("Appeal %s Referred to Committee for Review") % rec.name,
                    _("CEO %s has referred Disciplinary Appeal %s (Case: %s, Employee: %s) back to the Disciplinary Committee for further deliberation and recommendation.") % (
                        user.name, rec.name, rec.case_id.name if rec.case_id else '', rec.employee_id.name if rec.employee_id else ''
                    )
                )

    def action_committee_submit_appeal_recommendation(self):
        """Disciplinary Committee (Secretary or Chair) submits review findings & recommendation back to the CEO for final decision."""
        EmpModel = self.env['hr.employee'].sudo()
        sec_user = EmpModel.get_secretary_user()
        cpco_user = EmpModel.get_cpco_user()
        user = self.env.user
        is_pomd = bool((sec_user and user.id == sec_user.id) or user.has_group('discipline_management.group_discipline_pomd') or user.has_group('discipline_management.group_discipline_pomd_director'))
        is_cpco = bool((cpco_user and user.id == cpco_user.id) or user.has_group('discipline_management.group_discipline_cpco'))
        is_admin = user.has_group('discipline_management.group_discipline_admin') or user._is_superuser()

        if not (is_pomd or is_cpco or is_admin):
            raise UserError(_("Only the Disciplinary Committee Secretary or Chair can submit committee recommendations back to the CEO."))

        for rec in self:
            if rec.state != 'committee_review':
                raise UserError(_("The appeal is not currently under committee review."))

            if not rec.committee_appeal_recommendation:
                raise UserError(_("Please provide Committee Deliberation & Recommendation notes before submitting to the CEO."))

            rec.write({
                'state': 'under_review',
            })

            msg = _("Disciplinary Committee has completed review for appeal %s and submitted recommendation back to CEO for final decision.") % rec.name
            rec.message_post(body=msg)
            if rec.case_id:
                rec.case_id.sudo().message_post(body=msg)

            ceo_user = EmpModel.get_ceo_user()
            if ceo_user:
                rec._send_direct_discuss_msg(
                    ceo_user,
                    _("Committee Recommendation Submitted: Appeal %s") % rec.name,
                    _("The Disciplinary Committee has submitted its recommendation for Appeal %s (Case: %s, Employee: %s) for your final decision.") % (
                        rec.name, rec.case_id.name if rec.case_id else '', rec.employee_id.name if rec.employee_id else ''
                    )
                )

    def _send_direct_discuss_msg(self, recipient_user, title, body_text):
        if not recipient_user or not recipient_user.partner_id:
            return
        try:
            channel = self.env['discuss.channel'].with_user(self.env.user)._get_or_create_chat(
                partners_to=[recipient_user.partner_id.id]
            )
            if channel:
                msg_body = Markup(
                    '<p><strong>%s</strong></p><p>%s</p>'
                ) % (title, body_text)
                channel.message_post(
                    body=msg_body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    author_id=self.env.user.partner_id.id,
                )
        except Exception:
            pass

    def _apply_payroll_appeal_adjustment(self, case, new_pct, new_days, is_exonerated=False):
        """Synchronize payroll penalty records when an appeal decision modifies or overturns a penalty.
        - If the original deduction is still 'pending' (not yet transmitted/deducted in payroll):
          cancel it (if exonerated/zero) or update its percentage/days in place.
        - If the original deduction was already 'transferred' or 'deducted':
          preserve the historical deducted record and automatically generate a 'refund' (reimbursement)
          record for the decreased amount for the next payroll period.
        - If no deduction record existed yet, create the pending deduction record.
        """
        self.ensure_one()
        case_sudo = case.sudo()
        PenaltyModel = self.env['discipline.payroll.penalty'].sudo()
        all_penalties = PenaltyModel.search([('case_id', '=', case_sudo.id)])
        deduction_recs = all_penalties.filtered(lambda p: p.transaction_type == 'deduction' and p.state != 'cancelled')
        pending_deductions = deduction_recs.filtered(lambda p: p.state == 'pending')
        processed_deductions = deduction_recs.filtered(lambda p: p.state in ('transferred', 'deducted'))

        is_zero_penalty = is_exonerated or ((new_pct or 0.0) <= 0.0 and (new_days or 0.0) <= 0.0)

        # Case 1: Original deduction was ALREADY transmitted or deducted in payroll -> Generate Next-Period Reimbursement
        if processed_deductions:
            # Cancel any remaining un-transmitted deduction lines if any exist alongside processed ones
            if pending_deductions:
                pending_deductions.write({'state': 'cancelled', 'is_appeal_held': False})

            total_deducted = sum(processed_deductions.mapped('calculated_amount'))
            existing_refunds = all_penalties.filtered(
                lambda p: p.transaction_type == 'refund' and p.state in ('pending', 'transferred', 'reimbursed')
            )
            total_already_refunded = sum(existing_refunds.mapped('calculated_amount'))
            net_deducted = max(0.0, total_deducted - total_already_refunded)

            primary_deduction = processed_deductions[0]
            wage = primary_deduction._get_employee_wage()
            if not wage and primary_deduction.penalty_percentage > 0.0 and primary_deduction.calculated_amount > 0.0:
                wage = (primary_deduction.calculated_amount * 100.0) / float(primary_deduction.penalty_percentage)

            daily_rate = (wage / 30.0) if wage else (primary_deduction.daily_rate or 0.0)
            orig_days = primary_deduction.managerial_days or primary_deduction.suspension_days or 0
            if not daily_rate and orig_days > 0 and primary_deduction.calculated_amount > 0.0:
                daily_rate = primary_deduction.calculated_amount / float(orig_days)

            if is_zero_penalty:
                revised_amount = 0.0
            elif (new_pct or 0.0) > 0.0:
                revised_amount = (wage * float(new_pct)) / 100.0
            elif (new_days or 0.0) > 0.0:
                revised_amount = float(new_days) * daily_rate
            else:
                revised_amount = 0.0

            refund_delta = round(net_deducted - revised_amount, 2)
            if refund_delta > 0.0:
                EmpModel = self.env['hr.employee'].sudo()
                ceo_user = EmpModel.get_ceo_user()
                actual_reviewer = self.reviewer_id or self.designated_reviewer_id
                is_last_authority = bool(
                    (ceo_user and actual_reviewer and actual_reviewer.id == ceo_user.id) or
                    (actual_reviewer and actual_reviewer.has_group('discipline_management.group_discipline_ceo')) or
                    self.appeal_target_authority == 'ceo' or
                    self.appeal_level == 'fourth'
                )
                if is_exonerated or is_last_authority:
                    self.write({
                        'held_refund_amount': refund_delta,
                        'acceptance_state': 'not_applicable',
                    })
                    self._execute_held_payroll_refund()
                    case_sudo.message_post(
                        body=_(
                            'Appeal decision rendered resulting in reimbursement of ETB %.2f. '
                            'As this decision is final / exonerated, the reimbursement is released immediately.'
                        ) % refund_delta
                    )
                    return 'refund_processed'
                else:
                    self.write({
                        'held_refund_amount': refund_delta,
                        'acceptance_state': 'pending',
                    })
                    case_sudo.message_post(
                        body=_(
                            'Appeal decision rendered resulting in a penalty reduction. A reimbursement of ETB %.2f '
                            'is pending employee acceptance or appeal window closure (%s) before transmission to payroll.'
                        ) % (refund_delta, self.appeal_window_deadline or _('10 calendar days'))
                    )
                    return 'refund_pending_acceptance'

            return 'deducted' if any(p.state == 'deducted' for p in processed_deductions) else 'scheduled'

        # Case 2: Original deduction is still 'pending' (not yet transmitted/deducted) -> Option 2: Cancel original line + create new superseding line
        if pending_deductions:
            self.write({'held_refund_amount': 0.0})
            primary_pending = pending_deductions[0]
            
            # Cancel all existing pending deductions while preserving their original amounts and percentages
            for pen in pending_deductions:
                pen.write({
                    'state': 'cancelled',
                    'is_appeal_held': False,
                    'notes': _('Cancelled on Appeal: Superseded by Appeal [%s] decision. Preserved for audit trail.') % self.name,
                })
            
            if is_zero_penalty:
                case_sudo.message_post(body=_(
                    'Payroll penalty line [%(old)s] (%(pct)s%%) cancelled following Appeal [%(appeal)s] decision. Zero deduction will occur.'
                ) % {
                    'old': primary_pending.name,
                    'pct': primary_pending.penalty_percentage,
                    'appeal': self.name,
                })
                return 'cancelled'
            else:
                today = fields.Date.context_today(self)
                eff_date = case_sudo.final_decision_date or today
                target_month = case_sudo.payroll_month or str(today.month)
                
                new_pen_vals = {
                    'case_id': case_sudo.id,
                    'employee_id': case_sudo.employee_id.id,
                    'transaction_type': 'deduction',
                    'state': 'pending',
                    'effective_date': eff_date,
                    'payroll_month': target_month,
                    'is_appeal_held': False,
                    'parent_penalty_id': primary_pending.id,
                    'appeal_id': self.id,
                }
                if (new_pct or 0.0) > 0.0:
                    new_pen_vals.update({
                        'penalty_type': 'percentage',
                        'penalty_percentage': float(new_pct),
                        'notes': _('Appellate Penalty: Created following Appeal [%s] decision (Supersedes %s at %s%%).') % (
                            self.name, primary_pending.name, primary_pending.penalty_percentage
                        ),
                    })
                elif (new_days or 0.0) > 0.0:
                    p_type = 'suspension_without_pay' if primary_pending.penalty_type == 'suspension_without_pay' else 'managerial'
                    new_pen_vals.update({
                        'penalty_type': p_type,
                        'suspension_days': int(new_days) if p_type == 'suspension_without_pay' else 0,
                        'managerial_days': int(new_days) if p_type == 'managerial' else 0,
                        'notes': _('Appellate Penalty: Created following Appeal [%s] decision (Supersedes %s).') % (
                            self.name, primary_pending.name
                        ),
                    })
                new_pen = PenaltyModel.create(new_pen_vals)
                case_sudo.message_post(body=_(
                    'Payroll penalty line [%(old)s] (%(old_pct)s%%) cancelled on appeal. '
                    'New superseding line [%(new)s] (%(new_pct)s%%) scheduled for payroll.'
                ) % {
                    'old': primary_pending.name,
                    'old_pct': primary_pending.penalty_percentage,
                    'new': new_pen.name,
                    'new_pct': new_pct or new_days,
                })
                return 'scheduled'

        # Case 3: No pending deduction was found, but a revised positive penalty was decided
        if not is_zero_penalty and ((new_pct or 0.0) > 0.0 or (new_days or 0.0) > 0.0):
            today = fields.Date.context_today(self)
            eff_date = case_sudo.final_decision_date or today
            target_month = case_sudo.payroll_month or str(today.month)
            pen_vals = {
                'case_id': case_sudo.id,
                'employee_id': case_sudo.employee_id.id,
                'transaction_type': 'deduction',
                'state': 'pending',
                'effective_date': eff_date,
                'payroll_month': target_month,
                'is_appeal_held': False,
            }
            if (new_pct or 0.0) > 0.0:
                pen_vals.update({
                    'penalty_type': 'percentage',
                    'penalty_percentage': float(new_pct),
                    'notes': _('Scheduled revised percentage penalty of %s%% following Appeal %s decision.') % (new_pct, self.name),
                })
            elif (new_days or 0.0) > 0.0:
                pen_vals.update({
                    'penalty_type': 'managerial',
                    'managerial_days': int(new_days),
                    'notes': _('Scheduled revised managerial fine of %s day(s) following Appeal %s decision.') % (new_days, self.name),
                })
            PenaltyModel.create(pen_vals)
            return 'scheduled'

        return 'cancelled' if is_zero_penalty else 'not_applicable'

    def _execute_held_payroll_refund(self):
        """Execute the actual creation of refund record in discipline.payroll.penalty
        once the appellant accepts the decision or the appeal window closes."""
        self.ensure_one()
        case_sudo = self.case_id.sudo()
        if not case_sudo:
            return False
        PenaltyModel = self.env['discipline.payroll.penalty'].sudo()
        all_penalties = PenaltyModel.search([('case_id', '=', case_sudo.id)])
        deduction_recs = all_penalties.filtered(lambda p: p.transaction_type == 'deduction' and p.state != 'cancelled')
        processed_deductions = deduction_recs.filtered(lambda p: p.state in ('transferred', 'deducted'))
        if not processed_deductions:
            return False

        # Prevent duplicate refund generation for this appeal
        existing_this_appeal_refund = all_penalties.filtered(
            lambda p: p.transaction_type == 'refund' and p.appeal_id.id == self.id and p.state != 'cancelled'
        )
        if existing_this_appeal_refund:
            return existing_this_appeal_refund[0]

        total_deducted = sum(processed_deductions.mapped('calculated_amount'))
        existing_refunds = all_penalties.filtered(
            lambda p: p.transaction_type == 'refund' and p.state in ('pending', 'transferred', 'reimbursed')
        )
        total_already_refunded = sum(existing_refunds.mapped('calculated_amount'))
        net_deducted = max(0.0, total_deducted - total_already_refunded)

        primary_deduction = processed_deductions[0]
        wage = primary_deduction._get_employee_wage()
        if not wage and primary_deduction.penalty_percentage > 0.0 and primary_deduction.calculated_amount > 0.0:
            wage = (primary_deduction.calculated_amount * 100.0) / float(primary_deduction.penalty_percentage)

        daily_rate = (wage / 30.0) if wage else (primary_deduction.daily_rate or 0.0)
        orig_days = primary_deduction.managerial_days or primary_deduction.suspension_days or 0
        if not daily_rate and orig_days > 0 and primary_deduction.calculated_amount > 0.0:
            daily_rate = primary_deduction.calculated_amount / float(orig_days)

        is_zero_penalty = (self.decision_outcome == 'overturned') or (self.revised_punishment_type == 'exonerate') or (
            (self.revised_penalty_percentage or 0.0) <= 0.0 and (self.revised_fine_days or 0.0) <= 0.0
        )

        if is_zero_penalty:
            revised_amount = 0.0
        elif (self.revised_penalty_percentage or 0.0) > 0.0:
            revised_amount = (wage * float(self.revised_penalty_percentage)) / 100.0
        elif (self.revised_fine_days or 0.0) > 0.0:
            revised_amount = float(self.revised_fine_days) * daily_rate
        else:
            revised_amount = 0.0

        refund_delta = round(net_deducted - revised_amount, 2)
        if refund_delta <= 0.0 and self.held_refund_amount > 0.0:
            refund_delta = self.held_refund_amount

        if refund_delta > 0.0:
            today = fields.Date.context_today(self)
            orig_month = int(primary_deduction.payroll_month or today.month)
            next_payroll_month = str((orig_month % 12) + 1)

            refund_rec = PenaltyModel.create({
                'case_id': case_sudo.id,
                'employee_id': case_sudo.employee_id.id,
                'transaction_type': 'refund',
                'penalty_type': 'reimbursement',
                'refund_amount': refund_delta,
                'penalty_percentage': 0.0,
                'suspension_days': 0,
                'managerial_days': 0,
                'parent_penalty_id': primary_deduction.id,
                'appeal_id': self.id,
                'effective_date': today,
                'payroll_month': next_payroll_month,
                'state': 'pending',
                'notes': _(
                    'Appeal Reimbursement [%s] finalized upon %s. '
                    'Original Deducted: ETB %.2f | Revised Penalty: ETB %.2f | Reimbursement Due: ETB %.2f (Next Payroll Month: %s).'
                ) % (
                    self.name,
                    dict(self._fields['acceptance_state'].selection).get(self.acceptance_state, self.acceptance_state),
                    net_deducted,
                    revised_amount,
                    refund_delta,
                    next_payroll_month
                ),
            })
            case_sudo.write({'deduction_status': 'refund_scheduled'})
            case_sudo.message_post(
                body=_(
                    'Payroll Reimbursement [%s] of ETB %.2f released for next payroll period (Month %s) '
                    'following Appeal %s acceptance/closure.'
                ) % (refund_rec.name, refund_delta, next_payroll_month, self.name)
            )
            return refund_rec
        return False

    def _revert_demotion_if_needed(self, case):
        """Reinstate employee to their pre-demotion job position or cancel draft demotion if demotion was overturned or reduced."""
        self.ensure_one()
        orig_punish = self.original_punishment_type or case.decided_punishment_type or case.punishment_type
        had_demotion = (orig_punish == 'demotion' or case.is_demotion_decided or bool(case.demotion_id))
        if not had_demotion:
            return

        # Cancel linked draft employee demotion record in Employee Services if not yet approved
        if case.demotion_id and case.demotion_id.state == 'draft':
            try:
                case.demotion_id.sudo().write({'state': 'cancel'})
                case.demotion_id.message_post(body=_("Demotion cancelled automatically because Disciplinary Case Appeal overturned the demotion decision."))
                case.message_post(body=_("Appeal Decision Applied: Linked draft Employee Demotion record %s has been cancelled.") % (case.demotion_id.ref_num or ''))
            except Exception:
                pass

        case.is_demotion_decided = False

        target_restore_job = case.previous_job_id
        if not target_restore_job and case.employee_id:
            team_lead_job = self.env['hr.job'].sudo().search([('name', 'ilike', 'Customer Centric Frontend, Squad')], limit=1)
            target_restore_job = team_lead_job

        if target_restore_job and case.employee_id:
            emp_sudo = case.employee_id.sudo().with_context(no_leave_resource_calendar_update=True)
            revert_vals = {
                'job_id': target_restore_job.id,
            }
            if 'job_title' in emp_sudo._fields:
                revert_vals['job_title'] = target_restore_job.name
            if 'job_position' in emp_sudo._fields:
                revert_vals['job_position'] = target_restore_job.id
            emp_sudo.write(revert_vals)

            VersionModel = self.env.get('hr.version')
            if VersionModel:
                versions = VersionModel.sudo().search([('employee_id', '=', emp_sudo.id)])
                if versions:
                    v_vals = {'job_id': target_restore_job.id}
                    if 'job_position' in versions._fields:
                        v_vals['job_position'] = target_restore_job.id
                    versions.write(v_vals)

            case.message_post(body=_("Appeal Decision Applied: Demotion reversed. Employee %s reinstated to pre-demotion position '%s'.") % (
                emp_sudo.name, target_restore_job.name
            ))

    def action_render_decision(self):
        """Apply appeal decision and update original case outcome."""
        for rec in self:
            EmpModel = self.env['hr.employee'].sudo()
            ceo_user = EmpModel.get_ceo_user()
            is_ceo = bool((ceo_user and self.env.user.id == ceo_user.id) or self.env.user.has_group('discipline_management.group_discipline_ceo'))
            if not rec.can_user_review_current_stage and not (rec.appeal_target_authority == 'ceo' and is_ceo):
                target_label = dict(self._fields['appeal_target_authority'].selection).get(rec.appeal_target_authority, rec.appeal_target_authority)
                raise UserError(_('Authority Restriction: You do not have the required authority role (%s) to render decisions for this appeal stage.') % target_label)
            if not rec.decision_outcome:
                raise UserError(_('Select an Appeal Decision Outcome before finalizing.'))
            if not rec.appeal_decision_notes or not rec.appeal_decision_notes.strip():
                raise UserError(_('Mandatory Justification Required:\n\nPlease enter the "Decision Justification & Rationale" explaining the legal and procedural basis for this appeal decision before finalizing.'))

            rec._check_decision_outcome_validity()

            actual_reviewer = rec.reviewer_id or rec.designated_reviewer_id
            is_last_authority = bool(
                (ceo_user and self.env.user.id == ceo_user.id) or
                (ceo_user and actual_reviewer and actual_reviewer.id == ceo_user.id) or
                self.env.user.has_group('discipline_management.group_discipline_ceo') or
                (actual_reviewer and actual_reviewer.has_group('discipline_management.group_discipline_ceo')) or
                rec.appeal_target_authority == 'ceo' or
                rec.appeal_level == 'fourth'
            )
            is_exonerated = bool(
                rec.decision_outcome == 'overturned' or
                rec.revised_punishment_type == 'exonerate' or
                (rec.decision_outcome == 'penalty_reduced' and rec.revised_penalty_percentage == 0.0 and rec.revised_fine_days == 0.0 and rec.revised_punishment_type in ['exonerate', False])
            )
            acceptance_val = 'not_applicable' if (is_exonerated or is_last_authority) else 'pending'

            # Ensure appellate reviewer signature is captured and remembered
            rev_sig = rec.reviewer_signature or getattr(self.env.user, 'discipline_digital_signature', False) or getattr(self.env.user, 'digital_signature', False)
            if not rev_sig:
                # Look up recent signature used by this user on previous cases
                prev_case = self.env['discipline.case'].sudo().search([
                    ('signatory_signature', '!=', False),
                    '|', ('initiator_id', '=', self.env.user.id), ('create_uid', '=', self.env.user.id)
                ], order='id desc', limit=1)
                if prev_case and prev_case.signatory_signature:
                    rev_sig = prev_case.signatory_signature

            # Enforcing / rendering an appeal decision without a digital signature is strictly prohibited
            if not is_exonerated and (not rev_sig or len(rev_sig) < 50):
                raise UserError(_(
                    "Mandatory Digital Signature Required:\n\n"
                    "Enforcing an appeal decision without a signature is prevented. As the Appellate Authority (%s), "
                    "you must draw or load your digital signature under 'Appellate Authority Digital Sign-off' before finalizing."
                ) % (rec.reviewer_id.name or self.env.user.name))

            write_vals = {
                'review_date': fields.Date.context_today(self),
                'reviewer_id': rec.reviewer_id.id or self.env.user.id,
                'state': 'decided',
                'acceptance_state': acceptance_val,
            }
            if rev_sig:
                write_vals['reviewer_signature'] = rev_sig
                try:
                    self.env.user.sudo().write({'discipline_digital_signature': rev_sig})
                except Exception:
                    pass

            rec.write(write_vals)

            case = rec.case_id.sudo()
            if not case:
                continue

            if rec.decision_outcome == 'upheld':
                upheld_punish = rec.original_punishment_type or case.decided_punishment_type or case.punishment_type
                upheld_pct = rec.original_penalty_percentage if rec.original_penalty_percentage is not False else case.decided_penalty_percentage
                upheld_days = rec.original_fine_days if rec.original_fine_days is not False else case.decided_fine_days

                case.with_context(force_write=True).write({
                    'punishment_type': upheld_punish,
                    'decided_punishment_type': upheld_punish,
                    'penalty_percentage': upheld_pct,
                    'decided_penalty_percentage': upheld_pct,
                    'fine_days': upheld_days,
                    'decided_fine_days': upheld_days,
                    'state': 'enforced'
                })
                # Release appeal hold on any pending deductions
                pending_pens = self.env['discipline.payroll.penalty'].sudo().search([
                    ('case_id', '=', case.id),
                    ('state', '=', 'pending'),
                    ('is_appeal_held', '=', True),
                ])
                if pending_pens:
                    pending_pens.write({'is_appeal_held': False})
                case.action_process_appeal_window_deductions()
                case.message_post(body=_('Appeal %s decided: Original decision UPHELD. Appeal hold released on pending deductions.') % rec.name)

            elif rec.decision_outcome == 'overturned':
                # Revert employee disciplinary marks & restore mobility via sudo
                emp_sudo = case.employee_id.sudo().with_context(no_leave_resource_calendar_update=True)
                emp_vals = {
                    'active_disciplinary_action': False,
                    'is_ineligible_for_promotion_transfer': False,
                    'is_suspended': False,
                    'suspension_type': False,
                }
                if emp_sudo.disciplinary_warning_count > 0:
                    emp_vals['disciplinary_warning_count'] = emp_sudo.disciplinary_warning_count - 1
                if not emp_sudo.active:
                    emp_vals['active'] = True
                emp_sudo.write(emp_vals)
                
                # Reactivate user account if employee had been archived
                if emp_sudo.user_id and not emp_sudo.user_id.active:
                    emp_sudo.user_id.sudo().write({'active': True})
                
                rec._revert_demotion_if_needed(case)
                new_ded_status = rec._apply_payroll_appeal_adjustment(case, 0.0, 0.0, is_exonerated=True)
                
                case.sudo().with_context(force_write=True).write({
                    'penalty_percentage': 0.0,
                    'fine_days': 0.0,
                    'punishment_type': 'exonerate',
                    'active_duration_days': 0,
                    'active_penalty_end_date': False,
                    'deduction_status': new_ded_status,
                    'state': 'closed'
                })
                case.sudo().message_post(body=_('Appeal %s decided: Decision OVERTURNED. Employee exonerated and records restored.') % rec.name)

            elif rec.decision_outcome == 'penalty_reduced':
                is_full_exoneration = (rec.revised_punishment_type == 'exonerate') or (rec.revised_penalty_percentage == 0.0 and rec.revised_fine_days == 0.0 and rec.revised_punishment_type in ['exonerate', False])
                
                if is_full_exoneration:
                    # Revert employee disciplinary marks & restore mobility via sudo
                    emp_sudo = case.employee_id.sudo().with_context(no_leave_resource_calendar_update=True)
                    emp_vals = {
                        'active_disciplinary_action': False,
                        'is_ineligible_for_promotion_transfer': False,
                        'is_suspended': False,
                        'suspension_type': False,
                    }
                    if emp_sudo.disciplinary_warning_count > 0:
                        emp_vals['disciplinary_warning_count'] = emp_sudo.disciplinary_warning_count - 1
                    emp_sudo.write(emp_vals)
                    
                    rec._revert_demotion_if_needed(case)
                    new_ded_status = rec._apply_payroll_appeal_adjustment(case, 0.0, 0.0, is_exonerated=True)
                    
                    case.sudo().with_context(force_write=True).write({
                        'penalty_percentage': 0.0,
                        'fine_days': 0.0,
                        'punishment_type': 'exonerate',
                        'active_duration_days': 0,
                        'active_penalty_end_date': False,
                        'deduction_status': new_ded_status,
                        'state': 'closed'
                    })
                    case.sudo().message_post(body=_('Appeal %s decided: Penalty REDUCED to ZERO (Exonerated). Employee records restored.') % rec.name)

                else:
                    new_punish = rec.revised_punishment_type or case.punishment_type
                    val_days = 180
                    if new_punish == 'first_warning_penalty':
                        val_days = 90
                    elif new_punish in ('verbal_warning', 'exonerate'):
                        val_days = 0
                    elif new_punish in ('second_warning_penalty', 'final_warning_penalty'):
                        val_days = 180

                    if new_punish != 'demotion':
                        rec._revert_demotion_if_needed(case)

                    new_ded_status = rec._apply_payroll_appeal_adjustment(
                        case,
                        rec.revised_penalty_percentage,
                        rec.revised_fine_days,
                        is_exonerated=False
                    )

                    new_vals = {
                        'penalty_percentage': rec.revised_penalty_percentage,
                        'fine_days': rec.revised_fine_days,
                        'punishment_type': new_punish,
                        'decided_punishment_type': new_punish,
                        'decided_penalty_percentage': rec.revised_penalty_percentage,
                        'decided_fine_days': rec.revised_fine_days,
                        'active_duration_days': val_days,
                        'deduction_status': new_ded_status,
                        'state': 'enforced'
                    }
                    case.sudo().with_context(force_write=True).write(new_vals)
                    
                    case.sudo().message_post(body=_('Appeal %s decided: Penalty REDUCED (Pct: %s%%, Days: %s).') % (
                        rec.name, rec.revised_penalty_percentage, rec.revised_fine_days
                    ))

            rec._send_appeal_decision_notifications()

    def _send_appeal_decision_notifications(self):
        """Send official decision notifications to the appellant employee, case initiator, and prior reviewers upon decision rendering."""
        for rec in self:
            case = rec.case_id.sudo() if rec.case_id else False
            appellant_emp = rec.employee_id.sudo() if rec.employee_id else (case.employee_id.sudo() if case else False)
            appellant_user = appellant_emp.user_id if appellant_emp else False
            appellant_name = appellant_emp.name if appellant_emp else _('Employee')
            case_name = case.name if case else _('Disciplinary Case')
            appeal_lvl_label = dict(rec._fields['appeal_level'].selection).get(rec.appeal_level, rec.appeal_level)
            target_label = dict(rec._fields['appeal_target_authority'].selection).get(rec.appeal_target_authority, rec.appeal_target_authority)
            outcome_label = dict(rec._fields['decision_outcome'].selection).get(rec.decision_outcome, rec.decision_outcome or _('Decided'))
            reviewer_user = rec.reviewer_id or self.env.user
            reviewer_name = reviewer_user.name if reviewer_user else _('Appeal Authority')
            
            # Formulate punishment & penalty details
            if rec.decision_outcome == 'overturned':
                sanction_desc = _('Fully Exonerated / Decision Overturned (0.00% Penalty)')
            elif rec.decision_outcome == 'penalty_reduced':
                punish_label = dict(rec._fields['revised_punishment_type'].selection).get(rec.revised_punishment_type, rec.revised_punishment_type or '')
                pen_parts = []
                if rec.revised_penalty_percentage > 0.0:
                    pen_parts.append(_('%s%% Salary Deduction') % rec.revised_penalty_percentage)
                if rec.revised_fine_days > 0.0:
                    pen_parts.append(_('%d Day(s) Salary Fine') % int(rec.revised_fine_days))
                pen_str = (' (' + ', '.join(pen_parts) + ')') if pen_parts else ''
                sanction_desc = f"{punish_label}{pen_str}" if punish_label else _('Penalty Reduced')
            else: # upheld
                orig_punish = dict(rec._fields['original_punishment_type'].selection).get(rec.original_punishment_type, rec.original_punishment_type or '')
                orig_pen_parts = []
                if rec.original_penalty_percentage > 0.0:
                    orig_pen_parts.append(_('%s%% Salary Deduction') % rec.original_penalty_percentage)
                if rec.original_fine_days > 0.0:
                    orig_pen_parts.append(_('%d Day(s) Salary Fine') % int(rec.original_fine_days))
                orig_pen_str = (' (' + ', '.join(orig_pen_parts) + ')') if orig_pen_parts else ''
                sanction_desc = f"{orig_punish}{orig_pen_str} (Original Enforced Sanction Maintained)"

            rationale_text = rec.appeal_decision_notes or _('Decision rendered in accordance with Bank Disciplinary Policy.')

            # 1. Notify Appellant Employee (Chala)
            if appellant_user and appellant_user.partner_id:
                rec.sudo().message_subscribe(partner_ids=[appellant_user.partner_id.id])
                if case:
                    case.sudo().message_subscribe(partner_ids=[appellant_user.partner_id.id])
                
                try:
                    channel = self.env['discuss.channel'].with_user(reviewer_user)._get_or_create_chat(
                        partners_to=[appellant_user.partner_id.id]
                    )
                    if channel:
                        msg_body = Markup(_(
                            '<p><strong>Official Disciplinary Appeal Decision Notice (%s Level)</strong></p>'
                            '<p>Dear %s,</p>'
                            '<p>A formal decision has been rendered on your disciplinary appeal (Ref: <strong>%s</strong>) for Case <strong>%s</strong> by <strong>%s</strong> (%s).</p>'
                            '<ul>'
                            '<li><strong>Decision Outcome:</strong> %s</li>'
                            '<li><strong>Sanction / Decided Action:</strong> %s</li>'
                            '<li><strong>Decision Date:</strong> %s</li>'
                            '</ul>'
                            '<p><strong>Decision Justification &amp; Rationale:</strong><br/><em>%s</em></p>'
                            '<p>You can view full details in Bunna Bank ERP under <strong>Discipline Operations &gt; Appeals</strong>.</p>'
                        ) % (
                            appeal_lvl_label,
                            appellant_name,
                            rec.name,
                            case_name,
                            reviewer_name,
                            target_label,
                            outcome_label,
                            sanction_desc,
                            rec.review_date or fields.Date.today(),
                            rationale_text,
                        ))
                        channel.message_post(
                            body=msg_body,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment',
                            author_id=reviewer_user.partner_id.id,
                        )
                except Exception:
                    pass

            # 2. Notify Case Initiator / Reporting Manager (Eyob)
            initiator_user = (case and case.reported_by_id and case.reported_by_id.user_id) or (case.create_uid if case else False)
            if initiator_user and initiator_user.partner_id and initiator_user.id != reviewer_user.id:
                rec.sudo().message_subscribe(partner_ids=[initiator_user.partner_id.id])
                if case:
                    case.sudo().message_subscribe(partner_ids=[initiator_user.partner_id.id])
                
                try:
                    channel = self.env['discuss.channel'].with_user(reviewer_user)._get_or_create_chat(
                        partners_to=[initiator_user.partner_id.id]
                    )
                    if channel:
                        msg_body = Markup(_(
                            '<p><strong>Disciplinary Appeal Decision Update (%s Level)</strong></p>'
                            '<p>Dear %s,</p>'
                            '<p>The %s level appeal (Ref: <strong>%s</strong>) by <strong>%s</strong> regarding case <strong>%s</strong> has been concluded by <strong>%s</strong> (%s).</p>'
                            '<ul>'
                            '<li><strong>Outcome:</strong> %s</li>'
                            '<li><strong>Enforced Sanction:</strong> %s</li>'
                            '</ul>'
                            '<p><strong>Rationale:</strong> <em>%s</em></p>'
                        ) % (
                            appeal_lvl_label,
                            initiator_user.name,
                            appeal_lvl_label,
                            rec.name,
                            appellant_name,
                            case_name,
                            reviewer_name,
                            target_label,
                            outcome_label,
                            sanction_desc,
                            rationale_text,
                        ))
                        channel.message_post(
                            body=msg_body,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment',
                            author_id=reviewer_user.partner_id.id,
                        )
                except Exception:
                    pass

            # 3. Notify Previous Reviewer (e.g. Derese) if escalated
            if rec.parent_appeal_id and rec.parent_appeal_id.reviewer_id and rec.parent_appeal_id.reviewer_id.partner_id:
                prev_reviewer_user = rec.parent_appeal_id.reviewer_id
                if prev_reviewer_user.id != reviewer_user.id:
                    rec.sudo().message_subscribe(partner_ids=[prev_reviewer_user.partner_id.id])
                    try:
                        channel = self.env['discuss.channel'].with_user(reviewer_user)._get_or_create_chat(
                            partners_to=[prev_reviewer_user.partner_id.id]
                        )
                        if channel:
                            msg_body = Markup(_(
                                '<p><strong>Escalated Disciplinary Appeal Concluded (%s Level)</strong></p>'
                                '<p>Dear %s,</p>'
                                '<p>The escalated appeal (Ref: <strong>%s</strong>) by <strong>%s</strong> regarding case <strong>%s</strong> (prior appeal: %s) has been decided by <strong>%s</strong> (%s).</p>'
                                '<ul>'
                                '<li><strong>Outcome:</strong> %s</li>'
                                '<li><strong>Sanction:</strong> %s</li>'
                                '</ul>'
                                '<p><strong>Rationale:</strong> <em>%s</em></p>'
                            ) % (
                                appeal_lvl_label,
                                prev_reviewer_user.name,
                                rec.name,
                                appellant_name,
                                case_name,
                                rec.parent_appeal_id.name,
                                reviewer_name,
                                target_label,
                                outcome_label,
                                sanction_desc,
                                rationale_text,
                            ))
                            channel.message_post(
                                body=msg_body,
                                message_type='comment',
                                subtype_xmlid='mail.mt_comment',
                                author_id=reviewer_user.partner_id.id,
                            )
                    except Exception:
                        pass
        return {'type': 'ir.actions.act_window_close'}

    def action_create_next_appeal(self):
        """Submit Next Level Appeal if previous appeal was upheld or partially reduced upon review."""
        self.ensure_one()
        current_user = self.env.user
        emp = self.sudo().employee_id
        is_emp = bool(
            emp and (
                (emp.user_id and emp.user_id.id == current_user.id) or
                (current_user.sudo().employee_id and current_user.sudo().employee_id.id == emp.id) or
                (hasattr(current_user, 'employee_ids') and emp.id in current_user.sudo().employee_ids.ids)
            )
        )
        is_pomd = current_user.has_group('discipline_management.group_discipline_pomd') or current_user.has_group('discipline_management.group_discipline_admin')
        is_dismissal_inactive = bool(
            self.case_id and
            (self.case_id.severity_level == 'level_1' or self.case_id.punishment_type == 'dismissal') and
            emp and (not emp.active or (emp.user_id and not emp.user_id.active))
        )
        if not (is_emp or (is_pomd and is_dismissal_inactive)):
            raise UserError(_('Appeal Access Restriction: Only the subject employee (or POMD for dismissed/inactive employees) can submit an appeal escalation.'))

        if self.acceptance_state in ('accepted', 'window_closed'):
            raise UserError(_('This appeal decision has already been accepted and finalized. Further escalation is not permitted.'))

        if self.state != 'decided' or self.decision_outcome not in ('upheld', 'penalty_reduced'):
            raise UserError(_('A subsequent appeal can only be lodged if the current appeal was decided and not fully overturned/exonerated.'))

        # Determine next level
        actual_reviewer = self.reviewer_id or self.designated_reviewer_id
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        if (ceo_user and actual_reviewer and actual_reviewer.id == ceo_user.id) or (actual_reviewer and actual_reviewer.has_group('discipline_management.group_discipline_ceo')) or self.appeal_target_authority == 'ceo':
            raise UserError(_('This record was decided by the Chief Executive Officer (CEO), which is the final appeal authority. No further appeals can be submitted.'))

        level_map = {
            'first': 'second',
            'second': 'third',
            'third': 'fourth',
            'fourth': 'fifth',
        }
        next_level = level_map.get(self.appeal_level, 'fourth')
        next_title = _('Submit Appeal for Case %s') % self.case_id.name

        # Check if already submitted or if another appeal is active on this case
        active_case_appeals = self.case_id.appeal_ids.filtered(
            lambda a: a.id != self.id and a.state in ('draft', 'submitted', 'under_review')
        )
        if active_case_appeals:
            act = active_case_appeals[0]
            act_state = dict(act._fields['state'].selection).get(act.state, act.state)
            raise UserError(_(
                'Active Appeal in Progress: Case "%(case)s" already has an active appeal (Ref: %(ref)s) in "%(state)s" status.\n\n'
                'Under Bank Disciplinary Policy, only one active appeal can exist at a time. '
                'The pending appeal must be formally decided before lodging another appeal.'
            ) % {
                'case': self.case_id.name,
                'ref': act.name,
                'state': act_state,
            })

        existing_child = self.search([('parent_appeal_id', '=', self.id)], limit=1)
        if existing_child:
            raise UserError(_('An escalated appeal (%s) has already been lodged for this record.') % existing_child.name)

        self.write({'acceptance_state': 'appealed_further'})
        self.message_post(body=_('Appellant initiated further appeal escalation. Any held payroll reimbursement remains deferred pending outcome of the higher appeal level.'))

        return {
            'name': next_title,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.case_id.id,
                'default_parent_appeal_id': self.id,
                'default_appeal_level': next_level,
                'default_submission_date': fields.Date.context_today(self),
                'discipline_scope': True,
            }
        }

    def action_employee_accept_decision(self):
        """Appellant employee (or HR on their behalf) formally accepts the appeal decision.
        Finalizes acceptance and releases any held payroll refund."""
        for rec in self:
            if not rec.can_employee_accept_decision:
                raise UserError(_('This appeal decision cannot be accepted (it may already be accepted, fully exonerated, or rendered by the final authority).'))
            if rec.state not in ('decided', 'closed'):
                raise UserError(_('Decisions can only be accepted once a final decision is rendered.'))
            if rec.acceptance_state == 'accepted':
                raise UserError(_('This appeal decision has already been accepted.'))
            if rec.acceptance_state == 'appealed_further':
                raise UserError(_('This appeal was already escalated to a higher level.'))

            current_user = self.env.user
            emp = rec.sudo().employee_id
            is_appellant = bool(emp and emp.user_id and emp.user_id.id == current_user.id)
            is_submitter = bool(rec.submitted_by_id and rec.submitted_by_id.id == current_user.id)
            is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system')
            if not (is_appellant or is_submitter or is_admin):
                raise UserError(_('Only the appellant employee or HR Administrator can formally accept this decision.'))

            rec.write({'acceptance_state': 'accepted'})
            rec.message_post(body=_('Appeal decision formally ACCEPTED by %s. Case resolution finalized.') % current_user.name)
            if rec.case_id:
                rec.case_id.sudo().write({'state': 'closed'})
                rec.case_id.sudo().message_post(body=_('Appeal %s decision accepted by employee. Case resolution finalized and closed.') % rec.name)
            if rec.held_refund_amount > 0.0:
                rec._execute_held_payroll_refund()

    @api.model
    def _cron_process_appeal_acceptance_window(self):
        """Automatically marks expired appeal decision windows as closed/accepted
        and triggers execution of any held payroll refunds."""
        today = fields.Date.context_today(self)
        pending_appeals = self.search([
            ('state', 'in', ['decided', 'closed']),
            ('acceptance_state', '=', 'pending'),
            ('appeal_window_deadline', '!=', False),
            ('appeal_window_deadline', '<', today),
        ])
        for app in pending_appeals:
            app.write({'acceptance_state': 'window_closed'})
            app.message_post(body=_('Appeal acceptance window (10 calendar days) has expired without further escalation. Decision is deemed final.'))
            if app.case_id and app.case_id.state in ('enforced', 'appealed'):
                app.case_id.sudo().write({'state': 'closed'})
            if app.held_refund_amount > 0.0:
                app._execute_held_payroll_refund()

    @api.model
    def _cron_auto_escalate_overdue_appeals(self):
        """Automatically escalate appeals that have exceeded the authority review SLA window."""
        today = fields.Date.context_today(self)
        overdue_appeals = self.search([
            ('state', 'in', ['submitted', 'under_review']),
            ('sla_review_deadline', '!=', False),
            ('sla_review_deadline', '<', today),
            ('appeal_target_authority', '!=', 'ceo'),
        ])
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        cpco_user = EmpModel.get_cpco_user()

        for app in overdue_appeals:
            old_auth = dict(app._fields['appeal_target_authority'].selection).get(app.appeal_target_authority, app.appeal_target_authority)
            next_target = False
            new_reviewer = False

            if app.appeal_target_authority == 'directorate':
                next_target = 'chief'
                new_reviewer = cpco_user or (app.case_id.sudo().chief_id.user_id if app.case_id and app.case_id.sudo().chief_id else False)
            elif app.appeal_target_authority in ('chief', 'secretary'):
                next_target = 'ceo'
                new_reviewer = ceo_user

            if next_target:
                new_auth_label = dict(app._fields['appeal_target_authority'].selection).get(next_target, next_target)
                vals = {
                    'auto_escalated_authority': next_target,
                    'is_auto_escalated': True,
                }
                if new_reviewer:
                    vals['designated_reviewer_id'] = new_reviewer.id
                app.sudo().write(vals)

                # Recompute SLA deadline for the new authority (5 working days from today)
                day_count = 0
                curr = today
                while day_count < 5:
                    curr += timedelta(days=1)
                    if curr.weekday() < 5:
                        day_count += 1
                app.sudo().write({'sla_review_deadline': curr})

                escalate_msg = _(
                    '⚠️ <strong>Automatic SLA Escalation:</strong> Review deadline exceeded by %s.<br/>'
                    'Appeal automatically escalated to <strong>%s</strong> (%s) for prompt review.'
                ) % (old_auth, new_auth_label, new_reviewer.name if new_reviewer else 'Assigned Authority')

                app.message_post(body=escalate_msg)
                if app.case_id:
                    app.case_id.sudo().message_post(body=escalate_msg)

                # Send Discuss notification to the new authority
                if new_reviewer and new_reviewer.partner_id:
                    try:
                        app.message_notify(
                            partner_ids=[new_reviewer.partner_id.id],
                            body=_(
                                'Urgent: Disciplinary Appeal %s has been automatically escalated to you due to SLA breach by %s.'
                            ) % (app.name, old_auth),
                            subject=_('Urgent: Escalated Disciplinary Appeal %s') % app.name,
                        )
                    except Exception:
                        pass

    def action_create_second_appeal(self):
        """Backward compatibility alias for action_create_next_appeal."""
        return self.action_create_next_appeal()

    @api.model
    def _get_accessible_appeal_employee_ids(self):
        """Deprecated: discipline access is self-contained and does not alter hr.employee access rules."""
        return []
                