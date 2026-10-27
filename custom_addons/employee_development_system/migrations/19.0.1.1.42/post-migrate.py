"""Show course certificate wording on existing sessions without replacing edits."""


def migrate(cr, version):
    for field_name in (
        'certificate_title', 'certificate_body_text',
        'certificate_signatory_name', 'certificate_signatory_title',
    ):
        cr.execute(f"""
            UPDATE eds_session AS session
               SET {field_name} = course.{field_name}
              FROM eds_course AS course
             WHERE session.course_id = course.id
               AND (session.{field_name} IS NULL OR session.{field_name} = '')
               AND course.{field_name} IS NOT NULL
               AND course.{field_name} != ''
        """)
