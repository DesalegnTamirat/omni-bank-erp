# -*- coding: utf-8 -*-
import base64
import re
import urllib.parse
import uuid
from datetime import date, datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from werkzeug.exceptions import Forbidden

from odoo import _, http
from odoo.http import request
from odoo.tools.mimetypes import guess_mimetype

from .. import helpers

# Set to True to make announcements visible to logged-in users only.
REQUIRE_LOGIN = False

# ---- Search / filter / sort on the list page ----
SORTS = {
    'newest': 'date_published desc, id desc',
    'oldest': 'date_published asc, id asc',
    'title': 'name asc, id asc',
}
SORT_LABELS = {'newest': 'Newest first', 'oldest': 'Oldest first', 'title': 'Title A to Z'}
RANGE_LABELS = {
    'week': 'This week', 'month': 'This month', 'quarter': 'Last 3 months', 'year': 'This year'}
MAX_QUERY_LENGTH = 80
MAX_TERMS = 6

# ---- Anonymous comments ----
MIN_COMMENT_LENGTH = 3
TRIES_PER_HOUR = 20     # every attempt counts, so the human check cannot be guessed by brute force
REPORTS_PER_HOUR = 10
COMMENT_NOTICES = {
    'sent': ('success', 'Thank you. Your comment was received and will appear after it has been reviewed.'),
    'reported': ('success', 'Thank you. The comment was reported to the moderators.'),
    'closed': ('warning', 'Comments are closed for this announcement.'),
    'empty': ('danger', 'Please write your comment first.'),
    'short': ('danger', 'Your comment is too short.'),
    'long': ('danger', 'Your comment is too long. Please shorten it.'),
    'links': ('danger', 'Links are not allowed in comments.'),
    'challenge': ('danger', 'The answer to the question was not correct. Please try again.'),
    'expired': ('danger', 'The form was sent too quickly or has expired. Please try again.'),
    'rate': ('danger', 'Too many requests from your connection. Please try again later.'),
    'busy': ('warning', 'Comments on this announcement are paused for now because many are waiting for review.'),
}

# ---- Readership tracking (anonymous) ----
VISITOR_COOKIE = 'bunna_ann_vid'
TOKEN_RE = re.compile(r'^[0-9a-f]{32}$')
BOT_RE = re.compile(
    r'bot|crawl|spider|slurp|preview|headless|curl|wget|python-requests|httpclient|scrapy|'
    r'lighthouse|monitor|uptime|pingdom|facebookexternalhit', re.IGNORECASE)
GROUP_DRAFTER = 'bunna_hr_announcement.group_announcement_drafter'
GROUP_PUBLISHER = 'bunna_hr_announcement.group_announcement_publisher'

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

    @staticmethod
    def _secret():
        return request.env['ir.config_parameter'].sudo().get_param('database.secret') or 'bunna-announcements'

    def _fingerprint(self):
        """A one-way code that changes every day. It is only used to count requests."""
        return helpers.fingerprint(
            self._secret(), datetime.now(pytz.utc).date().isoformat(),
            request.httprequest.remote_addr, request.httprequest.headers.get('User-Agent', ''))

    def _archive_enabled(self):
        return bool(request.env['bunna.announcement.settings'].sudo().get_value('show_archive'))

    @staticmethod
    def _parse_date(value):
        try:
            return datetime.strptime((value or '').strip(), '%Y-%m-%d').date()
        except ValueError:
            return None

    def _list_params(self, kw, categories, archive_enabled):
        """Filter values from the web address. Anything invalid is simply ignored."""
        params = {}
        query = ' '.join((kw.get('q') or '').split())[:MAX_QUERY_LENGTH]
        if len(query) >= 2:
            params['q'] = query
        if kw.get('range') in RANGE_LABELS:
            params['range'] = kw['range']
        else:
            date_from = self._parse_date(kw.get('from'))
            date_to = self._parse_date(kw.get('to'))
            if date_from and date_to and date_from > date_to:
                date_from, date_to = date_to, date_from
            if date_from:
                params['from'] = date_from.isoformat()
            if date_to:
                params['to'] = date_to.isoformat()
        if kw.get('sort') in SORTS and kw['sort'] != 'newest':
            params['sort'] = kw['sort']
        if archive_enabled and kw.get('archive') == '1':
            params['archive'] = '1'
        try:
            category_id = int(kw.get('category') or 0)
        except (TypeError, ValueError):
            category_id = 0
        if category_id in categories.ids:
            params['category'] = str(category_id)
        return params

    @staticmethod
    def _url(params, **changes):
        """The list address with some filters changed or removed (value None removes it)."""
        merged = dict(params)
        for key, value in changes.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        return '/announcements' + ('?' + urllib.parse.urlencode(sorted(merged.items())) if merged else '')

    def _date_bounds(self, params, tz):
        """(start, end) of the chosen dates as UTC datetimes; days are counted in the company time zone."""
        today = datetime.now(pytz.utc).astimezone(tz).date()
        start_day = end_day = None
        key = params.get('range')
        if key == 'week':
            start_day = today - timedelta(days=today.weekday())
        elif key == 'month':
            start_day = today.replace(day=1)
        elif key == 'quarter':
            start_day = today - relativedelta(months=3)
        elif key == 'year':
            start_day = today.replace(month=1, day=1)
        else:
            if params.get('from'):
                start_day = date.fromisoformat(params['from'])
            if params.get('to'):
                end_day = date.fromisoformat(params['to']) + timedelta(days=1)

        def to_utc(day):
            return tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)

        return (to_utc(start_day) if start_day else None, to_utc(end_day) if end_day else None)

    def _list_domain(self, Announcement, params, tz):
        domain = Announcement._website_domain(include_expired=bool(params.get('archive')))
        for term in params.get('q', '').split()[:MAX_TERMS]:
            domain.append(('search_text', 'ilike', term))
        if params.get('category'):
            domain.append(('category_id', '=', int(params['category'])))
        start, end = self._date_bounds(params, tz)
        if start:
            domain.append(('date_published', '>=', start))
        if end:
            domain.append(('date_published', '<', end))
        return domain

    def _should_track(self):
        """Count only real readers: not bots, prefetches, or the people who manage announcements."""
        if not request.httprequest.method == 'GET':
            return False
        headers = request.httprequest.headers
        if 'prefetch' in (headers.get('Sec-Purpose', '') + headers.get('Purpose', '')).lower():
            return False
        user_agent = headers.get('User-Agent', '')
        if not user_agent or BOT_RE.search(user_agent):
            return False
        user = request.env.user
        if not user._is_public() and (user.has_group(GROUP_DRAFTER) or user.has_group(GROUP_PUBLISHER)):
            return False
        return bool(request.env['bunna.announcement.settings'].sudo().get_value('track_views'))

    def _login_redirect(self, path):
        if REQUIRE_LOGIN and request.env.user._is_public():
            return request.redirect('/web/login?redirect=%s' % path)
        return None

    @http.route(['/announcements', '/announcements/page/<int:page>'],
                type='http', auth='public', website=True, sitemap=False)
    def announcement_list(self, page=1, **kw):
        redirect = self._login_redirect('/announcements')
        if redirect:
            return redirect

        Announcement = request.env['bunna.announcement'].sudo()
        settings = request.env['bunna.announcement.settings'].sudo()
        categories = request.env['bunna.announcement.category'].sudo().search([])
        archive_enabled = self._archive_enabled()
        params = self._list_params(kw, categories, archive_enabled)
        selected_category = categories.filtered(lambda c: str(c.id) == params.get('category'))

        domain = self._list_domain(Announcement, params, settings.get_tz())
        total = Announcement.search_count(domain)
        page_size = settings.get_page_size()
        pager = request.website.pager(
            url='/announcements', url_args=params or None, total=total, page=page, step=page_size)
        announcements = Announcement.search(
            domain, order=SORTS[params.get('sort', 'newest')], limit=page_size, offset=pager['offset'])

        # "chips" for the active filters, each one removes itself when clicked
        chips = []
        if params.get('q'):
            chips.append({'label': _('Search: %s', params['q']), 'url': self._url(params, q=None)})
        if params.get('range'):
            chips.append({'label': RANGE_LABELS[params['range']], 'url': self._url(params, range=None)})
        if params.get('from'):
            chips.append({'label': _('From %s', params['from']), 'url': self._url(params, **{'from': None})})
        if params.get('to'):
            chips.append({'label': _('To %s', params['to']), 'url': self._url(params, to=None)})
        if selected_category:
            chips.append({'label': _('Category: %s', selected_category.name),
                          'url': self._url(params, category=None)})
        if params.get('archive'):
            chips.append({'label': _('Including expired'), 'url': self._url(params, archive=None)})
        if params.get('sort'):
            chips.append({'label': SORT_LABELS[params['sort']], 'url': self._url(params, sort=None)})

        return request.render('bunna_hr_announcement.announcement_list_page', {
            'announcements': announcements,
            'pager': pager,
            'categories': categories,
            'selected_category': selected_category,
            'category_urls': {c.id: self._url(params, category=str(c.id)) for c in categories},
            'all_url': self._url(params, category=None),
            'params': params,
            'chips': chips,
            'total': total,
            'has_filters': bool(params),
            'archive_enabled': archive_enabled,
            'range_options': list(RANGE_LABELS.items()),
            'sort_options': list(SORT_LABELS.items()),
        })

    @http.route('/announcements/<int:announcement_id>',
                type='http', auth='public', website=True, sitemap=False)
    def announcement_detail(self, announcement_id, **kw):
        redirect = self._login_redirect('/announcements/%s' % announcement_id)
        if redirect:
            return redirect

        Announcement = request.env['bunna.announcement'].sudo()
        announcement = Announcement.search(
            Announcement._website_domain(include_expired=self._archive_enabled()) + [('id', '=', announcement_id)], limit=1)
        if not announcement:
            # Draft, revoked, expired or unknown: never reveal it exists.
            return request.not_found()

        token = request.httprequest.cookies.get(VISITOR_COOKIE, '')
        new_token = False
        if self._should_track():
            if not TOKEN_RE.match(token):
                token = uuid.uuid4().hex  # random id, holds no personal data
                new_token = True
            request.env['bunna.announcement.view.daily'].sudo()._record_view(announcement.id, token)
        settings = request.env['bunna.announcement.settings'].sudo()
        comments_open = bool(
            announcement.allow_comments and settings.get_value('comments_site_enabled')
            and announcement.live_status == 'live')
        approved = announcement.comment_ids.filtered(lambda c: c.state == 'approved')
        approved = approved.sorted('id', reverse=True)[:200].sorted('id')
        response = request.render('bunna_hr_announcement.announcement_detail_page', {
            'announcement': announcement,
            'comments_open': comments_open,
            'approved_comments': approved,
            'show_comments': comments_open or bool(approved),
            'comment_notice': COMMENT_NOTICES.get(kw.get('comment')),
            'comment_max': settings.get_value('comment_max_length'),
            'challenge': helpers.new_challenge(self._secret()) if comments_open else None,
        })
        if new_token:
            response.set_cookie(VISITOR_COOKIE, token, max_age=365 * 24 * 3600, httponly=True,
                                samesite='Lax', secure=request.httprequest.is_secure)
        return response

    @http.route('/announcements/<int:announcement_id>/attachment/<int:attachment_id>',
                type='http', auth='public', website=True, sitemap=False)
    def announcement_attachment(self, announcement_id, attachment_id, download=None, **kw):
        redirect = self._login_redirect('/announcements/%s' % announcement_id)
        if redirect:
            return redirect

        Announcement = request.env['bunna.announcement'].sudo()
        announcement = Announcement.search(
            Announcement._website_domain(include_expired=self._archive_enabled()) + [('id', '=', announcement_id)], limit=1)
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

        if self._should_track():
            request.env['bunna.announcement.view.daily'].sudo()._record_file(
                announcement.id, 'open' if inline else 'download')

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
            Announcement._website_domain(include_expired=self._archive_enabled()) + [('id', '=', announcement_id)], limit=1)
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

    @http.route('/announcements/<int:announcement_id>/photo/<int:photo_id>',
                type='http', auth='public', website=True, sitemap=False)
    def announcement_photo(self, announcement_id, photo_id, size='thumb', **kw):
        redirect = self._login_redirect('/announcements/%s' % announcement_id)
        if redirect:
            return redirect

        Announcement = request.env['bunna.announcement'].sudo()
        announcement = Announcement.search(
            Announcement._website_domain(include_expired=self._archive_enabled())
            + [('id', '=', announcement_id)], limit=1)
        photo = request.env['bunna.announcement.photo'].sudo().search(
            [('id', '=', photo_id), ('announcement_id', '=', announcement.id)], limit=1) if announcement else None
        if not photo or not photo.has_image:
            # draft, revoked, expired (archive off) or unknown: photos are never served
            return request.not_found()

        hours = request.env['bunna.announcement.settings'].sudo().get_value('gallery_cache_hours')
        # the address changes when a photo does, so a long cache time is safe for edits
        cache_control = 'private, max-age=%s' % (hours * 3600) if hours else 'private, no-cache'
        data = photo.thumb if size != 'full' and photo.thumb else photo.image
        content = base64.b64decode(data or b'')
        mimetype = guess_mimetype(content)
        if mimetype not in IMAGE_MIMETYPES:
            return request.not_found()
        headers = [
            ('Content-Type', mimetype),
            ('Content-Length', str(len(content))),
            ('X-Content-Type-Options', 'nosniff'),
            ('Cache-Control', cache_control),
        ]
        return request.make_response(content, headers=headers)

    @http.route('/announcements/<int:announcement_id>/comment', type='http', auth='public',
                methods=['POST'], website=True, sitemap=False)
    def announcement_comment(self, announcement_id, **post):
        """Receive an anonymous comment. Nothing that identifies the sender is stored with it."""
        redirect = self._login_redirect('/announcements/%s' % announcement_id)
        if redirect:
            return redirect

        Announcement = request.env['bunna.announcement'].sudo()
        settings = request.env['bunna.announcement.settings'].sudo()
        announcement = Announcement.search(
            Announcement._website_domain() + [('id', '=', announcement_id)], limit=1)
        if not announcement:
            return request.not_found()

        def back(code):
            return request.redirect('/announcements/%s?%s#comments' % (
                announcement_id, urllib.parse.urlencode({'comment': code})))

        if not (announcement.allow_comments and settings.get_value('comments_site_enabled')):
            return back('closed')

        Throttle = request.env['bunna.announcement.throttle'].sudo()
        fingerprint = self._fingerprint()
        if Throttle._hit('try:' + fingerprint) > TRIES_PER_HOUR:
            return back('rate')
        if post.get('website'):
            return back('sent')  # a hidden field only robots fill in: pretend it worked

        status = helpers.verify_challenge(self._secret(), post.get('answer'), post.get('ts'), post.get('token'))
        if status != 'ok':
            return back(status)

        text = helpers.clean_comment(post.get('comment'))
        if not text:
            return back('empty')
        if len(text) < MIN_COMMENT_LENGTH:
            return back('short')
        if len(text) > settings.get_value('comment_max_length'):
            return back('long')
        if settings.get_value('comment_block_links') and helpers.has_link(text):
            return back('links')

        Comment = request.env['bunna.announcement.comment'].sudo()
        if Comment.search_count([('announcement_id', '=', announcement.id), ('state', '=', 'pending')]) \
                >= settings.get_value('comment_max_pending'):
            return back('busy')
        if Throttle._hit('ok:' + fingerprint) > settings.get_value('comment_rate_per_hour'):
            return back('rate')

        # only the text, the announcement and the DAY it arrived are stored
        Comment.create({
            'announcement_id': announcement.id,
            'body': text,
            'submitted_on': datetime.now(pytz.utc).astimezone(settings.get_tz()).date(),
        })
        announcement._alert_new_comment()
        return back('sent')

    @http.route('/announcements/comment/<int:comment_id>/report', type='http', auth='public',
                methods=['POST'], website=True, sitemap=False)
    def announcement_comment_report(self, comment_id, **post):
        Comment = request.env['bunna.announcement.comment'].sudo()
        comment = Comment.browse(comment_id).exists()
        if not comment or comment.state != 'approved':
            return request.not_found()
        Announcement = request.env['bunna.announcement'].sudo()
        announcement = Announcement.search(
            Announcement._website_domain() + [('id', '=', comment.announcement_id.id)], limit=1)
        if not announcement:
            return request.not_found()
        redirect = self._login_redirect('/announcements/%s' % announcement.id)
        if redirect:
            return redirect

        def back(code):
            return request.redirect('/announcements/%s?%s#comments' % (
                announcement.id, urllib.parse.urlencode({'comment': code})))

        Throttle = request.env['bunna.announcement.throttle'].sudo()
        fingerprint = self._fingerprint()
        if Throttle._hit('report:' + fingerprint) > REPORTS_PER_HOUR:
            return back('rate')
        if Throttle._hit('rc:%s:%s' % (comment.id, fingerprint)) > 1:
            return back('reported')  # the same reader already reported this comment

        request.env.cr.execute(
            "UPDATE bunna_announcement_comment SET report_count = report_count + 1 "
            "WHERE id = %s RETURNING report_count", (comment.id,))
        reports = request.env.cr.fetchone()[0]
        comment.invalidate_recordset(['report_count'])
        threshold = request.env['bunna.announcement.settings'].sudo().get_value('comment_report_hide_at')
        if threshold and reports >= threshold and comment.state == 'approved':
            comment._hide(_("Reported by readers"))
        return back('reported')
