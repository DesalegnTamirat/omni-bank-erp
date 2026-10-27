"""Keep existing role memberships while giving EDS-wide roles generic XML IDs."""


def migrate(cr, version):
    for old_name, new_name in (
        ('group_eds_plan_team_leader', 'group_eds_team_leader'),
        ('group_eds_plan_director', 'group_eds_director'),
        ('group_eds_plan_chief', 'group_eds_chief'),
    ):
        cr.execute("""
            UPDATE ir_model_data AS old
               SET name = %s
             WHERE old.module = 'employee_development_system'
               AND old.name = %s
               AND old.model = 'res.groups'
               AND NOT EXISTS (
                   SELECT 1 FROM ir_model_data AS existing
                    WHERE existing.module = old.module AND existing.name = %s
               )
        """, (new_name, old_name, new_name))
