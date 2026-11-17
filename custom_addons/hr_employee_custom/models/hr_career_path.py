# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrCareerPath(models.Model):
    """
    Career Path (FR-CFW-003, FR-CFW-004).
    A named career path anchored to a specific starting Job Position and Track Type.
    e.g., 'Branch Operations Path' anchored at 'Teller' job position under Value-Stream Track.
    """
    _name = 'hr.career.path'
    _description = 'Career Path'
    _inherit = ['mail.thread']
    _order = 'track_type, name'
    _rec_name = 'name'

    name = fields.Char(string='Career Path Name', required=True, translate=True)
    department_id = fields.Many2one('hr.department', string='Department')
    track_type = fields.Selection([
        ('managerial', 'Managerial / Leadership Track'),
        ('technical', 'Technical / Professional Track'),
        ('value_stream', 'Value-Stream / Operational Track'),
    ], string='Career Track', required=True, default='technical', tracking=True)
    anchor_job_id = fields.Many2one('hr.job', string='From Role',
                                     domain="[('grade', '!=', False)]",
                                     required=True, tracking=True,
                                     help='The entry-level job position where this career path begins.')
    final_job_id = fields.Many2one(
        'hr.job', 
        string='Culminating Target Role', 
        compute='_compute_final_job_id',
        store=True,
        help='The highest target position achieved at the end of this career path.'
    )
    description = fields.Text(string='Path Description')
    active = fields.Boolean(string='Active', default=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Approval'),
        ('approved', 'Approved'),
    ], string='Status', default='draft', tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    node_ids = fields.One2many('hr.career.path.node', 'career_path_id', string='Career Steps')
    node_count = fields.Integer(string='Steps', compute='_compute_node_count')
    is_creator = fields.Boolean(string='Is Creator', compute='_compute_is_creator')

    @api.constrains('anchor_job_id', 'track_type', 'active')
    def _check_unique_career_path(self):
        for rec in self:
            if not rec.anchor_job_id or not rec.active:
                continue
            existing = self.search([
                ('id', '!=', rec.id),
                ('anchor_job_id', '=', rec.anchor_job_id.id),
                ('track_type', '=', rec.track_type),
                ('active', '=', True),
            ], limit=1)
            if existing:
                track_label = dict(rec._fields['track_type'].selection).get(rec.track_type, rec.track_type)
                raise ValidationError(_(
                    "Duplicate Career Path: An active Career Path for Starting Role '%(role)s' in '%(track)s' already exists (Path: '%(name)s', Status: %(status)s)."
                ) % {
                    'role': rec.anchor_job_id.name,
                    'track': track_label,
                    'name': existing.name,
                    'status': dict(existing._fields['state'].selection).get(existing.state, existing.state),
                })

    @api.onchange('anchor_job_id')
    def _onchange_anchor_job_id(self):
        for rec in self:
            for node in rec.node_ids:
                node.previous_job_id = rec.anchor_job_id

    @api.depends('node_ids.target_job_id', 'node_ids.sequence')
    def _compute_final_job_id(self):
        for rec in self:
            if rec.node_ids:
                sorted_nodes = rec.node_ids.sorted('sequence')
                rec.final_job_id = sorted_nodes[-1].target_job_id
            else:
                rec.final_job_id = False

    @api.depends('node_ids')
    def _compute_node_count(self):
        for rec in self:
            rec.node_count = len(rec.node_ids)

    @api.depends_context('uid')
    def _compute_is_creator(self):
        is_admin = self.env.is_superuser() or self.env.is_admin() or self.env.user._is_admin() or self.env.user.id in (1, 2)
        for rec in self:
            # System Administrators / Superusers are not restricted by Maker-Checker for testing and administration
            rec.is_creator = False if is_admin else bool(rec.create_uid and rec.create_uid == self.env.user)

    def action_view_visualizer(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'career_path_visualizer',
            'name': _('Career Map - %s') % self.name,
            'context': {
                'active_career_path_id': self.id,
                'default_career_path_id': self.id,
            }
        }

    def action_open_career_map(self):
        '''Open Career Map visualizer for the starting role (anchor_job_id) of this path.'''
        self.ensure_one()
        if self.anchor_job_id:
            return self.anchor_job_id.action_open_career_map()
        return self.action_view_visualizer()

    def action_submit(self):
        for rec in self:
            if not rec.node_ids:
                raise ValidationError(_('Add at least one career step before submitting for approval.'))
            existing_approved = self.search([
                ('id', '!=', rec.id),
                ('anchor_job_id', '=', rec.anchor_job_id.id),
                ('track_type', '=', rec.track_type),
                ('state', '=', 'approved'),
                ('active', '=', True),
            ], limit=1)
            if existing_approved:
                raise ValidationError(_(
                    "Cannot submit: An approved Career Path '%s' already exists for Starting Role '%s' under this track."
                ) % (existing_approved.name, rec.anchor_job_id.name))
            rec.with_context(force_write=True).write({'state': 'submitted'})
            rec.message_post(body=_('Career Path %s submitted for approval.') % rec.name)

    def action_approve(self):
        for rec in self:
            # Maker-Checker Rule: creator cannot self-approve (System Admins / Superusers can override)
            is_admin = self.env.is_superuser() or self.env.is_admin() or self.env.user._is_admin() or self.env.user.id in (1, 2)
            if rec.create_uid == self.env.user and not is_admin:
                raise ValidationError(
                    _("Maker-Checker Violation: You cannot approve a Career Path that you created. "
                      "Another PPDD Manager must review and approve it.")
                )
            if not rec.node_ids:
                raise ValidationError(_('Add at least one career step before approving.'))
            existing_approved = self.search([
                ('id', '!=', rec.id),
                ('anchor_job_id', '=', rec.anchor_job_id.id),
                ('track_type', '=', rec.track_type),
                ('state', '=', 'approved'),
                ('active', '=', True),
            ], limit=1)
            if existing_approved:
                raise ValidationError(_(
                    "Cannot approve: An approved Career Path '%s' already exists for Starting Role '%s' under this track."
                ) % (existing_approved.name, rec.anchor_job_id.name))
            rec.with_context(force_write=True).write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('Career Path %s approved by %s.') % (rec.name, self.env.user.name))

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state == 'approved':
                raise ValidationError(_("You cannot reset an approved Career Path to draft."))
            rec.with_context(force_write=True).write({
                'state': 'draft',
                'approved_by_id': False,
                'approval_date': False,
            })
            rec.message_post(body=_('Career Path %s reset to draft.') % rec.name)

    def _get_career_map_job_ids(self):
        """Return the set of hr.job IDs referenced by these career paths or their nodes."""
        job_ids = set()
        for rec in self:
            if rec.anchor_job_id:
                job_ids.add(rec.anchor_job_id.id)
            job_ids.update(rec.node_ids._get_career_map_job_ids())
        return job_ids

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env['hr.job']._recompute_career_map_status(records._get_career_map_job_ids())
        return records

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state == 'approved' and not force_write and not self.env.su:
                locked_fields = {'anchor_job_id', 'track_type', 'node_ids'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(
                        _("Career Path '%s' is Active/Approved and cannot be structurally modified.") % rec.name
                    )
        status_fields = {'state', 'active', 'anchor_job_id', 'node_ids'}
        before_jobs = self._get_career_map_job_ids() if (set(vals.keys()) & status_fields) else set()
        res = super().write(vals)
        if set(vals.keys()) & status_fields:
            after_jobs = self._get_career_map_job_ids()
            self.env['hr.job']._recompute_career_map_status(before_jobs | after_jobs)
        return res

    def unlink(self):
        job_ids = self._get_career_map_job_ids()
        res = super().unlink()
        self.env['hr.job']._recompute_career_map_status(job_ids)
        return res


class HrCareerPathNode(models.Model):
    """
    Career Path Node (FR-CFW-004, FR-CFW-005).
    Represents a single step or role in the career path with full requirements.
    Each node defines the TARGET job position and all the requirements
    an employee must meet to be eligible for that target role.
    """
    _name = 'hr.career.path.node'
    _description = 'Career Step'
    _order = 'career_path_id, sequence'
    _rec_name = 'target_job_id'

    career_path_id = fields.Many2one('hr.career.path', string='Career Path',
                                      required=True, ondelete='cascade')
    parent_id = fields.Many2one('hr.career.path.node', string='Previous Step',
                                domain="[('career_path_id', '=', career_path_id)]",
                                ondelete='restrict', index=True,
                                help='Optional: If left empty, it will automatically branch from the Starting Role.')
    child_ids = fields.One2many('hr.career.path.node', 'parent_id', string='Next Steps')
    sequence = fields.Integer(string='Step Sequence', default=10)
    target_job_id = fields.Many2one('hr.job', string='To Role',
                                     domain="[('grade', '!=', False)]",
                                     required=True, ondelete='restrict',
                                     help='The job position an employee is aiming to reach via this step.')

    # Filtered list of hr.job IDs whose grade is equal to or above the anchor
    # job's grade — used as a domain on target_job_id in the view so that only
    # promotion-eligible or lateral positions are selectable.
    valid_target_job_ids = fields.Many2many(
        'hr.job',
        compute='_compute_valid_target_job_ids',
        string='Valid Target Jobs',
    )

    @api.depends('previous_job_id', 'career_path_id.anchor_job_id', 'movement_type')
    def _compute_valid_target_job_ids(self):
        all_graded_jobs = self.env['hr.job'].search([('grade', '!=', False)])
        for rec in self:
            from_job = rec.previous_job_id or (rec.career_path_id and rec.career_path_id.anchor_job_id)
            from_grade = getattr(from_job, 'grade', False) if from_job else False
            if not from_grade:
                # If no grade on From Role, display only graded positions except from_job
                rec.valid_target_job_ids = [(6, 0, [j.id for j in all_graded_jobs if not from_job or j.id != from_job.id])]
                continue

            from_lvl = from_grade.get_grade_level_num()
            if not from_lvl:
                rec.valid_target_job_ids = [(6, 0, [j.id for j in all_graded_jobs if not from_job or j.id != from_job.id])]
                continue

            valid_ids = []
            for job in all_graded_jobs:
                if from_job and job.id == from_job.id:
                    continue  # Can't move to the exact same position
                job_grade = getattr(job, 'grade', False)
                if not job_grade:
                    continue
                job_lvl = job_grade.get_grade_level_num()
                if not job_lvl:
                    continue

                if rec.movement_type in ('vertical', 'promotion'):
                    # Promotion: strictly higher grade (target_lvl > from_lvl).
                    # Positions with same grade or lower grade are NOT displayed.
                    if job_lvl > from_lvl:
                        valid_ids.append(job.id)
                elif rec.movement_type == 'lateral':
                    # Lateral: ONLY positions with the EXACT SAME GRADE as From Role (target_lvl == from_lvl).
                    if job_lvl == from_lvl:
                        valid_ids.append(job.id)
                elif rec.movement_type == 'dual':
                    # Dual-Career: same grade or higher
                    if job_lvl >= from_lvl:
                        valid_ids.append(job.id)
                else:
                    if job_lvl >= from_lvl:
                        valid_ids.append(job.id)

            rec.valid_target_job_ids = [(6, 0, valid_ids)]

    @api.onchange('movement_type', 'previous_job_id', 'career_path_id')
    def _onchange_movement_type_or_from_role(self):
        self._compute_valid_target_job_ids()
        if self.target_job_id and self.valid_target_job_ids:
            if self.target_job_id.id not in self.valid_target_job_ids.ids:
                self.target_job_id = False
        return {
            'domain': {
                'target_job_id': [('id', 'in', self.valid_target_job_ids.ids), ('grade', '!=', False)]
            }
        }

    movement_type = fields.Selection([
        ('vertical', 'Promotion'),
        ('lateral', 'Lateral Transfer'),
        ('dual', 'Dual-Career (Expert Track)'),
    ], string='Movement Type', default='vertical', required=True)

    # --- Reused Job Profile Data ---
    job_description = fields.Html(related='target_job_id.description', string="Job Description", readonly=True)
    competencies_id = fields.One2many(related='target_job_id.competencies_id', string="Required Competencies", readonly=True)
    experiance_id = fields.One2many(related='target_job_id.experiance_id', string="Experience Required", readonly=True)

    # --- Progression Rules / Gates ---
    inherited_competencies_html = fields.Html(string='Inherited Required Competencies', compute='_compute_inherited_competencies', store=False)

    @api.depends('target_job_id')
    def _compute_inherited_competencies(self):
        for rec in self:
            html = ''
            if rec.target_job_id:
                # Try to get competencies from competency.role.mapping if it exists (dynamically to avoid hard dependency)
                if 'competency.role.mapping' in self.env:
                    mapping = self.env['competency.role.mapping'].search([('job_position_id', '=', rec.target_job_id.id)], limit=1)
                    if mapping and mapping.line_ids:
                        html += '<div class="table-responsive"><table class="table table-sm table-striped table-bordered mt-2">'
                        html += '<thead class="table-light"><tr>'
                        html += '<th style="width: 40%;"><i class="fa fa-star-o me-2"></i>Competency Name</th>'
                        html += '<th style="width: 30%;"><i class="fa fa-bullseye me-2"></i>Pillar</th>'
                        html += '<th style="width: 30%;"><i class="fa fa-level-up me-2"></i>Required Level</th>'
                        html += '</tr></thead><tbody>'
                        for line in mapping.line_ids:
                            c_name = line.competency_id.name if hasattr(line.competency_id, 'name') else 'Unknown'
                            c_pillar_val = getattr(line.competency_id, 'pillar', None)
                            if c_pillar_val:
                                p_selection = dict(line.competency_id._fields['pillar'].selection)
                                c_pillar = p_selection.get(c_pillar_val, c_pillar_val)
                            else:
                                c_pillar = 'N/A'
                            c_lvl_val = getattr(line, 'required_proficiency', None)
                            if c_lvl_val:
                                selection = dict(line._fields['required_proficiency'].selection)
                                c_lvl = selection.get(c_lvl_val, c_lvl_val)
                            else:
                                c_lvl = 'N/A'
                            bg_color = 'text-bg-secondary'
                            if c_pillar_val == 'core': bg_color = 'text-bg-primary'
                            elif c_pillar_val == 'leadership': bg_color = 'text-bg-warning'
                            elif c_pillar_val == 'technical': bg_color = 'text-bg-success'
                            html += '<tr>'
                            html += f'<td class="align-middle"><strong>{c_name}</strong></td>'
                            html += f'<td class="align-middle"><span class="badge rounded-pill {bg_color}">{c_pillar}</span></td>'
                            html += f'<td class="align-middle"><span class="badge text-bg-info" style="font-size: 0.9em;">{c_lvl}</span></td>'
                            html += '</tr>'
                        html += '</tbody></table></div>'
                    else:
                        html += '<p><i>No competency mapping found for this job position.</i></p>'
                else:
                    html += '<p><i>Competency Management module not installed.</i></p>'
            rec.inherited_competencies_html = html

    min_tenure_years = fields.Float(string='Required Experience', compute='_compute_target_job_reqs', store=True, readonly=False,
                                       help='Minimum time required in the previous role before moving to this node.')
    min_pms_score = fields.Float(string='Minimum PMS Score', compute='_compute_target_job_reqs', store=True, readonly=False,
                                 help='Minimum performance score required to move to this node (from HR Policies on Job Position).')
    required_qualification = fields.Char(string='Required Qualification', compute='_compute_target_job_reqs', store=True, readonly=True)
    def _default_previous_job_id(self):
        default_prev = self.env.context.get('default_previous_job_id') or self.env.context.get('default_anchor_job_id')
        if default_prev:
            return default_prev
        default_path_id = self.env.context.get('default_career_path_id')
        if default_path_id:
            path = self.env['hr.career.path'].browse(default_path_id)
            if path and path.anchor_job_id:
                return path.anchor_job_id.id
        return False

    previous_job_id = fields.Many2one(
        'hr.job', string='From Role',
        domain="[('grade', '!=', False)]",
        compute='_compute_previous_job_id',
        store=True,
        readonly=False,
        precompute=True,
        default=_default_previous_job_id,
        help='The starting job position that the employee moves from for this career step.')

    @api.depends('career_path_id.anchor_job_id')
    def _compute_previous_job_id(self):
        for rec in self:
            if not rec.previous_job_id:
                if rec.career_path_id and rec.career_path_id.anchor_job_id:
                    rec.previous_job_id = rec.career_path_id.anchor_job_id
                else:
                    prev_id = self.env.context.get('default_previous_job_id') or self.env.context.get('default_anchor_job_id')
                    rec.previous_job_id = prev_id if prev_id else False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'previous_job_id' in fields_list and not res.get('previous_job_id'):
            prev_id = self._default_previous_job_id()
            if prev_id:
                res['previous_job_id'] = prev_id
        return res

    @api.onchange('career_path_id')
    def _onchange_career_path_id(self):
        if self.career_path_id and self.career_path_id.anchor_job_id and not self.previous_job_id:
            self.previous_job_id = self.career_path_id.anchor_job_id
        return self._onchange_movement_type_or_from_role()

    @api.onchange('previous_job_id')
    def _onchange_previous_job_id(self):
        if self.previous_job_id and self.career_path_id:
            if self.career_path_id.anchor_job_id and self.previous_job_id == self.career_path_id.anchor_job_id:
                self.parent_id = False
            else:
                parent_node = self.career_path_id.node_ids.filtered(
                    lambda n: n != self and n.target_job_id == self.previous_job_id
                )
                self.parent_id = parent_node[0] if parent_node else False
        return self._onchange_movement_type_or_from_role()

    @api.onchange('target_job_id')
    def _onchange_target_job_id(self):
        if self.target_job_id:
            if hasattr(self.target_job_id, 'minimum_pms_score') and self.target_job_id.minimum_pms_score:
                self.min_pms_score = self.target_job_id.minimum_pms_score
            else:
                self.min_pms_score = 0.0

    @api.depends('target_job_id', 'target_job_id.qualification_id', 'target_job_id.experiance_id', 'target_job_id.minimum_pms_score')
    def _compute_target_job_reqs(self):
        import re
        for rec in self:
            if not rec.target_job_id:
                rec.required_qualification = ''
                rec.min_tenure_years = 0.0
                continue
                
            # 1. Qualification
            if rec.target_job_id.qualification_id:
                quals = rec.target_job_id.qualification_id
                qual_strings = []
                for q in quals:
                    if q.qualification:
                        qual_strings.append(q.qualification.display_name)
                rec.required_qualification = ', '.join(qual_strings)
            else:
                rec.required_qualification = ''
                
            # 2. Experience
            if rec.target_job_id.experiance_id:
                total_exp = 0.0
                for exp in rec.target_job_id.experiance_id:
                    req_num = getattr(exp, 'requirement', 0.0)
                    if req_num > 0:
                        total_exp += req_num
                    else:
                        exp_text = exp.experience.experience if hasattr(exp, 'experience') and hasattr(exp.experience, 'experience') and exp.experience.experience else ''
                        if exp_text:
                            match = re.search(r'\d+(\.\d+)?', str(exp_text))
                            if match:
                                total_exp += float(match.group())
                rec.min_tenure_years = total_exp
            elif hasattr(rec.target_job_id, 'minimum_number_years_in_company') and rec.target_job_id.minimum_number_years_in_company:
                rec.min_tenure_years = rec.target_job_id.minimum_number_years_in_company
            else:
                rec.min_tenure_years = 0.0

            # 3. Minimum PMS Score from HR Policies tab on Job Position
            if hasattr(rec.target_job_id, 'minimum_pms_score') and rec.target_job_id.minimum_pms_score:
                rec.min_pms_score = float(rec.target_job_id.minimum_pms_score)
            else:
                rec.min_pms_score = 0.0

    notes = fields.Text(string='Additional Criteria / Notes')

    @api.constrains('target_job_id', 'previous_job_id', 'career_path_id', 'movement_type')
    def _check_grade_progression_rules(self):
        for rec in self:
            if not rec.target_job_id:
                continue
            from_job = rec.previous_job_id or (rec.career_path_id and rec.career_path_id.anchor_job_id)
            if not from_job:
                continue

            from_grade = getattr(from_job, 'grade', False)
            target_grade = getattr(rec.target_job_id, 'grade', False)

            if not from_grade:
                raise ValidationError(_(
                    "Grade Missing: The From Role '%s' has no grade assigned. "
                    "All positions in a Career Path must have an assigned grade."
                ) % from_job.name)

            if not target_grade:
                raise ValidationError(_(
                    "Grade Missing: The To Role '%s' has no grade assigned. "
                    "All positions in a Career Path must have an assigned grade."
                ) % rec.target_job_id.name)

            from_lvl = from_grade.get_grade_level_num()
            target_lvl = target_grade.get_grade_level_num()

            if not from_lvl or not target_lvl:
                continue

            from_grade_name = from_grade.grade_name or from_grade.grade_code or f"Grade {from_lvl}"
            target_grade_name = target_grade.grade_name or target_grade.grade_code or f"Grade {target_lvl}"

            if rec.movement_type in ('vertical', 'promotion'):
                if target_lvl <= from_lvl:
                    raise ValidationError(_(
                        "Grade Rule Violation (Promotion):\n\n"
                        "A promotion step from '%(from_job)s' (Grade: %(from_grade)s) must move to a higher grade.\n\n"
                        "Selected position '%(target_job)s' has Grade %(target_grade)s, which is not above %(from_grade)s."
                    ) % {
                        'from_job': from_job.name,
                        'from_grade': from_grade_name,
                        'target_job': rec.target_job_id.name,
                        'target_grade': target_grade_name,
                    })
            elif rec.movement_type == 'lateral':
                if target_lvl != from_lvl:
                    raise ValidationError(_(
                        "Grade Rule Violation (Lateral Transfer):\n\n"
                        "A lateral transfer step from '%(from_job)s' (Grade: %(from_grade)s) must be at the EXACT SAME GRADE.\n\n"
                        "Selected position '%(target_job)s' has Grade %(target_grade)s, but must be Grade %(from_grade)s."
                    ) % {
                        'from_job': from_job.name,
                        'from_grade': from_grade_name,
                        'target_job': rec.target_job_id.name,
                        'target_grade': target_grade_name,
                    })

    @api.constrains('career_path_id', 'previous_job_id', 'target_job_id')
    def _check_unique_step(self):
        for rec in self:
            if not rec.career_path_id or not rec.target_job_id:
                continue
            from_role_id = rec.previous_job_id.id or (rec.career_path_id.anchor_job_id.id if rec.career_path_id.anchor_job_id else False)
            for node in rec.career_path_id.node_ids:
                if node.id == rec.id:
                    continue
                node_from_id = node.previous_job_id.id or (rec.career_path_id.anchor_job_id.id if rec.career_path_id.anchor_job_id else False)
                if node_from_id == from_role_id and node.target_job_id.id == rec.target_job_id.id:
                    from_name = rec.previous_job_id.name if rec.previous_job_id else (rec.career_path_id.anchor_job_id.name if rec.career_path_id.anchor_job_id else _('Starting Role'))
                    raise ValidationError(_(
                        "Duplicate Progression Step: A step from '%(from_role)s' to '%(to_role)s' already exists in this Career Path."
                    ) % {
                        'from_role': from_name,
                        'to_role': rec.target_job_id.name,
                    })

    @api.constrains('target_job_id', 'career_path_id')
    def _check_target_not_anchor(self):
        for rec in self:
            if rec.career_path_id and rec.target_job_id and rec.career_path_id.anchor_job_id:
                if rec.target_job_id.id == rec.career_path_id.anchor_job_id.id:
                    raise ValidationError(_(
                        "Logical Error: A Career Step (Target) cannot be the exact same job position as the Path's Anchor (Entry) role. "
                        "An employee cannot be promoted into the role they already hold!"
                    ))

    def _get_career_map_job_ids(self):
        """Return the set of hr.job IDs referenced by these career step nodes."""
        job_ids = set()
        for rec in self:
            if rec.target_job_id:
                job_ids.add(rec.target_job_id.id)
            if rec.previous_job_id:
                job_ids.add(rec.previous_job_id.id)
            if rec.parent_id and rec.parent_id.target_job_id:
                job_ids.add(rec.parent_id.target_job_id.id)
        return job_ids

    def _check_parent_approved(self):
        for rec in self:
            if rec.career_path_id and rec.career_path_id.state == 'approved' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("You cannot modify a step on an Approved/Active Career Path."))

    def write(self, vals):
        self._check_parent_approved()
        if vals.get('movement_type') == 'promotion':
            vals['movement_type'] = 'vertical'
        status_fields = {'target_job_id', 'previous_job_id', 'parent_id', 'career_path_id'}
        before_jobs = self._get_career_map_job_ids() if (set(vals.keys()) & status_fields) else set()
        res = super().write(vals)
        if 'target_job_id' in vals or 'movement_type' in vals:
            self._check_parent_approved()
        if 'previous_job_id' in vals and 'parent_id' not in vals:
            for rec in self:
                if rec.previous_job_id and rec.career_path_id:
                    if rec.career_path_id.anchor_job_id and rec.previous_job_id == rec.career_path_id.anchor_job_id:
                        if rec.parent_id:
                            rec.parent_id = False
                    else:
                        parent_node = rec.career_path_id.node_ids.filtered(
                            lambda n: n != rec and n.target_job_id == rec.previous_job_id
                        )
                        target_parent = parent_node[0] if parent_node else False
                        if rec.parent_id != target_parent:
                            rec.parent_id = target_parent
        if set(vals.keys()) & status_fields:
            after_jobs = self._get_career_map_job_ids()
            self.env['hr.job']._recompute_career_map_status(before_jobs | after_jobs)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('movement_type') == 'promotion':
                vals['movement_type'] = 'vertical'
            path_id = vals.get('career_path_id') or self.env.context.get('default_career_path_id')
            if not vals.get('previous_job_id'):
                if path_id:
                    path = self.env['hr.career.path'].browse(path_id)
                    if path and path.anchor_job_id:
                        vals['previous_job_id'] = path.anchor_job_id.id
                elif self.env.context.get('default_previous_job_id'):
                    vals['previous_job_id'] = self.env.context.get('default_previous_job_id')

            prev_job_id = vals.get('previous_job_id')
            if prev_job_id and 'parent_id' not in vals and path_id:
                path = self.env['hr.career.path'].browse(path_id)
                if path and path.anchor_job_id and prev_job_id == path.anchor_job_id.id:
                    vals['parent_id'] = False
                elif path:
                    parent_node = path.node_ids.filtered(lambda n: n.target_job_id.id == prev_job_id)
                    if parent_node:
                        vals['parent_id'] = parent_node[0].id
        records = super().create(vals_list)
        for rec in records:
            if not rec.parent_id and rec.previous_job_id and rec.career_path_id:
                if rec.career_path_id.anchor_job_id and rec.previous_job_id == rec.career_path_id.anchor_job_id:
                    continue
                parent_node = rec.career_path_id.node_ids.filtered(
                    lambda n: n != rec and n.target_job_id == rec.previous_job_id
                )
                if parent_node:
                    rec.parent_id = parent_node[0]
        records._check_parent_approved()
        self.env['hr.job']._recompute_career_map_status(records._get_career_map_job_ids())
        return records

    def unlink(self):
        self._check_parent_approved()
        job_ids = self._get_career_map_job_ids()
        res = super().unlink()
        self.env['hr.job']._recompute_career_map_status(job_ids)
        return res
