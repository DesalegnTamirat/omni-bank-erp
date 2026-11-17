from fnmatch import fnmatch

from odoo import api, fields, models


class DmsRule(models.Model):
    _name = 'dms.rule'
    _description = 'Auto-filing Rule'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        'ir.model', string='Attached To', required=True, ondelete='cascade',
        domain=[('transient', '=', False)], help="Attachments added to records of this model are filed.")
    res_model = fields.Char(related='model_id.model', store=True, index=True)
    name_pattern = fields.Char(
        string='File Name Pattern', help="Optional, e.g. invoice*.pdf or *.png (not case sensitive).")
    mimetype_prefix = fields.Char(string='File Type', help="Optional, e.g. application/pdf or image/")
    folder_id = fields.Many2one('dms.folder', string='File Into', required=True, ondelete='cascade')
    tag_ids = fields.Many2many('dms.tag', 'dms_rule_tag_rel', 'rule_id', 'tag_id', string='Tags')
    company_id = fields.Many2one('res.company')

    def _match(self, attachment):
        self.ensure_one()
        if self.name_pattern and not fnmatch((attachment.name or '').lower(), self.name_pattern.lower()):
            return False
        if self.mimetype_prefix and not (attachment.mimetype or '').startswith(self.mimetype_prefix):
            return False
        return True

    @api.model
    def _autofile(self, attachments):
        """File the attachments for which a rule matches (first rule by sequence wins)."""
        rules = self.sudo().search([('res_model', 'in', list(set(attachments.mapped('res_model'))))])
        if not rules:
            return
        Document = self.env['dms.document'].sudo().with_context(dms_no_autofile=True)
        done = set(Document.with_context(active_test=False).search_fetch(
            [('source_attachment_id', 'in', attachments.ids)], ['source_attachment_id']).source_attachment_id.ids)
        vals_list = []
        for att in attachments:
            if att.id in done:
                continue
            rule = next((r for r in rules if r.res_model == att.res_model and r._match(att)), None)
            if rule and Document._is_file_allowed(att.raw, att.name):
                vals_list.append({
                    'name': att.name, 'file_name': att.name, 'file': att.datas,
                    'folder_id': rule.folder_id.id, 'tag_ids': [(6, 0, rule.tag_ids.ids)],
                    'res_model': att.res_model, 'res_id': att.res_id, 'source_attachment_id': att.id,
                    'description': rule.name,
                })
        if vals_list:
            Document.create(vals_list)
