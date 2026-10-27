"""Align existing invitation switches and session attendance percentages."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("""
        UPDATE eds_enrollment
           SET selected = FALSE
         WHERE selected IS TRUE AND state != 'suggested'
    """)
    env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True})
    env.invalidate_all()

    last_id = 0
    attendance_model = env['eds.session.attendance']
    while True:
        cr.execute("""
            SELECT id FROM eds_session_attendance
             WHERE id > %s ORDER BY id LIMIT 500
        """, [last_id])
        ids = [row[0] for row in cr.fetchall()]
        if not ids:
            break
        attendance_model.browse(ids)._compute_program_attendance()
        last_id = ids[-1]

    last_id = 0
    session_model = env['eds.session']
    while True:
        cr.execute("""
            SELECT DISTINCT session.id
              FROM eds_session AS session
              JOIN eds_session_attendance AS attendance
                ON attendance.session_id = session.id
             WHERE session.id > %s
             ORDER BY session.id LIMIT 200
        """, [last_id])
        ids = [row[0] for row in cr.fetchall()]
        if not ids:
            break
        session_model.browse(ids)._compute_attendance_rate()
        last_id = ids[-1]
