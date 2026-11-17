# -*- coding: utf-8 -*-
"""The "Search: Employees" list of the approver / disbursor lines: the
columns that are not needed there are hidden. Only for that picker (the field
sets the context key `resl_employee_picker`); the normal Employees list is
not touched."""
from odoo import api, models

# columns to hide, matched by the label the user sees (lower case)
_HIDE_LABELS = {
    'tags', 'next activity deadline', 'attendance approver', 'time off approver',
    'birthday', 'related user', 'coach', 'nationality (country)', 'nationality',
    'activity by', 'activities', 'contract start date', 'contract end date',
    'contract type', 'employee type', 'presence', 'wage', 'work phone',
}
# ... and by technical name
_HIDE_NAMES = {
    'category_ids', 'activity_date_deadline', 'activity_user_id', 'activity_ids',
    'activity_state', 'activity_summary', 'activity_type_id', 'attendance_manager_id',
    'leave_manager_id', 'birthday', 'user_id', 'coach_id', 'country_id',
    'contract_date_start', 'contract_date_end', 'first_contract_date',
    'contract_type_id', 'employee_type', 'hr_presence_state', 'hr_icon_display',
    'wage', 'work_phone', 'mobile_phone',
}


class HrEmployeePickerList(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'list' and self.env.context.get('resl_employee_picker'):
            for node in arch.iter('field'):
                fld = self._fields.get(node.get('name'))
                label = (node.get('string') or (fld.string if fld else '') or '').strip().lower()
                if (node.get('name') in _HIDE_NAMES or label in _HIDE_LABELS
                        or 'nationality' in label):
                    node.set('column_invisible', '1')
                    node.attrib.pop('optional', None)
        return arch, view