def migrate(cr, version):
    """Keep existing examination files private when sharing controls arrive."""
    cr.execute("""
        UPDATE eds_material
           SET visibility = 'staff'
         WHERE material_type = 'examination'
           AND visibility = 'participants'
    """)
