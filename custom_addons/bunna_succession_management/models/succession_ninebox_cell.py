# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SuccessionNineboxConfiguration(models.Model):
    """
    Unified 9-Box Matrix Configuration Model.
    Holds the 9 Matrix Cell Definitions for intuitive HR administration.
    """
    _name = 'succession.ninebox.configuration'
    _description = '9-Box Matrix Unified Configuration'

    name = fields.Char(default='9-Box Matrix Configuration', required=True, index=True)

    cell_ids = fields.One2many(
        'succession.ninebox.cell',
        'matrix_config_id',
        string='Matrix Cells'
    )

    @api.model
    def get_config(self):
        config = self.search([], limit=1)
        if not config:
            config = self.create({'name': '9-Box Matrix Configuration'})
        self.env['succession.ninebox.cell']._ensure_default_cells(config)
        return config




class SuccessionNineboxCell(models.Model):
    """
    9-Box Grid Cell Configuration Model.
    Defines cell labels, qualification score ranges (PMS and Competency Match %),
    and recommended HR actions for each of the 9 matrix intersections.
    """
    _name = 'succession.ninebox.cell'
    _description = 'Succession 9-Box Cell Definition'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)

    matrix_config_id = fields.Many2one(
        'succession.ninebox.configuration',
        string='Matrix Configuration',
        ondelete='cascade',
        index=True
    )

    potential_rating = fields.Selection([
        ('low', 'Low Potential'),
        ('medium', 'Medium Potential'),
        ('high', 'High Potential'),
    ], string='Potential Level', required=True, index=True)

    performance_rating = fields.Selection([
        ('low', 'Low Performance'),
        ('medium', 'Medium Performance'),
        ('high', 'High Performance'),
    ], string='Performance Level', required=True, index=True)

    name = fields.Char(string='Cell Display Label', required=True, translate=True)
    description = fields.Text(string='Recommended HR Strategy & Guidance')

    # Numerical qualification boundaries defined directly per box
    min_pms_score = fields.Float(
        string='Min PMS Score',
        default=0.0,
        help="Minimum Performance Appraisal score (PMS) required to qualify for this box."
    )
    max_pms_score = fields.Float(
        string='Max PMS Score',
        default=100.0,
        help="Maximum Performance Appraisal score (PMS) for this box."
    )
    min_potential_match = fields.Float(
        string='Min Potential Match (%)',
        default=0.0,
        help="Minimum Job Competency Match % required to qualify for this box."
    )
    max_potential_match = fields.Float(
        string='Max Potential Match (%)',
        default=100.0,
        help="Maximum Job Competency Match % for this box."
    )

    tier_color = fields.Selection([
        ('gold', 'Gold / Green'),
        ('teal', 'Teal / Blue'),
        ('brick', 'Brick / Red'),
        ('purple', 'Royal Purple'),
        ('amber', 'Amber / Yellow'),
        ('slate', 'Slate / Gray'),
    ], string='Color Tier', default='teal')

    color_hex = fields.Char(string='Custom Hex Color', default='#06B6D4')
    priority = fields.Selection([
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('urgent', 'Urgent'),
    ], string='Succession Priority', default='medium')
    is_high_potential = fields.Boolean(string='High Potential Flag', default=False)
    is_watchlist = fields.Boolean(string='Watchlist / Alert Flag', default=False)

    _perf_pot_unique = models.Constraint(
        'unique(performance_rating, potential_rating)',
        'A cell definition already exists for this Performance and Potential combination!',
    )

    @api.model
    def _ensure_default_cells(self, config):
        """Ensures that all 9 matrix cells exist with standard non-overlapping definitions."""
        default_cells_data = [
            {
                'sequence': 10,
                'potential_rating': 'high',
                'performance_rating': 'high',
                'name': 'Star Performer',
                'tier_color': 'gold',
                'min_pms_score': 85.0,
                'max_pms_score': 100.0,
                'min_potential_match': 80.0,
                'max_potential_match': 100.0,
                'description': 'High Potential & High Performance: Primary successors for critical leadership roles. Prioritize executive coaching and retention.',
            },
            {
                'sequence': 20,
                'potential_rating': 'high',
                'performance_rating': 'medium',
                'name': 'High Potential',
                'tier_color': 'teal',
                'min_pms_score': 70.0,
                'max_pms_score': 84.99,
                'min_potential_match': 80.0,
                'max_potential_match': 100.0,
                'description': 'High Potential & Medium Performance: Emerging leaders. Provide stretch assignments and operational coaching to accelerate performance.',
            },
            {
                'sequence': 30,
                'potential_rating': 'high',
                'performance_rating': 'low',
                'name': 'Rough Diamond',
                'tier_color': 'teal',
                'min_pms_score': 0.0,
                'max_pms_score': 69.99,
                'min_potential_match': 80.0,
                'max_potential_match': 100.0,
                'description': 'High Potential & Low Performance: High natural capability but unproven performance. Investigate barriers, onboarding, or role fit.',
            },
            {
                'sequence': 40,
                'potential_rating': 'medium',
                'performance_rating': 'high',
                'name': 'High Performer',
                'tier_color': 'teal',
                'min_pms_score': 85.0,
                'max_pms_score': 100.0,
                'min_potential_match': 60.0,
                'max_potential_match': 79.99,
                'description': 'Medium Potential & High Performance: Strong individual contributors. Broaden leadership exposure and lateral career moves.',
            },
            {
                'sequence': 50,
                'potential_rating': 'medium',
                'performance_rating': 'medium',
                'name': 'Core Employee',
                'tier_color': 'teal',
                'min_pms_score': 70.0,
                'max_pms_score': 84.99,
                'min_potential_match': 60.0,
                'max_potential_match': 79.99,
                'description': 'Medium Potential & Medium Performance: Steady, reliable backbone contributors. Support capability development.',
            },
            {
                'sequence': 60,
                'potential_rating': 'medium',
                'performance_rating': 'low',
                'name': 'Inconsistent',
                'tier_color': 'brick',
                'min_pms_score': 0.0,
                'max_pms_score': 69.99,
                'min_potential_match': 60.0,
                'max_potential_match': 79.99,
                'description': 'Medium Potential & Low Performance: Inconsistent output. Clarify KPIs, conduct performance reviews, and establish development goals.',
            },
            {
                'sequence': 70,
                'potential_rating': 'low',
                'performance_rating': 'high',
                'name': 'Solid Professional',
                'tier_color': 'teal',
                'min_pms_score': 85.0,
                'max_pms_score': 100.0,
                'min_potential_match': 0.0,
                'max_potential_match': 59.99,
                'description': 'Low Potential & High Performance: Exceptional functional experts with limited desire or readiness for larger executive scope.',
            },
            {
                'sequence': 80,
                'potential_rating': 'low',
                'performance_rating': 'medium',
                'name': 'Solid Contributor',
                'tier_color': 'brick',
                'min_pms_score': 70.0,
                'max_pms_score': 84.99,
                'min_potential_match': 0.0,
                'max_potential_match': 59.99,
                'description': 'Low Potential & Medium Performance: Solid performer in current position with limited scope for advancement. Maintain engagement.',
            },
            {
                'sequence': 90,
                'potential_rating': 'low',
                'performance_rating': 'low',
                'name': 'Underperformer',
                'tier_color': 'brick',
                'min_pms_score': 0.0,
                'max_pms_score': 69.99,
                'min_potential_match': 0.0,
                'max_potential_match': 59.99,
                'description': 'Low Potential & Low Performance: Requires immediate Performance Improvement Plan (PIP) or exit / redeployment.',
            },
        ]

        existing_cells = self.search([])
        # Link any unlinked cells
        unlinked = existing_cells.filtered(lambda c: not c.matrix_config_id)
        if unlinked:
            unlinked.write({'matrix_config_id': config.id})

        # Check existing coordinate coverage
        existing_coords = {(c.performance_rating, c.potential_rating): c for c in existing_cells}

        for item in default_cells_data:
            key = (item['performance_rating'], item['potential_rating'])
            if key not in existing_coords:
                cell_vals = dict(item)
                cell_vals['matrix_config_id'] = config.id
                self.create(cell_vals)
            else:
                c = existing_coords[key]
                upd = {}
                if not c.sequence or c.sequence != item['sequence']:
                    upd['sequence'] = item['sequence']
                # Correct known corrupt ranges (e.g. Solid Professional having 75-100 min_potential_match)
                if key == ('high', 'low') and c.min_potential_match > 59.99:
                    upd['min_potential_match'] = 0.0
                    upd['max_potential_match'] = 59.99
                if upd:
                    c.write(upd)

    def write(self, vals):
        res = super().write(vals)
        watch_fields = {
            'min_pms_score', 'max_pms_score',
            'min_potential_match', 'max_potential_match',
            'performance_rating', 'potential_rating', 'name'
        }
        if any(f in vals for f in watch_fields):
            candidates = self.env['succession.candidate'].sudo().search([])
            if candidates:
                candidates._compute_9box_ratings()
                candidates._compute_9box_label()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        candidates = self.env['succession.candidate'].sudo().search([])
        if candidates:
            candidates._compute_9box_ratings()
            candidates._compute_9box_label()
        return records
