from odoo import models, api, fields


class DiscussChannelCustom(models.Model):
    _inherit = 'discuss.channel'

    @api.model
    def _get_or_create_chat(self, partners_to, pin=False):
        """Override default pin=False so automated system notifications 
        do not automatically pin 1-on-1 chat channels in the Discuss sidebar."""
        return super()._get_or_create_chat(partners_to, pin=pin)

    def message_post(self, **kwargs):
        """Post message and ensure automated system notifications keep 
        chat/group channels unpinned from the Discuss left sidebar."""
        res = super().message_post(**kwargs)
        for channel in self:
            if channel.channel_type in ('chat', 'group'):
                now = fields.Datetime.now()
                channel.mapped('channel_member_ids').sudo().write({
                    'is_pinned': False,
                    'unpin_dt': now,
                })
        return res
