"""Remove unused session recurrence data."""


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE eds_session
          DROP COLUMN IF EXISTS recurrence,
          DROP COLUMN IF EXISTS recurrence_details
    """)
