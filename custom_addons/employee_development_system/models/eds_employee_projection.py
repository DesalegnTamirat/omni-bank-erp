"""Show linked employee names inside readable EDS records without HR access."""


def safe_employee_web_read(records, specification, super_web_read,
                           field_names=('employee_id',)):
    """Project only name labels for explicitly listed HR Many2one fields.

    The caller's EDS record access is checked before any sudo read. Requests
    for other HR fields continue through Odoo's normal access rules.
    """
    label_fields = {}
    for field_name in field_names:
        field = records._fields.get(field_name)
        field_spec = specification.get(field_name, {})
        nested = field_spec.get('fields') if isinstance(field_spec, dict) else None
        if (field and field.type == 'many2one'
                and field.comodel_name == 'hr.employee'
                and isinstance(nested, dict)
                and set(nested) <= {'id', 'name', 'display_name'}
                and ('name' in nested or 'display_name' in nested)):
            label_fields[field_name] = nested

    if not label_fields:
        return super_web_read(specification)

    records.check_access('read')
    base_spec = {name: spec for name, spec in specification.items()
                 if name not in label_fields}
    result = super_web_read(base_spec)
    if not result:
        return result

    relations = records.sudo().read(list(label_fields), load=False)
    employee_ids = {
        values[field_name] for values in relations for field_name in label_fields
        if values.get(field_name)
    }
    names = {
        employee['id']: employee['name'] or ''
        for employee in records.env['hr.employee'].sudo().browse(
            sorted(employee_ids)).read(['name'], load=False)
    }
    for values, relation in zip(result, relations):
        for field_name, nested in label_fields.items():
            employee_id = relation.get(field_name)
            if not employee_id:
                values[field_name] = False
                continue
            label = {'id': employee_id}
            if 'name' in nested:
                label['name'] = names.get(employee_id, '')
            if 'display_name' in nested:
                label['display_name'] = names.get(employee_id, '')
            values[field_name] = label
    return result
