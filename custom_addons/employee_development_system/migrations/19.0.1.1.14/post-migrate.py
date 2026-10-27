def migrate(cr, version):
    """Fold the retired cycle approval stages into the closed collection state."""
    cr.execute("""
        UPDATE eds_tna_cycle
           SET state = 'closed'
         WHERE state IN ('consolidating', 'under_approval', 'approved', 'locked')
    """)
