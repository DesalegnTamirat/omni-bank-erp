import logging
_logger = logging.getLogger(__name__)
# -*- coding: utf-8 -*-
"""
main.py
=======
Restored bunna_custom_web_page controller.
Integrates the Career Opportunities board directly with the External ATS Candidate Profile and CV system.
"""

import urllib.parse
import odoo
from odoo import http, _
from odoo.exceptions import AccessDenied
from odoo.http import request



class CustomWebController(http.Controller):

    @http.route('/ats', type='http', auth="public", website=True)
    def ats_portal(self, **kw):
        """Dedicated ATS route: redirects directly to ATS Career Vacancies board."""
        return request.redirect('/jobs')

    @http.route(['/hello-odoo'], type='http', auth='public', website=True)
    def hello_page(self, **kwargs):
        user = request.env.user
        user_name = user.name if (user and len(user) == 1 and not user._is_public()) else 'Public user'
        return request.render('bunna_custom_web_page.hello_page_template', {
            'user_name': user_name,
        })

    @http.route('/jobs', type='http', auth="public", website=True)
    def jobs_page(self, **kw):
        """Forces candidate authentication and profile completeness check before showing vacancies."""
        if request.env.user._is_public():
            return request.redirect("/jobs/login")

        user = request.env.user
        candidate = request.env['candidate.profile'].sudo().search(['|', ('partner_id', '=', user.partner_id.id), ('user_id', '=', user.id)], limit=1)
        
        user_phone = getattr(user, 'phone', '') or (user.partner_id and user.partner_id.phone) or (user.partner_id and getattr(user.partner_id, 'mobile', '')) or ''
        
        if not candidate:
            candidate = request.env['candidate.profile'].sudo().create({
                'partner_id': user.partner_id.id,
                'user_id': user.id,
                'name': user.name,
                'email': user.email or user.login,
                'phone': user_phone,
            })
        
        effective_phone = candidate.phone or user_phone
        if effective_phone:
            if not candidate.phone:
                candidate.sudo().write({'phone': effective_phone})
            if user.partner_id and user.partner_id.phone != effective_phone:
                user.partner_id.sudo().write({'phone': effective_phone, 'mobile': effective_phone})
            if hasattr(user, 'phone') and getattr(user, 'phone', False) != effective_phone:
                user.sudo().write({'phone': effective_phone})

        is_admin = not user.share and not user._is_public() and (
            user.has_group('custom_recruitment.group_recruitment_administrator') or
            user.has_group('custom_recruitment.group_recruitment_manager') or
            user.has_group('hr_recruitment.group_hr_recruitment_manager') or
            user.has_group('hr_recruitment.group_hr_recruitment_user') or
            user.has_group('base.group_system') or
            user.has_group('base.group_erp_manager')
        )

        # Verify Electronic CV profile completeness for regular candidates only (Admins bypass)
        if not is_admin:
            if not candidate.education_ids or not candidate.experience_ids:
                return request.redirect("/my/candidate/profile")

        today = odoo.fields.Date.today()
        if is_admin:
            domain = [
                ('sourcing_type', 'in', ('external', 'both')),
                ('reference', 'not ilike', '/INT/'),
                ('vacancy_status', 'in', ('published', 'closed')),
                ('active', '=', True),
            ]
        else:
            domain = [
                ('sourcing_type', 'in', ('external', 'both')),
                ('reference', 'not ilike', '/INT/'),
                ('vacancy_status', '=', 'published'),
                ('vacancy_status', '!=', 'closed'),
                ('active', '=', True),
                '|', ('last_date_to_apply', '=', False), ('last_date_to_apply', '>=', today),
            ]

        vacancies = request.env['job.vacancy'].sudo().search(domain, order="id desc")

        news_posts = request.env['ats.news'].sudo().search([
            ('state', '=', 'published'),
        ], order="is_featured desc, publish_date desc")

        applied_vacancies_map = {}
        if candidate:
            candidate_apps = request.env['hr.applicant'].sudo().search([
                '|',
                ('candidate_profile_id', '=', candidate.id),
                ('email_from', '=ilike', candidate.email or 'never_match')
            ])
            for app in candidate_apps:
                stage_name = app.stage_id.name if app.stage_id else 'Applied'
                app_info = {
                    'applicant_id': app.id,
                    'stage_name': stage_name,
                    'stage_id': app.stage_id.id if app.stage_id else False,
                }
                if app.app_reference:
                    applied_vacancies_map[app.app_reference.id] = app_info
                    applied_vacancies_map[str(app.app_reference.id)] = app_info
                    if app.app_reference.reference:
                        applied_vacancies_map[str(app.app_reference.reference).strip()] = app_info

        return request.render("bunna_custom_web_page.jobs_coming_soon_template", {
            'vacancies': vacancies,
            'news_posts': news_posts,
            'applied_vacancies_map': applied_vacancies_map,
        })

    @http.route('/jobs/apply/<int:job_id>', type='http', auth="user", website=True)
    def job_apply_page(self, job_id, **kw):
        """Forces candidate authentication and profile completeness check before applying."""
        vacancy = request.env['job.vacancy'].sudo().browse(job_id)
        today = odoo.fields.Date.today()
        is_closed = vacancy.vacancy_status == 'closed' or (vacancy.last_date_to_apply and vacancy.last_date_to_apply < today)
        if not vacancy.exists() or is_closed or vacancy.sourcing_type not in ('external', 'both'):
            return request.redirect('/jobs')

        user = request.env.user
        # Get or create candidate profile linked to the logged-in user
        candidate = request.env['candidate.profile'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)
        if not candidate:
            candidate = request.env['candidate.profile'].sudo().create({
                'partner_id': user.partner_id.id,
                'user_id': user.id,
                'name': user.name,
                'email': user.email or user.login,
                'phone': user.phone or '',
            })

        # Verify Electronic CV profile completeness (must have education and experience entries)
        if not candidate.education_ids or not candidate.experience_ids:
            error_msg = _("To apply for Career Opportunities, you must first successfully complete your Master CV Profile (including at least one Educational Qualification and one Work Experience entry).")
            return request.redirect(f"/my/candidate/profile?error={urllib.parse.quote(error_msg)}")

        # Check if already applied
        existing_app = request.env['hr.applicant'].sudo().search([
            ('app_reference', '=', vacancy.id),
            ('candidate_profile_id', '=', candidate.id),
        ], limit=1)
        if existing_app:
            return request.redirect('/my/candidate/applications')

        configured_certs = request.env['recruitment.certification'].sudo().search([], order='name')
        return request.render("bunna_custom_web_page.job_application_form_template", {
            'vacancy': vacancy,
            'candidate': candidate,
            'configured_certs': configured_certs,
        })

    @http.route('/jobs/apply/submit', type='http', auth="user", methods=['POST'], website=True, csrf=True)
    def job_apply_submit(self, **kw):
        vacancy_id = int(kw.get('vacancy_id', 0))
        vacancy = request.env['job.vacancy'].sudo().browse(vacancy_id)
        today = odoo.fields.Date.today()
        is_closed = vacancy.vacancy_status == 'closed' or (vacancy.last_date_to_apply and vacancy.last_date_to_apply < today)
        if not vacancy.exists() or is_closed:
            return request.redirect('/jobs')

        user = request.env.user
        candidate = request.env['candidate.profile'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)
        if not candidate or not candidate.education_ids or not candidate.experience_ids:
            return request.redirect('/jobs')

        # Check if already applied
        existing_app = request.env['hr.applicant'].sudo().search([
            ('app_reference', '=', vacancy.id),
            ('candidate_profile_id', '=', candidate.id),
        ], limit=1)
        if existing_app:
            return request.redirect('/my/candidate/applications')

        # Save application-time candidate profile fields
        candidate.sudo().write({
            'working_status': kw.get('working_status', candidate.working_status),
            'current_company': kw.get('current_company', candidate.current_company),
            'join_immediately': kw.get('join_immediately') in ['1', 'true', 'yes', True],
            'current_salary': float(kw.get('current_salary', 0.0) or 0.0),
        })

        # Create simplified applicant record
        expected_salary = float(kw.get('expected_salary') or 0.0)
        notice_period_days = int(kw.get('notice_period_days') or 0)
        cover_letter = kw.get('cover_letter', '').strip()

        applicant = request.env['hr.applicant'].sudo().create({
                        'partner_name': candidate.name,
            'email_from': candidate.email,
            'partner_phone': candidate.phone,
            'job_id': vacancy.job_position.id,
            'app_reference': vacancy.id,
            'application_type': 'External',
            'candidate_profile_id': candidate.id,
            'cover_letter': cover_letter,
            'expected_salary': expected_salary,
            'notice_period_days': notice_period_days,
            'bunna_app_status': 'draft',
        })

        # Sync master CV qualifications/experiences to application lines
        candidate.sync_to_application(applicant)

        # Render styled application acknowledgment success page
        return request.render("bunna_custom_web_page.job_application_success_template", {
            'applicant_name': candidate.name,
            'applicant_email': candidate.email,
            'vacancy': vacancy,
            'applicant': applicant,
            'candidate': candidate,
        })

    @http.route('/courses', type='http', auth="public", website=True)
    def courses_page(self, **kw):
        return request.render("bunna_custom_web_page.courses_coming_soon_template")

    @http.route('/tender', type='http', auth="public", website=True)
    def tender_page(self, **kw):
        return request.render("bunna_custom_web_page.tender_coming_soon_template")

    @http.route('/policies', type='http', auth="public", website=True)
    def policies_page(self, **kw):
        return request.render("bunna_custom_web_page.policies_page_template")

    @http.route('/faq', type='http', auth="public", website=True)
    def faq_page(self, **kw):
        return request.render("bunna_custom_web_page.faq_page_template")

    @http.route('/odoo/employee-service-requests/new', type='http', auth='user', website=True)
    def redirect_to_employee_service_request(self, **kwargs):
        return request.redirect('/my/home')

    @http.route(['/jobs/status', '/jobs/check-status'], type='http', auth="public", website=True)
    def check_application_status(self, **kw):
        return request.redirect('/my/candidate/applications')

    # ---------------------------------------------------------------
    # Guest Custom Login and Registration Flow (Email-Only & 6-Digit OTP)
    # ---------------------------------------------------------------
    @http.route('/jobs/login', type='http', auth="public", website=True)
    def jobs_login(self, activated=0, **kw):
        if not request.env.user._is_public():
            return request.redirect('/my/candidate/profile')
        return request.render("bunna_custom_web_page.jobs_login_template", {
            'email': kw.get('email', ''),
            'activated': activated,
        })

    @http.route('/jobs/login/submit', type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def jobs_login_submit(self, **kw):
        email_input = kw.get('email', '').strip().lower()
        password = kw.get('password', '')

        user = request.env['res.users'].sudo().with_context(active_test=False).search([
            '|', ('login', '=', email_input), ('email', '=', email_input)
        ], limit=1)

        if not user:
            return request.render("bunna_custom_web_page.jobs_login_template", {
                'error': 'Invalid email address or password.',
                'email': email_input,
            })

        if not user.active:
            return request.redirect(f'/jobs/verify_email?email={email_input}&unverified=1')

        credential = {'login': user.login, 'password': password, 'type': 'password'}
        try:
            auth_info = request.session.authenticate(request.env, credential)
            if auth_info and auth_info.get('uid'):
                return request.redirect('/my/candidate/profile')
        except (AccessDenied, odoo.exceptions.AccessDenied):
            _logger.warning("LOGIN FAILED: Incorrect password for user '%s'", user.login)
        except Exception as e:
            _logger.error("LOGIN EXCEPTION for user '%s': %s", user.login, str(e))

        return request.render("bunna_custom_web_page.jobs_login_template", {
            'error': 'Invalid email address or password.',
            'email': email_input,
        })

    @http.route('/jobs/register', type='http', auth="public", website=True)
    def jobs_register(self, **kw):
        if not request.env.user._is_public():
            return request.redirect('/my/candidate/profile')
        return request.render("bunna_custom_web_page.jobs_register_template")

    @http.route('/jobs/register/submit', type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def jobs_register_submit(self, **kw):
        first_name = kw.get('first_name', '').strip()
        middle_name = kw.get('middle_name', '').strip()
        last_name = kw.get('last_name', '').strip()
        email = kw.get('email', '').strip().lower()
        phone = kw.get('phone', '').strip()
        gender = kw.get('gender', 'male')
        password = kw.get('password', '')
        confirm_password = kw.get('confirm_password', '')

        if not (first_name and last_name and email and phone and password):
            return request.render("bunna_custom_web_page.jobs_register_template", {
                'error': 'All required fields must be filled.',
                'first_name': first_name, 'middle_name': middle_name, 'last_name': last_name,
                'email': email, 'phone': phone,
            })

        if '@' not in email or '.' not in email:
            return request.render("bunna_custom_web_page.jobs_register_template", {
                'error': 'Please enter a valid official email address.',
                'first_name': first_name, 'middle_name': middle_name, 'last_name': last_name,
                'email': email, 'phone': phone,
            })

        if password != confirm_password:
            return request.render("bunna_custom_web_page.jobs_register_template", {
                'error': 'Passwords do not match.',
                'first_name': first_name, 'middle_name': middle_name, 'last_name': last_name,
                'email': email, 'phone': phone,
            })

        full_name = f"{first_name} {middle_name} {last_name}".strip()

        Users = request.env['res.users'].sudo()
        Candidates = request.env['candidate.profile'].sudo()

        existing_user = Users.search(['|', ('login', '=', email), ('email', '=', email)], limit=1)

        if existing_user:
            return request.render("bunna_custom_web_page.jobs_register_template", {
                'error': 'This email address is already registered. Please sign in.',
                'email': email,
            })

        try:
            user_vals = {
                'name': full_name,
                'login': email,
                'email': email,
                'password': password,
                'active': True,
            }
            if hasattr(Users, 'phone'):
                user_vals['phone'] = phone

            new_user = Users.create(user_vals)

            if new_user.partner_id:
                new_user.partner_id.sudo().write({
                    'phone': phone,
                    'mobile': phone,
                })

            candidate = Candidates.create({
                'partner_id': new_user.partner_id.id,
                'user_id': new_user.id,
                'name': full_name,
                'email': email,
                'phone': phone,
                'gender': gender,
                'active': True,
            })

            # Send Welcome Email
            try:
                mail_values = {
                    'subject': 'Welcome to Bunna Bank Career Portal',
                    'body_html': f"""
                        <div style="font-family: Arial, sans-serif; padding: 20px; color: #1D2B32;">
                            <h2 style="color: #541718;">Bunna Bank Job Application Portal</h2>
                            <p>Dear <strong>{full_name}</strong>,</p>
                            <p>Your candidate account has been registered successfully. You can now log in using your official email address: <strong>{email}</strong>.</p>
                            <p>Please log in and complete your Master CV Profile (Personal Info, Education, Experience, Master CV Document) to apply for open vacancies.</p>
                            <p>Best regards,<br/><strong>Bunna Bank HR Team</strong></p>
                        </div>
                    """,
                    'email_to': email,
                    'email_from': 'recruitment@bunnabanket.com',
                }
                request.env['mail.mail'].sudo().create(mail_values).send()
            except Exception as mail_err:
                _logger.warning("COULD NOT SEND WELCOME EMAIL: %s", str(mail_err))

            # Redirect to login with success alert
            return request.redirect('/jobs/login?registered=1')

        except Exception as e:
            _logger.error("REGISTRATION FAILURE: %s", str(e))
            return request.render("bunna_custom_web_page.jobs_register_template", {
                'error': f'Registration error: {str(e)}',
                'first_name': first_name, 'email': email,
            })
    @http.route('/jobs/verify_email', type='http', auth="public", website=True)
    def verify_email_page(self, email='', unverified=0, **kw):
        return request.render("bunna_custom_web_page.jobs_verify_email_template", {
            'email': email,
            'unverified': unverified,
        })

    @http.route('/jobs/verify_email/submit', type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def verify_email_submit(self, **kw):
        email = kw.get('email', '').strip().lower()
        code = kw.get('code', '').strip()

        candidate = request.env['candidate.profile'].sudo().with_context(active_test=False).search([
            ('email', '=', email),
            ('activation_code', '=', code),
        ], limit=1)

        if not candidate:
            return request.render("bunna_custom_web_page.jobs_verify_email_template", {
                'error': 'Invalid verification code. Please check your email inbox.',
                'email': email,
            })

        # Activate user and candidate
        candidate.write({'active': True})
        if candidate.user_id:
            candidate.user_id.write({'active': True})

        return request.redirect('/jobs/login?activated=1')
    @http.route('/jobs/forgot_password', type='http', auth="public", website=True)
    def jobs_forgot_password(self, **kw):
        return request.render("bunna_custom_web_page.jobs_forgot_password_template")

    @http.route('/jobs/forgot_password/submit', type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def jobs_forgot_password_submit(self, **kw):
        email = kw.get('email', '').strip()
        if not email:
            return request.render("bunna_custom_web_page.jobs_forgot_password_template", {
                'error': 'Please enter your email address.',
            })

        candidate = request.env['candidate.profile'].sudo().search([
            ('email', '=', email),
        ], limit=1)

        if not candidate:
            return request.render("bunna_custom_web_page.jobs_forgot_password_template", {
                'error': 'No registered candidate found with this email address.',
            })

        import uuid
        token = str(uuid.uuid4())
        candidate.sudo().write({'reset_token': token})

        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url') or 'http://localhost:8082'
        reset_url = f"{base_url}/jobs/reset_password?token={token}"
        company_logo_url = f"{base_url}/web/binary/company_logo"

        email_body = f"""
        <div style="background-color: #f4f6f8; padding: 3rem 1rem; font-family: 'Segoe UI', Helvetica, Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); overflow: hidden; border-top: 5px solid #561818; padding: 2.5rem; text-align: center;">
                <!-- Logo -->
                <img src="{company_logo_url}" style="height: 50px; margin-bottom: 2rem;" alt="Bunna Bank"/>
                
                <!-- Content -->
                <div style="text-align: left; color: #1D2B32; font-size: 1rem; line-height: 1.6; margin-bottom: 2.5rem;">
                    <p>Dear <strong>{candidate.name}</strong>,</p>
                    <p>We received a request to reset your password for your Bunna Bank Job Application System account. Please click the button below to set a new password.</p>
                </div>
                
                <!-- Button -->
                <div style="margin-bottom: 2.5rem;">
                    <a href="{reset_url}" style="background-color: #541718; color: #ffffff; padding: 12px 35px; font-weight: bold; border-radius: 8px; text-decoration: none; display: inline-block; box-shadow: 0 4px 10px rgba(84, 23, 24, 0.25);">Reset Password</a>
                </div>
                
                <p style="color: #726732; font-size: 0.85rem; margin-top: 2rem;">If you did not request this, you can safely ignore this email.</p>
            </div>
        </div>
        """

        request.env['mail.mail'].sudo().create({
            'subject': 'Reset Your Password - Bunna Bank Careers',
            'email_to': email,
            'body_html': email_body,
        }).send()

        return request.render("bunna_custom_web_page.jobs_forgot_password_template", {
            'success_msg': 'A password reset link has been sent to your email address.',
        })

    @http.route('/jobs/reset_password', type='http', auth="public", website=True)
    def jobs_reset_password(self, **kw):
        token = kw.get('token')
        if not token:
            return request.redirect('/jobs/login')

        candidate = request.env['candidate.profile'].sudo().search([
            ('reset_token', '=', token),
        ], limit=1)

        if not candidate:
            return request.render("bunna_custom_web_page.jobs_login_template", {
                'error': 'Invalid or expired password reset token.',
            })

        return request.render("bunna_custom_web_page.jobs_reset_password_template", {
            'token': token,
        })

    @http.route('/jobs/reset_password/submit', type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def jobs_reset_password_submit(self, **kw):
        token = kw.get('token')
        password = kw.get('password')
        confirm_password = kw.get('confirm_password')

        if not token:
            return request.redirect('/jobs/login')

        candidate = request.env['candidate.profile'].sudo().search([
            ('reset_token', '=', token),
        ], limit=1)

        if not candidate:
            return request.render("bunna_custom_web_page.jobs_login_template", {
                'error': 'Invalid or expired password reset token.',
            })

        if not password or password != confirm_password:
            return request.render("bunna_custom_web_page.jobs_reset_password_template", {
                'token': token,
                'error': 'Passwords do not match or are empty.',
            })

        user = candidate.user_id
        if user:
            user.sudo().write({'password': password})
        candidate.sudo().write({'reset_token': False})

        return request.render("bunna_custom_web_page.jobs_login_template", {
            'success_msg': 'Password reset successfully! Please login with your new password.',
        })
    # ---------------------------------------------------------------
    # Candidate Change Password Flow
    # ---------------------------------------------------------------
    @http.route(['/my/candidate/change_password', '/my/candidate/change-password'], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def candidate_change_password(self, **kw):
        user = request.env.user
        candidate = request.env['candidate.profile'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)

        error = False
        success = False
        if request.httprequest.method == 'POST':
            old_pwd = kw.get('old_password', '')
            new_pwd = kw.get('new_password', '')
            confirm_pwd = kw.get('confirm_password', '')

            try:
                user._check_credentials(old_pwd, {'interactive': True})
                if not new_pwd or new_pwd != confirm_pwd:
                    error = "New Password and Confirm Password do not match."
                elif len(new_pwd) < 6:
                    error = "New Password must be at least 6 characters long."
                else:
                    user.sudo().write({'password': new_pwd})
                    success = "Your password has been updated successfully!"
            except Exception:
                error = "The current password you entered is incorrect."

        values = {
            'candidate': candidate,
            'cand': candidate,
            'error': error,
            'success': success,
            'active_tab': 'password',
            'is_profile_complete': True,
        }
        return request.render('bunna_custom_web_page.change_password_template', values)
