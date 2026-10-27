from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Remove old out-of-cycle demand while preserving imported diagnostics."""
    env = api.Environment(cr, SUPERUSER_ID, {'eds_allow_locked_edit': True})
    cycles = env['eds.tna.cycle'].search([('restrict_tna_courses', '=', True)])
    for cycle in cycles:
        diagnostics = env['eds.tna.entry'].search([
            ('cycle_id', '=', cycle.id),
            ('source', 'in', ('competency_gap', 'pms')),
        ])
        if diagnostics:
            diagnostics._compute_suggested_courses()
            diagnostics._compute_recommended_course()
        cycle._sync_course_demand()
