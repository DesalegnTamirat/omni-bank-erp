# -*- coding: utf-8 -*-
import base64
import mimetypes
import os
import re
import logging
from datetime import datetime
from urllib.parse import urlsplit
from odoo import http, _, fields
from odoo.http import request, Response, content_disposition
from ..models.lms_course import external_media_url_allowed

_logger = logging.getLogger(__name__)


class LmsController(http.Controller):

    @staticmethod
    def _external_media_url_allowed(url, allowed_hosts):
        return external_media_url_allowed(url, allowed_hosts)

    def _check_video_access(self, lesson_id, env=None):
        """
        Authorization check for video streaming and heartbeat (FR-LMS-004, FR-LMS-005).
        Returns (True, lesson, enrollment) if authorized, or (False, error_response, None).
        Returns HTTP 403 / Access Denied without leaking whether the lesson exists.
        """
        if env is None:
            try:
                env = request.env
            except Exception:
                return False, Response("Forbidden: Access Denied", status=403), None
        user = env.user
        emp = user.employee_id
        if not emp:
            _logger.warning("Video access denied: user %s has no linked employee", user.login)
            return False, Response("Forbidden: Access Denied", status=403), None

        # Sudo read to verify lesson and course existence without information disclosure
        lesson = env['lms.lesson'].sudo().browse(int(lesson_id))
        if not lesson.exists() or not lesson.course_id:
            return False, Response("Forbidden: Access Denied", status=403), None

        is_staff = user.has_group('learning_management.group_lms_instructor') or \
                   user.has_group('learning_management.group_lms_manager')

        # Check course enrollment for this employee
        enrollment = env['lms.enrollment'].sudo().search([
            ('employee_id', '=', emp.id),
            ('course_id', '=', lesson.course_id.id),
            ('state', 'in', ('enrolled', 'in_progress', 'completed')),
        ], order='attempt_number desc, id desc', limit=1)

        if not enrollment and not is_staff:
            _logger.warning("Video access denied: employee %s not enrolled in course %s", emp.name, lesson.course_id.name)
            return False, Response("Forbidden: Access Denied", status=403), None

        # An enrolled learner may finish the frozen version after retirement.
        if not is_staff and (not enrollment or not enrollment._course_available_for_learning()):
            _logger.warning("Video access denied: course %s in state %s", lesson.course_id.name, lesson.course_id.state)
            return False, Response("Forbidden: Access Denied", status=403), None

        # Check pre-assessment gating (FR-LMS-013)
        if enrollment and lesson.course_id.has_pre_assessment and not enrollment.pre_assessment_passed and not is_staff:
            _logger.warning("Video access denied: pre-assessment not passed for employee %s", emp.name)
            return False, Response("Forbidden: You must pass the pre-course assessment first.", status=403), None

        # Check learning path sequencing gating (FR-LMS-002)
        if enrollment and enrollment.is_locked and not is_staff:
            _logger.warning("Video access denied: course is locked by learning path sequencing for employee %s", emp.name)
            return False, Response("Forbidden: Prerequisite courses must be completed first.", status=403), None

        if enrollment and not is_staff:
            lessons = lesson.course_id.lesson_ids
            prior = lessons[:lessons.ids.index(lesson.id)].filtered('is_mandatory')
            completed = enrollment.lesson_progress_ids.filtered(
                lambda progress: progress.state == 'completed'
            ).mapped('lesson_id')
            if prior - completed:
                return False, Response("Forbidden: Complete earlier mandatory lessons first.", status=403), None

        return True, lesson, enrollment

    @http.route(['/lms/lesson/<int:lesson_id>/document'], type='http', auth='user')
    def download_lesson_document(self, lesson_id, **kwargs):
        authorized, result, _enrollment = self._check_video_access(lesson_id)
        if not authorized:
            return result
        lesson = result
        if lesson.lesson_type != 'document' or not lesson.document_file:
            return request.not_found()
        filename = os.path.basename((lesson.document_filename or 'lesson-document').replace('\\', '/'))
        filename = filename.replace('\r', '').replace('\n', '') or 'lesson-document'
        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        content = base64.b64decode(lesson.document_file)
        return Response(content, headers=[
            ('Content-Type', content_type),
            ('Content-Disposition', content_disposition(filename)),
            ('Content-Length', str(len(content))),
            ('Cache-Control', 'private, no-store'),
            ('X-Content-Type-Options', 'nosniff'),
        ])

    @http.route(['/lms/video/<int:lesson_id>/stream'], type='http', auth='user')
    def stream_lesson_video(self, lesson_id, **kwargs):
        """
        Internal Video Streaming Controller with HTTP 206 Partial Content Range support.
        Enables browser buffering across branches without an external video platform.
        Enforces enrollment and course visibility before serving any bytes.
        """
        authorized, result, enrollment = self._check_video_access(lesson_id)
        if not authorized:
            return result
        lesson = result

        # If hosted via internal streaming URL, redirect
        if lesson.video_source_type == 'url' and lesson.video_url:
            allowed_hosts = request.env['ir.config_parameter'].sudo().get_param(
                'learning_management.media_allowed_hosts', ''
            )
            if not self._external_media_url_allowed(lesson.video_url, allowed_hosts):
                return Response('Configure an approved HTTPS media host for this video.', status=503)
            return request.redirect(lesson.video_url)

        attachment = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'lms.lesson'), ('res_id', '=', lesson.id),
            ('res_field', '=', 'video_file'),
        ], limit=1)
        if not attachment or not attachment.store_fname:
            return Response('Video storage is not configured for streaming.', status=503)
        file_path = attachment._full_path(attachment.store_fname)
        if not os.path.isfile(file_path):
            return Response('Video file is unavailable.', status=503)
        file_size = attachment.file_size
        range_header = request.httprequest.headers.get('Range')
        start, end = 0, file_size - 1
        status = 200
        if range_header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header.strip())
            if not match or not any(match.groups()):
                return Response(status=416, headers=[('Content-Range', f'bytes */{file_size}')])
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else file_size - 1
            else:
                suffix = int(match.group(2))
                start = max(0, file_size - suffix)
            if (not match.group(1) and not int(match.group(2))) or start >= file_size or end < start:
                return Response(status=416, headers=[('Content-Range', f'bytes */{file_size}')])
            end = min(end, file_size - 1)
            status = 206
        length = max(0, end - start + 1)
        def chunks():
            with open(file_path, 'rb') as video:
                video.seek(start)
                remaining = length
                while remaining:
                    data = video.read(min(1024 * 1024, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data
        headers = [
            ('Content-Type', attachment.mimetype or 'video/mp4'),
            ('Content-Length', str(length)),
            ('Accept-Ranges', 'bytes'),
            ('Cache-Control', 'private, no-store'),
            ('X-Content-Type-Options', 'nosniff'),
            ('Referrer-Policy', 'no-referrer'),
        ]
        if status == 206:
            headers.append(('Content-Range', f'bytes {start}-{end}/{file_size}'))
        return Response(chunks(), status=status, headers=headers, direct_passthrough=True)

    @http.route(['/lms/video/<int:lesson_id>/manifest.m3u8'], type='http', auth='user')
    def get_video_manifest(self, lesson_id, **kwargs):
        """
        Placeholder for a future HLS packaging service.
        """
        authorized, result, enrollment = self._check_video_access(lesson_id)
        if not authorized:
            return result
        lesson = result

        if lesson.video_source_type == 'url' and lesson.video_url:
            allowed_hosts = request.env['ir.config_parameter'].sudo().get_param(
                'learning_management.media_allowed_hosts', ''
            )
            if (self._external_media_url_allowed(lesson.video_url, allowed_hosts)
                    and urlsplit(lesson.video_url).path.lower().endswith('.m3u8')):
                return request.redirect(lesson.video_url)

        # An MP4 file cannot be split into arbitrary HLS byte ranges. The player
        # uses the authenticated HTTP Range endpoint until real HLS segments exist.
        return Response('HLS packaging is not configured; use the stream endpoint.', status=501)

    @http.route(['/lms/video/<int:lesson_id>/player'], type='http', auth='user', website=True)
    def render_video_player(self, lesson_id, **kwargs):
        """
        Responsive player for the authenticated HTTP Range stream and watch heartbeat.
        """
        authorized, result, enrollment = self._check_video_access(lesson_id)
        if not authorized:
            return result
        lesson = result

        user = request.env.user
        emp = user.employee_id
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        progress = request.env['lms.lesson.progress'].sudo().search([
            ('enrollment_id', '=', enrollment.id if enrollment else 0),
            ('lesson_id', '=', lesson.id),
        ], limit=1)

        last_pos = progress.last_position_seconds if progress else 0.0

        values = {
            'lesson': lesson,
            'course': lesson.course_id,
            'enrollment': enrollment,
            'user_name': user.name,
            'emp_code': getattr(emp, 'registration_number', '') or getattr(emp, 'identification_id', '') or str(user.id),
            'timestamp': timestamp,
            'last_position': last_pos,
            'lesson_completed': bool(progress and progress.state == 'completed'),
            'stream_url': f"/lms/video/{lesson.id}/stream",
        }
        return request.render('learning_management.lesson_video_player', values)

    @http.route(['/lms/video/heartbeat'], type='jsonrpc', auth='user')
    def video_heartbeat(self, lesson_id, current_time, duration):
        """
        Anti-Skip Watch Time Heartbeat (FR-LMS-007, FR-LMS-008, FR-LMS-009).
        Called periodically (e.g. every 5s) by video player.
        Enforces enrollment authorization before processing heartbeat.
        """
        authorized, result, enrollment = self._check_video_access(lesson_id)
        if not authorized:
            return {'status': 'error', 'message': 'Access Denied', 'code': 403}
        lesson = result

        if not enrollment:
            return {'status': 'error', 'message': 'Not enrolled in course', 'code': 403}

        progress = request.env['lms.lesson.progress'].sudo().search([
            ('enrollment_id', '=', enrollment.id),
            ('lesson_id', '=', lesson.id),
        ], limit=1)

        if not progress:
            progress = request.env['lms.lesson.progress'].sudo().create({
                'enrollment_id': enrollment.id,
                'lesson_id': lesson.id,
                'employee_id': request.env.user.employee_id.id,
            })

        result = progress.sudo().update_progress(current_time, duration)
        return {
            'status': 'success',
            'allowed_position': result['allowed_position'],
            'is_completed': result['is_completed'],
            'last_position': progress.last_position_seconds,
        }

    @http.route(['/lms/certificate/verify/<string:verification_code>'], type='http', auth='public', website=True)
    def verify_certificate(self, verification_code, **kwargs):
        """
        Public Digital Certificate Authenticity Verification (FR-LMS-018).
        """
        cert = request.env['lms.certificate'].sudo().search([('verification_code', '=', verification_code.strip())], limit=1)
        if not cert:
            return request.render('learning_management.certificate_verify_not_found', {'code': verification_code})

        values = {
            'cert': cert,
            'is_valid': cert.state == 'valid' and (
                not cert.expiry_date or cert.expiry_date >= fields.Date.context_today(cert)
            ),
            'learner_name': cert.employee_id.name,
            'course_name': cert.course_id.name,
            'issue_date': cert.issue_date,
            'expiry_date': cert.expiry_date or 'Permanent / No Expiry',
            'cert_number': cert.name,
        }
        return request.render('learning_management.certificate_verify_success', values)
