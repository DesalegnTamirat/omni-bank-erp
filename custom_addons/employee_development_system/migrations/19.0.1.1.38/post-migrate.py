"""Refresh draft session candidates from the highest scored TNA course demand."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("""
        SELECT DISTINCT session.id
          FROM eds_session AS session
          JOIN eds_annual_plan_line AS line ON line.id = session.plan_line_id
          LEFT JOIN eds_plan_line_course_demand_rel AS linked
            ON linked.plan_line_id = line.id
         WHERE session.status = 'draft'
           AND (line.course_demand_id IS NOT NULL OR linked.demand_id IS NOT NULL)
    """)
    session_ids = [row[0] for row in cr.fetchall()]
    if session_ids:
        env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True})
        env['eds.session'].browse(session_ids)._populate_suggested_enrollments()
