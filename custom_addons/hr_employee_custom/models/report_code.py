from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrReportCode(models.Model):
    _name        = 'hr.report.code'
    _description = 'HR Report Code'
    _inherit     = ['archive.mixin']
    _order       = 'code asc'
    _rec_name    = 'code'

    # ── Identification ────────────────────────────────────────────────────
    code = fields.Integer(
        string='Report Code',
        required=True,
        copy=False,
        index=True,
        help='Unique numeric code identifying this report.',
    )

    name = fields.Char(
        string='Name',
        required=True,
    )

    active = fields.Boolean(
        string='Active',
        default=True,
    )

    # ── SQL Constraints ───────────────────────────────────────────────────
    _unique_report_code = models.Constraint(
        'UNIQUE(code)',
        'Report Code must be unique. This code already exists.'
    )

    # ── Python Constraints ────────────────────────────────────────────────
    @api.constrains('code')
    def _check_code_positive(self):
        for rec in self:
            if rec.code <= 0:
                raise ValidationError(_('Report Code must be a positive number.'))
            duplicate = self.search([('code', '=', rec.code), ('id', '!=', rec.id)], limit=1)
            if duplicate:
                raise ValidationError(
                    _('Report Code "%s" already exists on "%s". Code must be unique.')
                    % (rec.code, duplicate.name)
                )

    # ── Button Actions ────────────────────────────────────────────────────
    def action_save_report_code(self):
        self.ensure_one()
        self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            'simple_notification',
            {
                'title':   _('Saved'),
                'message': _('Report Code %s — "%s" has been saved successfully.') % (self.code, self.name),
                'sticky':  False,
                'type':    'success',
            },
        )
        return {
            'type':      'ir.actions.act_window',
            'name':      _('Report Codes'),
            'res_model': 'hr.report.code',
            'view_mode': 'list,form',
            'target':    'current',
        }

    def action_archive_report_code(self):
        self.ensure_one()
        code = self.code
        name = self.name
        self.write({'active': False})
        self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            'simple_notification',
            {
                'title':   _('Archived'),
                'message': _('Report Code %s — "%s" has been archived.') % (code, name),
                'sticky':  False,
                'type':    'warning',
            },
        )
        return {
            'type':      'ir.actions.act_window',
            'name':      _('Report Codes'),
            'res_model': 'hr.report.code',
            'view_mode': 'list,form',
            'target':    'current',
        }