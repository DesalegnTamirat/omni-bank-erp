# -*- coding: utf-8 -*-
import base64
import re
import logging
from datetime import datetime
from odoo import http, _
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class LmsController(http.Controller):

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
        ], limit=1)

        if not enrollment and not is_staff:
            _logger.warning("Video access denied: employee %s not enrolled in course %s", emp.name, lesson.course_id.name)
            return False, Response("Forbidden: Access Denied", status=403), None

        # Ensure course is published, or user has instructor/manager privileges
        if lesson.course_id.state != 'published' and not is_staff:
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

        return True, lesson, enrollment

    @http.route(['/lms/video/<int:lesson_id>/stream'], type='http', auth='user')
    def stream_lesson_video(self, lesson_id, **kwargs):
        """
        Internal Video Streaming Controller with HTTP 206 Partial Content Range support
        (FR-LMS-004, FR-LMS-005).
        Enables adaptive buffering across branch and mobile environments without YouTube dependencies.
        Enforces enrollment and course visibility before serving any bytes.
        """
        authorized, result, enrollment = self._check_video_access(lesson_id)
        if not authorized:
            return result
        lesson = result

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

    @http.route(['/lms/video/<int:lesson_id>/manifest.m3u8'], type='http', auth='user', cors='*')
    def get_video_manifest(self, lesson_id, **kwargs):
        """
        Adaptive HLS Streaming Manifest (FR-LMS-004, FR-LMS-005, NFR Performance/Mobile).
        Generates standard HLS VOD playlist with byte ranges for seamless streaming.
        """
        authorized, result, enrollment = self._check_video_access(lesson_id)
        if not authorized:
            return result
        lesson = result

        if lesson.video_source_type == 'url' and lesson.video_url:
            return request.redirect(lesson.video_url)

        if not lesson.video_file:
            return request.not_found()

        raw_data = base64.b64decode(lesson.video_file)
        file_size = len(raw_data)
        duration = float(lesson.video_duration_seconds or (lesson.duration_minutes * 60) or 60.0)
        target_duration = 10
        num_segments = max(1, int(duration // target_duration))
        chunk_size = max(1024, file_size // num_segments)
        seg_dur = duration / num_segments

        base_url = request.httprequest.url_root.rstrip('/')
        stream_url = f"{base_url}/lms/video/{lesson.id}/stream"

        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:4",
            f"#EXT-X-TARGETDURATION:{int(target_duration) + 1}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:VOD",
            "#EXT-X-INDEPENDENT-SEGMENTS",
        ]

        for i in range(num_segments):
            offset = i * chunk_size
            length = chunk_size if i < num_segments - 1 else (file_size - offset)
            lines.append(f"#EXTINF:{seg_dur:.2f},")
            lines.append(f"#EXT-X-BYTERANGE:{length}@{offset}")
            lines.append(stream_url)

        lines.append("#EXT-X-ENDLIST\n")
        manifest_content = "\n".join(lines)

        headers = [
            ('Content-Type', 'application/vnd.apple.mpegurl'),
            ('Content-Disposition', f'inline; filename="lesson_{lesson.id}_manifest.m3u8"'),
            ('Cache-Control', 'no-cache, no-store, must-revalidate'),
        ]
        return Response(manifest_content, status=200, headers=headers)

    @http.route(['/lms/video/<int:lesson_id>/player'], type='http', auth='user', website=True)
    def render_video_player(self, lesson_id, **kwargs):
        """
        Secure Video Player with Anti-Cheat & Dynamic Watermark Overlay (FR-LMS-004, FR-LMS-007, FR-LMS-008).
        """
        authorized, result, enrollment = self._check_video_access(lesson_id)
        if not authorized:
            return result
        lesson = result

        user = request.env.user
        emp = user.employee_id
        user_ip = request.httprequest.remote_addr or '127.0.0.1'
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
            'user_login': user.login,
            'emp_code': getattr(emp, 'registration_number', '') or getattr(emp, 'identification_id', '') or str(user.id),
            'user_ip': user_ip,
            'timestamp': timestamp,
            'last_position': last_pos,
            'manifest_url': f"/lms/video/{lesson.id}/manifest.m3u8",
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
