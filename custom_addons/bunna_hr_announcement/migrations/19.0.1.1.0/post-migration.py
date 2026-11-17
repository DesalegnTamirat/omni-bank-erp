# -*- coding: utf-8 -*-
from html import escape


def migrate(cr, version):
    """Body changed from plain Text to Html: keep old paragraphs and line breaks."""
    cr.execute("SELECT id, body FROM bunna_announcement WHERE body IS NOT NULL")
    for rec_id, body in cr.fetchall():
        if not body or body.lstrip().startswith('<'):
            continue
        paragraphs = [p for p in body.replace('\r\n', '\n').split('\n\n') if p.strip()]
        html = ''.join('<p>%s</p>' % escape(p.strip()).replace('\n', '<br/>') for p in paragraphs)
        cr.execute("UPDATE bunna_announcement SET body = %s WHERE id = %s", (html, rec_id))
