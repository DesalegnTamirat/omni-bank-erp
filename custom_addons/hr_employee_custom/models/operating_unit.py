# -*- coding: utf-8 -*-
from email.policy import default

from odoo.exceptions import UserError
from odoo import api, fields, models, _


class OperatingUnit(models.Model):
    _name = "operating.unit"
    _description = "Operating Unit"
    _order = 'sol_id'
    name = fields.Char(required=True)
    # code = fields.Char(string="Code")
    code = fields.Many2one(
        comodel_name='hr.report.code',
        string='Report Code',
    )
    manager_id = fields.Many2one('hr.employee',string ="Manager")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
    )
    # partner_id = fields.Many2one("res.partner", "Company", readonly=True,default=lambda self: self.env.company)
    user_ids = fields.Many2many(
        "res.users",
        "operating_unit_users_rel",
        "operating_unit_id",
        "user_id",
        "Users Allowed",
    )

    ## added for operating unit
    job_position_ids = fields.One2many(
        comodel_name='operating.unit.job.position',
        inverse_name='operating_unit_id',
        string='Job Positions',
    )
    sol_id = fields.Integer(
        string='Sol ID',
        required=True,
        help='Numeric Sol identifier for this operating unit.',
    )

    # ── Classification ────────────────────────────────────────────────────
    work_unit_type = fields.Selection(
        selection=[
            ('branch', 'Branch'),
            ('sub_branch', 'Sub-Branch'),
            ('head_office', 'Head Office'),
            ('regional_office', 'Regional Office'),
            ('district_office', 'District Office'),
            ('service_center', 'Service Center'),
            ('other', 'Other'),
        ],
        string='Work Unit Type',
        required=True,
    )

    parent_unit = fields.Many2one(
        comodel_name='operating.unit',
        string='Parent Unit',
        ondelete='set null',
        domain="[('id', '!=', id)]",
        help='Leave empty if this is a top-level unit.',
    )

    branch_grade = fields.Char(
        string='Branch Grade',
    )
    latitude=fields.Float(string="Latitude")
    longitude = fields.Float(string="Longitude")
    district = fields.Char(string="District")
    region = fields.Char(string="Region")
    department = fields.Many2one('hr.department', string='Department')

    def _compute_display_name(self):
        for ou in self:
            name = ou.name
            if ou.code:
                name = "[{}] {}".format(ou.code, name)
            ou.display_name = name

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if isinstance(value, str) and value:
            domain = [
                         "|",
                         ("code", operator, value),
                     ] + domain
        return domain

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record.user_ids += self.env.user
        return records

    def write(self, vals):
        return super().write(vals)

    def unlink(self):
        raise UserError(_(
            "Operating Units cannot be deleted. Please archive them instead."
        ))


    hardship_allowance = fields.Float(
        string='Hardship Allowance',
        default=0.00,
        digits=(16, 2),
    )


    # ── Python Constraints ────────────────────────────────────────────────
    @api.constrains('sol_id')
    def _check_sol_id_positive(self):
        for rec in self:
            if rec.sol_id <= 0:
                raise UserError(_('Sol ID must be a positive number.'))


    @api.constrains('hardship_allowance')
    def _check_hardship_allowance(self):
        for rec in self:
            if rec.hardship_allowance < 0:
                raise UserError(
                    _('Hardship Allowance cannot be negative.')
                )

    # ── Button Actions ────────────────────────────────────────────────────
    def action_save_operating_unit(self):
        """Triggered by the Save button — shows success toast then returns to list."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Operating Unit "%s" has been saved successfully.') % self.name,
                'sticky': False,
                'type': 'success',
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'operating.unit',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'current',
                },
            },
        }

    def action_archive_operating_unit(self):
        """Toggle active — Archive if active, Unarchive if archived."""
        self.ensure_one()
        name = self.name
        new_state = not self.active
        self.write({'active': new_state})
        title = _('Unarchived') if new_state else _('Archived')
        msg = _('Operating Unit "%s" has been %s.') % (name, title.lower())
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': msg,
                'sticky': False,
                'type': 'warning' if not new_state else 'success',
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'operating.unit',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'current',
                },
            },
        }
