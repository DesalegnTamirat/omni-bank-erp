# -*- coding: utf-8 -*-
import base64
import re
import logging
from odoo import http, _
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class LmsController(http.Controller):

    @http.route(['/lms/video/<int:lesson_id>/stream'], type='http', auth='user')
    def stream_lesson_video(self, lesson_id, **kwargs):
        """
        Internal Video Streaming Controller with HTTP 206 Partial Content Range support
        (FR-LMS-004, FR-LMS-005).
        Enables adaptive buffering across branch and mobile environments without YouTube dependencies.
        """
        lesson = request.env['lms.lesson'].browse(lesson_id)
        if not lesson.exists():
            return request.not_found()

        # If hosted via internal streaming URL, redirect
        if lesson.video_source_type == 'url' and lesson.video_url:
            return request.redirect(lesson.video_url)

        if not lesson.video_file:
            return request.not_found()

        raw_data = base64.b64decode(lesson.video_file)
        file_size = len(raw_data)
        range_header = request.httprequest.headers.get('Range')

        if range_header:
            match = re.search(r'bytes=(\d+)-(\d*)', range_header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else file_size - 1
                length = end - start + 1
                chunk = raw_data[start:end + 1]

                headers = [
                    ('Content-Type', 'video/mp4'),
                    ('Content-Range', f'bytes {start}-{end}/{file_size}'),
                    ('Accept-Ranges', 'bytes'),
                    ('Content-Length', str(length)),
                ]
                return Response(chunk, status=206, headers=headers)

        headers = [
            ('Content-Type', 'video/mp4'),
            ('Content-Length', str(file_size)),
            ('Accept-Ranges', 'bytes'),
        ]
        return Response(raw_data, status=200, headers=headers)

    @http.route(['/lms/video/heartbeat'], type='jsonrpc', auth='user')
    def video_heartbeat(self, lesson_id, current_time, duration):
        """
        Anti-Skip Watch Time Heartbeat (FR-LMS-007, FR-LMS-008, FR-LMS-009).
        Called periodically (e.g. every 5s) by video player.
        """
        emp = request.env.user.employee_id
        if not emp:
            return {'status': 'error', 'message': 'No linked employee record'}

        lesson = request.env['lms.lesson'].browse(int(lesson_id))
        if not lesson.exists():
            return {'status': 'error', 'message': 'Lesson not found'}

        # Find active enrollment
        enrollment = request.env['lms.enrollment'].search([
            ('employee_id', '=', emp.id),
            ('course_id', '=', lesson.course_id.id),
        ], limit=1)

        if not enrollment:
            return {'status': 'error', 'message': 'Not enrolled in course'}

        progress = request.env['lms.lesson.progress'].search([
            ('enrollment_id', '=', enrollment.id),
            ('lesson_id', '=', lesson.id),
        ], limit=1)

        if not progress:
            progress = request.env['lms.lesson.progress'].create({
                'enrollment_id': enrollment.id,
                'lesson_id': lesson.id,
                'employee_id': emp.id,
            })

        result = progress.update_progress(current_time, duration)
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
            'is_valid': cert.state == 'valid',
            'learner_name': cert.employee_id.name,
            'course_name': cert.course_id.name,
            'issue_date': cert.issue_date,
            'expiry_date': cert.expiry_date or 'Permanent / No Expiry',
            'cert_number': cert.name,
        }
        return request.render('learning_management.certificate_verify_success', values)
