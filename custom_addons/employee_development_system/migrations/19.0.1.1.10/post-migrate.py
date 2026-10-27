from odoo import SUPERUSER_ID, api


def _batches(model, domain=None, size=500):
    last_id = 0
    while True:
        batch = model.search([('id', '>', last_id)] + (domain or []),
                             order='id', limit=size)
        if not batch:
            return
        yield batch
        last_id = batch[-1].id


def migrate(cr, version):
    """Refresh saved priorities and course demand after the scoring policy changes."""
    env = api.Environment(cr, SUPERUSER_ID, {'eds_allow_locked_edit': True})
    for entries in _batches(env['eds.tna.entry'], [('source', '=', 'manual')]):
        entries._compute_score_gap_severity()
        entries._compute_priority_score()

    for evidence in _batches(env['eds.tna.cycle.course.evidence']):
        evidence._compute_need_severity()

    for demand in _batches(env['eds.tna.cycle.course.employee']):
        demand._compute_need_severity()
        demand._compute_overall_priority_score()
    env.flush_all()
