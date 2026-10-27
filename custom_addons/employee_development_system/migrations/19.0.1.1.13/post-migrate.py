def migrate(cr, version):
    """Remove obsolete leader job filters from historical work-unit needs."""
    cr.execute("""
        UPDATE eds_tna_entry
           SET job_position_id = NULL
         WHERE request_level = 'work_unit'
           AND job_position_id IS NOT NULL
    """)
