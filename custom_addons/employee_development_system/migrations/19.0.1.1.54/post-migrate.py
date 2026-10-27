"""Remove unused meeting-editor UI and access records after action repointing."""

from odoo import SUPERUSER_ID, api


OBSOLETE_XML_IDS = (
    'view_eds_meeting_minutes_list',
    'view_eds_meeting_minutes_search',
    'view_eds_annual_plan_meeting_minutes_inherit',
    'view_eds_vendor_selection_meeting_minutes_inherit',
    'view_eds_hotel_selection_meeting_minutes_inherit',
    'view_eds_sponsorship_meeting_minutes_inherit',
    'view_eds_unscheduled_meeting_minutes_inherit',
    'view_eds_tna_consolidation_meeting_minutes_inherit',
    'view_eds_rfp_meeting_minutes_inherit',
    'access_eds_meeting_minutes_officer',
    'access_eds_meeting_minutes_admin',
    'access_eds_meeting_minutes_action_officer',
    'access_eds_meeting_minutes_action_admin',
    'rule_eds_meeting_minutes_company',
    'rule_eds_meeting_minutes_action_company',
    'seq_eds_meeting_minutes',
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for name in OBSOLETE_XML_IDS:
        xmlid = 'employee_development_system.%s' % name
        record = env.ref(xmlid, raise_if_not_found=False)
        if record:
            record.unlink()
