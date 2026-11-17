from odoo import models


class IrRule(models.Model):
    _inherit = 'ir.rule'

    def _compute_domain_context_values(self):
        """ir.rule._compute_domain is ormcache'd per (uid, model, mode,
        context keys). The RESL delegation rules put the user's delegators
        (res.users.resl_effective_user_ids, resl_deleg_*, scope work units)
        straight into the domain, so without this the first domain computed
        for a user stays cached: a delegation created, ended or starting
        later was ignored and the delegate never saw the request.

        Adding the user's CURRENT delegators to the cache key gives a fresh
        domain whenever the delegation situation changes (new / ended
        delegation, start or end date reached).
        """
        yield from super()._compute_domain_context_values()
        if self.env.su or not self.env.uid:
            yield None
            return
        memo = self.env.cr.cache.setdefault('resl_delegation_signature', {})
        uid = self.env.uid
        if uid not in memo:
            try:
                memo[uid] = tuple(sorted(self.env.user._resl_delegator_users().ids))
            except Exception:
                memo[uid] = ()
        yield memo[uid]