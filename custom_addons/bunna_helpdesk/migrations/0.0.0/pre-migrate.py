"""
Migration script run on any version update.
Ensures new SQL columns exist before Odoo runs table queries and evaluates security rule domains.
"""


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE helpdesk_ticket_team
        ADD COLUMN IF NOT EXISTS visibility VARCHAR DEFAULT 'company',
        ADD COLUMN IF NOT EXISTS assignment_method VARCHAR DEFAULT 'manual',
        ADD COLUMN IF NOT EXISTS last_assignment_user_id INTEGER,
        ADD COLUMN IF NOT EXISTS use_rating BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS rating_template_id INTEGER,
        ADD COLUMN IF NOT EXISTS use_timesheets BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS analytic_account_id INTEGER;

        UPDATE helpdesk_ticket_team
        SET visibility = CASE
            WHEN show_in_portal IS TRUE THEN 'portal'
            ELSE 'company'
        END
        WHERE visibility IS NULL;

        ALTER TABLE res_company
        ADD COLUMN IF NOT EXISTS helpdesk_mgmt_sla_active BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS helpdesk_mgmt_auto_close_active BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS helpdesk_mgmt_auto_close_days INTEGER DEFAULT 30,
        ADD COLUMN IF NOT EXISTS helpdesk_mgmt_auto_close_stage_id INTEGER;
    """)
