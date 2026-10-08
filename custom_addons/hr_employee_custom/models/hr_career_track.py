# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrCareerTrack(models.Model):
    """
    Career Track (FR-CFW-001, FR-CFW-002).
    Represents the overarching career channel an employee follows.
    e.g., Managerial Track, Technical/Specialist Track, Value-Stream Track.
    """
    _name = 'hr.career.track'
    _description = 'Career Track'
    _inherit = ['mail.thread']
    _order = 'sequence'

    name = fields.Char(string='Career Track Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    track_type = fields.Selection([
        ('managerial', 'Managerial / Leadership Track'),
        ('technical', 'Technical / Professional Track'),
        ('value_stream', 'Value-Stream / Operational Track'),
    ], string='Track Type', required=True, default='technical', tracking=True)
    description = fields.Html(string='Description', help="Detailed description of this career track")
    active = fields.Boolean(string='Active', default=True)
    career_path_ids = fields.One2many('hr.career.path', 'track_id', string='Career Paths')
    career_path_count = fields.Integer(string='Career Paths', compute='_compute_career_path_count')

    @api.depends('career_path_ids')
    def _compute_career_path_count(self):
        for rec in self:
            rec.career_path_count = len(rec.career_path_ids)

    def action_view_career_paths(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Career Paths: %s') % self.name,
            'res_model': 'hr.career.path',
            'view_mode': 'list,form',
            'domain': [('track_id', '=', self.id)],
            'context': {'default_track_id': self.id},
        }


class HrCareerPath(models.Model):
    """
    Career Path (FR-CFW-003, FR-CFW-004).
    A named career path under a track, anchored to a specific starting Job Position.
    e.g., 'Branch Operations Track' anchored at 'Teller' job position.
    """
    _name = 'hr.career.path'
    _description = 'Career Path'
    _inherit = ['mail.thread']
    _order = 'track_id, name'
    _rec_name = 'name'

    name = fields.Char(string='Career Path Name', required=True, translate=True)
    track_id = fields.Many2one('hr.career.track', string='Career Track', required=True,
                                ondelete='restrict')
    anchor_job_id = fields.Many2one('hr.job', string='Position',
                                     required=True, tracking=True,
                                     help='The entry-level job position where this career path begins.')
    description = fields.Text(string='Path Description')
    active = fields.Boolean(string='Active', default=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Approval'),
        ('approved', 'Approved'),
        ('archived', 'Archived'),
    ], string='Status', default='draft', tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    node_ids = fields.One2many('hr.career.path.node', 'career_path_id', string='Career Steps')
    node_count = fields.Integer(string='Steps', compute='_compute_node_count')

    @api.depends('node_ids')
    def _compute_node_count(self):
        for rec in self:
            rec.node_count = len(rec.node_ids)

    def action_submit(self):
        for rec in self:
            if not rec.node_ids:
                raise ValidationError(_('Add at least one career step before submitting.'))
            rec.with_context(force_write=True).write({'state': 'submitted'})
            rec.message_post(body=_('Career Path %s submitted for approval.') % rec.name)

    def action_approve(self):
        for rec in self:
            if not rec.node_ids:
                raise ValidationError(_('Add at least one career step before approving.'))
            rec.with_context(force_write=True).write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('Career Path %s approved.') % rec.name)

    def action_archive(self):
        self.with_context(force_write=True).write({'state': 'archived', 'active': False})

    def action_reset_to_draft(self):
        self.with_context(force_write=True).write({'state': 'draft'})

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state in ('approved', 'submitted') and not force_write and not self.env.su:
                locked_fields = {'anchor_job_id', 'track_id', 'node_ids'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(
                        _("Career Path '%s' is %s and cannot be structurally modified. "
                          "Please reset to draft to edit.") % (rec.name, rec.state)
                    )
        return super().write(vals)


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
    target_job_id = fields.Many2one('hr.job', string='Target Job Position',
                                     required=True, ondelete='restrict',
                                     help='The job position an employee is aiming to reach via this step.')
    movement_type = fields.Selection([
        ('vertical', 'Vertical (Promotion)'),
        ('lateral', 'Lateral (Transfer)'),
        ('dual', 'Dual-Career (Expert Track)'),
    ], string='Movement Type', default='vertical', required=True)

    # --- Reused Job Profile Data ---
    job_description = fields.Html(related='target_job_id.description', string="Job Description", readonly=True)
    competencies_id = fields.One2many(related='target_job_id.competencies_id', string="Required Competencies", readonly=True)
    experiance_id = fields.One2many(related='target_job_id.experiance_id', string="Experience Required", readonly=True)

    # --- Progression Rules / Gates ---
    inherited_competencies_html = fields.Html(string='Required Competencies', compute='_compute_inherited_competencies', store=False)

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

    min_tenure_years = fields.Float(string='Minimum Experience (Years)', default=0.0,
                                       help='Minimum time required in the previous role before moving to this node.')
    min_pms_score = fields.Float(string='Minimum PMS Score', default=3.5,
                                 help='Minimum performance score required to move to this node.')
    required_qualification = fields.Char(string='Required Qualification', compute='_compute_target_job_reqs', store=True)
    previous_job_id = fields.Many2one('hr.job', string='Previous Role', compute='_compute_previous_job_id', store=False)

    @api.depends('parent_id', 'career_path_id.anchor_job_id')
    def _compute_previous_job_id(self):
        for rec in self:
            if rec.parent_id:
                rec.previous_job_id = rec.parent_id.target_job_id
            else:
                rec.previous_job_id = rec.career_path_id.anchor_job_id

    @api.depends('target_job_id', 'target_job_id.qualification_id')
    def _compute_target_job_reqs(self):
        for rec in self:
            if rec.target_job_id:
                quals = rec.target_job_id.qualification_id
                if quals:
                    qual_strings = []
                    for q in quals:
                        if hasattr(q, 'qualification'):
                            val = q.qualification
                            if hasattr(val, 'qualification'):
                                qual_strings.append(val.qualification)
                            elif isinstance(val, str):
                                qual_strings.append(val)
                    rec.required_qualification = ', '.join(filter(None, qual_strings))
                else:
                    rec.required_qualification = ''
            else:
                rec.required_qualification = ''

    @api.onchange('target_job_id')
    def _onchange_target_job_id_exp(self):
        if self.target_job_id and hasattr(self.target_job_id, 'minimum_number_years_in_company'):
            self.min_tenure_years = self.target_job_id.minimum_number_years_in_company
        else:
            self.min_tenure_years = 0.0

    notes = fields.Text(string='Additional Criteria / Notes')

    @api.constrains('target_job_id', 'career_path_id')
    def _check_target_not_anchor(self):
        for rec in self:
            if rec.career_path_id and rec.target_job_id and rec.career_path_id.anchor_job_id:
                if rec.target_job_id.id == rec.career_path_id.anchor_job_id.id:
                    raise ValidationError(_(
                        "Logical Error: A Career Step (Target) cannot be the exact same job position as the Path's Anchor (Entry) role. "
                        "An employee cannot be promoted into the role they already hold!"
                    ))

    def _check_parent_approved(self):
        for rec in self:
            if rec.career_path_id and rec.career_path_id.state == 'approved' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("You cannot modify a step on an Approved Career Path. Please Reset the Career Path to Draft first."))

    def write(self, vals):
        self._check_parent_approved()
        res = super().write(vals)
        if 'target_job_id' in vals or 'movement_type' in vals:
            self._check_parent_approved()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_parent_approved()
        return records

    def unlink(self):
        self._check_parent_approved()
        return super().unlink()

