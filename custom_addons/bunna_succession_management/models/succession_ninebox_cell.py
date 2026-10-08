# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class SuccessionNineboxCell(models.Model):
    """
    9-Box Grid Cell Configuration Model.
    Defines cell labels, color tiers, priority, recommended HR actions,
    and flags for each of the 9 matrix intersections (Performance x Potential).
    """
    _name = 'succession.ninebox.cell'
    _description = 'Succession 9-Box Cell Definition'
    _order = 'potential_rating desc, performance_rating desc'

    performance_rating = fields.Selection([
        ('low', 'Low Performance'),
        ('medium', 'Medium Performance'),
        ('high', 'High Performance'),
    ], string='Performance Level', required=True)

    potential_rating = fields.Selection([
        ('low', 'Low Potential'),
        ('medium', 'Medium Potential'),
        ('high', 'High Potential'),
    ], string='Potential Level', required=True)

    name = fields.Char(string='Cell Label', required=True)
    tier_color = fields.Selection([
        ('gold', 'Gold / Green'),
        ('teal', 'Teal / Blue'),
        ('brick', 'Brick / Red'),
    ], string='Color Tier', default='teal', required=True)

    priority = fields.Selection([
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('urgent', 'Urgent'),
    ], string='Succession Priority', default='medium')

    description = fields.Text(string='Recommended HR Action')
    is_high_potential = fields.Boolean(string='High Potential Flag', default=False)
    is_watchlist = fields.Boolean(string='Watchlist / Alert Flag', default=False)
    criteria_display = fields.Char(
        string='Auto-Match Criteria', compute='_compute_criteria_display')

    def _compute_criteria_display(self):
        company = self.env.company
        high_perf = company.succ_high_perf_threshold or 4.0
        med_perf = company.succ_med_perf_threshold or 3.0
        high_pot = company.succ_high_pot_threshold or 80.0
        med_pot = company.succ_med_pot_threshold or 60.0

        for rec in self:
            if rec.performance_rating == 'high':
                perf_str = "PMS ≥ %.2f" % high_perf
            elif rec.performance_rating == 'medium':
                perf_str = "PMS %.2f–%.2f" % (med_perf, high_perf - 0.01)
            else:
                perf_str = "PMS < %.2f" % med_perf

            if rec.potential_rating == 'high':
                pot_str = "Match ≥ %.0f%%" % high_pot
            elif rec.potential_rating == 'medium':
                pot_str = "Match %.0f–%.0f%%" % (med_pot, high_pot - 1)
            else:
                pot_str = "Match < %.0f%%" % med_pot

            rec.criteria_display = "%s | %s" % (perf_str, pot_str)

    _sql_constraints = [
        ('perf_pot_unique', 'unique(performance_rating, potential_rating)',
         'A cell definition already exists for this Performance and Potential combination!')
    ]

    def _auto_init(self):
        res = super()._auto_init()
        self.init_default_cells()
        return res

    @api.model
    def init_default_cells(self):
        """Seed default 9-box cell definitions if none exist."""
        defaults = [
            # High Potential (Row 2)
            ('low', 'high', 'Rough Diamond', 'teal', 'high',
             'Has high potential for future roles but currently underperforming. Needs coaching, reassignment, or motivation.', True, False),
            ('medium', 'high', 'High Potential', 'gold', 'high',
             'Meets current expectations and shows strong capability for upward movement within 1-2 years.', True, False),
            ('high', 'high', 'Star Performer', 'gold', 'critical',
             'Consistently exceeds expectations and possesses all competencies for the next level. Ready for immediate promotion.', True, False),

            # Medium Potential (Row 1)
            ('low', 'medium', 'Inconsistent', 'brick', 'low',
             'Has some potential but fails to deliver reliable results. Requires a structured performance improvement plan.', False, True),
            ('medium', 'medium', 'Core Employee', 'teal', 'medium',
             'The reliable backbone of the team. Meets expectations and has moderate potential for gradual growth.', False, False),
            ('high', 'medium', 'High Performer', 'gold', 'high',
             'Outstanding current contributor but lacks specific competencies for the next level. Needs targeted development.', False, False),

            # Low Potential (Row 0)
            ('low', 'low', 'Underperformer', 'brick', 'urgent',
             'Failing current role and lacks potential for future roles. Requires immediate intervention or managed exit.', False, True),
            ('medium', 'low', 'Solid Contributor', 'teal', 'low',
             'Meets basic expectations but has reached their capability ceiling. Best kept in current role.', False, False),
            ('high', 'low', 'Solid Professional', 'teal', 'medium',
             'Expert in current role (high results) but lacks strategic skills/desire for next level. Great for mentoring.', False, False),
        ]

        for perf, pot, label, tier, prio, desc, is_hipot, is_watch in defaults:
            cell = self.search([('performance_rating', '=', perf), ('potential_rating', '=', pot)], limit=1)
            if not cell:
                self.create({
                    'performance_rating': perf,
                    'potential_rating': pot,
                    'name': label,
                    'tier_color': tier,
                    'priority': prio,
                    'description': desc,
                    'is_high_potential': is_hipot,
                    'is_watchlist': is_watch,
                })
