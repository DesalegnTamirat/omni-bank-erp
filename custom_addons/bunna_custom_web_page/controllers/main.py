import urllib.parse
import logging
import re
_logger = logging.getLogger(__name__)
# -*- coding: utf-8 -*-
"""
main.py
=======
Restored bunna_custom_web_page controller.
Integrates the Career Opportunities board directly with the External ATS Candidate Profile and CV system.
"""

import odoo
from odoo import http, fields, _
from odoo.exceptions import AccessDenied
from odoo.http import request




def validate_ats_password(password, confirm_password=None, old_password=None, user_info=None):
    """
    Enforces Bunna Bank ATS Password Security Policy:
    - Minimum length: At least 12 characters
    - At least 1 uppercase letter (A-Z)
    - At least 1 lowercase letter (a-z)
    - At least 1 numerical digit (0-9)
    - At least 1 special character / symbol (@$!%*?&#^()_+=-~ etc.)
    - Must match confirm_password (if provided)
    - Must not match old_password (when changing password)
    - Must not contain user's name or email (if provided)
    """
    if not password:
        return "Password is required."
    if confirm_password is not None and password != confirm_password:
        return "New Password and Confirm Password do not match."
    if len(password) < 12:
        return "Password must be at least 12 characters long."
    if not re.search(r'[A-Z]', password):
        return "Password must include at least one uppercase letter (A-Z)."
    if not re.search(r'[a-z]', password):
        return "Password must include at least one lowercase letter (a-z)."
    if not re.search(r'[0-9]', password):
        return "Password must include at least one number (0-9)."
    if not re.search(r'[@$!%*?&#^()_+=\-\[\]{}|~:;<>,./?\\]', password):
        return "Password must include at least one special character (@$!%*?&#^()_+=- etc.)."
    if old_password and password == old_password:
        return "New password cannot be the same as your current password."
    if user_info:
        for val in user_info:
            if val and len(str(val)) >= 3 and str(val).lower() in password.lower():
                return "Password must not contain parts of your name or email address."
    return None

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
        candidate = request.env['candidate.profile'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)
        if not candidate:
            candidate = request.env['candidate.profile'].sudo().create({
                'partner_id': user.partner_id.id,
                'user_id': user.id,
                'name': user.name,
                'email': user.email or user.login,
                'phone': user.phone or '',
            })

        is_admin = not user.share and not user._is_public() and (
            user.has_group('custom_recruitment.group_recruitment_administrator') or
            user.has_group('custom_recruitment.group_recruitment_manager') or
            user.has_group('hr_recruitment.group_hr_recruitment_manager') or
            user.has_group('hr_recruitment.group_hr_recruitment_user') or
            user.has_group('base.group_system') or
            user.has_group('base.group_erp_manager')
        )

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
            'candidate': candidate,
            'cand': candidate,
            'error': kw.get('error'),
        })

    @http.route('/jobs/apply/<int:job_id>', type='http', auth="user", website=True)
    def job_apply_page(self, job_id, **kw):
        """Forces candidate authentication and profile completeness check before applying."""
        vacancy = request.env['job.vacancy'].sudo().browse(job_id)
        if not vacancy.exists() or vacancy.vacancy_status == 'closed' or vacancy.sourcing_type not in ('external', 'both'):
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

        # Verify Electronic CV profile completeness
        names = (candidate.name or '').strip().split(' ')
        first_name = names[0] if len(names) > 0 else ''
        middle_name = names[1] if len(names) > 1 else ''
        has_personal = bool(candidate.name and first_name and middle_name and candidate.phone and candidate.gender)
        if not has_personal or not candidate.education_ids or not candidate.cv_file:
            err = "To apply for Career Opportunities, you must complete all required profile sections (Personal Information, at least one Educational Qualification, and your Master CV upload)."
            return request.redirect('/my/candidate/profile?error=' + urllib.parse.quote(err))

        # Verify Bunna Bank Account
        if not candidate.has_bunna_account:
            err = "Please verify your Bunna Bank account before proceeding with your application."
            return request.redirect(f'/my/candidate/account_info?apply_job_id={job_id}&error=' + urllib.parse.quote(err))

        # Check if vacancy requires work experience and candidate has none
        min_exp = vacancy.minimum_experience_years or 0.0
        bank_exp = vacancy.banking_experience_required or 0.0
        cand_exp = candidate.total_experience or candidate.total_experience_years or 0.0
        has_exp = bool(candidate.experience_ids and cand_exp > 0)
        if (min_exp > 0 or bank_exp > 0) and not has_exp:
            exp_needed = f"{min_exp:g} year(s)" if min_exp > 0 else f"{bank_exp:g} year(s) banking"
            err = f"You are not allowed to apply for this vacancy without work experience. This position requires a minimum of {exp_needed} of experience. You can only apply for fresh graduate vacancies or vacancies requiring 0 years of experience."
            return request.redirect('/jobs?error=' + urllib.parse.quote(err))

        # Check candidate minimum age (must be >= 18 years)
        # Check if vacancy requires work experience and candidate has none
        min_exp = vacancy.minimum_experience_years or 0.0
        bank_exp = vacancy.banking_experience_required or 0.0
        cand_exp = candidate.total_experience or candidate.total_experience_years or 0.0
        has_exp = bool(candidate.experience_ids and cand_exp > 0)
        if (min_exp > 0 or bank_exp > 0) and not has_exp:
            exp_needed = f"{min_exp:g} year(s)" if min_exp > 0 else f"{bank_exp:g} year(s) banking"
            err = f"You are not allowed to apply for this vacancy without work experience. This position requires a minimum of {exp_needed} of experience. You can only apply for fresh graduate vacancies or vacancies requiring 0 years of experience."
            return request.redirect('/jobs?error=' + urllib.parse.quote(err))

        if candidate.dob or candidate.birth_date:
            d = candidate.dob or candidate.birth_date
            today = odoo.fields.Date.today()
            age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
            if age < 18:
                err = f"Age Validation Error: Candidates must be at least 18 years old to apply for career opportunities. Your current age is {age} years."
                return request.redirect('/my/candidate/profile?step=2&error=' + urllib.parse.quote(err))

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
        if not vacancy.exists() or vacancy.vacancy_status == 'closed':
            return request.redirect('/jobs')

        user = request.env.user
        candidate = request.env['candidate.profile'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)
        names = (candidate.name or '').strip().split(' ')
        first_name = names[0] if len(names) > 0 else ''
        middle_name = names[1] if len(names) > 1 else ''
        has_personal = bool(candidate and candidate.name and first_name and middle_name and candidate.phone and candidate.gender)
        if not candidate or not has_personal or not candidate.education_ids or not candidate.cv_file:
            return request.redirect('/my/candidate/profile')

        # Check if vacancy requires work experience and candidate has none
        min_exp = vacancy.minimum_experience_years or 0.0
        bank_exp = vacancy.banking_experience_required or 0.0
        cand_exp = candidate.total_experience or candidate.total_experience_years or 0.0
        has_exp = bool(candidate.experience_ids and cand_exp > 0)
        if (min_exp > 0 or bank_exp > 0) and not has_exp:
            exp_needed = f"{min_exp:g} year(s)" if min_exp > 0 else f"{bank_exp:g} year(s) banking"
            err = f"You are not allowed to apply for this vacancy without work experience. This position requires a minimum of {exp_needed} of experience. You can only apply for fresh graduate vacancies or vacancies requiring 0 years of experience."
            return request.redirect('/jobs?error=' + urllib.parse.quote(err))

        if candidate.dob or candidate.birth_date:
            d = candidate.dob or candidate.birth_date
            today = odoo.fields.Date.today()
            age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
            if age < 18:
                err = f"Age Validation Error: Candidates must be at least 18 years old to apply for career opportunities. Your current age is {age} years."
                return request.redirect('/my/candidate/profile?step=2&error=' + urllib.parse.quote(err))

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

        candidate = request.env['candidate.profile'].sudo().with_context(active_test=False).search([
            '|', ('user_id', '=', user.id), ('email', '=ilike', email_input)
        ], limit=1)

        if not user.active or (candidate and not candidate.active):
            return request.render("bunna_custom_web_page.jobs_login_template", {
                'error': 'Your account is not activated yet. Please click the activation link sent to your registered email address.',
                'email': email_input,
                'show_resend_activation': True,
            })

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

    def _send_candidate_activation_email(self, candidate, activation_token):
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url') or 'http://localhost:8082'
        activation_url = f"{base_url}/jobs/activate?token={activation_token}&email={candidate.email}"
        company_logo_url = f"{base_url}/web/binary/company_logo"

        _logger.info("=================================================================")
        _logger.info(">>> CANDIDATE ACTIVATION LINK FOR [%s]:", candidate.email)
        _logger.info(">>> %s", activation_url)
        _logger.info("=================================================================")

        body_html = f"""
            <div style="background-color: #f4f6f8; padding: 3rem 1rem; font-family: 'Segoe UI', Helvetica, Arial, sans-serif;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); overflow: hidden; border-top: 5px solid #385721; padding: 2.5rem; text-align: center;">
                    <img src="{company_logo_url}" style="height: 50px; margin-bottom: 2rem;" alt="Bunna Bank"/>
                    <h2 style="color: #541718; margin-bottom: 1.5rem;">Bunna Bank Job Application Portal</h2>
                    
                    <div style="text-align: left; color: #1D2B32; font-size: 1rem; line-height: 1.6; margin-bottom: 2rem;">
                        <p>Dear <strong>{candidate.name}</strong>,</p>
                        <p>Thank you for registering on the Bunna Bank Job Application Portal.</p>
                        <p>To activate your candidate account and start applying for open positions, please click the button below to verify your email address:</p>
                        <p style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 10px 12px; margin: 15px 0; color: #856404; font-size: 0.9rem;">
                            <strong>Important:</strong> This activation link will expire in <strong>5 minutes</strong>. If multiple activation links are requested, only the latest link will be accepted.
                        </p>
                    </div>
                    
                    <div style="margin-bottom: 2rem;">
                        <a href="{activation_url}" style="background-color: #385721; color: #ffffff; padding: 14px 35px; font-weight: bold; border-radius: 8px; text-decoration: none; display: inline-block; box-shadow: 0 4px 10px rgba(56, 87, 33, 0.3);">Activate Account</a>
                    </div>
                    
                    <div style="text-align: left; color: #726732; font-size: 0.85rem; line-height: 1.5; border-top: 1px solid #e5e7eb; padding-top: 1.5rem; margin-top: 1.5rem;">
                        <p>If the button above does not work, please copy and paste the following link into your web browser:<br/>
                        <a href="{activation_url}" style="color: #385721; word-break: break-all;">{activation_url}</a></p>
                        <p style="color: #888; margin-top: 1rem;">If you did not create an account on the Bunna Bank Job Application Portal, please ignore this email.</p>
                    </div>
                </div>
            </div>
        """

        try:
            mail_server = request.env['ir.mail_server'].sudo().search([('active', '=', True)], limit=1)
            email_from = mail_server.smtp_user if (mail_server and mail_server.smtp_user) else 'recruitment@bunnabanket.com'
            mail_values = {
                'subject': 'Bunna Bank Career Portal - Activate Your Account',
                'body_html': body_html,
                'email_to': candidate.email,
                'email_from': email_from,
            }
            if mail_server:
                mail_values['mail_server_id'] = mail_server.id
            mail = request.env['mail.mail'].sudo().create(mail_values)
            mail.send()
        except Exception as mail_err:
            _logger.warning("COULD NOT SEND ACTIVATION EMAIL: %s", str(mail_err))

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

        phone_cleaned = re.sub(r'[\s\-\(\)]', '', phone)
        if not re.match(r'^(\+251|00251|251|0)(9|7)\d{8}$', phone_cleaned):
            return request.render("bunna_custom_web_page.jobs_register_template", {
                'error': 'Please enter a valid Ethiopian mobile phone number (e.g. 0911223344, 0711223344, or +251911223344).',
                'first_name': first_name, 'middle_name': middle_name, 'last_name': last_name,
                'email': email, 'phone': phone,
            })

        user_info = [first_name, middle_name, last_name, email.split('@')[0] if '@' in email else '']
        pwd_error = validate_ats_password(password, confirm_password=confirm_password, user_info=user_info)
        if pwd_error:
            return request.render("bunna_custom_web_page.jobs_register_template", {
                'error': pwd_error,
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
            import uuid
            from datetime import timedelta
            activation_token = str(uuid.uuid4())
            expiry = fields.Datetime.now() + timedelta(minutes=5)

            new_user = Users.with_context(no_reset_password=True).create({
                'name': full_name,
                'login': email,
                'email': email,
                'password': password,
                'active': False,
            })

            candidate = Candidates.create({
                'partner_id': new_user.partner_id.id,
                'user_id': new_user.id,
                'name': full_name,
                'email': email,
                'phone': phone,
                'gender': gender,
                'active': False,
                'activation_token': activation_token,
                'activation_token_expiry': expiry,
            })

            # Send Activation Email
            self._send_candidate_activation_email(candidate, activation_token)

            return request.render("bunna_custom_web_page.jobs_register_success_template", {
                'email': email,
            })

        except Exception as e:
            _logger.error("REGISTRATION FAILURE: %s", str(e))
            return request.render("bunna_custom_web_page.jobs_register_template", {
                'error': f'Registration error: {str(e)}',
                'first_name': first_name, 'email': email,
            })

    @http.route('/jobs/activate', type='http', auth="public", website=True)
    def jobs_activate_account(self, token='', email='', **kw):
        token = (token or '').strip()
        email = (email or '').strip().lower()

        if not token:
            return request.render("bunna_custom_web_page.jobs_login_template", {
                'error': 'Invalid activation request. Missing activation token.',
            })

        domain = [('activation_token', '=', token)]
        if email:
            domain.append(('email', '=ilike', email))

        candidate = request.env['candidate.profile'].sudo().with_context(active_test=False).search(domain, limit=1)

        # 1. If candidate with this token was NOT found:
        if not candidate:
            existing_cand = False
            if email:
                existing_cand = request.env['candidate.profile'].sudo().with_context(active_test=False).search([
                    ('email', '=ilike', email)
                ], limit=1)

            if existing_cand and existing_cand.active and (not existing_cand.user_id or existing_cand.user_id.active):
                return request.render("bunna_custom_web_page.jobs_login_template", {
                    'error': 'Your account is already activated. Please sign in.',
                    'email': email,
                })
            elif existing_cand and existing_cand.activation_token:
                return request.render("bunna_custom_web_page.jobs_login_template", {
                    'error': 'This activation link is no longer valid because a newer activation email was sent. Please use the link from your latest email or request a new one.',
                    'email': email,
                    'show_resend_activation': True,
                })
            else:
                return request.render("bunna_custom_web_page.jobs_login_template", {
                    'error': 'Invalid or expired activation link. Please request a new activation link.',
                    'email': email,
                    'show_resend_activation': True if email else False,
                })

        # 2. Candidate found with this token -> check if 5 minutes have elapsed!
        now = fields.Datetime.now()
        if candidate.activation_token_expiry and candidate.activation_token_expiry < now:
            return request.render("bunna_custom_web_page.jobs_login_template", {
                'error': 'This activation link has expired (activation links are valid for 5 minutes). Please request a new activation link.',
                'email': candidate.email,
                'show_resend_activation': True,
            })

        # 3. Valid, latest token and within 5 minutes -> activate!
        candidate.sudo().write({
            'active': True,
            'activation_token': False,
            'activation_token_expiry': False,
        })

        if candidate.user_id:
            candidate.user_id.sudo().write({'active': True})
            if candidate.user_id.partner_id:
                candidate.user_id.partner_id.sudo().write({'active': True})
        elif candidate.partner_id:
            candidate.partner_id.sudo().write({'active': True})

        _logger.info("CANDIDATE ACTIVATED SUCCESSFULLY: %s", candidate.email)
        return request.redirect('/jobs/login?activated=1')

    @http.route('/jobs/resend_activation', type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def jobs_resend_activation(self, **kw):
        email = kw.get('email', '').strip().lower()
        if not email:
            return request.render("bunna_custom_web_page.jobs_login_template", {
                'error': 'Please provide your email address to resend activation link.',
            })

        candidate = request.env['candidate.profile'].sudo().with_context(active_test=False).search([
            ('email', '=ilike', email)
        ], limit=1)

        if not candidate:
            return request.render("bunna_custom_web_page.jobs_login_template", {
                'error': 'No candidate account found with this email address.',
                'email': email,
            })

        if candidate.active and (not candidate.user_id or candidate.user_id.active):
            return request.render("bunna_custom_web_page.jobs_login_template", {
                'error': 'Your account is already activated. Please sign in.',
                'email': email,
            })

        import uuid
        from datetime import timedelta
        # Always generate a brand-new token and 5-minute expiry to invalidate all older links
        token = str(uuid.uuid4())
        expiry = fields.Datetime.now() + timedelta(minutes=5)
        candidate.sudo().write({
            'activation_token': token,
            'activation_token_expiry': expiry,
        })

        self._send_candidate_activation_email(candidate, token)

        return request.render("bunna_custom_web_page.jobs_login_template", {
            'activation_sent': 1,
            'email': email,
        })

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

        cand_user = candidate.user_id
        user_info = [candidate.name or '', (candidate.email or (cand_user.email if cand_user else '') or '').split('@')[0]]
        pwd_error = validate_ats_password(password, confirm_password=confirm_password, user_info=user_info)
        if pwd_error:
            return request.render("bunna_custom_web_page.jobs_reset_password_template", {
                'token': token,
                'error': pwd_error,
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
                user._check_credentials({'type': 'password', 'password': old_pwd}, {'interactive': True})
                cand_info = [candidate.name if candidate else '', user.name or '', (user.email or user.login or '').split('@')[0]]
                pwd_error = validate_ats_password(new_pwd, confirm_password=confirm_pwd, old_password=old_pwd, user_info=cand_info)
                if pwd_error:
                    error = pwd_error
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

    @http.route('/my/candidate/check_cbs_account', type='jsonrpc', auth='user', methods=['POST'])
    def check_cbs_account(self, account_number=None, phone=None, **kw):
        """Verifies candidate Bunna Bank account by Account Number against Finacle CBS API."""
        identifier = str(account_number or phone or '').strip()
        if not identifier:
            return {'success': False, 'message': 'Please enter a valid Bunna Bank account number.'}

        clean_account = re.sub(r'[\s\-]', '', identifier)
        user = request.env.user
        candidate = request.env['candidate.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not candidate:
            candidate = request.env['candidate.profile'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)

        # Call dedicated internal CBS API service
        try:
            from .cbs_service import query_cbs_api
            success, cust_data, msg = query_cbs_api(request.env, clean_account)
            if success and cust_data:
                vals = {
                    'has_bunna_account': True,
                    'bunna_account_number': cust_data.get('account_number') or clean_account,
                    'bunna_account_name': cust_data.get('name') or '',
                    'bunna_account_type': cust_data.get('account_type') or 'Saving Account',
                    'bunna_account_status': str(cust_data.get('account_status') or 'active').title(),
                    'bunna_branch_name': cust_data.get('branch_name') or 'BIB Main Branch',
                    'bunna_account_phone': cust_data.get('phone') or '',
                    'bunna_account_verified_at': odoo.fields.Datetime.now(),
                }
                if candidate:
                    candidate.sudo().write(vals)

                return {
                    'success': True,
                    'data': {
                        'account_number': vals['bunna_account_number'],
                        'name': vals['bunna_account_name'],
                        'account_type': vals['bunna_account_type'],
                        'account_status': vals['bunna_account_status'],
                        'branch_name': vals['bunna_branch_name'],
                        'phone': vals['bunna_account_phone'],
                    },
                    'message': 'Bunna Bank Account successfully verified!'
                }
            else:
                return {
                    'success': False,
                    'message': msg or f"No Bunna Bank account found for account number {clean_account}. Please check the account number or verify your connection to the Bunna Bank internal network/VPN."
                }
        except Exception as e:
            _logger.exception("Error checking CBS account %s: %s", clean_account, e)
            return {
                'success': False,
                'message': f"Error communicating with Core Banking System: {str(e)}"
            }

    @http.route('/my/candidate/account_info', type='http', auth='user', website=True)
    def candidate_account_info_page(self, **kw):
        user = request.env.user
        candidate = request.env['candidate.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not candidate:
            candidate = request.env['candidate.profile'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)

        apply_job_id = kw.get('apply_job_id')
        vacancy = False
        if apply_job_id:
            try:
                vacancy = request.env['job.vacancy'].sudo().browse(int(apply_job_id))
            except Exception:
                pass

        return request.render("bunna_custom_web_page.ats_account_info_template", {
            'candidate': candidate,
            'cand': candidate,
            'active_tab': 'account_info',
            'apply_job_id': apply_job_id,
            'vacancy': vacancy,
            'error': kw.get('error'),
            'success': kw.get('success'),
        })

