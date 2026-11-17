# -*- coding: utf-8 -*-
import logging
import threading
import time
from datetime import timedelta
from odoo import models, fields, api, SUPERUSER_ID, _, tools
from odoo.http import request

_logger = logging.getLogger(__name__)

# Global in-memory cache to debounce activity timestamp updates across concurrent web requests.
# Key: (user_id, base_sid) -> float monotonic timestamp
_ACTIVITY_LOCK = threading.Lock()
_ACTIVITY_CACHE = {}


class UserActiveSession(models.Model):
    _name = 'user.active.session'
    _description = 'Active User Session Registry'
    _order = 'last_activity desc, id desc'

    name = fields.Char(string='Session Title', compute='_compute_name', store=True)
    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', related='user_id.employee_id', store=True)
    sid = fields.Char(string='Session ID', required=True, index=True)
    ip_address = fields.Char(string='IP Address')
    user_agent = fields.Char(string='User Agent / Browser')
    login_time = fields.Datetime(string='Login Time', default=fields.Datetime.now, required=True)
    last_activity = fields.Datetime(string='Last Activity', default=fields.Datetime.now, required=True, index=True)
    is_active = fields.Boolean(string='Is Active', default=True, index=True)

    @api.depends('user_id', 'sid')
    def _compute_name(self):
        for rec in self:
            uname = rec.user_id.name if rec.user_id else 'Unknown'
            sid_short = rec.sid[:8] if rec.sid else ''
            rec.name = f"{uname} ({sid_short})"

    @api.model
    def get_idle_timeout(self):
        """Returns the idle logout timeout in seconds configured in odoo.conf (default: 600)."""
        try:
            val = tools.config.get('idle_logout_timeout', 600)
            return int(val) if val else 600
        except Exception:
            return 600

    @api.model
    def check_and_expire_idle_sessions(self, user_id=None):
        """
        Finds active user session records whose last_activity is older than
        idle_logout_timeout and updates their status to is_active = False.
        If user_id is provided, only checks sessions for that specific user.
        """
        timeout_sec = self.get_idle_timeout()
        if timeout_sec <= 0:
            return
        cutoff = fields.Datetime.now() - timedelta(seconds=timeout_sec)
        domain = [
            ('is_active', '=', True),
            ('last_activity', '<', cutoff)
        ]
        if user_id:
            domain.append(('user_id', '=', user_id))
        idle_sessions = self.sudo().search(domain)
        if idle_sessions:
            _logger.info(
                "Deactivating %d idle user session(s) older than %s seconds (last_activity < %s)",
                len(idle_sessions), timeout_sec, cutoff
            )
            try:
                with self.env.cr.savepoint():
                    idle_sessions.sudo().write({'is_active': False})
            except Exception as e:
                _logger.debug("Idle session expiration write skipped due to concurrency: %s", e)

    @api.autovacuum
    def _gc_idle_sessions(self):
        """Autovacuum cron to periodically sweep and deactivate idle sessions."""
        self.check_and_expire_idle_sessions()

    def action_kill_session(self):
        """Allows administrator to manually terminate a user session by changing its status to inactive."""
        for rec in self:
            _logger.info("Admin manually terminated session sid=%s for user_id=%s (%s)", rec.sid, rec.user_id.id, rec.user_id.login)
            rec.sudo().write({'is_active': False})
            with _ACTIVITY_LOCK:
                _ACTIVITY_CACHE.pop((rec.user_id.id, (rec.sid or '')[:30]), None)

    @api.model
    def _is_same_session(self, sid1, sid2):
        """
        Determines if two session tokens belong to the same browser session.
        Compares base session token (first 30 characters) to handle Odoo 19 res.device token appends.
        """
        if not sid1 or not sid2:
            return False
        if sid1 == sid2 or sid1.startswith(sid2) or sid2.startswith(sid1) or sid1[:30] == sid2[:30]:
            return True
        return False

    @api.model
    def check_and_register_login(self, user_id, sid, force_logout=False, ip_address=None, user_agent=None):
        if not user_id:
            return {'allow': True}

        self.check_and_expire_idle_sessions(user_id=user_id)

        active_sessions = self.sudo().search([
            ('user_id', '=', user_id),
            ('is_active', '=', True)
        ])

        if active_sessions and force_logout:
            _logger.info("User %s requested force logout — deactivating %d active session(s).", user_id, len(active_sessions))
            active_sessions.sudo().write({'is_active': False})
            with _ACTIVITY_LOCK:
                keys_to_del = [k for k in _ACTIVITY_CACHE if k[0] == user_id]
                for k in keys_to_del:
                    _ACTIVITY_CACHE.pop(k, None)
            if sid:
                self.register_or_update_active(user_id, sid, ip_address=ip_address, user_agent=user_agent)
            return {'allow': True}

        if active_sessions and not force_logout:
            # Check if sid matches any existing active session (same browser)
            if sid and any(self._is_same_session(s.sid, sid) for s in active_sessions):
                return {'allow': True}
            return {'allow': False, 'reason': 'active_session_exists'}

        if sid:
            self.register_or_update_active(user_id, sid, ip_address=ip_address, user_agent=user_agent)
        return {'allow': True}

    @api.model
    def register_or_update_active(self, user_id, sid, ip_address=None, user_agent=None):
        if not user_id or not sid:
            return False

        base_sid = sid[:30] if sid else ''
        cache_key = (user_id, base_sid)
        now_mono = time.monotonic()

        # 1. Fast-path in-memory monotonic debounce:
        # Avoids hitting the DB and prevents concurrent requests from attempting
        # simultaneous UPDATEs on the same session record.
        with _ACTIVITY_LOCK:
            last_seen = _ACTIVITY_CACHE.get(cache_key, 0)
            if now_mono - last_seen < 30:
                return True
            _ACTIVITY_CACHE[cache_key] = now_mono
            # Housekeeping: prune expired entries if cache grows
            if len(_ACTIVITY_CACHE) > 2000:
                cutoff_mono = now_mono - 3600
                expired = [k for k, v in _ACTIVITY_CACHE.items() if v < cutoff_mono]
                for k in expired:
                    _ACTIVITY_CACHE.pop(k, None)

        now = fields.Datetime.now()

        active_sessions = self.sudo().search([
            ('user_id', '=', user_id),
            ('is_active', '=', True)
        ])

        # Match by base session token
        matching = active_sessions.filtered(lambda s: self._is_same_session(s.sid, sid))
        if matching:
            session_rec = matching[0]

            # 2. Database update using isolated cursor and non-blocking advisory transaction lock.
            # This completely prevents PostgreSQL "could not serialize access due to concurrent update"
            # across concurrent threads/workers, with zero locking contention and zero bad-query logs.
            try:
                with self.env.registry.cursor() as new_cr:
                    new_cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (847291, session_rec.id))
                    locked = new_cr.fetchone()[0]
                    if locked:
                        new_cr.execute("""
                            UPDATE user_active_session
                            SET sid = %s,
                                last_activity = %s,
                                ip_address = COALESCE(%s, ip_address),
                                user_agent = COALESCE(%s, user_agent),
                                write_date = %s,
                                write_uid = %s
                            WHERE id = %s
                        """, (
                            sid,
                            now,
                            ip_address or None,
                            user_agent or None,
                            now,
                            self.env.uid or SUPERUSER_ID,
                            session_rec.id
                        ))
                        new_cr.commit()
            except Exception as e:
                _logger.debug("Non-blocking session activity update skipped: %s", e)

            session_rec.invalidate_recordset(['sid', 'last_activity', 'ip_address', 'user_agent'])
            return session_rec

        # If no active session exists for this user and token, create one
        try:
            return self.sudo().create({
                'user_id': user_id,
                'sid': sid,
                'ip_address': ip_address,
                'user_agent': user_agent,
                'login_time': now,
                'last_activity': now,
                'is_active': True,
            })
        except Exception as e:
            _logger.debug("Active session record creation skipped: %s", e)
            return False

    @api.model
    def terminate_session(self, sid=None, user_id=None):
        """
        Deactivates session record(s) when a user logs out or session is terminated.
        Updates session status from Active (is_active = True) to Inactive (is_active = False).
        """
        if not sid and not user_id:
            return

        with _ACTIVITY_LOCK:
            if user_id:
                keys_to_del = [k for k in _ACTIVITY_CACHE if k[0] == user_id]
                for k in keys_to_del:
                    _ACTIVITY_CACHE.pop(k, None)
            elif sid:
                base_sid = (sid or '')[:30]
                keys_to_del = [k for k in _ACTIVITY_CACHE if k[1] == base_sid]
                for k in keys_to_del:
                    _ACTIVITY_CACHE.pop(k, None)

        target_uid = user_id or (self.env.uid if self.env.uid and self.env.uid != SUPERUSER_ID else None)
        domain = [('is_active', '=', True)]
        if target_uid:
            domain.append(('user_id', '=', target_uid))

        active_sessions = self.sudo().search(domain)
        if not active_sessions:
            return

        matching = False
        if sid:
            matching = active_sessions.filtered(lambda s: self._is_same_session(s.sid, sid))

        if matching:
            _logger.info("Deactivating session matching sid=%s for user_id=%s on logout", sid, matching.mapped('user_id.id'))
            matching.sudo().write({'is_active': False})
        else:
            _logger.info("Deactivating %d active session(s) for user_id=%s on logout", len(active_sessions), target_uid)
            active_sessions.sudo().write({'is_active': False})

    @api.model
    def is_session_valid(self, user_id, sid):
        if not user_id or not sid:
            return True

        user = self.env['res.users'].sudo().browse(user_id)
        if not user.exists() or user._is_public():
            return True

        self.check_and_expire_idle_sessions(user_id=user_id)

        active_sessions = self.sudo().search([
            ('user_id', '=', user_id),
            ('is_active', '=', True)
        ])

        if not active_sessions:
            # If no active session is registered in DB, allow
            return True

        # Check if sid matches any active session for this user
        matching = active_sessions.filtered(lambda s: self._is_same_session(s.sid, sid))
        if matching:
            return True

        return False
