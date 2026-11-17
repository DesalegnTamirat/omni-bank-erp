# -*- coding: utf-8 -*-
from odoo import api, models


class WebsiteMenu(models.Model):
    _inherit = 'website.menu'

    @api.model
    def _bunna_place_announcements_menu(self):
        """Put the Announcements link right after Home on every website.

        Odoo keeps one copy of each menu per website, and that copy keeps its
        original sequence, so the order has to be fixed on those copies.
        Safe to run many times: the result is always the same.
        """
        for website in self.env['website'].search([]):
            top = website.menu_id
            if not top:
                continue
            items = self.search([('parent_id', '=', top.id)], order='sequence, id')
            announcements = items.filtered(lambda m: m.url == '/announcements')
            if not announcements:
                continue
            others = items - announcements
            home = others.filtered(
                lambda m: m.url in ('/', '/home') or (m.name or '').strip().lower().startswith('home'))[:1]
            ordered = list(others)
            position = ordered.index(home) + 1 if home else 0
            ordered[position:position] = list(announcements)
            for index, menu in enumerate(ordered):
                sequence = (index + 1) * 10
                if menu.sequence != sequence:
                    menu.sequence = sequence