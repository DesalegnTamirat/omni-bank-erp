# -*- coding: utf-8 -*-
"""
base_patch.py
─────────────
Patches odoo.models.BaseModel at module load time so every model's
create / write / unlink is intercepted. Only models with an active
audit.rule are actually logged — the check is fast and cheap.
"""
import logging
import threading
from datetime import datetime

from odoo import models, api
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

# Thread-local flag to prevent re-entrant audit logging (e.g., audit logs
# triggering more writes that get intercepted → infinite loop / mail cascade).
_audit_local = threading.local()

# Fields that must never be audited — they trigger expensive or recursive ops.
_SKIP_FIELDS = frozenset({'password', 'password_crypt', '__last_update'})

# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_ip(env):
    try:
        from odoo.http import request
        if request and request.httprequest:
            xff = request.httprequest.environ.get('HTTP_X_FORWARDED_FOR', '')
            return xff.split(',')[0].strip() if xff else request.httprequest.remote_addr or ''
    except Exception:
        pass
    return ''


def _field_to_str(record, fname):
    try:
        field = record._fields.get(fname)
        if not field:
            return ''
        val = record[fname]
        if field.type == 'many2one':
            return f'{val.id} ({val.display_name})' if val else ''
        if field.type in ('many2many', 'one2many'):
            return ', '.join(f'{r.id} ({r.display_name})' for r in val) if val else ''
        if field.type == 'selection':
            sel = dict(field.selection) if isinstance(field.selection, list) else {}
            return str(sel.get(val, val)) if val is not None else ''
        if field.type == 'binary':
            return '[binary]' if val else ''
        if field.type == 'boolean':
            return 'True' if val else 'False'
        if isinstance(val, datetime):
            return val.strftime('%Y-%m-%d %H:%M:%S')
        return str(val) if val is not None else ''
    except Exception:
        return '[error]'


def _get_active_rule(env, model_name):
    """Return audit.rule record or None. Skips audit models themselves."""
    if model_name in ('audit.log', 'audit.rule'):
        return None
    try:
        return env['audit.rule'].sudo().search(
            [('model_name', '=', model_name), ('active', '=', True)], limit=1
        ) or None
    except Exception:
        return None


def _user_ctx(env):
    u = env.user
    return dict(user_id=u.id, user_name=u.name, user_login=u.login, ip_address=_get_ip(env))


def _model_ctx(env, model_name):
    ir = env['ir.model'].sudo().search([('model', '=', model_name)], limit=1)
    return dict(
        model_id=ir.id if ir else False,
        model_name=model_name,
        model_description=ir.name if ir else model_name,
        module=(ir.modules or 'base').split(',')[0].strip() if ir else 'base',
    )


def _write_logs(env, logs):
    if logs:
        env['audit.log'].sudo_create_log(logs)


# ── The actual ORM patching ───────────────────────────────────────────────────

_ORIGINAL_CREATE = models.BaseModel.create
_ORIGINAL_WRITE  = models.BaseModel.write
_ORIGINAL_UNLINK = models.BaseModel.unlink

_PATCHED = False  # guard against double-patching


def _patched_create(self, vals_list):
    records = _ORIGINAL_CREATE(self, vals_list)
    # Skip if we are already inside an audit log call (re-entrancy guard)
    if getattr(_audit_local, 'active', False):
        return records
    rule = _get_active_rule(self.env, self._name)
    if rule and rule.log_create:
        _audit_local.active = True
        try:
            mctx = _model_ctx(self.env, self._name)
            uctx = _user_ctx(self.env)
            logs = [{
                **mctx, **uctx,
                'res_id': r.id,
                'res_name': r.display_name if hasattr(r, 'display_name') else str(r.id),
                'operation': 'create',
                'field_id': False, 'field_name': False,
                'field_description': False, 'field_type': False,
                'old_value': False, 'new_value': 'Record created',
            } for r in records]
            _write_logs(self.env, logs)
        except Exception as e:
            _logger.error('Audit create failed [%s]: %s', self._name, e)
        finally:
            _audit_local.active = False
    return records


def _patched_write(self, vals):
    # Re-entrancy guard: prevent audit logging from triggering itself
    # (e.g., writing audit.log → chatter → mail → more writes → loop)
    if getattr(_audit_local, 'active', False):
        return _ORIGINAL_WRITE(self, vals)

    rule = _get_active_rule(self.env, self._name)
    old_vals = {}

    if rule and rule.log_write:
        try:
            # Determine which fields to audit — skip sensitive/expensive fields
            if rule.field_ids:
                allowed = {f.name for f in rule.field_ids} - _SKIP_FIELDS
                audit_fields = [k for k in vals if k in allowed]
            else:
                audit_fields = [k for k in vals if k not in _SKIP_FIELDS]

            # Snapshot old values before write
            for rec in self:
                old_vals[rec.id] = {f: _field_to_str(rec, f) for f in audit_fields if f in rec._fields}
        except Exception as e:
            _logger.error('Audit pre-write snapshot failed [%s]: %s', self._name, e)

    result = _ORIGINAL_WRITE(self, vals)

    if rule and rule.log_write and old_vals:
        _audit_local.active = True
        try:
            mctx = _model_ctx(self.env, self._name)
            uctx = _user_ctx(self.env)

            # Build field metadata map
            fnames = list(next(iter(old_vals.values()), {}).keys())
            ir_fields = {}
            for f in self.env['ir.model.fields'].sudo().search([
                ('model_id.model', '=', self._name), ('name', 'in', fnames)
            ]):
                ir_fields[f.name] = {'id': f.id, 'desc': f.field_description, 'type': f.ttype}

            logs = []
            for rec in self:
                old = old_vals.get(rec.id, {})
                rname = rec.display_name if hasattr(rec, 'display_name') else str(rec.id)
                for fname, old_v in old.items():
                    new_v = _field_to_str(rec, fname)
                    if old_v == new_v:
                        continue
                    meta = ir_fields.get(fname, {})
                    logs.append({
                        **mctx, **uctx,
                        'res_id': rec.id, 'res_name': rname,
                        'operation': 'write',
                        'field_id': meta.get('id', False),
                        'field_name': fname,
                        'field_description': meta.get('desc', fname),
                        'field_type': meta.get('type', ''),
                        'old_value': old_v,
                        'new_value': new_v,
                    })
            _write_logs(self.env, logs)
        except Exception as e:
            _logger.error('Audit post-write failed [%s]: %s', self._name, e)
        finally:
            _audit_local.active = False

    return result


def _patched_unlink(self):
    # Re-entrancy guard
    if getattr(_audit_local, 'active', False):
        return _ORIGINAL_UNLINK(self)

    rule = _get_active_rule(self.env, self._name)
    snapshots = []
    if rule and rule.log_unlink:
        _audit_local.active = True
        try:
            mctx = _model_ctx(self.env, self._name)
            uctx = _user_ctx(self.env)
            snapshots = [{
                **mctx, **uctx,
                'res_id': r.id,
                'res_name': r.display_name if hasattr(r, 'display_name') else str(r.id),
                'operation': 'unlink',
                'field_id': False, 'field_name': False,
                'field_description': False, 'field_type': False,
                'old_value': 'Record existed', 'new_value': 'Record deleted',
            } for r in self]
        except Exception as e:
            _logger.error('Audit pre-unlink snapshot failed [%s]: %s', self._name, e)
        finally:
            _audit_local.active = False

    result = _ORIGINAL_UNLINK(self)

    if snapshots:
        _audit_local.active = True
        try:
            _write_logs(self.env, snapshots)
        except Exception as e:
            _logger.error('Audit post-unlink log failed [%s]: %s', self._name, e)
        finally:
            _audit_local.active = False

    return result


def apply_patch():
    global _PATCHED
    if _PATCHED:
        return
    models.BaseModel.create = _patched_create
    models.BaseModel.write  = _patched_write
    models.BaseModel.unlink = _patched_unlink
    _PATCHED = True
    _logger.info('audit_trail: ORM patch applied (create/write/unlink)')


# Apply immediately when this module is imported
apply_patch()
