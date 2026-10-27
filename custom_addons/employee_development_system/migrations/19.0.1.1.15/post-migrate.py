from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Retire nameless legacy demand and untouched placeholder draft plan lines."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    placeholders = env['eds.tna.cycle.course.line'].search([
        ('course_id', '=', False), ('course_name', '=', 'Unassigned Program'),
    ])
    def _is_nameless(demand):
        entries = demand.employee_demand_ids.mapped('evidence_ids.entry_id')
        return bool(entries) and all(
            not entry.course_id and not entry.requested_course_ids
            and not entry.is_custom_course and not (entry.proposed_program or '').strip()
            and not entry.competency_id and not entry.pms_measure_id
            for entry in entries
        )

    legacy = placeholders.filtered(_is_nameless)
    if not legacy:
        return
    legacy.write({'selected_for_planning': False})
    plan_lines = env['eds.annual.plan.line'].search([
        ('program_name', '=', 'Unassigned Program'),
        ('course_id', '=', False), ('plan_id.state', '=', 'draft'),
        ('status', '=', 'planned'),
    ])
    for line in plan_lines:
        sources = line.course_demand_ids | line.course_demand_id
        if not sources or sources - legacy:
            continue
        if (line.session_ids or line.budget_allocated or line.manual_budget_allocated
                or line.budget_line_ids.filtered('unit_price')):
            continue
        line.unlink()
