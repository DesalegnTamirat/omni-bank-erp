from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PlanningFiscalYear(models.Model):
    _name = 'planning.fiscal.year'
    _description = 'Planning Fiscal Year'
    _order = 'year_start desc'
    _rec_name = 'name'

    # ── Identification ────────────────────────────────────────────────────
    year_start = fields.Integer(
        string='Start Year',
        required=True,
        help='Enter a 4-digit year, e.g. 2023 to represent the "2023-2024" fiscal year.',
    )

    name = fields.Char(
        string='Fiscal Year',
        compute='_compute_name',
        store=True,
        help='Display label, e.g. "2023-2024".',
    )

    date_start = fields.Date(
        string='Start Date',
        compute='_compute_dates',
        store=True,
        help='Always 01-Jul of the Start Year.',
    )

    date_end = fields.Date(
        string='End Date',
        compute='_compute_dates',
        store=True,
        help='Always 30-Jun of the following year.',
    )

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            'year_start_company_unique',
            'UNIQUE(year_start, company_id)',
            'A Fiscal Year with this Start Year already exists for this company.',
        ),
    ]

    # ── Compute ───────────────────────────────────────────────────────────
    @api.depends('year_start')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s-%s' % (rec.year_start, rec.year_start + 1) if rec.year_start else ''

    @api.depends('year_start')
    def _compute_dates(self):
        for rec in self:
            if rec.year_start and 1000 <= rec.year_start <= 9999:
                rec.date_start = date(rec.year_start, 7, 1)
                rec.date_end = date(rec.year_start + 1, 6, 30)
            else:
                rec.date_start = False
                rec.date_end = False

    # ── Constraints ───────────────────────────────────────────────────────
    @api.constrains('year_start')
    def _check_year_start(self):
        for rec in self:
            if rec.year_start and not (1000 <= rec.year_start <= 9999):
                raise ValidationError(_('Start Year must be a 4-digit number (e.g. 2023).'))

    @api.constrains('year_start', 'company_id')
    def _check_duplicate_fiscal_year(self):
        for rec in self:
            if not rec.year_start:
                continue
            duplicate = self.search([
                ('year_start', '=', rec.year_start),
                ('company_id', '=', rec.company_id.id),
                ('id', '!=', rec.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'Fiscal Year "%s" already exists for this company. '
                    'Please choose a different Start Year.'
                ) % rec.name)

    # ── Header button actions (Edit / Save with feedback) ─────────────────
    def action_edit_fiscal_year(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'planning.fiscal.year',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {'form_view_initial_mode': 'edit'},
        }

    def action_save_fiscal_year(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Saved'),
                'message': _('Fiscal Year "%s" has been saved successfully.') % self.name,
                'sticky': False,
                'type': 'success',
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'planning.fiscal.year',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'current',
                },
            },
        }