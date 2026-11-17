# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class DmsUploadWizard(models.TransientModel):
    _name = 'dms.upload.wizard'
    _description = 'Upload Document'

    file = fields.Binary(string='File', required=True)
    file_name = fields.Char(string='File Name', required=True)
    folder_mode = fields.Selection([
        ('folder', 'In a specific folder'),
        ('no_folder', 'Without folder (custom permissions)'),
    ], string='Storage Location', default='folder', required=True)
    folder_id = fields.Many2one('dms.folder', string='Target Folder')
    tag_ids = fields.Many2many('dms.tag', string='Tags')
    description = fields.Text(string='Description')

    # Custom permission fields when folder_mode == 'no_folder'
    inherit_folder_rules = fields.Boolean(
        string='Restricted', default=False,
        help="If unticked, all internal users can view this document. If ticked, access is restricted to the targets below.")
    read_user_ids = fields.Many2many(
        'res.users', 'dms_upload_wiz_user_rel', 'wizard_id', 'user_id',
        string='Allowed Users', domain=[('share', '=', False)])
    read_group_ids = fields.Many2many(
        'res.groups', 'dms_upload_wiz_group_rel', 'wizard_id', 'group_id',
        string='Allowed Groups')
    read_department_ids = fields.Many2many(
        'hr.department', 'dms_upload_wiz_dept_rel', 'wizard_id', 'dept_id',
        string='Allowed Departments')
    read_operating_unit_ids = fields.Many2many(
        'operating.unit', 'dms_upload_wiz_ou_rel', 'wizard_id', 'ou_id',
        string='Allowed Operating Units')

    # Linked record (optional)
    res_model = fields.Char(string='Linked Model')
    res_id = fields.Integer(string='Linked Record ID')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        default_folder_id = self.env.context.get('default_folder_id')
        if default_folder_id:
            folder = self.env['dms.folder'].browse(default_folder_id).exists()
            if folder:
                res['folder_id'] = folder.id
        elif not res.get('folder_id'):
            inbox = self.env.ref('documents_lite.dms_folder_inbox', raise_if_not_found=False)
            if inbox:
                res['folder_id'] = inbox.id
        if self.env.context.get('default_res_model'):
            res['res_model'] = self.env.context.get('default_res_model')
        if self.env.context.get('default_res_id'):
            res['res_id'] = self.env.context.get('default_res_id')
        return res

    def action_upload(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Please select a file to upload.'))
        if self.folder_mode == 'folder' and not self.folder_id:
            raise UserError(_('Please pick a destination folder or select "Without folder".'))

        folder_id = self.folder_id.id if self.folder_mode == 'folder' and self.folder_id else False

        # If without folder, use inbox or root folder if needed by schema, but mark restricted
        if not folder_id:
            inbox = self.env.ref('documents_lite.dms_folder_inbox', raise_if_not_found=False)
            folder_id = inbox.id if inbox else False
            if not folder_id:
                any_folder = self.env['dms.folder'].search([], limit=1)
                folder_id = any_folder.id if any_folder else False

        vals = {
            'name': self.file_name,
            'file_name': self.file_name,
            'file': self.file,
            'folder_id': folder_id,
            'tag_ids': [(6, 0, self.tag_ids.ids)],
            'description': self.description,
            'res_model': self.res_model or False,
            'res_id': self.res_id or False,
        }

        if self.folder_mode == 'no_folder':
            vals.update({
                'custom_permission': True,
                'is_restricted': self.inherit_folder_rules,
                'read_user_ids': [(6, 0, self.read_user_ids.ids)],
                'read_group_ids': [(6, 0, self.read_group_ids.ids)],
                'read_department_ids': [(6, 0, self.read_department_ids.ids)],
                'read_operating_unit_ids': [(6, 0, self.read_operating_unit_ids.ids)],
            })

        doc = self.env['dms.document'].create(vals)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Upload Successful'),
                'message': _('Document "%(name)s" uploaded successfully.', name=doc.name),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window_close',
                },
            },
        }
