"""Retire the obsolete meeting editor before views are validated.

Also clear anonymous employee assessment action views. The prior XML recreated
those rows on each upgrade and violates Odoo's one-view-per-mode constraint.
"""

OLD_VIEW_IDS = (
    'view_eds_meeting_minutes_list',
    'view_eds_meeting_minutes_search',
    'view_eds_annual_plan_meeting_minutes_inherit',
    'view_eds_vendor_selection_meeting_minutes_inherit',
    'view_eds_hotel_selection_meeting_minutes_inherit',
    'view_eds_sponsorship_meeting_minutes_inherit',
    'view_eds_unscheduled_meeting_minutes_inherit',
    'view_eds_tna_consolidation_meeting_minutes_inherit',
    'view_eds_rfp_meeting_minutes_inherit',
)


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_ui_view
           SET active = FALSE
         WHERE id IN (
               SELECT res_id FROM ir_model_data
                WHERE module = 'employee_development_system'
                  AND model = 'ir.ui.view'
                  AND name = ANY(%s)
         )
    """, (list(OLD_VIEW_IDS),))

    cr.execute("""
        DELETE FROM ir_act_window_view
         WHERE act_window_id IN (
               SELECT res_id FROM ir_model_data
                WHERE module = 'employee_development_system'
                  AND model = 'ir.actions.act_window'
                  AND name = 'action_eds_assessment_own'
         )
           AND view_mode IN ('list', 'form')
           AND NOT EXISTS (
               SELECT 1 FROM ir_model_data AS imd
                WHERE imd.model = 'ir.actions.act_window.view'
                  AND imd.res_id = ir_act_window_view.id
           )
    """)
