# -*- coding: utf-8 -*-
"""
Migration 19.0.6.0.0
All original question types are preserved as-is.
Only 'selection' (introduced temporarily) is mapped back to 'custom'.
"""


def migrate(cr, version):
    # If any record was saved with the temporary 'selection' type, map it back
    for table in ('hr_exit_interview_question', 'hr_exit_interview_line'):
        cr.execute(f"""
            UPDATE {table}
            SET question_type = 'custom'
            WHERE question_type = 'selection';
        """)
