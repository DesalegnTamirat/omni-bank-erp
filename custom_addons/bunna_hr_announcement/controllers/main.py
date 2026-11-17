# -*- coding: utf-8 -*-
import base64
import urllib.parse

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request
from odoo.tools.mimetypes import guess_mimetype

# Set to True to make announcements visible to logged-in users only.
REQUIRE_LOGIN = False

IMAGE_MIMETYPES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}

MIMETYPES = {
    'pdf': 'application/pdf',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xls': 'application/vnd.ms-excel',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
}


class BunnaAnnouncementController(http.Controller):

    def _login_redirect(self, path):
        if REQUIRE_LOGIN and request.env.user._is_public():
            return request.redirect('/web/login?redirect=%s' % path)
        return None

    @http.route(['/announcements', '/announcements/page/<int:page>'],
                type='http', auth='public', website=True, sitemap=False)
    def announcement_list(self, page=1, category=None, **kw):
        redirect = self._login_redirect('/announcements')
        if redirect:
            return redirect

        Announcement = request.env['bunna.announcement'].sudo()
        categories = request.env['bunna.announcement.category'].sudo().search([])

        try:
            category_id = int(category or 0)
        except (TypeError, ValueError):
            category_id = 0
        selected_category = categories.filtered(lambda c: c.id == category_id)

        domain = Announcement._website_domain()
        if selected_category:
            domain.append(('category_id', '=', selected_category.id))

        page_size = request.env['bunna.announcement.settings'].sudo().get_page_size()
        total = Announcement.search_count(domain)
        pager = request.website.pager(
            url='/announcements',
            url_args={'category': selected_category.id} if selected_category else None,
            total=total, page=page, step=page_size)
        announcements = Announcement.search(
            domain, limit=page_size, offset=pager['offset'])

        return request.render('bunna_hr_announcement.announcement_list_page', {
            'announcements': announcements,
            'pager': pager,
            'categories': categories,
            'selected_category': selected_category,
        })

    @http.route('/announcements/<int:announcement_id>',
                type='http', auth='public', website=True, sitemap=False)
    def announcement_detail(self, announcement_id, **kw):
        redirect = self._login_redirect('/announcements/%s' % announcement_id)
        if redirect:
            return redirect

        Announcement = request.env['bunna.announcement'].sudo()
        announcement = Announcement.search(
            Announcement._website_domain() + [('id', '=', announcement_id)], limit=1)
        if not announcement:
            # Draft, revoked, expired or unknown: never reveal it exists.
            return request.not_found()

        return request.render('bunna_hr_announcement.announcement_detail_page', {
            'announcement': announcement,
        })

    @http.route('/announcements/<int:announcement_id>/attachment/<int:attachment_id>',
                type='http', auth='public', website=True, sitemap=False)
    def announcement_attachment(self, announcement_id, attachment_id, download=None, **kw):
        redirect = self._login_redirect('/announcements/%s' % announcement_id)
        if redirect:
            return redirect

        Announcement = request.env['bunna.announcement'].sudo()
        announcement = Announcement.search(
            Announcement._website_domain() + [('id', '=', announcement_id)], limit=1)
        attachment = announcement.attachment_ids.filtered(lambda a: a.id == attachment_id)
        if not attachment:
            # Unpublished/revoked post or wrong id: files are never served.
            return request.not_found()

        want_download = str(download) == '1'
        inline = attachment.is_viewable and not want_download
        # Server-side enforcement of the per-post download setting
        if not announcement.allow_download and not inline:
            raise Forbidden()

        # View-only files may only be shown inside the post page (iframe/img),
        # not opened directly in a new tab/window.
        if inline and not announcement.allow_download:
            if request.httprequest.headers.get('Sec-Fetch-Dest') == 'document':
                return request.redirect('/announcements/%s' % announcement_id)

        content = base64.b64decode(attachment.file or b'')
        mimetype = MIMETYPES.get(attachment.extension, 'application/octet-stream')
        disposition = 'inline' if inline else 'attachment'
        headers = [
            ('Content-Type', mimetype),
            ('Content-Length', str(len(content))),
            ('Content-Disposition',
             "%s; filename*=UTF-8''%s" % (disposition, urllib.parse.quote(attachment.file_name))),
            ('X-Content-Type-Options', 'nosniff'),
            ('Cache-Control', 'private, max-age=600'),
        ]
        return request.make_response(content, headers=headers)

    @http.route('/announcements/<int:announcement_id>/image',
                type='http', auth='public', website=True, sitemap=False)
    def announcement_image(self, announcement_id, size='large', **kw):
        redirect = self._login_redirect('/announcements/%s' % announcement_id)
        if redirect:
            return redirect

        Announcement = request.env['bunna.announcement'].sudo()
        announcement = Announcement.search(
            Announcement._website_domain() + [('id', '=', announcement_id)], limit=1)
        if not announcement or not announcement.has_image:
            return request.not_found()

        data = announcement.image_256 if size == 'small' and announcement.image_256 else announcement.image
        content = base64.b64decode(data or b'')
        mimetype = guess_mimetype(content)
        if mimetype not in IMAGE_MIMETYPES:
            return request.not_found()
        headers = [
            ('Content-Type', mimetype),
            ('Content-Length', str(len(content))),
            ('X-Content-Type-Options', 'nosniff'),
            ('Cache-Control', 'private, max-age=600'),
        ]
        return request.make_response(content, headers=headers)
