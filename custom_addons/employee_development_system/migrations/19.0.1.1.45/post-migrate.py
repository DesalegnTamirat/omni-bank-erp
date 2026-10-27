"""Link current-year selected competency needs to unambiguous catalog courses.

Older competency imports kept a proposed program title but no course link.
Only exact, unique catalog matches are repaired; ambiguous or absent matches
remain for L&D review. Preserve demand and evidence IDs while resyncing.
"""

import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT line.id, line.cycle_id, catalog.id, line.course_name
          FROM eds_tna_cycle_course_line AS line
          JOIN eds_tna_cycle AS cycle ON cycle.id = line.cycle_id
          JOIN (
                SELECT lower(btrim(name)) AS course_key, min(id) AS id
                  FROM eds_course
                 GROUP BY lower(btrim(name))
                HAVING count(*) = 1
               ) AS catalog
            ON catalog.course_key = lower(btrim(line.course_name))
         WHERE cycle.year = to_char(current_date, 'YYYY')
           AND cycle.state = 'closed'
           AND line.selected_for_planning IS TRUE
           AND line.total_employees > 0
           AND line.course_id IS NULL
           AND NOT EXISTS (
                SELECT 1 FROM eds_tna_cycle_course_line AS existing
                 WHERE existing.cycle_id = line.cycle_id
                   AND existing.course_id = catalog.id
           )
    """)
    targets = cr.fetchall()
    cycle_ids = set()
    repaired = 0
    for line_id, cycle_id, course_id, course_name in targets:
        cr.execute("""
            UPDATE eds_tna_entry AS entry
               SET course_id = %s
             WHERE entry.course_id IS NULL
               AND entry.is_custom_course IS FALSE
               AND lower(btrim(entry.proposed_program)) = lower(btrim(%s))
               AND EXISTS (
                    SELECT 1
                      FROM eds_tna_cycle_course_evidence AS evidence
                      JOIN eds_tna_cycle_course_employee AS demand
                        ON demand.id = evidence.demand_id
                     WHERE evidence.entry_id = entry.id
                       AND demand.course_line_id = %s
               )
        """, [course_id, course_name, line_id])
        cr.execute("""
            SELECT count(*)
              FROM eds_tna_cycle_course_evidence AS evidence
              JOIN eds_tna_cycle_course_employee AS demand
                ON demand.id = evidence.demand_id
              JOIN eds_tna_entry AS entry ON entry.id = evidence.entry_id
             WHERE demand.course_line_id = %s
               AND entry.course_id IS DISTINCT FROM %s
        """, [line_id, course_id])
        if cr.fetchone()[0]:
            continue
        cr.execute("""
            UPDATE eds_tna_cycle_course_line
               SET course_id = %s
             WHERE id = %s
        """, [course_id, line_id])
        cycle_ids.add(cycle_id)
        repaired += 1

    if cycle_ids:
        env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True})
        env.invalidate_all()
        for cycle in env['eds.tna.cycle'].browse(sorted(cycle_ids)):
            cycle._sync_course_demand()
    _logger.info('Linked %s current-year selected TNA demands to catalog courses.', repaired)
