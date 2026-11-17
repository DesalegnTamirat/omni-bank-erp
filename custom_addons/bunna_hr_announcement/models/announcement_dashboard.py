# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

GROUP_DRAFTER = 'bunna_hr_announcement.group_announcement_drafter'
GROUP_PUBLISHER = 'bunna_hr_announcement.group_announcement_publisher'
GROUP_ADMIN = 'bunna_hr_announcement.group_announcement_manager'

EXPIRY_WARNING_DAYS = 7
LIST_LIMIT = 5
CHART_DAYS = 14
STATS_DAYS = 30


class BunnaAnnouncementDashboard(models.AbstractModel):
    """Numbers for the Announcements dashboard.

    Everything is read with the current user's own access rights, so a Drafter only ever
    counts and sees their own announcements (the record rules do the filtering).
    """
    _name = 'bunna.announcement.dashboard'
    _description = 'Announcement Dashboard'

    # ------------------------------------------------------------------
    @api.model
    def _fmt(self, value):
        if not value:
            return ''
        return fields.Datetime.context_timestamp(self, value).strftime('%d %b %Y, %H:%M')

    @api.model
    def get_data(self):
        user = self.env.user
        is_admin = user.has_group(GROUP_ADMIN)
        is_publisher = is_admin or user.has_group(GROUP_PUBLISHER)
        is_drafter = is_publisher or user.has_group(GROUP_DRAFTER)
        if not is_drafter:
            raise AccessError(_("The dashboard is for Announcement Drafters, Publishers and Administrators."))
        role = 'admin' if is_admin else 'publisher' if is_publisher else 'drafter'
        role_label = {'admin': _("Administrator"), 'publisher': _("Publisher"), 'drafter': _("Drafter")}[role]

        Ann = self.env['bunna.announcement']
        now = fields.Datetime.now()
        soon = now + timedelta(days=EXPIRY_WARNING_DAYS)
        status_labels = dict(Ann._fields['live_status'].selection)

        live = [('state', '=', 'published'),
                '|', ('date_published', '=', False), ('date_published', '<=', now),
                '|', ('date_expire', '=', False), ('date_expire', '>', now)]
        counts = {
            'draft': [('state', '=', 'draft')],
            'scheduled': [('state', '=', 'published'), ('date_published', '>', now)],
            'live': live,
            'expired': [('state', '=', 'published'), ('date_expire', '!=', False), ('date_expire', '<=', now)],
            'revoked': [('state', '=', 'revoked')],
        }

        def status_kpi(key, label, tone, hint):
            return {
                'key': key, 'label': label, 'tone': tone, 'hint': hint,
                'value': Ann.search_count(counts[key]),
                'res_model': 'bunna.announcement',
                'domain': [('live_status', '=', key)],
            }

        kpis = [
            status_kpi('live', _("Live"), 'success', _("Visible on the website now")),
            status_kpi('scheduled', _("Scheduled"), 'info', _("Waiting for the publish date")),
            status_kpi('draft', _("Drafts"), 'muted',
                       _("Not published yet") if is_publisher else _("Your drafts")),
            status_kpi('expired', _("Expired"), 'warning', _("Past the expiry date")),
            status_kpi('revoked', _("Revoked"), 'danger', _("Taken down")),
        ]

        data = {
            'role': role,
            'role_label': role_label,
            'user_name': user.name,
            'scope_note': '' if is_publisher else _("You see your own announcements only."),
            'today': fields.Date.context_today(self).strftime('%A, %d %B %Y'),
            'can_create': is_drafter,
            'kpis': kpis,
            'chart': None,
            'top': [],
            'lists': [],
            'links': [],
        }

        def item(rec, meta=''):
            return {'id': rec.id, 'name': rec.name or _("(No title)"),
                    'status': rec.live_status, 'status_label': status_labels.get(rec.live_status, ''),
                    'meta': meta}

        # ---- Lists everybody gets ----------------------------------------
        drafts = Ann.search([('state', '=', 'draft')], order='write_date desc, id desc', limit=LIST_LIMIT)
        data['lists'].append({
            'key': 'drafts',
            'title': _("Drafts waiting to be published") if is_publisher else _("My drafts"),
            'empty': _("No drafts."),
            'items': [item(r, _("Edited %s", self._fmt(r.write_date))) for r in drafts],
        })
        scheduled = Ann.search(counts['scheduled'], order='date_published asc', limit=LIST_LIMIT)
        data['lists'].append({
            'key': 'scheduled',
            'title': _("Going live next"),
            'empty': _("Nothing scheduled."),
            'items': [item(r, _("Publishes %s", self._fmt(r.date_published))) for r in scheduled],
        })
        data['links'].append({'label': _("All announcements"), 'action': 'action_bunna_announcement'})

        # ---- Publisher and Administrator ---------------------------------
        if is_publisher:
            Comment = self.env['bunna.announcement.comment']
            Daily = self.env['bunna.announcement.view.daily']

            expiring_domain = live + [('date_expire', '!=', False), ('date_expire', '<=', soon)]
            kpis.append({
                'key': 'expiring', 'label': _("Expiring soon"), 'tone': 'warning',
                'hint': _("Live, ends within %s days", EXPIRY_WARNING_DAYS),
                'value': Ann.search_count(expiring_domain),
                'res_model': 'bunna.announcement', 'domain': expiring_domain,
            })
            kpis.append({
                'key': 'pending_comments', 'label': _("Comments to review"), 'tone': 'primary',
                'hint': _("Waiting for a moderator"),
                'value': Comment.search_count([('state', '=', 'pending')]),
                'action': 'action_bunna_announcement_comment',
            })
            kpis.append({
                'key': 'reported_comments', 'label': _("Reported comments"), 'tone': 'danger',
                'hint': _("Readers flagged them"),
                'value': Comment.search_count([('state', '!=', 'hidden'), ('report_count', '>', 0)]),
                'res_model': 'bunna.announcement.comment',
                'domain': [('state', '!=', 'hidden'), ('report_count', '>', 0)],
            })

            expiring = Ann.search(expiring_domain, order='date_expire asc', limit=LIST_LIMIT)
            data['lists'].insert(0, {
                'key': 'expiring',
                'title': _("Expiring in the next %s days", EXPIRY_WARNING_DAYS),
                'empty': _("Nothing is about to expire."),
                'items': [item(r, _("Expires %s", self._fmt(r.date_expire))) for r in expiring],
            })

            # Readership: last 14 days chart, 30 day totals, top announcements
            today = Daily._today_local()
            start = today - timedelta(days=CHART_DAYS - 1)
            by_day = {}
            for day, views in Daily._read_group([('date', '>=', start)], ['date:day'], ['views:sum']):
                day = day.date() if hasattr(day, 'date') else day
                by_day[day] = int(views or 0)
            points = []
            for i in range(CHART_DAYS):
                day = start + timedelta(days=i)
                points.append({'label': day.strftime('%d %b'), 'short': day.strftime('%d'),
                               'value': by_day.get(day, 0)})
            since = today - timedelta(days=STATS_DAYS - 1)
            totals = Daily._read_group([('date', '>=', since)], [], ['views:sum', 'unique_visitors:sum'])
            total_views, total_visitors = (int(v or 0) for v in (totals[0] if totals else (0, 0)))
            data['chart'] = {
                'title': _("Views, last %s days", CHART_DAYS),
                'points': points,
                'max': max([p['value'] for p in points] + [1]),
                'summary': _("%(views)s views and %(visitors)s new visitors in the last %(days)s days",
                             views=total_views, visitors=total_visitors, days=STATS_DAYS),
            }
            kpis.append({
                'key': 'views', 'label': _("Views (%s days)", STATS_DAYS), 'tone': 'primary',
                'hint': _("%s new visitors", total_visitors), 'value': total_views,
                'action': 'action_bunna_announcement_readership',
            })
            for announcement, views in Daily._read_group(
                    [('date', '>=', since)], ['announcement_id'], ['views:sum'],
                    order='views:sum desc', limit=LIST_LIMIT):
                if views:
                    data['top'].append({'id': announcement.id, 'name': announcement.name or _("(No title)"),
                                        'value': int(views)})

            data['links'] += [
                {'label': _("Publishing report"), 'action': 'action_bunna_announcement_report'},
                {'label': _("Comments"), 'action': 'action_bunna_announcement_comment'},
                {'label': _("Readership"), 'action': 'action_bunna_announcement_readership'},
                {'label': _("Audit log"), 'action': 'action_bunna_announcement_log'},
            ]

        # ---- Administrator only ------------------------------------------
        if is_admin:
            Log = self.env['bunna.announcement.log']
            kpis.append({
                'key': 'archived', 'label': _("Archived"), 'tone': 'muted',
                'hint': _("Hidden everywhere"),
                'value': Ann.with_context(active_test=False).search_count([('active', '=', False)]),
                'res_model': 'bunna.announcement', 'domain': [('active', '=', False)],
            })
            kpis.append({
                'key': 'edited', 'label': _("Edits after publishing"), 'tone': 'warning',
                'hint': _("Last 7 days"),
                'value': Log.search_count([('action', '=', 'edited'),
                                           ('date', '>=', now - timedelta(days=7))]),
                'action': 'action_bunna_announcement_log',
            })
            data['links'] += [
                {'label': _("Website settings"), 'action': 'action_bunna_announcement_settings'},
                {'label': _("Categories"), 'action': 'action_bunna_announcement_category'},
                {'label': _("Priorities"), 'action': 'action_bunna_announcement_priority'},
            ]

        return data
