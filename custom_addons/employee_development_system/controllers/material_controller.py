# -*- coding: utf-8 -*-
"""Role-aware delivery of course materials from a training session."""

import base64
import mimetypes
from html import escape
from urllib.parse import urlparse

from odoo import http
from odoo.http import Response, content_disposition, request


class EdsMaterialController(http.Controller):

    @staticmethod
    def _company_allowed(record):
        return not record.company_id or record.company_id in request.env.user.company_ids

    @staticmethod
    def _staff_user():
        return request.env.user.has_group('employee_development_system.group_eds_officer')

    @http.route('/eds/session/<int:session_id>/materials', type='http', auth='user')
    def session_materials(self, session_id, **kwargs):
        session = request.env['eds.session'].sudo().browse(session_id).exists()
        if not session or not self._company_allowed(session):
            return request.not_found()
        user = request.env.user
        materials = session.course_id.material_ids.sudo().filtered(
            lambda material: material._can_open_for_session(session, user)
        )
        if not self._staff_user() and not materials:
            # A material-free session is still accessible to an assigned trainer or
            # accepted participant, but the page must not reveal other sessions.
            assigned = bool(session.trainer_ids.filtered(
                lambda trainer: trainer.employee_id.user_id == user
                or trainer.external_partner_id == user.partner_id
            ))
            accepted = bool(request.env['eds.enrollment'].sudo().search_count([
                ('session_id', '=', session.id),
                ('employee_id.user_id', '=', user.id),
                ('state', 'in', ('enrolled', 'completed')),
            ])) and session.status in ('scheduled', 'ongoing', 'rescheduled', 'completed')
            if not (assigned or accepted):
                return Response('Forbidden', status=403)

        type_labels = dict(request.env['eds.material']._fields['material_type'].selection)
        rows = ''.join(
            '<tr><td>{title}</td><td>{kind}</td><td>{version}</td>'
            '<td><a href="/eds/material/{id}" target="_blank" rel="noopener">Open / Download</a></td></tr>'.format(
                title=escape(material.title or ''),
                kind=escape(type_labels.get(material.material_type, 'Other')),
                version=escape(material.version or ''),
                id=material.id,
            ) for material in materials
        )
        table = (
            '<table><thead><tr><th>Material</th><th>Type</th><th>Version</th><th></th></tr></thead>'
            f'<tbody>{rows}</tbody></table>' if rows else
            '<p>No materials are available for your role on this session yet.</p>'
        )
        html = (
            '<!doctype html><html><head><meta charset="utf-8"><title>Training Materials</title>'
            '<style>body{font:16px system-ui,sans-serif;background:#f7f8f5;color:#222;'
            'max-width:960px;margin:40px auto;padding:0 20px}h1{color:#531719}'
            'table{width:100%;border-collapse:collapse;background:white}th,td{padding:13px;'
            'text-align:left;border-bottom:1px solid #dde2db}th{background:#edf1e9}'
            'a{color:#4b641f;font-weight:600}</style></head><body>'
            f'<h1>Training Materials</h1><p>{escape(session.course_id.name or session.program_name or session.name)}</p>'
            f'{table}</body></html>'
        )
        return Response(html, content_type='text/html; charset=utf-8', headers=[
            ('Cache-Control', 'private, no-store'),
            ('X-Content-Type-Options', 'nosniff'),
        ])

    @http.route('/eds/material/<int:material_id>', type='http', auth='user')
    def open_material(self, material_id, **kwargs):
        material = request.env['eds.material'].sudo().browse(material_id).exists()
        if not material or not self._company_allowed(material) or not material._has_content():
            return request.not_found()
        user = request.env.user
        if not material._can_open_for_user(user):
            return Response('Forbidden', status=403)
        if material.source_kind == 'link':
            url = (material.resource_url or '').strip()
            parsed = urlparse(url)
            if not ((url.startswith('/') and not url.startswith('//') and not url.startswith('/\\'))
                    or (parsed.scheme in ('http', 'https') and parsed.netloc)):
                return request.not_found()
            return request.redirect(url)

        content = base64.b64decode(material.document)
        filename = material.filename or 'training-material'
        mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        return Response(content, headers=[
            ('Content-Type', mime_type),
            ('Content-Disposition', content_disposition(filename)),
            ('Content-Length', str(len(content))),
            ('Cache-Control', 'private, no-store'),
            ('X-Content-Type-Options', 'nosniff'),
        ])
