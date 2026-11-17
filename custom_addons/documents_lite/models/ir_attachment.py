from odoo import api, models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _dms_autofile_candidates(self):
        return self.filtered(
            lambda a: a.res_model and a.res_id and not a.res_field and a.type == 'binary'
            and not a.res_model.startswith(('dms.', 'ir.', 'mail.compose', 'base_import')))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('dms_no_autofile') and any(v.get('res_model') for v in vals_list):
            candidates = records._dms_autofile_candidates()
            if candidates:
                self.env['dms.rule']._autofile(candidates)
        return records

    def write(self, vals):
        res = super().write(vals)
        if ('res_model' in vals or 'res_id' in vals) and not self.env.context.get('dms_no_autofile'):
            candidates = self._dms_autofile_candidates()
            if candidates:
                self.env['dms.rule']._autofile(candidates)
        return res
