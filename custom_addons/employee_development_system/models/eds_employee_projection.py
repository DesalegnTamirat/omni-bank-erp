"""Show linked employee names inside readable EDS records without HR access."""


def safe_employee_web_read(records, specification, super_web_read,
                           field_names=('employee_id',)):
    """Project only name labels for explicitly listed HR Many2one and Many2many fields.

    The caller's EDS record access is checked before any sudo read. Requests
    for other HR fields continue through Odoo's normal access rules.
    """
    label_fields = {}
    for field_name in field_names:
        field = records._fields.get(field_name)
        field_spec = specification.get(field_name, {})
        nested = field_spec.get('fields') if isinstance(field_spec, dict) else None
        if (field and field.type in ('many2one', 'many2many')
                and field.comodel_name == 'hr.employee'
                and isinstance(nested, dict)
                and set(nested) <= {'id', 'name', 'display_name'}
                and ('name' in nested or 'display_name' in nested)):
            label_fields[field_name] = (field.type, nested)

    if not label_fields:
        return super_web_read(specification)

    records.check_access('read')
    base_spec = {name: spec for name, spec in specification.items()
                 if name not in label_fields}
    result = super_web_read(base_spec)
    if not result:
        return result

    relations = records.sudo().read(list(label_fields), load=False)
    employee_ids = set()
    for values in relations:
        for fname, (ftype, _) in label_fields.items():
            val = values.get(fname)
            if not val:
                continue
            if ftype == 'many2one':
                employee_ids.add(val)
            elif ftype == 'many2many' and isinstance(val, (list, tuple)):
                employee_ids.update(val)

    names = {
        employee['id']: employee['name'] or ''
        for employee in records.env['hr.employee'].sudo().browse(
            sorted(employee_ids)).read(['name'], load=False)
    }
    for values, relation in zip(result, relations):
        for field_name, (ftype, nested) in label_fields.items():
            raw_val = relation.get(field_name)
            if not raw_val:
                values[field_name] = [] if ftype == 'many2many' else False
                continue
            if ftype == 'many2one':
                label = {'id': raw_val}
                if 'name' in nested:
                    label['name'] = names.get(raw_val, '')
                if 'display_name' in nested:
                    label['display_name'] = names.get(raw_val, '')
                values[field_name] = label
            else:
                items = []
                for eid in raw_val:
                    item = {'id': eid}
                    if 'name' in nested:
                        item['name'] = names.get(eid, '')
                    if 'display_name' in nested:
                        item['display_name'] = names.get(eid, '')
                    items.append(item)
                values[field_name] = items
    return result
