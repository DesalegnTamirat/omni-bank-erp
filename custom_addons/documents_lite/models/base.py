from lxml import etree

from odoo import _, api, fields, models

# Forms that get a "Documents" smart button when their app is installed.
DMS_BUTTON_MODELS = {
    'res.partner', 'product.template', 'sale.order', 'purchase.order', 'project.project',
    'project.task', 'hr.employee', 'crm.lead', 'account.move',
}
DMS_BUTTON_ICON = 'fa-folder-open'


class Base(models.AbstractModel):
    _inherit = 'base'

    def action_dms_open_documents(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('documents_lite.dms_linked_document_action')
        action['domain'] = [('res_model', '=', self._name), ('res_id', '=', self.id)]
        action['context'] = {
            'default_res_model': self._name, 'default_res_id': self.id,
            'dms_linked': True, 'create': True,
        }
        action['name'] = _('Documents: %s', self.display_name)
        return action

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'form' and self._name in DMS_BUTTON_MODELS:
            boxes = arch.xpath("//div[@name='button_box']")
            if boxes and not arch.xpath("//button[@name='action_dms_open_documents']"):
                button = etree.fromstring(
                    '<button name="action_dms_open_documents" type="object" class="oe_stat_button" '
                    'groups="documents_lite.group_dms_user" invisible="not id" icon="%s">'
                    '<field name="id" widget="dms_stat" string="Documents"/></button>' % DMS_BUTTON_ICON)
                boxes[0].append(button)
        return arch, view


# Where a user's operating units come from. Adjust these to match your HR setup.
# Fields on the employee record(s) linked to the user:
EMPLOYEE_UNIT_FIELDS = ('operating_unit_id',)
# Fields directly on the user:
USER_UNIT_FIELDS = ('assigned_operating_unit_ids',)
EMPLOYEE_KEYS = {'department_id', 'user_id', *EMPLOYEE_UNIT_FIELDS}


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Used by the Documents record rules (a rule can only read fields, not call methods).
    dms_department_ids = fields.Many2many(
        'hr.department', compute='_compute_dms_access_targets', compute_sudo=True,
        string='Documents: Departments')
    dms_operating_unit_ids = fields.Many2many(
        'operating.unit', compute='_compute_dms_access_targets', compute_sudo=True,
        string='Documents: Operating Units')

    @api.depends('employee_ids.department_id')
    def _compute_dms_access_targets(self):
        """What a folder access rule can match this user on.

        * Departments: the user's own department(s) plus every parent department, so a
          rule on "Finance" also lets in someone working in "Finance / Accounts".
        * Operating units: the user's own units (see EMPLOYEE_UNIT_FIELDS and
          USER_UNIT_FIELDS above) plus every parent unit, so a rule on a district also lets
          in the people working in its branches.
        """
        for user in self:
            employees = user.employee_ids
            departments = employees.department_id
            department_ids = set(departments.ids)
            for department in departments:
                department_ids.update(int(i) for i in (department.parent_path or '').split('/') if i)
            user.dms_department_ids = [(6, 0, sorted(department_ids))]
            units = user.env['operating.unit']
            for source, names in ((employees, EMPLOYEE_UNIT_FIELDS), (user, USER_UNIT_FIELDS)):
                for name in names:
                    field = source._fields.get(name)
                    if field is not None and field.comodel_name == 'operating.unit':
                        units |= source[name]
            user.dms_operating_unit_ids = [(6, 0, self._dms_with_parent_units(units).ids)]

    @api.model
    def _dms_with_parent_units(self, units):
        """The units plus all their ancestors (walks ``parent_unit``, safe against cycles)."""
        if 'parent_unit' not in units._fields:
            return units
        result = units
        pending = units.parent_unit
        while pending - result:
            new = pending - result
            result |= new
            pending = new.parent_unit
        return result

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        if any(set(USER_UNIT_FIELDS) & set(vals) for vals in vals_list):
            self.env.registry.clear_cache()
        return users

    def write(self, vals):
        res = super().write(vals)
        if set(USER_UNIT_FIELDS) & set(vals):
            self.env.registry.clear_cache()
        return res


# ---- Keep folder access in step with HR data
# Keep folder access in step with HR data.
# 
# Odoo caches the evaluated record-rule domain per user. The Documents rules match a user on
# department / operating unit, so that cache must be dropped when those change; otherwise
# someone who moves department would keep (or miss) access until the server restarts.
class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(EMPLOYEE_KEYS & set(vals) for vals in vals_list):
            self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        if EMPLOYEE_KEYS & set(vals):
            self.env.registry.clear_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res


class HrVersion(models.Model):
    _inherit = 'hr.version'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(EMPLOYEE_KEYS & set(vals) for vals in vals_list):
            self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        if EMPLOYEE_KEYS & set(vals):
            self.env.registry.clear_cache()
        return res


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    def write(self, vals):
        res = super().write(vals)
        if 'parent_id' in vals:
            self.env.registry.clear_cache()
        return res


class OperatingUnit(models.Model):
    _inherit = 'operating.unit'

    def write(self, vals):
        res = super().write(vals)
        if 'parent_unit' in vals:
            self.env.registry.clear_cache()
        return res
