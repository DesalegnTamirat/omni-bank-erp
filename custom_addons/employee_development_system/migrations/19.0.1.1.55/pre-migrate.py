"""Recreate an approval-minute report action if an earlier failed upgrade left a dangling XML ID."""


def migrate(cr, version):
    cr.execute("""
        DELETE FROM ir_model_data AS data
         WHERE data.module = 'employee_development_system'
           AND data.name = 'action_report_eds_meeting_minutes'
           AND data.model = 'ir.actions.report'
           AND NOT EXISTS (SELECT 1 FROM ir_actions AS action
                            WHERE action.id = data.res_id)
    """)
