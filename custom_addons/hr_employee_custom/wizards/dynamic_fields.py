# from odoo import fields, models, _, api
#
# class EmployeeDynamicFields(models.TransientModel):
#     _name = 'employee.dynamic.fields'
#     _description = 'Dynamic Fields'
#     _inherit = 'ir.model.fields'
#
#     position_field = fields.Many2one('ir.model.fields', string='Field Name', required=True)
#     position = fields.Selection([('before', 'Before'),
#                                 ('after', 'After')], string='Position', required=True)
#     model_id = fields.Many2one('ir.model', string='Model', required=True, index=True, ondelete='cascade',
#                               help="The model this field belongs to")
#     ref_model_id = fields.Many2one('ir.model', string='Model', index=True)
#     # In odoo 13 the field 'selection' is deprecated, so adding a new field to get the selection values.
#     selection_field = fields.Char(string="Selection Options")
#     rel_field = fields.Many2one('ir.model.fields', string='Related Field')
#     field_type = fields.Selection(selection='get_possible_field_types', string='Field Type', required=True)
#     ttype = fields.Selection(string="Field Type", related='field_type')
#     extra_features = fields.Boolean(string="Show Extra Properties")
#
#     # @api.model
#     # def get_possible_field_types(self):
#     #     field_list = sorted((key, key) for key in fields.MetaField.by_type)
#     #     field_list.remove(('one2many', 'one2many'))
#     #     field_list.remove(('reference', 'reference'))
#     #     return field_list
#
#     # @api.depends('field_type')
#     # @api.onchange('field_type')
#     # def onchange_field_type(self):
#     #     if self.field_type:
#     #         if self.field_type == 'binary':
#     #             return {'domain': {'widget': [('name', '=', 'image')]}}
#     #         # elif self.field_type == 'many2many':
#     #         #     return {'domain': {'widget': [('name', 'in', ['many2many_tags', 'binary'])]}}
#     #         elif self.field_type == 'selection':
#     #             return {'domain': {'widget': [('name', 'in', ['radio', 'priority'])]}}
#     #         elif self.field_type == 'float':
#     #             return {'domain': {'widget': [('name', '=', 'monetary')]}}
#     #         elif self.field_type == 'many2one':
#     #             return {'domain': {'widget': [('name', '=', 'selection')]}}
#     #         else:
#     #             return {'domain': {'widget': [('id', '=', False)]}}
#     #     return {'domain': {'widget': [('id', '=', False)]}}
#     def create_fields(self):
#            self.env['ir.model.fields'].sudo().create({'name': self.name,
#                                                       'field_description': self.field_description,
#                                                       'model_id': self.model_id.id,
#                                                       'ttype': self.field_type,
#                                                       'relation': self.ref_model_id.model,
#                                                       'required': self.required,
#                                                       'index': self.index,
#                                                       'store': self.store,
#                                                       'help': self.help,
#                                                       'readonly': self.readonly,
#                                                       'selection': self.selection_field,
#                                                       'copied': self.copied,
#                                                       'is_employee_dynamic': True
#                                                       })
#            inherit_id = self.env.ref('hr.view_employee_form')
#            arch_base = _('<?xml version="1.0"?>'
#                          '<data>'
#                          '<field name="%s" position="%s">'
#                          '<field name="%s"/>'
#                          '</field>'
#                          '</data>') % (self.position_field.name, self.position, self.name)
#            if self.widget:
#                arch_base = _('<?xml version="1.0"?>'
#                              '<data>'
#                              '<field name="%s" position="%s">'
#                              '<field name="%s" widget="%s"/>'
#                              '</field>'
#                              '</data>') % (self.position_field.name, self.position, self.name, self.widget.name)
#            self.env['ir.ui.view'].sudo().create({'name': 'employee.dynamic.fields.%s' % self.name,
#                                                  'type': 'form',
#                                                  'model': 'hr.employee',
#                                                  'mode': 'extension',
#                                                  'inherit_id': inherit_id.id,
#                                                  'arch_base': arch_base,
#                                                  'active': True})
#            return {
#                'type': 'ir.actions.client',
#                'tag': 'reload',
#            }
