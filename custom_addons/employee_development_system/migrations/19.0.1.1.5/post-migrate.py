from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Show already-submitted employee questionnaires on assigned trainer profiles."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    evaluation_model = env['eds.evaluation.level1']
    feedback_model = env['eds.trainer.feedback']
    last_id = 0
    while True:
        batch = evaluation_model.search([
            ('id', '>', last_id),
            ('state', 'in', ('submitted', 'consolidated')),
        ], order='id', limit=500)
        if not batch:
            break
        feedback_model.sync_from_level1(batch)
        last_id = batch[-1].id
