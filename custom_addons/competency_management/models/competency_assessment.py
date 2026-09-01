# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyAssessmentCycle(models.Model):
    """Scheduled competency assessment cycle /010,."""
    _name = 'competency.assessment.cycle'
    _description = 'Competency Assessment Cycle'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Cycle Name', required=True)
    code = fields.Char(string='Cycle Code', index=True)
    period_start = fields.Date(string='Period Start', required=True, default=fields.Date.context_today)
    period_end = fields.Date(string='Period End')
    assessment_deadline = fields.Date(string='Assessment Deadline')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('in_review', 'In Review'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True)
    assessment_ids = fields.One2many('competency.assessment', 'cycle_id', string='Assessments')
    assessment_count = fields.Integer(string='Assessments', compute='_compute_assessment_count')
    notes = fields.Text(string='Notes')

    @api.depends('assessment_ids')
    def _compute_assessment_count(self):
        for rec in self:
            rec.assessment_count = len(rec.assessment_ids)

    @api.constrains('period_start', 'period_end')
    def _check_periods(self):
        for rec in self:
            if rec.period_end and rec.period_start and rec.period_end < rec.period_start:
                raise ValidationError(_('Period End cannot be before Period Start.'))

    def action_start(self):
        """Draft -> Open with notifications (FR-COM-045)."""
        self.with_context(force_write=True).write({'state': 'open'})
        for rec in self:
            rec.message_post(body=_('Assessment cycle %s opened. Deadline: %s.') % (rec.name, rec.assessment_deadline or 'Not set'))
            # Schedule activity notifications for supervisors and employees in scope
            for asm in assessments:
                target_name = asm.employee_id.name if asm.employee_id else _('yourself')
                atype = dict(asm._fields['assessment_type'].selection).get(asm.assessment_type, asm.assessment_type)
                # Notify Assessor (Self, Supervisor, Peer, Team)
                if asm.assessor_id:
                    asm.activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('Competency Assessment Required: %s (%s)') % (target_name, atype),
                        note=_('Assessment cycle %s is now open! Please log in to complete your evaluation for %s (%s). Deadline: %s.') % (
                            rec.name, target_name, atype, rec.assessment_deadline or 'N/A'
                        ),
                        user_id=asm.assessor_id.id,
                        date_deadline=rec.assessment_deadline or fields.Date.context_today(self),
                    )

    def action_start_review(self):
        self.with_context(force_write=True).write({'state': 'in_review'})

    def action_close(self):
        self.with_context(force_write=True).write({'state': 'closed'})
        for rec in self:
            rec.message_post(body=_('Assessment cycle %s closed.') % rec.name)

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state == 'closed' and not force_write and not self.env.su:
                locked_fields = {'name', 'period_start', 'period_end', 'assessment_deadline'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(_("This assessment cycle (%s) is closed and cannot be edited.") % rec.name)
        return super().write(vals)


class CompetencyAssessment(models.Model):
    """A single employee assessment within a cycle (FR-COM-011, FR-COM-012)."""
    _name = 'competency.assessment'
    _description = 'Competency Assessment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, copy=False)
    cycle_id = fields.Many2one(
        'competency.assessment.cycle', string='Assessment Cycle', required=True,
        domain="[('state', '=', 'open')]", ondelete='cascade', tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True,
        domain=lambda self: self._get_allowed_employee_domain())
    department_id = fields.Many2one(related='employee_id.department_id', string='Department', store=True, readonly=True)
    job_id = fields.Many2one(related='employee_id.job_id', string='Job Position', store=True, readonly=True)

    @api.model
    def _get_assessment_type_selection(self):
        """Rule 1: Dynamically filter assessment types based on logged-in user role."""
        user = self.env.user
        emp = user.employee_id
        
        selection = [('self', 'Self-Assessment')]
        
        if self.env.su or user.has_group('competency_management.group_competency_admin'):
            return [
                ('self', 'Self-Assessment'),
                ('peer', 'Peer Assessment'),
                ('supervisor', 'Supervisor Assessment'),
                ('team', 'Team Assessment'),
            ]
            
        if emp:
            if emp.parent_id:
                selection.append(('peer', 'Peer Assessment'))
                selection.append(('supervisor', 'Supervisor Assessment'))
            
            subordinates = self.env['hr.employee'].search([('parent_id', '=', emp.id)], limit=1)
            if subordinates or emp.child_ids:
                selection.append(('team', 'Team Assessment'))
                
        return selection

    @api.model
    def _get_allowed_employee_domain(self):
        user = self.env.user
        if self.env.su or user.has_group('competency_management.group_competency_admin'):
            return []
        
        emp = user.employee_id
        if not emp:
            return [('id', '=', False)]
            
        allowed_ids = set()
        allowed_ids.add(emp.id)
        
        subordinates = self.env['hr.employee'].search([('id', 'child_of', emp.id)])
        allowed_ids.update(subordinates.ids)
        
        if emp.parent_id:
            peers = self.env['hr.employee'].search([('parent_id', '=', emp.parent_id.id)])
            allowed_ids.update(peers.ids)
            
        return [('id', 'in', list(allowed_ids))]

    assessor_id = fields.Many2one('res.users', string='Assessor', default=lambda self: self.env.user, readonly=True)
    assessment_type = fields.Selection(
        selection='_get_assessment_type_selection', string='Assessment Type',
        required=True, tracking=True)

    @api.onchange('assessment_type')
    def _onchange_assessment_type_set_employee_domain(self):
        """Rule 2: Restrict employee selection domain strictly based on chosen assessment type and auto-assign valid default."""
        user = self.env.user
        emp = user.employee_id
        
        if self.assessment_type == 'self':
            if emp:
                self.employee_id = emp.id
            return {'domain': {'employee_id': [('id', '=', emp.id if emp else False)]}}

        if not emp:
            self.employee_id = False
            return {'domain': {'employee_id': [('id', '=', False)]}}

        if self.assessment_type == 'peer':
            # Peer selection: same manager or same department (excluding self)
            peers = self.env['hr.employee']
            if emp.parent_id:
                peers |= self.env['hr.employee'].search([('parent_id', '=', emp.parent_id.id), ('id', '!=', emp.id)])
            if emp.department_id:
                peers |= self.env['hr.employee'].search([('department_id', '=', emp.department_id.id), ('id', '!=', emp.id)])
            if not peers:
                peers = self.env['hr.employee'].search([('id', '!=', emp.id)], limit=50)
            
            self.employee_id = peers[0].id if peers else False
            return {'domain': {'employee_id': [('id', 'in', peers.ids)]}}
            
        elif self.assessment_type == 'supervisor':
            # Supervisor selection: parent_id, coach_id, or department manager
            supervisors = self.env['hr.employee']
            if emp.parent_id:
                supervisors |= emp.parent_id
            if getattr(emp, 'coach_id', False) and emp.coach_id:
                supervisors |= emp.coach_id
            if emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.id != emp.id:
                supervisors |= emp.department_id.manager_id

            if not supervisors and emp.department_id:
                # Fallback to parent department manager
                dept = emp.department_id.parent_id
                while dept and not supervisors:
                    if dept.manager_id and dept.manager_id.id != emp.id:
                        supervisors |= dept.manager_id
                    dept = dept.parent_id

            if not supervisors:
                # Fallback to employees with manager/director in job title
                supervisors = self.env['hr.employee'].search([
                    ('id', '!=', emp.id),
                    '|', ('job_id.name', 'ilike', 'manager'), ('job_id.name', 'ilike', 'director')
                ], limit=30)

            self.employee_id = supervisors[0].id if supervisors else False
            return {'domain': {'employee_id': [('id', 'in', supervisors.ids)]}}
            
        elif self.assessment_type == 'team':
            # Team selection: direct reports or subordinates
            subordinates = self.env['hr.employee'].search([('parent_id', '=', emp.id)])
            if not subordinates and emp.department_id and emp.department_id.manager_id.id == emp.id:
                subordinates = self.env['hr.employee'].search([('department_id', '=', emp.department_id.id), ('id', '!=', emp.id)])
            
            self.employee_id = subordinates[0].id if subordinates else False
            return {'domain': {'employee_id': [('id', 'in', subordinates.ids)]}}

        return {'domain': {'employee_id': []}}
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('supervisor_review', 'Supervisor Review'),
        ('hr_verified', 'HR Verified'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], string='Status', default='draft', tracking=True)
    line_ids = fields.One2many('competency.assessment.line', 'assessment_id', string='Competency Ratings')
    core_line_ids = fields.One2many('competency.assessment.line', 'assessment_id', string='Core Competencies', domain=[('pillar', '=', 'core')])
    leadership_line_ids = fields.One2many('competency.assessment.line', 'assessment_id', string='Leadership Competencies', domain=[('pillar', '=', 'leadership')])
    technical_line_ids = fields.One2many('competency.assessment.line', 'assessment_id', string='Technical Competencies', domain=[('pillar', '=', 'technical')])
    average_gap = fields.Float(string='Average Gap', compute='_compute_average_gap', store=True)
    is_locked = fields.Boolean(string='Locked', compute='_compute_is_locked')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    # 360 Multi-Rater extension fields (FR-COM-012, FR-ASM-002, FR-ASM-005)
    parent_assessment_id = fields.Many2one('competency.assessment', string='Parent 360 Assessment', ondelete='cascade', tracking=True)
    child_assessment_ids = fields.One2many('competency.assessment', 'parent_assessment_id', string='Rater Assessments')
    is_rater_assessment = fields.Boolean(string='Is Child Rater Assessment', default=False)
    rater_type = fields.Selection([
        ('self', 'Self'),
        ('peer', 'Peer'),
        ('subordinate', 'Subordinate'),
        ('supervisor', 'Supervisor'),
        ('other', 'Other'),
    ], string='Rater Type')
    rater_id = fields.Many2one('res.users', string='Rater User')
    is_anonymous = fields.Boolean(string='Anonymize 360 Feedback', default=False,
                                   help='Hide rater name from line managers for peer/subordinate 360 reviews (FR-ASM-002).')
    anonymized_rater_label = fields.Char(string='Display Rater Label', compute='_compute_anonymized_rater_label')

    @api.depends('is_anonymous', 'rater_type', 'rater_id')
    def _compute_anonymized_rater_label(self):
        for rec in self:
            if rec.is_anonymous and rec.rater_type in ('peer', 'subordinate'):
                rec.anonymized_rater_label = _("Anonymous 360 Rater (%s)") % (rec.rater_type.capitalize() if rec.rater_type else 'Peer')
            elif rec.rater_id:
                rec.anonymized_rater_label = rec.rater_id.name
            else:
                rec.anonymized_rater_label = _("Unassigned")

    def action_consolidate_multi_source(self):
        """Consolidate Self, Manager, 360 Feedback, and Skills Test scores into one achievement determination (FR-ASM-005)."""
        for parent in self:
            if not parent.employee_id:
                continue
            
            competency_scores = {}
            competency_reqs = {}
            
            # 1. Child 360 raters
            for child in parent.child_assessment_ids.filtered(lambda c: c.state in ('submitted', 'supervisor_review', 'hr_verified', 'approved', 'locked')):
                for line in child.line_ids:
                    cid = line.competency_id.id
                    competency_scores.setdefault(cid, []).append(int(line.current_level or 1))
                    competency_reqs[cid] = line.required_level
                    
            # 2. Skills Tests (FR-ASM-003)
            skills_tests = self.env['competency.skills.test'].search([('employee_id', '=', parent.employee_id.id)])
            for test in skills_tests:
                if test.verified_level:
                    cid = test.competency_id.id
                    competency_scores.setdefault(cid, []).append(int(test.verified_level))

            # Update line ratings
            for cid, score_list in competency_scores.items():
                avg_score = round(sum(score_list) / len(score_list))
                lvl_str = str(max(1, min(4, avg_score)))
                existing_line = parent.line_ids.filtered(lambda l: l.competency_id.id == cid)
                if existing_line:
                    existing_line.write({'current_level': lvl_str})
                else:
                    self.env['competency.assessment.line'].create({
                        'assessment_id': parent.id,
                        'competency_id': cid,
                        'current_level': lvl_str,
                        'required_level': competency_reqs.get(cid, '2'),
                    })
            parent.message_post(body=_("Multi-source assessment scores (360 feedback + Skills Tests) consolidated into final achievement levels."))

    @api.depends('line_ids', 'line_ids.gap')
    def _compute_average_gap(self):
        for rec in self:
            gaps = [line.gap for line in rec.line_ids if line.gap is not None]
            rec.average_gap = round(sum(gaps) / len(gaps), 2) if gaps else 0.0

    @api.depends('state')
    def _compute_is_locked(self):
        for rec in self:
            rec.is_locked = rec.state == 'locked'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if not record.name:
                record.name = self.env['ir.sequence'].sudo().next_by_code('competency.assessment') or \
                    'CMP-A-%s' % record.id
        return records

    @api.model
    def _get_matrix_required_level(self, pillar, grade=False, job=False, job_name=''):
        """Determine required proficiency level (1..4) based on configured Competency Matrix settings."""
        config = self.env['competency.matrix.config'].get_active_config()
        
        # 1. Configured Determinant Mode Check
        if config.proficiency_determinant == 'job_grade' and grade:
            g_line = self.env['competency.grade.matrix'].search([
                ('config_id', '=', config.id),
                ('grade_id', '=', grade.id)
            ], limit=1)
            if g_line:
                if pillar == 'core': return g_line.required_core_level
                elif pillar == 'leadership': return g_line.required_leadership_level if g_line.required_leadership_level != '0' else '1'
                else: return g_line.required_technical_level
                
        elif config.proficiency_determinant == 'job_position' and job:
            j_line = self.env['competency.job.matrix'].search([
                ('config_id', '=', config.id),
                ('job_id', '=', job.id)
            ], limit=1)
            if j_line:
                if pillar == 'core': return j_line.required_core_level
                elif pillar == 'leadership': return j_line.required_leadership_level if j_line.required_leadership_level != '0' else '1'
                else: return j_line.required_technical_level

        # Fallback to standard guidelines
        g_name = (grade.grade_name or '').lower() if grade else ''
        j_name = (job.name if job else job_name or '').lower()
        
        # Chief & D/Chief
        if 'chief' in g_name or 'chief' in j_name:
            if pillar == 'core': return '4'
            elif pillar == 'leadership': return '4'
            else: return '2'
            
        # Director I, II & ToT Leaders
        if 'director' in g_name or 'director' in j_name or 'tot leader' in j_name:
            if pillar == 'core': return '4'
            elif pillar == 'leadership': return '3'
            else: return '3'
            
        # BM-II, III, Division Managers & STL
        if 'division manager' in j_name or 'bm-ii' in j_name or 'bm-iii' in j_name or 'stl' in j_name:
            if pillar == 'core': return '3'
            elif pillar == 'leadership': return '2'
            else: return '3'
            
        # Team Leader, BM-I & related
        if 'team leader' in j_name or 'bm-i' in j_name or 'manager' in j_name:
            if pillar == 'core': return '3'
            elif pillar == 'leadership': return '2'
            else: return '4'
            
        # Non Supervisory Job Grade 11-12
        if any(x in g_name for x in ['11', '12', 'xi', 'xii']):
            if pillar == 'core': return '2'
            elif pillar == 'leadership': return '1'
            else: return '4'
            
        # Non Supervisory Job Grade 7-10
        if any(x in g_name for x in ['7', '8', '9', '10', 'vii', 'viii', 'ix', 'x']):
            if pillar == 'core': return '2'
            elif pillar == 'leadership': return '1'
            else: return '3'
            
        # Default / Grade 6 and below
        if pillar == 'core': return '1'
        elif pillar == 'leadership': return '1'
        else: return '2'

    @api.onchange('employee_id')
    def _onchange_employee_id_populate_competencies(self):
        """Automatically populate/refresh competency rating lines when employee_id changes in draft state."""
        if self.state == 'draft' and self.employee_id:
            self._do_populate_lines()

    def _do_populate_lines(self):
        """Internal helper to populate competency rating lines for self.employee_id."""
        if not self.employee_id:
            self.line_ids = [(5, 0, 0)]
            return 0, ''
        employee = self.employee_id
        job_pos = employee.job_id or getattr(employee, 'job_position', False)
        mapping = False
        if job_pos:
            mapping = self.env['competency.role.mapping'].search([
                ('job_position_id', '=', job_pos.id),
                ('state', '=', 'approved')
            ], order='id desc', limit=1)
            if not mapping:
                mapping = self.env['competency.role.mapping'].search([
                    ('job_position_id', '=', job_pos.id)
                ], order='id desc', limit=1)

        raw_line_vals = []
        if mapping and mapping.line_ids:
            for mline in mapping.line_ids:
                if mline.competency_id:
                    raw_line_vals.append({
                        'competency_id': mline.competency_id.id,
                        'pillar': mline.competency_id.pillar or 'technical',
                        'current_level': False,
                        'required_level': mline.required_proficiency or '2',
                    })
            mapping_name_str = mapping.mapping_name
        else:
            grade_rec = getattr(employee, 'grade_id', False) or getattr(employee, 'job_grade', False)
            j_name = job_pos.name if job_pos else ''
            j_lower = j_name.lower()
            is_managerial = any(k in j_lower for k in ['manager', 'director', 'chief', 'leader', 'head', 'supervisor', 'president', 'vp']) or getattr(employee, 'is_managerial', False)

            core_comps = self.env['competency.competency'].search([('pillar', '=', 'core'), ('status', '=', 'active')])
            for comp in core_comps:
                req_lvl = self._get_matrix_required_level('core', grade=grade_rec, job=job_pos, job_name=j_name)
                raw_line_vals.append({
                    'competency_id': comp.id,
                    'pillar': 'core',
                    'current_level': False,
                    'required_level': req_lvl or '2',
                })

            if is_managerial:
                lead_comps = self.env['competency.competency'].search([('pillar', '=', 'leadership'), ('status', '=', 'active')])
                for comp in lead_comps:
                    req_lvl = self._get_matrix_required_level('leadership', grade=grade_rec, job=job_pos, job_name=j_name)
                    raw_line_vals.append({
                        'competency_id': comp.id,
                        'pillar': 'leadership',
                        'current_level': False,
                        'required_level': req_lvl or '2',
                    })

            tech_comps = self.env['competency.competency']
            if job_pos and getattr(job_pos, 'department_id', False):
                dept_name = job_pos.department_id.name
                tech_comps = self.env['competency.competency'].search([
                    ('pillar', '=', 'technical'),
                    ('status', '=', 'active'),
                    ('functional_domain', '=ilike', dept_name)
                ])
            if not tech_comps:
                tech_comps = self.env['competency.competency'].search([
                    ('pillar', '=', 'technical'),
                    ('status', '=', 'active')
                ], limit=5)

            for comp in tech_comps:
                req_lvl = self._get_matrix_required_level('technical', grade=grade_rec, job=job_pos, job_name=j_name)
                raw_line_vals.append({
                    'competency_id': comp.id,
                    'pillar': 'technical',
                    'current_level': False,
                    'required_level': req_lvl or '2',
                })

            mapping_name_str = _("Competency Matrix Guidelines (%s)") % (j_name or 'Default')

        # Check if record is saved (real database integer ID) or unsaved (onchange/NewId)
        if isinstance(self.id, int):
            self.line_ids.sudo().unlink()
            if raw_line_vals:
                create_vals = [dict(v, assessment_id=self.id) for v in raw_line_vals]
                created_lines = self.env['competency.assessment.line'].sudo().create(create_vals)
                cnt = len(created_lines)
            else:
                cnt = 0
        else:
            commands = [(5, 0, 0)] + [(0, 0, v) for v in raw_line_vals]
            self.line_ids = commands
            cnt = len(raw_line_vals)

        return cnt, mapping_name_str

    def action_populate_competencies(self):
        """Populate competency rating lines explicitly upon user clicking 'Populate Competencies'."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Competencies can only be populated when the assessment is in Draft state."))
        if not self.cycle_id or not self.assessment_type or not self.employee_id:
            raise UserError(_("Assessment Cycle, Assessment Type, and Employee are required before populating competencies."))
        
        cnt, mapping_name_str = self._do_populate_lines()
        self.message_post(body=_('Competency rating lines populated from %s (%d competencies).') % (mapping_name_str, cnt))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Competency Assessment'),
            'res_model': 'competency.assessment',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'main',
        }

    def action_auto_fill_lines(self):
        return self.action_populate_competencies()

    def action_submit(self):
        """Draft -> Submitted with unrated checks and employee activity notification."""
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Add at least one competency rating line before submitting.'))
            unrated = rec.line_ids.filtered(lambda l: not l.current_level)
            if unrated:
                unrated_names = ", ".join(unrated.mapped('competency_id.name')[:5])
                raise UserError(_('Please rate your current proficiency level for all competencies before submitting. %d competency(ies) remaining unrated: %s%s') % (
                    len(unrated), unrated_names, "..." if len(unrated) > 5 else ""
                ))
            rec.with_context(force_write=True).write({'state': 'submitted'})
            rec.message_post(body=_('Assessment %s submitted for review.') % rec.name)

    def compute_aggregate_360_ratings(self):
        return self.action_consolidate_multi_source()

    def _check_segregation_of_duties(self):
        """Segregation of duties guard: Block self-approval by subject, assessor, or creator (FR-COM-055)."""
        for rec in self:
            subject_user = rec.employee_id.user_id if rec.employee_id else False
            assessor_user = rec.assessor_id or False
            creator_user = rec.create_uid or False
            current_user = self.env.user
            
            if not self.env.su:
                if (subject_user and current_user == subject_user) or \
                   (assessor_user and current_user == assessor_user) or \
                   (creator_user and current_user == creator_user):
                    raise ValidationError(_("You cannot approve your own assessment/IDP. This action must be performed by a different authorized user (FR-COM-055)."))

    def action_submit(self):
        """Draft -> Submitted workflow with employee confirmation (FR-COM-047)."""
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Add at least one competency rating line before submitting.'))
            rec.with_context(force_write=True).write({'state': 'submitted'})
            rec.message_post(body=_('Assessment %s submitted for review.') % rec.name)
            
            if rec.employee_id and rec.employee_id.user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Assessment Submitted: %s') % rec.name,
                    note=_('Your competency assessment %s has been submitted successfully.') % rec.name,
                    user_id=rec.employee_id.user_id.id,
                )

    def action_supervisor_review(self):
        """Submitted -> Supervisor Review with supervisor activity notification (FR-COM-048)."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'supervisor_review'})
            supervisor_user = rec.employee_id.parent_id.user_id if (rec.employee_id and rec.employee_id.parent_id) else False
            if supervisor_user:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Supervisor Review Needed: Assessment %s') % rec.name,
                    note=_('Please review and complete assessment for %s.') % rec.employee_id.name,
                    user_id=supervisor_user.id,
                    date_deadline=rec.cycle_id.assessment_deadline or fields.Date.context_today(self),
                )

    def action_hr_verify(self):
        for rec in self:
            rec._check_segregation_of_duties()
            rec.with_context(force_write=True).write({'state': 'hr_verified'})

    def action_approve(self):
        """Approved -> final approval with Segregation of Duties guard (FR-COM-055)."""
        for rec in self:
            rec._check_segregation_of_duties()
            rec.with_context(force_write=True).write({'state': 'approved'})
            rec.message_post(body=_('Assessment %s approved.') % rec.name)
            
            gap_lines = rec.line_ids.filtered(lambda l: int(l.current_level or 1) < int(l.required_level or 1))
            # Auto-feed TNA entry into EDS cycle if EDS is available
            if 'eds.tna.entry' in self.env:
                cycle = self.env['eds.tna.cycle'].search([('state', 'in', ['draft', 'collecting'])], limit=1)
                if cycle:
                    for line in gap_lines:
                        existing_tna = self.env['eds.tna.entry'].search([
                            ('cycle_id', '=', cycle.id),
                            ('employee_id', '=', rec.employee_id.id),
                            ('competency_id', '=', line.competency_id.id),
                        ], limit=1)
                        if not existing_tna:
                            self.env['eds.tna.entry'].create({
                                'cycle_id': cycle.id,
                                'employee_id': rec.employee_id.id,
                                'competency_id': line.competency_id.id,
                                'source': 'competency_gap',
                                'justification': _('Auto-generated from Competency Assessment %s gap.') % rec.name,
                            })

    def action_lock(self):
        """Lock finalized assessment against further modification."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'locked'})
            rec.message_post(body=_('Assessment %s locked.') % rec.name)

    def action_unlock(self):
        """Authorized override with justification."""
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('competency_management.group_competency_admin')):
            raise UserError(_('Only Competency Administrators can unlock finalized assessments.'))
        if not self.notes:
            raise UserError(_('Provide a justification in Notes before unlocking.'))
        self.with_context(force_write=True).write({'state': 'approved'})
        self.message_post(body=_('Assessment %s unlocked by %s.') % (self.name, self.env.user.name))

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state == 'locked' and not force_write and not self.env.su:
                locked_fields = {'employee_id', 'cycle_id', 'assessment_type', 'assessor_id', 'line_ids', 'notes'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(_("Assessment %s is locked. Only Competency Administrators can unlock finalized assessments using the Unlock action.") % rec.name)
        return super().write(vals)

    @api.model
    def _cron_pending_assessment_reminders(self):
        """Daily cron: pending assessment reminders, upcoming deadline alerts & overdue escalations (FR-COM-046, FR-COM-048)."""
        today = fields.Date.context_today(self)
        
        # 1. Upcoming Deadline Alerts (7 days, 3 days, 1 day before deadline)
        upcoming_assessments = self.search([
            ('state', 'in', ['draft', 'submitted', 'supervisor_review']),
            ('cycle_id.assessment_deadline', '!=', False),
            ('cycle_id.assessment_deadline', '>', today)
        ])
        for asm in upcoming_assessments:
            days_left = (asm.cycle_id.assessment_deadline - today).days
            if days_left in (7, 3, 1):
                target_user = False
                if asm.state in ('draft', 'submitted') and asm.employee_id.user_id:
                    target_user = asm.employee_id.user_id
                elif asm.state == 'supervisor_review' and asm.employee_id.parent_id and asm.employee_id.parent_id.user_id:
                    target_user = asm.employee_id.parent_id.user_id
                    
                if target_user:
                    asm.activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('UPCOMING DEADLINE (%d days left): Competency Assessment %s') % (days_left, asm.name),
                        note=_('Reminder: Your competency assessment %s is due in %d days (Deadline: %s).') % (asm.name, days_left, asm.cycle_id.assessment_deadline),
                        user_id=target_user.id,
                        date_deadline=asm.cycle_id.assessment_deadline,
                    )

        # 2. Overdue Assessments (Deadline reached or passed)
        overdue_assessments = self.search([
            ('state', 'in', ['draft', 'submitted', 'supervisor_review']),
            ('cycle_id.assessment_deadline', '!=', False),
            ('cycle_id.assessment_deadline', '<=', today)
        ])
        for asm in overdue_assessments:
            target_user = False
            if asm.state in ('draft', 'submitted') and asm.employee_id.user_id:
                target_user = asm.employee_id.user_id
            elif asm.state == 'supervisor_review' and asm.employee_id.parent_id and asm.employee_id.parent_id.user_id:
                target_user = asm.employee_id.parent_id.user_id
                
            if target_user:
                asm.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('OVERDUE: Competency Assessment %s') % asm.name,
                    note=_('URGENT: Competency Assessment %s passed its deadline (%s) and is overdue for completion.') % (asm.name, asm.cycle_id.assessment_deadline),
                    user_id=target_user.id,
                    date_deadline=today,
                )

    def get_achievement_summary_sentence(self):
        """Returns plain-language alignment sentence (FR-RPT-001 / FR-GAP-007)."""
        self.ensure_one()
        total = len(self.line_ids)
        if not total:
            return _("No competencies rated for position %s.") % (self.job_id.name if self.job_id else 'N/A')
        meets_or_exceeds = len(self.line_ids.filtered(lambda l: l.achievement_status in ('meets', 'exceeds')))
        pct = round((meets_or_exceeds / total) * 100, 1)
        job_name = self.job_id.name if self.job_id else 'assigned position'
        return _("Employee meets %d of %d required competencies (%s%% alignment) for position %s.") % (
            meets_or_exceeds, total, pct, job_name
        )

    def get_recommended_development_actions(self):
        """Returns recommended action mappings for below-status competencies (FR-GAP-004)."""
        self.ensure_one()
        below_lines = self.line_ids.filtered(lambda l: l.achievement_status == 'below')
        recommendations = []
        for line in below_lines:
            comp_name = line.competency_id.name
            pillar = line.pillar or 'technical'
            gap = line.gap or 1
            if pillar == 'core':
                action = _("Structured Corporate Culture & Execution Workshop / Peer Coaching")
            elif pillar == 'leadership':
                action = _("Executive Leadership Mentoring & Supervisory Management Seminar")
            else:
                if gap > 1:
                    action = _("Formal Technical Training Program & Intensive Hands-on Workshop")
                else:
                    action = _("On-the-job Coaching & Guided Shadowing with Senior Officer")
            recommendations.append({
                'competency': comp_name,
                'pillar': pillar.capitalize(),
                'gap': gap,
                'priority': (line.gap_priority or 'medium').capitalize(),
                'action': action,
            })
        return recommendations


class CompetencyAssessmentLine(models.Model):
    """One competency rating inside an assessment (FR-ASM-006, FR-GAP-005)."""
    _name = 'competency.assessment.line'
    _description = 'Competency Assessment Line'

    assessment_id = fields.Many2one(
        'competency.assessment', string='Assessment', required=True, ondelete='cascade')
    cycle_id = fields.Many2one(related='assessment_id.cycle_id', string='Assessment Cycle', store=True, readonly=True, index=True)
    employee_id = fields.Many2one(related='assessment_id.employee_id', string='Employee', store=True, readonly=True, index=True)
    department_id = fields.Many2one(related='assessment_id.department_id', string='Department', store=True, readonly=True, index=True)
    operating_unit_id = fields.Many2one(related='assessment_id.employee_id.operating_unit_id', string='Operating Unit', store=True, readonly=True, index=True)
    job_id = fields.Many2one(related='assessment_id.job_id', string='Job Position', store=True, readonly=True, index=True)
    state = fields.Selection(related='assessment_id.state', string='Assessment Status', store=True, readonly=True, index=True)

    tna_measure = fields.Selection([
        ('below', 'Underqualified'),
        ('meets', 'Fit'),
        ('exceeds', 'Overqualified'),
    ], string='Fitness Status', compute='_compute_tna_measure', store=True, index=True)

    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade',
        domain="[('state', '=', 'approved'), ('status', '=', 'active')]")
    competency_definition = fields.Text(related='competency_id.definition', string='Competency Definition', readonly=True)
    pillar = fields.Selection(related='competency_id.pillar', string='Pillar', readonly=True, store=True)
    
    indicator_level_1 = fields.Text(string='Level 1 (Basic) Indicator', compute='_compute_level_indicators')
    indicator_level_2 = fields.Text(string='Level 2 (Intermediate) Indicator', compute='_compute_level_indicators')
    indicator_level_3 = fields.Text(string='Level 3 (Advanced) Indicator', compute='_compute_level_indicators')
    indicator_level_4 = fields.Text(string='Level 4 (Expert) Indicator', compute='_compute_level_indicators')
    current_level_indicator = fields.Text(string='Level Indicator Preview', compute='_compute_current_level_indicator')
    
    behavioral_guide_html = fields.Html(string='Proficiency Behavioral Indicators Guide', compute='_compute_level_indicators')

    @api.depends('current_level', 'indicator_level_1', 'indicator_level_2', 'indicator_level_3', 'indicator_level_4')
    def _compute_current_level_indicator(self):
        for rec in self:
            lvl = str(rec.current_level or '1')
            if lvl == '1':
                rec.current_level_indicator = rec.indicator_level_1 or 'Level 1 Basic behavioral indicator.'
            elif lvl == '2':
                rec.current_level_indicator = rec.indicator_level_2 or 'Level 2 Intermediate behavioral indicator.'
            elif lvl == '3':
                rec.current_level_indicator = rec.indicator_level_3 or 'Level 3 Advanced behavioral indicator.'
            elif lvl == '4':
                rec.current_level_indicator = rec.indicator_level_4 or 'Level 4 Expert behavioral indicator.'
            else:
                rec.current_level_indicator = False

    @api.depends('competency_id')
    def _compute_level_indicators(self):
        matrix_config = self.env['competency.matrix.config'].get_active_config()
        for rec in self:
            if rec.competency_id:
                levels = self.env['competency.proficiency.level'].search([
                    ('competency_id', '=', rec.competency_id.id)
                ])
                l_map = {l.level: l.behavioral_indicators for l in levels if l.behavioral_indicators}
                
                l1 = l_map.get('1') or (getattr(matrix_config, 'tech_indicator_level_1') if rec.competency_id.pillar == 'technical' else 'Level 1 (Basic) behavioral indicators.')
                l2 = l_map.get('2') or (getattr(matrix_config, 'tech_indicator_level_2') if rec.competency_id.pillar == 'technical' else 'Level 2 (Intermediate) behavioral indicators.')
                l3 = l_map.get('3') or (getattr(matrix_config, 'tech_indicator_level_3') if rec.competency_id.pillar == 'technical' else 'Level 3 (Advanced) behavioral indicators.')
                l4 = l_map.get('4') or (getattr(matrix_config, 'tech_indicator_level_4') if rec.competency_id.pillar == 'technical' else 'Level 4 (Expert) behavioral indicators.')
                
                rec.indicator_level_1 = l1
                rec.indicator_level_2 = l2
                rec.indicator_level_3 = l3
                rec.indicator_level_4 = l4
                
                rec.behavioral_guide_html = f"""
                <div style="font-family: inherit; font-size: 13px; color: #1d2b32;">
                    <div style="margin-bottom: 8px; padding: 8px 12px; background-color: #f8f9fa; border-left: 4px solid #726732; border-radius: 4px;">
                        <strong style="color: #726732;">Level 1 (Basic):</strong> {l1}
                    </div>
                    <div style="margin-bottom: 8px; padding: 8px 12px; background-color: #f8f9fa; border-left: 4px solid #1d2b32; border-radius: 4px;">
                        <strong style="color: #1d2b32;">Level 2 (Intermediate):</strong> {l2}
                    </div>
                    <div style="margin-bottom: 8px; padding: 8px 12px; background-color: #f8f9fa; border-left: 4px solid #c17540; border-radius: 4px;">
                        <strong style="color: #c17540;">Level 3 (Advanced):</strong> {l3}
                    </div>
                    <div style="margin-bottom: 8px; padding: 8px 12px; background-color: #f8f9fa; border-left: 4px solid #541718; border-radius: 4px;">
                        <strong style="color: #541718;">Level 4 (Expert):</strong> {l4}
                    </div>
                </div>
                """
            else:
                rec.indicator_level_1 = False
                rec.indicator_level_2 = False
                rec.indicator_level_3 = False
                rec.indicator_level_4 = False
                rec.behavioral_guide_html = False

    current_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Current Proficiency', required=False, default=False)
    required_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Required Proficiency', required=True, default='2')
    gap = fields.Integer(string='Gap', compute='_compute_gap', store=True, group_operator='avg',
                         help='Required minus Current proficiency (positive = development gap).')
    current_level_num = fields.Integer(string='Current Level (Numeric)', compute='_compute_level_nums', store=True, group_operator='avg')
    required_level_num = fields.Integer(string='Required Level (Numeric)', compute='_compute_level_nums', store=True, group_operator='avg')
    achievement_status = fields.Selection([
        ('exceeds', 'Exceeds Required Level'),
        ('meets', 'Meets Required Level'),
        ('below', 'Below Required Level'),
    ], string='Achievement Status', compute='_compute_achievement_status_and_priority', store=True)
    gap_priority = fields.Selection([
        ('high', 'High Priority'),
        ('medium', 'Medium Priority'),
        ('low', 'Low Priority / No Gap'),
    ], string='Gap Priority', compute='_compute_achievement_status_and_priority', store=True)
    comments = fields.Text(string='Comments')
    evidence_attachment_ids = fields.Many2many('ir.attachment', string='Supporting Evidence')

    @api.constrains('competency_id')
    def _check_competency_status(self):
        for line in self:
            if line.competency_id and line.competency_id.state == 'retired':
                raise ValidationError(_("The competency '%s' is retired and cannot be assessed.") % line.competency_id.name)

    @api.depends('current_level', 'required_level')
    def _compute_level_nums(self):
        for rec in self:
            rec.current_level_num = int(rec.current_level) if rec.current_level and str(rec.current_level).isdigit() else 0
            rec.required_level_num = int(rec.required_level) if rec.required_level and str(rec.required_level).isdigit() else 0

    @api.depends('current_level', 'required_level')
    def _compute_gap(self):
        for rec in self:
            if rec.current_level and rec.required_level:
                rec.gap = int(rec.required_level) - int(rec.current_level)
            else:
                rec.gap = 0

    @api.depends('gap', 'current_level', 'required_level')
    def _compute_tna_measure(self):
        for rec in self:
            if not rec.current_level:
                rec.tna_measure = False
                continue
            gap_val = rec.gap or 0
            if gap_val > 0:
                rec.tna_measure = 'below'
            elif gap_val == 0:
                rec.tna_measure = 'meets'
            else:
                rec.tna_measure = 'exceeds'

    @api.depends('gap', 'current_level', 'required_level')
    def _compute_achievement_status_and_priority(self):
        for rec in self:
            if not rec.current_level:
                rec.achievement_status = False
                rec.gap_priority = False
                continue
            gap_val = rec.gap or 0
            if gap_val < 0:
                rec.achievement_status = 'exceeds'
                rec.gap_priority = 'low'
            elif gap_val == 0:
                rec.achievement_status = 'meets'
                rec.gap_priority = 'low'
            elif gap_val == 1:
                rec.achievement_status = 'below'
                rec.gap_priority = 'medium'
            else:
                rec.achievement_status = 'below'
                rec.gap_priority = 'high'

    _sql_constraints = [
        ('assessment_competency_uniq', 'unique(assessment_id, competency_id)',
         'This competency is already rated in the assessment!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if line.assessment_id and line.assessment_id.state == 'locked' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot add rating lines to locked assessment %s.") % line.assessment_id.name)
        return lines

    def write(self, vals):
        res = super().write(vals)
        for line in self:
            if line.assessment_id and line.assessment_id.state == 'locked' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot modify rating lines on locked assessment %s.") % line.assessment_id.name)
        return res

    @api.ondelete(at_uninstall=False)
    def _prevent_unlink_on_locked(self):
        for line in self:
            if line.assessment_id and line.assessment_id.state == 'locked' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot delete rating lines from locked assessment %s.") % line.assessment_id.name)



