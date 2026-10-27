"""Remove retired template import UI and the bank-wide TNA menu."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xml_id in (
        'menu_eds_template_import',
        'menu_eds_report_tna',
        'action_eds_template_import_wizard',
        'view_eds_template_import_wizard_form',
        'access_eds_template_import_wizard_off',
        'access_eds_template_import_wizard_mgr',
        'access_eds_template_import_wizard_adm',
    ):
        record = env.ref('employee_development_system.' + xml_id,
                         raise_if_not_found=False)
        if record:
            record.unlink()

    # Older approved addenda did not retain their request link. Recover only
    # unambiguous plan/course matches so existing sessions keep their source.
    candidates = {}
    for request in env['eds.unscheduled.request'].search([
        ('state', '=', 'approved'), ('annual_plan_id', '!=', False),
        ('course_id', '!=', False),
    ]):
        key = (request.annual_plan_id.id, request.course_id.id)
        candidates.setdefault(key, []).append(request.id)
    for line in env['eds.annual.plan.line'].search([
        ('is_addendum', '=', True), ('unscheduled_request_id', '=', False),
        ('course_id', '!=', False),
    ]):
        matches = candidates.get((line.plan_id.id, line.course_id.id), [])
        if len(matches) == 1:
            line.unscheduled_request_id = matches[0]
    cr.execute("""
        UPDATE eds_session AS session
           SET source_type = 'unscheduled',
               unscheduled_request_id = line.unscheduled_request_id
          FROM eds_annual_plan_line AS line
         WHERE session.plan_line_id = line.id
           AND line.unscheduled_request_id IS NOT NULL
    """)
