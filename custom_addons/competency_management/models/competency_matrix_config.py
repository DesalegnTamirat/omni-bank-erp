# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools, _


class CompetencyMatrixConfig(models.Model):
    """Configuration model for Proficiency Level Determination and Technical Behavioral Indicators."""
    _name = 'competency.matrix.config'
    _description = 'Competency Proficiency Matrix Configuration'

    name = fields.Char(string='Setting Title', default='Bunna Bank Competency Matrix Configuration', required=True)
    
    proficiency_determinant = fields.Selection([
        ('job_grade', 'By Job Grade (Grade-Based Guidelines)'),
        ('job_position', 'By Job Position (Role-Based Guidelines)'),
    ], string='Proficiency Level Determinant Mode', required=True, default='job_grade',
       help="Select whether required competency proficiency levels are governed by Job Grade or Job Position.")

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
        """Return list of allowed pillars ('core', 'leadership', 'technical') for an assessment type."""
        self.ensure_one()
        pillars = []
        prefix = assessment_type if assessment_type in ('peer', 'subordinate', 'supervisor', 'team', 'self') else 'self'
        
        if getattr(self, f'{prefix}_eval_core', True):
            pillars.append('core')
        if getattr(self, f'{prefix}_eval_leadership', True):
            pillars.append('leadership')
        if getattr(self, f'{prefix}_eval_technical', True):
            pillars.append('technical')
            
        return pillars or ['core', 'leadership', 'technical']

    grade_matrix_line_ids = fields.One2many(
        'competency.grade.matrix', 'config_id', string='Job Grade Proficiency Matrix'
    )
    job_matrix_line_ids = fields.One2many(
        'competency.job.matrix', 'config_id', string='Job Position Proficiency Matrix'
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        self.env.registry.clear_cache()
        return res

    @api.model
    def get_active_config(self):
        """Helper to return singleton active matrix configuration record."""
        config_id = self._get_active_config_id()
        return self.browse(config_id)

    @api.model
    @tools.ormcache()
    def _get_active_config_id(self):
        """Helper to get/cache the ID of the active matrix configuration."""
        config = self.search([], limit=1)
        if not config:
            config = self.create({'name': 'Bunna Bank Competency Matrix Configuration'})
        if not config.grade_matrix_line_ids or not config.job_matrix_line_ids:
            config._seed_matrix_guidelines()
        return config.id

    def _seed_matrix_guidelines(self):
        """Pre-populate Job Grade Matrix Guidelines and Job Position Matrix Guidelines."""
        self.ensure_one()
        
        # 1. SEED JOB GRADE MATRIX
        existing_grade_ids = self.grade_matrix_line_ids.mapped('grade_id.id')
        all_grades = self.env['employee.grade'].search([])
        
        grade_vals = []
        for grade in all_grades:
            if grade.id in existing_grade_ids:
                continue
            code_upper = (grade.grade_code or '').upper().strip()
            name_upper = (grade.grade_name or '').upper().strip()
            full_str = f"{code_upper} {name_upper}"
            
            # Grades XVII to XVIII (Executive)
            if 'XVIII' in full_str or 'XVII' in full_str:
                core, lead, tech = '4', '4', '4'
            # Grades XIV to XVI (Managerial)
            elif 'XVI' in full_str or 'XV' in full_str or 'XIV' in full_str:
                core, lead, tech = '3', '3', '3'
            # Grades X to XIII (Senior Officers / Specialists)
            elif 'XIII' in full_str or 'XII' in full_str or 'XI' in full_str or 'X' in full_str:
                core, lead, tech = '3', '2', '3'
            # Grades VI to IX (Clerical / Officers)
            elif 'IX' in full_str or 'VIII' in full_str or 'VII' in full_str or 'VI' in full_str:
                core, lead, tech = '2', '1', '2'
            # Grades I to V (Support / Non-Clerical)
            elif 'V' in full_str or 'IV' in full_str or 'III' in full_str or 'II' in full_str or 'I' in full_str:
                core, lead, tech = '1', '0', '1'
            else:
                core, lead, tech = '2', '1', '2'

            grade_vals.append({
                'config_id': self.id,
                'grade_id': grade.id,
                'required_core_level': core,
                'required_leadership_level': lead,
                'required_technical_level': tech,
            })
            
        if grade_vals:
            self.env['competency.grade.matrix'].create(grade_vals)

        # 2. SEED JOB POSITION MATRIX
        existing_job_ids = self.job_matrix_line_ids.mapped('job_id.id')
        all_jobs = self.env['hr.job'].search([])
        
        job_vals = []
        for job in all_jobs:
            if job.id in existing_job_ids:
                continue
            title_lower = (job.name or '').lower()
            
            if any(k in title_lower for k in ['director', 'chief', 'vice president', 'president', 'executive', 'head']):
                core, lead, tech = '4', '4', '4'
            elif any(k in title_lower for k in ['manager', 'supervisor', 'lead', 'principal']):
                core, lead, tech = '3', '3', '3'
            elif any(k in title_lower for k in ['senior', 'specialist', 'expert', 'analyst', 'auditor', 'engineer']):
                core, lead, tech = '3', '2', '3'
            elif any(k in title_lower for k in ['officer', 'associate', 'representative', 'accountant']):
                core, lead, tech = '2', '1', '2'
            elif any(k in title_lower for k in ['junior', 'assistant', 'clerk', 'cashier', 'teller']):
                core, lead, tech = '2', '0', '2'
            elif any(k in title_lower for k in ['driver', 'messenger', 'janitor', 'guard', 'attendant', 'technician']):
                core, lead, tech = '1', '0', '1'
            else:
                core, lead, tech = '2', '1', '2'

            job_vals.append({
                'config_id': self.id,
                'job_id': job.id,
                'required_core_level': core,
                'required_leadership_level': lead,
                'required_technical_level': tech,
            })
            
        if job_vals:
            self.env['competency.job.matrix'].create(job_vals)


class CompetencyGradeMatrix(models.Model):
    """Proficiency Level Requirements per Job Grade."""
    _name = 'competency.grade.matrix'
    _description = 'Job Grade Proficiency Requirement Matrix'
    _order = 'grade_id'

    config_id = fields.Many2one('competency.matrix.config', string='Matrix Config', ondelete='cascade')
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

    config_id = fields.Many2one('competency.matrix.config', string='Matrix Config', ondelete='cascade')
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
