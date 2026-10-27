"""Give legacy text-only plan programs catalog identities.

Approved plan programs need usable courses for session scheduling. Older draft
programs become draft catalog entries so they remain identifiable and can be
reviewed before the plan advances.
"""

from collections import defaultdict

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['eds.annual.plan.line'].search([
        ('course_id', '=', False), ('program_name', '!=', False),
    ])
    by_name = defaultdict(list)
    for line in lines:
        name = (line.program_name or '').strip()
        if name:
            by_name[name.casefold()].append(line)

    catalog = defaultdict(list)
    for course in env['eds.course'].with_context(active_test=False).search([]):
        catalog[course.name.strip().casefold()].append(course)

    changed_ids = []
    for key, group in by_name.items():
        approved = any(line.plan_id.state in ('published', 'amended') for line in group)
        candidates = [course for course in catalog[key]
                      if course.status in ('draft', 'active')]
        if candidates:
            course = sorted(candidates, key=lambda item: (item.status != 'active', item.id))[0]
        else:
            sample = group[0]
            course = env['eds.course'].create({
                'name': sample.program_name.strip(),
                'status': 'active' if approved else 'draft',
                'program_category': sample.program_category or 'technical_functional',
                'target_audience': sample.target_audience or 'all_staff',
                'recommended_source': sample.delivery_method or 'internal',
                'duration_days': max(sample.duration_days or 1, 1),
            })
            catalog[key].append(course)

        ids = [line.id for line in group]
        changed_ids.extend(ids)
        cr.execute("""
            UPDATE eds_annual_plan_line
               SET course_id = %s, program_name = %s
             WHERE id = ANY(%s)
        """, [course.id, course.name, ids])
        cr.execute("""
            UPDATE eds_session
               SET course_id = %s, program_name = %s
             WHERE plan_line_id = ANY(%s) AND course_id IS NULL
        """, [course.id, course.name, ids])
        cr.execute("""
            UPDATE eds_course_vendor_selection
               SET course_id = %s
             WHERE plan_line_id = ANY(%s) AND course_id IS NULL
        """, [course.id, ids])
        cr.execute("""
            UPDATE eds_hotel_selection
               SET course_id = %s
             WHERE plan_line_id = ANY(%s) AND course_id IS NULL
        """, [course.id, ids])

    if changed_ids:
        env.invalidate_all()
        env['eds.annual.plan.line'].browse(changed_ids).modified(['course_id', 'program_name'])
