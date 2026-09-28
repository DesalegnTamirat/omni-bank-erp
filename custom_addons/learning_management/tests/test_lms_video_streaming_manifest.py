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
        cls.learner_user = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Video Test Learner',
            'login': 'video_test_learner@bunnabank.et',
            'password': 'LearnerPassword123!',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_learner').id])],
        })
        cls.learner_emp = cls.env['hr.employee'].create({
            'name': 'Video Test Learner Emp',
            'user_id': cls.learner_user.id,
        })

        cls.unauth_user = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Unenrolled User',
            'login': 'unenrolled_test@bunnabank.et',
            'password': 'UnenrolledPassword123!',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_learner').id])],
        })
        cls.unauth_emp = cls.env['hr.employee'].create({
            'name': 'Unenrolled Emp',
            'user_id': cls.unauth_user.id,
        })

        cls.category = cls.env['lms.category'].search([], limit=1)
        if not cls.category:
            cls.category = cls.env['lms.category'].create({
                'name': 'Streaming Test Category',
                'code': 'STC-01',
            })

        cls.course = cls.env['lms.course'].create({
            'name': 'AML Compliance Video Streaming Course',
            'code': 'AML-STREAM-001',
            'category_id': cls.category.id,
            'instructor_id': cls.learner_emp.id,
            'description': '<p>AML Compliance Video Streaming Course Description</p>',
            'state': 'published',
        })

        fake_video_data = base64.b64encode(b'FakeMP4DataHeader' * 500).decode('utf-8')
        cls.lesson = cls.env['lms.lesson'].create({
            'name': 'Core AML Video Lecture',
            'course_id': cls.course.id,
            'lesson_type': 'video',
            'video_file': fake_video_data,
            'duration_minutes': 60.0,
            'video_duration_seconds': 3600,
            'sequence': 1,
        })

        cls.enrollment = cls.env['lms.enrollment'].create({
            'course_id': cls.course.id,
            'employee_id': cls.learner_emp.id,
            'state': 'in_progress',
        })

    def test_01_hls_manifest_authorized(self):
        """Verify enrolled employee receives valid HLS VOD manifest with byte ranges."""
        self.authenticate('video_test_learner@bunnabank.et', 'LearnerPassword123!')
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
        self.authenticate('unenrolled_test@bunnabank.et', 'UnenrolledPassword123!')
        resp = self.url_open(f'/lms/video/{self.lesson.id}/manifest.m3u8')
        self.assertEqual(resp.status_code, 403)

    def test_03_video_player_rendering(self):
        """Verify secure player page renders with watermark layers and anti-cheat elements."""
        self.authenticate('video_test_learner@bunnabank.et', 'LearnerPassword123!')
        resp = self.url_open(f'/lms/video/{self.lesson.id}/player')
        self.assertEqual(resp.status_code, 200)
        content = resp.text
        self.assertIn('lmsWatermarkLayer', content)
        self.assertIn('lmsVideoPlayer', content)
        self.assertIn('/lms/video/heartbeat', content)
