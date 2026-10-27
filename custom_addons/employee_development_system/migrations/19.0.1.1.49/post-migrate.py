"""Correct saved work-unit headcounts from their nominated employees."""

import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        WITH selected AS (
            SELECT entry.id, count(rel.employee_id)::integer AS employee_count
              FROM eds_tna_entry AS entry
              LEFT JOIN eds_tna_entry_work_unit_emps_rel AS rel
                ON rel.entry_id = entry.id
             WHERE entry.request_level = 'work_unit'
             GROUP BY entry.id
        )
        UPDATE eds_tna_entry AS entry
           SET target_participant_count = selected.employee_count
          FROM selected
         WHERE entry.id = selected.id
           AND entry.target_participant_count IS DISTINCT FROM selected.employee_count
    """)
    _logger.info('Corrected %s work-unit TNA employee counts.', cr.rowcount)
