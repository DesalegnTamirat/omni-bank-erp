# -*- coding: utf-8 -*-
import base64
from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install', 'learning_management', 'lms_video')
class TestLmsVideoStreamingManifest(HttpCase):
    """
    Test suite for Prompt 5 (LMS Video Adaptive Streaming Manifest & Screen Capture Deterrent):
    - HLS VOD playlist manifest (/lms/video/<id>/manifest.m3u8)
    - Anti-leak authorization guards (HTTP 403 on non-enrolled users)
    - Video player template with watermark overlay
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_admin = cls.env.ref('base.user_admin')
        cls.emp_admin = cls.user_admin.employee_id
        if not cls.emp_admin:
            cls.emp_admin = cls.env['hr.employee'].search([('user_id', '=', cls.user_admin.id)], limit=1)

        cls.course = cls.env['lms.course'].create({
            'name': 'AML & Compliance Video Streaming Course',
            'code': 'AML-STREAM-001',
            'state': 'published',
        })

        fake_video_data = base64.b64encode(b'FakeMP4DataHeader' * 500).decode('utf-8')
        cls.lesson = cls.env['lms.lesson'].create({
            'name': 'Core AML Video Lecture',
            'course_id': cls.course.id,
            'lesson_type': 'video',
            'video_file': fake_video_data,
            'duration': 60.0,
            'sequence': 1,
        })

        cls.enrollment = cls.env['lms.enrollment'].create({
            'course_id': cls.course.id,
            'employee_id': cls.emp_admin.id,
            'state': 'in_progress',
        })

    def test_01_hls_manifest_authorized(self):
        """Verify enrolled employee receives valid HLS VOD manifest with byte ranges."""
        self.authenticate('admin', 'admin')
        resp = self.url_open(f'/lms/video/{self.lesson.id}/manifest.m3u8')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/vnd.apple.mpegurl', resp.headers.get('Content-Type', ''))
        content = resp.text
        self.assertIn('#EXTM3U', content)
        self.assertIn('#EXT-X-TARGETDURATION', content)
        self.assertIn('#EXT-X-BYTERANGE:', content)
        self.assertIn('#EXT-X-ENDLIST', content)
        self.assertIn(f'/lms/video/{self.lesson.id}/stream', content)

    def test_02_manifest_unauthorized(self):
        """Verify non-enrolled user receives HTTP 403 Access Denied."""
        # Unlink enrollment
        self.enrollment.unlink()
        self.authenticate('admin', 'admin')
        # Admin as manager has staff access; remove instructor/manager group to test strict learner gating
        mgr_grp = self.env.ref('learning_management.group_lms_manager')
        inst_grp = self.env.ref('learning_management.group_lms_instructor')
        self.user_admin.write({'group_ids': [(3, mgr_grp.id), (3, inst_grp.id)]})

        try:
            resp = self.url_open(f'/lms/video/{self.lesson.id}/manifest.m3u8')
            self.assertEqual(resp.status_code, 403)
        finally:
            # Restore admin group
            self.user_admin.write({'group_ids': [(4, mgr_grp.id), (4, inst_grp.id)]})

    def test_03_video_player_rendering(self):
        """Verify secure player page renders with watermark layers and anti-cheat elements."""
        # Ensure enrollment exists
        self.env['lms.enrollment'].create({
            'course_id': self.course.id,
            'employee_id': self.emp_admin.id,
            'state': 'in_progress',
        })
        self.authenticate('admin', 'admin')
        resp = self.url_open(f'/lms/video/{self.lesson.id}/player')
        self.assertEqual(resp.status_code, 200)
        content = resp.text
        self.assertIn('lmsWatermarkLayer', content)
        self.assertIn('lmsVideoPlayer', content)
        self.assertIn('/lms/video/heartbeat', content)
