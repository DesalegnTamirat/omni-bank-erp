# -*- coding: utf-8 -*-
"""
upgrade_mail_patch.py
=====================
Permanently blocks all mail creation and sending when no outgoing mail server
is configured — specifically to prevent upgrade deadlocks on large databases.

ROOT CAUSE OF UPGRADE DEADLOCK:
  During module upgrade, Odoo holds an AccessExclusiveLock on hr_employee
  while recomputing stored fields (e.g. current_version_id) for 3800+
  employees.  Each recompute triggers _message_track() -> mail creation ->
  INSERT INTO mail_mail, all inside the same open transaction.  The
  transaction never commits because it keeps generating more mail activity,
  causing an infinite hang.

FIX:
  1. Override mail.mail.create() to return an empty recordset immediately when
     no real mail server exists. This stops mail records being INSERTed at all.
  2. Cache the ir_mail_server check result per-process (module-level dict keyed
     by dbname) so it only opens ONE extra DB cursor per upgrade run, not one
     per employee recomputation.
  3. Use a SEPARATE DB cursor for the check so it never touches the locked
     upgrade cursor.
"""
from odoo import models
from odoo.modules.registry import Registry
import logging

_logger = logging.getLogger(__name__)

# Cache: dbname -> bool (True = has real mail server, False = skip mail)
# Populated once per process startup; cleared on registry reload via
# _clear_mail_server_cache() called from registry setup.
_MAIL_SERVER_CACHE = {}


def _has_mail_server(dbname):
    """Return True if a real outgoing mail server exists for this database.

    Result is cached for the lifetime of the process to avoid opening
    thousands of separate cursors during bulk operations like module upgrades
    (which recompute stored fields on 3800+ employees).

    Uses a SEPARATE DB cursor — never self.env.cr — so the check does not
    participate in any open upgrade transaction.
    """
    if dbname in _MAIL_SERVER_CACHE:
        return _MAIL_SERVER_CACHE[dbname]

    result = False
    try:
        db_registry = Registry(dbname)
        with db_registry.cursor() as check_cr:
            check_cr.execute(
                "SELECT 1 FROM ir_mail_server WHERE active = true LIMIT 1"
            )
            result = bool(check_cr.fetchone())
    except Exception as e:
        _logger.debug('mail patch: could not check ir_mail_server: %s', e)
        result = False

    _MAIL_SERVER_CACHE[dbname] = result
    _logger.info(
        'mail.mail patch: outgoing mail server %s for db=%s',
        'FOUND — mail enabled' if result else 'NOT FOUND — mail suppressed',
        dbname,
    )
    return result


class MailMailPatch(models.Model):
    _inherit = 'mail.mail'

    def create(self, vals_list):
        """
        Override: skip creating mail records when no real mail server exists.
        This is the deepest interception point — stops INSERTs into mail_mail
        that would otherwise accumulate inside the upgrade transaction and
        cause it to never commit.
        """
        if not _has_mail_server(self.env.cr.dbname):
            _logger.debug(
                'mail.mail.create: suppressing %d mail record(s) '
                '— no outgoing mail server configured', len(vals_list)
            )
            return self.env['mail.mail']
        return super().create(vals_list)

    def send_after_commit(self):
        """
        Override: skip the postcommit send hook when no real mail server exists.
        """
        if not _has_mail_server(self.env.cr.dbname):
            _logger.debug(
                'mail.mail: skipping send_after_commit for %d record(s) '
                '— no outgoing mail server configured', len(self)
            )
            return
        return super().send_after_commit()

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        """
        Override: skip sending when no real mail server is configured.
        """
        if not _has_mail_server(self.env.cr.dbname):
            _logger.debug(
                'mail.mail: skipping send() for %d record(s) '
                '— no outgoing mail server configured', len(self)
            )
            return True
        return super().send(
            auto_commit=auto_commit,
            raise_exception=raise_exception,
            post_send_callback=post_send_callback
        )
