# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools, _


class CompetencyMatrixConfig(models.Model):
    """Configuration model for Proficiency Level Determination and Technical Behavioral Indicators."""
    _name = 'competency.matrix.config'
    _description = 'Competency Proficiency Matrix Configuration'

    name = fields.Char(string='Setting Title', default='Bunna Bank Competency Matrix Configuration', required=True)
    
    # Global Configurable Technical Behavioral Indicators
    tech_indicator_level_1 = fields.Text(
        string='Level 1 (Basic) Technical Behavioral Indicator',
        default="Understands foundational technical concepts. Executes routine tasks under guidance and applies standard operating procedures in daily operations."
    )
    tech_indicator_level_2 = fields.Text(
        string='Level 2 (Intermediate) Technical Behavioral Indicator',
        default="Demonstrates solid working technical knowledge. Balances daily operational responsibilities with active participation in improvement projects and resolves standard technical issues independently."
    )
    tech_indicator_level_3 = fields.Text(
        string='Level 3 (Advanced) Technical Behavioral Indicator',
        default="Demonstrates deep technical expertise. Actively manages complex technical challenges, optimizes workflows, and mentors team members across specialized functional areas."
    )
    tech_indicator_level_4 = fields.Text(
        string='Level 4 (Expert) Technical Behavioral Indicator',
        default="Shapes technical standards and strategic direction at an enterprise level. Designs overall framework governance, drives innovation, and builds institutional capability."
    )

    # 360-Degree Evaluator Weights for Gap Math
    weight_self = fields.Float(string='Self Assessment Weight', default=2.0, required=True)
    weight_peer = fields.Float(string='Peer Assessment Weight', default=1.0, required=True)
    weight_subordinate = fields.Float(string='Subordinate Assessment Weight', default=1.0, required=True)
    weight_supervisor = fields.Float(string='Supervisor Assessment Weight', default=3.0, required=True)
    weight_team = fields.Float(string='Team Assessment Weight', default=0.0, required=True)

    # 360-Degree Random Sampling Caps
    max_peer_assessments = fields.Integer(
        string='Max Peer Assessments Per Evaluator', default=3, required=True,
        help="Maximum number of peer assessments randomly assigned to an evaluator per cycle."
    )
    max_subordinate_assessments = fields.Integer(
        string='Max Subordinate Assessments Per Evaluator', default=2, required=True,
        help="Maximum number of subordinate assessments randomly assigned to an evaluator per cycle."
    )

    # 360-Degree Evaluator Pillar Scope Rules
    peer_eval_core = fields.Boolean(string='Peer: Core Pillar', default=True)
    peer_eval_leadership = fields.Boolean(string='Peer: Leadership Pillar', default=True)
    peer_eval_technical = fields.Boolean(string='Peer: Technical Pillar', default=True)

    subordinate_eval_core = fields.Boolean(string='Subordinate: Core Pillar', default=True)
    subordinate_eval_leadership = fields.Boolean(string='Subordinate: Leadership Pillar', default=True)
    subordinate_eval_technical = fields.Boolean(string='Subordinate: Technical Pillar', default=True)

    supervisor_eval_core = fields.Boolean(string='Supervisor: Core Pillar', default=True)
    supervisor_eval_leadership = fields.Boolean(string='Supervisor: Leadership Pillar', default=True)
    supervisor_eval_technical = fields.Boolean(string='Supervisor: Technical Pillar', default=True)

    team_eval_core = fields.Boolean(string='Team: Core Pillar', default=True)
    team_eval_leadership = fields.Boolean(string='Team: Leadership Pillar', default=True)
    team_eval_technical = fields.Boolean(string='Team: Technical Pillar', default=True)

    self_eval_core = fields.Boolean(string='Self: Core Pillar', default=True)
    self_eval_leadership = fields.Boolean(string='Self: Leadership Pillar', default=True)
    self_eval_technical = fields.Boolean(string='Self: Technical Pillar', default=True)

    def get_allowed_pillars_for_type(self, assessment_type):
        """Return list of allowed pillars ('core', 'leadership', 'technical') for an assessment type
        based strictly on the configured boolean flags in matrix configuration.
        """
        config = self if self else self.get_active_config()
        config = config[0] if config else False
        if not config:
            return ['core', 'leadership', 'technical']

        prefix_map = {
            'self': 'self_eval_',
            'peer': 'peer_eval_',
            'subordinate': 'subordinate_eval_',
            'supervisor': 'supervisor_eval_',
            'team': 'team_eval_',
        }
        prefix = prefix_map.get(assessment_type, 'self_eval_')
        allowed = []
        for pillar in ['core', 'leadership', 'technical']:
            field_name = f"{prefix}{pillar}"
            if getattr(config, field_name, True):
                allowed.append(pillar)

        return allowed

    grade_matrix_line_ids = fields.One2many(
        'competency.grade.matrix', 'config_id', string='Job Grade Proficiency Matrix'
    )
    job_matrix_line_ids = fields.One2many(
        'competency.job.matrix', 'config_id', string='Job Position Proficiency Matrix'
    )
    grade_matrix_count = fields.Integer(string='Job Grade Guidelines Count', compute='_compute_matrix_counts')
    job_matrix_count = fields.Integer(string='Job Position Guidelines Count', compute='_compute_matrix_counts')

    def _compute_matrix_counts(self):
        for rec in self:
            rec.grade_matrix_count = len(rec.grade_matrix_line_ids)
            rec.job_matrix_count = len(rec.job_matrix_line_ids)

    def action_view_job_matrix(self):
        self.ensure_one()
        action = self.env.ref('competency_management.action_competency_job_matrix').read()[0]
        action['domain'] = [('config_id', '=', self.id)]
        action['context'] = {'default_config_id': self.id}
        return action

    def action_view_grade_matrix(self):
        self.ensure_one()
        action = self.env.ref('competency_management.action_competency_grade_matrix').read()[0]
        action['domain'] = [('config_id', '=', self.id)]
        action['context'] = {'default_config_id': self.id}
        return action

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        self.env.registry.clear_cache()
        weight_fields = {'weight_self', 'weight_peer', 'weight_subordinate', 'weight_supervisor', 'weight_team'}
        if set(vals.keys()) & weight_fields:
            all_lines = self.env['competency.assessment.line'].sudo().search([])
            all_lines.with_context(skip_360_recompute=True)._compute_360_ratings()
        return res

    @api.model
    @tools.ormcache()
    def _get_active_config_id(self):
        """Return cached ID of singleton active matrix configuration record."""
        config = self.search([], limit=1)
        if not config:
            config = self.create({'name': 'Bunna Bank Competency Matrix Configuration'})
        return config.id

    @api.model
    def get_active_config(self):
        """Helper to return singleton active matrix configuration record bound to current environment."""
        config_id = self._get_active_config_id()
        config = self.browse(config_id)
        if not config.exists():
            self.env.registry.clear_cache()
            config_id = self._get_active_config_id()
            config = self.browse(config_id)
        return config

    @api.model
    def action_open_matrix_guidelines(self):
        """Action: Open Proficiency Matrix Guidelines form view dynamically for active singleton config."""
        config = self.get_active_config()
        view_id = self.env.ref('competency_management.view_competency_matrix_config_form').id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Proficiency Matrix Guidelines'),
            'res_model': 'competency.matrix.config',
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'res_id': config.id,
            'target': 'current',
        }

    @api.model
    def action_open_360_rules(self):
        """Action: Open Global Behavioral & 360° Rules form view dynamically for active singleton config."""
        config = self.get_active_config()
        view_id = self.env.ref('competency_management.view_competency_360_config_form').id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Behavioral & 360° Assessment Rules'),
            'res_model': 'competency.matrix.config',
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'res_id': config.id,
            'target': 'current',
        }


class CompetencyGradeMatrix(models.Model):
    """Proficiency Level Requirements per Job Grade."""
    _name = 'competency.grade.matrix'
    _description = 'Job Grade Proficiency Requirement Matrix'
    _order = 'grade_id'

    config_id = fields.Many2one('competency.matrix.config', string='Matrix Config', required=True, ondelete='cascade')
    grade_id = fields.Many2one('employee.grade', string='Job Grade', required=True)
    grade_name = fields.Char(related='grade_id.grade_name', string='Grade Name', readonly=True)

    required_core_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Core Competency Level', required=True, default='2')

    required_leadership_level = fields.Selection([
        ('0', 'Not Applicable'),
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Leadership Competency Level', required=True, default='1')

    required_technical_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Technical Competency Level', required=True, default='3')


class CompetencyJobMatrix(models.Model):
    """Proficiency Level Requirements per Job Position."""
    _name = 'competency.job.matrix'
    _description = 'Job Position Proficiency Requirement Matrix'
    _order = 'job_id'

    config_id = fields.Many2one('competency.matrix.config', string='Matrix Config', required=True, ondelete='cascade')
    job_id = fields.Many2one('hr.job', string='Job Position', required=True)
    job_name = fields.Char(related='job_id.name', string='Position Title', readonly=True)

    required_core_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Core Competency Level', required=True, default='2')

    required_leadership_level = fields.Selection([
        ('0', 'Not Applicable'),
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Leadership Competency Level', required=True, default='1')

    required_technical_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Technical Competency Level', required=True, default='3')
