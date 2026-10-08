import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ReslSoftDeleteMixin(models.AbstractModel):
    """Soft delete: a record "deleted" from the front end is NOT removed from
    the database. It is marked instead:

        del_flag = True      (who: del_uid, when: del_date)
        active   = False     (so it disappears from every list, search,
                              kanban and many2one automatically)

    Un-archiving a record clears the mark again. A real SQL delete is still
    possible on purpose by passing context `resl_hard_delete=True` (never done
    from the UI).
    """
    _name = 'resl.soft.delete.mixin'
    _description = 'Soft delete (del_flag) for RESL records'

    active = fields.Boolean(
        default=True, index=True, copy=False,
        readonly=True,  # hides the Archive/Unarchive gear-menu actions in the UI; code can still write it
    )
    del_flag = fields.Boolean(
        string='Deleted', default=False, index=True, copy=False, readonly=True,
        help="Set when the record was deleted from the front end. The row is kept in the database.",
    )
    del_date = fields.Datetime(string='Deleted On', copy=False, readonly=True)
    del_uid = fields.Many2one('res.users', string='Deleted By', copy=False, readonly=True)

    def write(self, vals):
        # Keep active and del_flag in sync, whichever one the caller touches
        # (Delete button, Archive / Unarchive from the gear menu, code).
        if 'active' in vals:
            vals = dict(vals)
            if vals['active']:
                vals.update(del_flag=False, del_date=False, del_uid=False)
            else:
                vals.update(del_flag=True, del_date=fields.Datetime.now(), del_uid=self.env.user.id)
        return super().write(vals)

    def _soft_delete(self):
        """Flag the records as deleted instead of removing them."""
        if self:
            _logger.info("Soft-deleting %s ids=%s by user %s", self._name, self.ids, self.env.uid)
            self.sudo().write({'active': False})
        return True

    def unlink(self):
        if self.env.context.get('resl_hard_delete'):
            return super().unlink()
        return self._soft_delete()