import urllib.parse
from datetime import datetime

def _validate_uploaded_file(file_obj, max_mb=5, allowed_exts=None, label="File"):
    """
    Validates uploaded file size and extension based on Bunna Bank ATS standards.
    Returns (bytes_data_base64, filename, error_msg).
    """
    if not file_obj or not hasattr(file_obj, 'read'):
        return False, False, None
    filename = getattr(file_obj, 'filename', '') or ''
    if not filename:
        return False, False, None
    
    content = file_obj.read()
    if not content:
        return False, False, None
    
    # 1. Size check
    max_bytes = max_mb * 1024 * 1024
    if len(content) > max_bytes:
        size_mb = len(content) / (1024 * 1024)
        return False, False, _("%s size (%.2f MB) exceeds the maximum allowed limit of %d MB. Please upload a smaller or compressed file.") % (label, size_mb, max_mb)
    
    # 2. Extension check
    if allowed_exts:
        ext = filename.split('.')[-1].lower() if '.' in filename else ''
        clean_exts = [e.lower().lstrip('.') for e in allowed_exts]
        if ext not in clean_exts:
            return False, False, _("%s format (.%s) is not supported. Allowed formats: %s.") % (label, ext, ', '.join(allowed_exts))
            
    return base64.b64encode(content), filename, None

def _clean_date(d_str):
    if not d_str:
        return False
    d_str = str(d_str).strip()
    try:
        dt = datetime.strptime(d_str, '%Y-%m-%d')
        if dt.year < 1900 or dt.year > 2100:
            return False
        return d_str
    except (ValueError, TypeError):
        return False

# -*- coding: utf-8 -*-
import base64
from odoo import http, fields, _
from odoo.http import request, content_disposition


class ATSPortalController(http.Controller):

    def _is_profile_complete(self, candidate):
        user = request.env.user
        # Administrator role users bypass profile completion restriction
        if user.has_group('custom_recruitment.group_recruitment_administrator') or user.has_group('base.group_system') or user.has_group('base.group_erp_manager'):
            return True
        if not candidate:
            return False
        # Profile is complete if candidate has Personal Info, Education, Experience, and Master CV Uploaded
        return bool(candidate.cv_file and candidate.education_ids and candidate.experience_ids and candidate.phone)

    def _get_candidate_profile(self):
        """Get or create the candidate profile for the current logged-in user."""
        user = request.env.user
        if user._is_public():
            return False
        
        profile = request.env['candidate.profile'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)
        if not profile:
            profile = request.env['candidate.profile'].sudo().create({
                'partner_id': user.partner_id.id,
                'user_id': user.id,
                'name': user.name or user.partner_id.name,
                'email': user.email or user.login,
                'phone': user.phone or user.partner_id.phone or '',
            })
        return profile

    def _is_recruitment_admin(self):
        user = request.env.user
        if user._is_public() or user.share:
            return False
        return (
            user.has_group('custom_recruitment.group_recruitment_administrator') or
            user.has_group('custom_recruitment.group_recruitment_manager') or
            user.has_group('hr_recruitment.group_hr_recruitment_manager') or
            user.has_group('hr_recruitment.group_hr_recruitment_user') or
            user.has_group('base.group_system') or
            user.has_group('base.group_erp_manager')
        )

    def _is_hired_or_employee_applicant(self, app):
        """Returns True if the applicant is hired, contract signed/proposal, or already exists as an employee in hr.employee / hr.version."""
        if not app:
            return False
        if app.employee_id or app.contract_created_new or app.bunna_app_status == 'hired':
            return True
        stage_name = (app.stage_id.name or '').strip().lower() if app.stage_id else ''
        if any(keyword in stage_name for keyword in ['contract signed', 'contract proposal', 'hired', 'signed']):
            return True

        emp_model = request.env['hr.employee'].sudo()
        # Check if applicant's email exists in hr.employee
        email = (app.email_from or '').strip().lower()
        if email:
            email_domain = []
            if 'work_email' in emp_model._fields:
                email_domain.append(('work_email', '=ilike', email))
            if 'private_email' in emp_model._fields:
                email_domain.append(('private_email', '=ilike', email))
            if email_domain:
                if len(email_domain) > 1:
                    email_domain = ['|'] * (len(email_domain) - 1) + email_domain
                if emp_model.search(email_domain, limit=1):
                    return True

        # Check if applicant's partner exists in hr.employee
        if app.partner_id:
            partner_domain = []
            if 'work_contact_id' in emp_model._fields:
                partner_domain.append(('work_contact_id', '=', app.partner_id.id))
            if 'user_partner_id' in emp_model._fields:
                partner_domain.append(('user_partner_id', '=', app.partner_id.id))
            if 'user_id' in emp_model._fields:
                partner_domain.append(('user_id.partner_id', '=', app.partner_id.id))
            if partner_domain:
                if len(partner_domain) > 1:
                    partner_domain = ['|'] * (len(partner_domain) - 1) + partner_domain
                if emp_model.search(partner_domain, limit=1):
                    return True
        return False

    def _is_hired_or_employee_candidate(self, candidate):
        """Returns True if candidate profile belongs to an employee registered in hr.employee / hr.version or has signed contract."""
        if not candidate:
            return False
        # Check if candidate user has an employee record
        if candidate.user_id and hasattr(candidate.user_id, 'employee_ids') and candidate.user_id.employee_ids:
            return True

        emp_model = request.env['hr.employee'].sudo()
        # Check partner link to employee
        if candidate.partner_id:
            partner_domain = []
            if 'work_contact_id' in emp_model._fields:
                partner_domain.append(('work_contact_id', '=', candidate.partner_id.id))
            if 'user_partner_id' in emp_model._fields:
                partner_domain.append(('user_partner_id', '=', candidate.partner_id.id))
            if 'user_id' in emp_model._fields:
                partner_domain.append(('user_id.partner_id', '=', candidate.partner_id.id))
            if partner_domain:
                if len(partner_domain) > 1:
                    partner_domain = ['|'] * (len(partner_domain) - 1) + partner_domain
                if emp_model.search(partner_domain, limit=1):
                    return True

        # Check candidate email in hr.employee
        email = (candidate.email or '').strip().lower()
        if email:
            email_domain = []
            if 'work_email' in emp_model._fields:
                email_domain.append(('work_email', '=ilike', email))
            if 'private_email' in emp_model._fields:
                email_domain.append(('private_email', '=ilike', email))
            if email_domain:
                if len(email_domain) > 1:
                    email_domain = ['|'] * (len(email_domain) - 1) + email_domain
                if emp_model.search(email_domain, limit=1):
                    return True

        # Check if candidate has any application with Contract Signed / Hired / employee_id
        for app in candidate.application_ids:
            if self._is_hired_or_employee_applicant(app):
                return True
        return False

    # ---------------------------------------------------------------
    # 1. External Vacancies List & Search (/jobs)
    # ---------------------------------------------------------------
    @http.route(['/jobs', '/jobs/list', '/jobs/page/<int:page>'], type='http', auth='public', website=True)
    def jobs_list(self, page=1, search='', location='', **kwargs):
        """Displays open external vacancies for candidates, plus closed vacancies for recruitment admins."""
        request.env['job.vacancy'].sudo()._cron_auto_close_expired_vacancies()
        is_admin = self._is_recruitment_admin()
        today = fields.Date.today()
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
                ('active', '=', True),
                '|', ('last_date_to_apply', '=', False), ('last_date_to_apply', '>=', today),
            ]
        if search:
            domain.append('|')
            domain.append(('reference', 'ilike', search))
            domain.append(('job_title', 'ilike', search))
        if location:
            domain.append(('job_location', 'ilike', location))

        candidate_profile = self._get_candidate_profile()
        if candidate_profile and not self._is_profile_complete(candidate_profile):
            return request.redirect('/my/candidate/profile?step=1&profile_required=1')
        vacancies = request.env['job.vacancy'].sudo().search(domain, order='create_date desc')

        applied_vacancies_map = {}
        if candidate_profile:
            candidate_apps = request.env['hr.applicant'].sudo().search([
                '|',
                ('candidate_profile_id', '=', candidate_profile.id),
                ('email_from', '=ilike', candidate_profile.email or 'never_match')
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

        values = {
            'vacancies': vacancies,
            'search': search,
            'location': location,
            'candidate_profile': candidate_profile,
            'is_recruitment_admin': is_admin,
            'applied_vacancies_map': applied_vacancies_map,
        }
        return request.render('custom_recruitment.ats_jobs_list_template', values)

    @http.route('/jobs/<int:vacancy_id>', type='http', auth='user', website=True)
    def job_detail(self, vacancy_id, **kwargs):
        """Displays details of an external vacancy. Closed vacancies accessible only to recruitment admins."""
        vacancy = request.env['job.vacancy'].sudo().browse(vacancy_id)
        if not vacancy.exists() or vacancy.sourcing_type not in ('external', 'both'):
            return request.notFound()

        is_admin = self._is_recruitment_admin()
        if not is_admin and (vacancy.vacancy_status != 'published' or vacancy.vacancy_status == 'closed'):
            return request.notFound()

        candidate_profile = self._get_candidate_profile()
        has_applied = False
        applied_stage_name = 'Applied'
        if candidate_profile:
            existing_app = request.env['hr.applicant'].sudo().search([
                '|',
                ('app_reference', '=', vacancy.id),
                ('app_reference', '=', vacancy.reference),
                ('candidate_profile_id', '=', candidate_profile.id),
            ], limit=1)
            if existing_app:
                has_applied = True
                applied_stage_name = existing_app.stage_id.name if existing_app.stage_id else 'Applied'

        values = {
            'vacancy': vacancy,
            'candidate_profile': candidate_profile,
            'has_applied': has_applied,
            'applied_stage_name': applied_stage_name,
            'is_recruitment_admin': is_admin,
        }
        return request.render('custom_recruitment.ats_job_detail_template', values)

    @http.route('/jobs/<int:vacancy_id>/apply', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def job_apply(self, vacancy_id, **kwargs):
        """Handles job application submission. Closed vacancies block applications for all."""
        vacancy = request.env['job.vacancy'].sudo().browse(vacancy_id)
        if not vacancy.exists() or vacancy.sourcing_type not in ('external', 'both') or vacancy.vacancy_status == 'closed':
            return request.notFound()

        candidate = self._get_candidate_profile()
        if not candidate:
            return request.redirect('/jobs/login')

        existing_app = request.env['hr.applicant'].sudo().search([
            ('app_reference', '=', vacancy.id),
            ('candidate_profile_id', '=', candidate.id),
        ], limit=1)
        if existing_app:
            return request.redirect('/my/candidate/applications')

        if request.httprequest.method == 'POST':
            cover_letter = kwargs.get('cover_letter', '')
            expected_salary = float(kwargs.get('expected_salary', 0.0) or 0.0)
            notice_period_days = int(kwargs.get('notice_period_days', 0) or 0)

            applicant = request.env['hr.applicant'].sudo().create({
                                'job_id': vacancy.job_id.id if vacancy.job_id else False,
                'app_reference': vacancy.id,
                'application_type': 'External',
                'partner_name': candidate.name,
                'email_from': candidate.email,
                'partner_phone': candidate.phone,
                'cover_letter': cover_letter,
                'expected_salary': expected_salary,
                'notice_period_days': notice_period_days,
            })

            candidate.sync_to_application(applicant)
            return request.redirect('/my/candidate/applications?submitted=1')

        values = {
            'vacancy': vacancy,
            'candidate': candidate,
        }
        return request.render('custom_recruitment.ats_job_apply_template', values)

    # ---------------------------------------------------------------
    # Candidate Dashboard with Numeric Metrics Cards
    # ---------------------------------------------------------------
    @http.route(['/my/candidate/dashboard'], type='http', auth='user', website=True)
    def candidate_dashboard(self, **kwargs):
        """Displays dashboard with numerical metrics & quick stats."""
        candidate = self._get_candidate_profile()
        if not candidate:
            return request.redirect('/jobs/login')
        if not self._is_profile_complete(candidate):
            return request.redirect('/my/candidate/profile?step=1&profile_required=1')

        domain = [
            '|',
            ('candidate_profile_id', '=', candidate.id),
            ('email_from', '=ilike', candidate.email or 'never_match_placeholder'),
            ('bunna_app_status', '!=', 'hired'),
            ('contract_created_new', '!=', True),
        ]
        raw_applications = request.env['hr.applicant'].sudo().search(domain, order='create_date desc')
        applications = raw_applications.filtered(lambda a: not self._is_hired_or_employee_applicant(a))

        # Auto-link candidate_profile_id on any apps matched by email but missing the link
        for app in applications:
            if not app.candidate_profile_id and candidate.email and app.email_from and app.email_from.lower() == candidate.email.lower():
                app.sudo().write({'candidate_profile_id': candidate.id})

        open_vacancies_count = request.env['job.vacancy'].sudo().search_count([
            ('sourcing_type', 'in', ('external', 'both')),
            ('vacancy_status', '=', 'published'),
            ('active', '=', True),
        ])

        # ── Real candidate status from external.recruitment.selected.candidates table ──
        # Priority: ext_selected.selection_type > candidate_score.selection_status > bunna_app_status > stage
        EXT_SEL_LABELS = {
            'selected': 'Selected',
            'reserved': 'Reserved',
            'rejected': 'Rejected',
        }
        SCORE_SEL_LABELS = {
            'selected': 'Selected',
            'reserve': 'Reserved',
            'rejected': 'Rejected',
            'disqualified': 'Disqualified',
            'pending': 'Eligible',
        }
        BUNNA_LABELS = {
            'shortlisted': 'Shortlisted',
            'interview': 'Interview',
            'offer': 'Offer Issued',
            'hired': 'Hired',
            'rejected': 'Rejected',
        }
        STAGE_PRIORITY = ['Hired', 'Selected', 'Offer Issued', 'Interview', 'Reserved', 'Shortlisted', 'Eligible', 'Applied']

        # Build a map: applicant_id -> selection_type from external.recruitment.selected.candidates
        app_ids = [app.id for app in applications if app.id]
        ext_sel_records = request.env['external.recruitment.selected.candidates'].sudo().search([
            ('applicant_name', 'in', app_ids),
            ('active', '=', True),
        ])
        ext_sel_map = {}  # applicant_id -> selection_type label
        for rec in ext_sel_records:
            app_id = rec.applicant_name.id if rec.applicant_name else False
            if app_id and rec.selection_type:
                # Keep highest priority status if multiple records exist
                existing = ext_sel_map.get(app_id)
                new_label = EXT_SEL_LABELS.get(rec.selection_type, rec.selection_type.capitalize())
                priority_order = {'Selected': 0, 'Reserved': 1, 'Rejected': 2}
                if not existing or priority_order.get(new_label, 99) < priority_order.get(existing, 99):
                    ext_sel_map[app_id] = new_label

        # Also match by email for cases where applicant_name link may be missing
        if candidate.email:
            ext_sel_by_email = request.env['external.recruitment.selected.candidates'].sudo().search([
                ('applicant_email', '=ilike', candidate.email),
                ('active', '=', True),
            ])
            for rec in ext_sel_by_email:
                if rec.applicant_name and rec.applicant_name.id not in ext_sel_map:
                    ext_sel_map[rec.applicant_name.id] = EXT_SEL_LABELS.get(rec.selection_type, rec.selection_type.capitalize())

        def _get_real_status(app):
            """Return the highest-authority status for the application.
            Priority: external_selected_candidates > candidate_score > bunna_app_status > stage_id
            """
            # 1. Check external.recruitment.selected.candidates table
            if app.id in ext_sel_map:
                return ext_sel_map[app.id]
            # 2. Check recruitment.candidate.score.selection_status
            if app.candidate_score_id and app.candidate_score_id.selection_status:
                return SCORE_SEL_LABELS.get(app.candidate_score_id.selection_status, 'Eligible')
            # 3. Check bunna_app_status
            if app.bunna_app_status and app.bunna_app_status != 'draft':
                return BUNNA_LABELS.get(app.bunna_app_status, 'Applied')
            # 4. Fallback to Kanban stage_id
            raw = app.stage_id.name if app.stage_id else 'Applied'
            return 'Applied' if raw in ['New', 'Initial', 'Initial Screening', 'Draft', 'Submitted'] else raw

        in_review_count = 0
        stage_counts = {}
        for app in applications:
            status = _get_real_status(app)
            if status not in ['Rejected', 'Disqualified', 'Refused', 'Cancelled']:
                in_review_count += 1
            stage_counts[status] = stage_counts.get(status, 0) + 1

        # Most prominent active stage (highest priority found)
        current_status = 'Applied'
        for priority in STAGE_PRIORITY:
            for stage_label in stage_counts:
                if priority.lower() in stage_label.lower():
                    current_status = stage_label
                    break
            if current_status != 'Applied':
                break

        # Build concise summary like "Selected: 1 | Applied: 1"
        stage_summary_parts = ['{}: {}'.format(k, v) for k, v in stage_counts.items()]
        stage_status_summary = ' | '.join(stage_summary_parts) if stage_summary_parts else 'No Applications'

        # Calculate completeness
        completeness = 20
        if candidate.cv_file: completeness += 16
        if candidate.education_ids: completeness += 16
        if candidate.experience_ids: completeness += 16
        if candidate.certification_ids: completeness += 16
        if candidate.document_ids: completeness += 16

        published_news_count = request.env['ats.news'].sudo().search_count([
            ('state', '=', 'published'),
        ])

        news_posts = request.env['ats.news'].sudo().search([
            ('state', '=', 'published'),
        ], order="is_featured desc, publish_date desc", limit=4)

        is_admin = self._is_recruitment_admin()
        closed_vacancies_count = request.env['job.vacancy'].sudo().search_count([
            ('sourcing_type', 'in', ('external', 'both')),
            ('vacancy_status', '=', 'closed'),
            ('active', '=', True),
        ])

        values = {
            'candidate': candidate,
            'applications': applications,
            'total_applications': len(applications),
            'in_review_count': in_review_count,
            'current_status': current_status,
            'stage_status_summary': stage_status_summary,
            'stage_counts': stage_counts,
            'open_vacancies_count': open_vacancies_count,
            'closed_vacancies_count': closed_vacancies_count,
            'is_recruitment_admin': is_admin,
            'published_news_count': published_news_count,
            'completeness': min(100, completeness),
            'news_posts': news_posts,
            'ext_sel_map': ext_sel_map,
        }
        return request.render('custom_recruitment.ats_candidate_dashboard_template', values)

    # ---------------------------------------------------------------
    # Administrative Applicants List per Vacancy (/my/recruitment/applicants)
    # ---------------------------------------------------------------
    @http.route(['/my/recruitment/applicants', '/my/recruitment/applicants/vacancy/<int:vacancy_id>'], type='http', auth='user', website=True)
    def admin_applicants_list(self, vacancy_id=None, search='', selected_vacancy_id=None, **kwargs):
        """Displays list of candidate applications per vacancy. Restricted strictly to recruitment administrators."""
        if not self._is_recruitment_admin():
            return request.redirect('/jobs')

        target_vacancy_id = vacancy_id or selected_vacancy_id or kwargs.get('vacancy_id')
        if target_vacancy_id:
            try:
                target_vacancy_id = int(target_vacancy_id)
            except (ValueError, TypeError):
                target_vacancy_id = False

        external_vacancies = request.env['job.vacancy'].sudo().search([
            ('sourcing_type', 'in', ('external', 'both')),
            ('reference', 'not ilike', '/INT/'),
            ('active', '=', True)
        ], order='create_date desc')
        external_vacancy_ids = external_vacancies.ids

        domain = [('active', '=', True)]
        if target_vacancy_id:
            domain.append(('app_reference', '=', target_vacancy_id))
        else:
            domain.append(('app_reference', 'in', external_vacancy_ids))

        if search:
            domain.extend(['|', '|', '|',
                ('partner_name', 'ilike', search),
                ('email_from', 'ilike', search),
                ('partner_phone', 'ilike', search),
                ('cover_letter', 'ilike', search)
            ])

        applicants = request.env['hr.applicant'].sudo().search(domain, order='create_date desc')
        # Exclude candidates whose contract is signed, are hired, or registered in Core HR (hr.employee / hr.version)
        applicants = applicants.filtered(lambda a: not self._is_hired_or_employee_applicant(a))

        selected_vacancy = request.env['job.vacancy'].sudo().browse(target_vacancy_id) if target_vacancy_id else False

        values = {
            'applicants': applicants,
            'all_vacancies': external_vacancies,
            'selected_vacancy_id': target_vacancy_id,
            'selected_vacancy': selected_vacancy,
            'search': search,
            'total_applicants_count': len(applicants),
        }
        return request.render('custom_recruitment.ats_admin_applicants_template', values)

    @http.route('/my/recruitment/applicants/<int:applicant_id>', type='http', auth='user', website=True)
    def admin_applicant_detail(self, applicant_id, **kwargs):
        """Displays full candidate profile and application details for a specific applicant. Restricted to recruitment admins."""
        if not self._is_recruitment_admin():
            return request.redirect('/jobs')

        applicant = request.env['hr.applicant'].sudo().browse(applicant_id)
        if not applicant.exists():
            return request.redirect('/my/recruitment/applicants')

        candidate = applicant.candidate_profile_id

        values = {
            'applicant': applicant,
            'candidate': candidate,
            'cp': candidate,
        }
        return request.render('custom_recruitment.ats_admin_applicant_detail_template', values)

    # ---------------------------------------------------------------
    # Administrative Master Candidate Profiles Routes (/my/recruitment/candidates)
    # ---------------------------------------------------------------
    @http.route('/my/recruitment/candidates', type='http', auth='user', website=True)
    def admin_candidates_list(self, search='', gender='', **kwargs):
        """Lists all registered Candidate Master Profiles. Accessible strictly to recruitment admins."""
        if not self._is_recruitment_admin():
            return request.redirect('/jobs')

        domain = [('active', '=', True)]
        if search:
            search = search.strip()
            domain.extend([
                '|', '|', '|', '|',
                ('name', 'ilike', search),
                ('email', 'ilike', search),
                ('phone', 'ilike', search),
                ('national_id', 'ilike', search),
                ('city', 'ilike', search)
            ])
        if gender:
            domain.append(('gender', '=', gender))

        candidates = request.env['candidate.profile'].sudo().search(domain, order='create_date desc')
        # Exclude candidates who have become employees or whose contracts are signed
        candidates = candidates.filtered(lambda c: not self._is_hired_or_employee_candidate(c))

        values = {
            'candidates': candidates,
            'search': search,
            'gender': gender,
            'total_candidates_count': len(candidates),
        }
        return request.render('custom_recruitment.ats_admin_candidates_template', values)

    @http.route('/my/recruitment/candidates/<int:candidate_id>', type='http', auth='user', website=True)
    def admin_candidate_profile_detail(self, candidate_id, **kwargs):
        """Displays full Master Candidate Profile detail view for recruitment admins."""
        if not self._is_recruitment_admin():
            return request.redirect('/jobs')

        candidate = request.env['candidate.profile'].sudo().browse(candidate_id)
        if not candidate.exists():
            return request.redirect('/my/recruitment/candidates')

        # Find all job applications submitted by this candidate
        applications = request.env['hr.applicant'].sudo().search([
            '|',
            ('candidate_profile_id', '=', candidate.id),
            ('email_from', '=ilike', candidate.email or 'never_match')
        ], order='create_date desc')

        values = {
            'candidate': candidate,
            'cp': candidate,
            'applications': applications,
        }
        return request.render('custom_recruitment.ats_admin_candidate_detail_template', values)

    # ---------------------------------------------------------------
    # Candidate News & Announcements Page (/my/candidate/news)
    # ---------------------------------------------------------------
    @http.route(['/my/candidate/news', '/my/candidate/news/<int:news_id>'], type='http', auth='user', website=True)
    def candidate_news(self, news_id=None, search='', post_type='', **kwargs):
        """Displays published news & announcements page for candidates."""
        candidate = self._get_candidate_profile()
        if not candidate:
            return request.redirect('/jobs/login')
        if not self._is_profile_complete(candidate):
            return request.redirect('/my/candidate/profile?step=1&profile_required=1')

        domain = [('state', '=', 'published')]
        if search:
            domain.extend(['|', '|', ('name', 'ilike', search), ('summary', 'ilike', search), ('content', 'ilike', search)])
        if post_type:
            domain.append(('post_type', '=', post_type))

        all_news = request.env['ats.news'].sudo().search(domain, order="is_featured desc, publish_date desc, id desc")

        import re
        news_items = []
        for n in all_news:
            if n.summary:
                clean_summary = n.summary
            else:
                raw_text = re.sub(r'<[^>]+>', ' ', str(n.content or ''))
                raw_text = ' '.join(raw_text.split())
                clean_summary = raw_text[:180] + ('...' if len(raw_text) > 180 else '')
            news_items.append({
                'news': n,
                'summary_text': clean_summary,
            })

        selected_news = False
        if news_id:
            selected_news = request.env['ats.news'].sudo().browse(news_id)
            if not selected_news.exists() or selected_news.state != 'published':
                selected_news = False

        values = {
            'candidate': candidate,
            'all_news': all_news,
            'news_items': news_items,
            'selected_news': selected_news,
            'search': search,
            'post_type': post_type,
        }
        return request.render('custom_recruitment.ats_candidate_news_template', values)

    @http.route(['/my/candidate/applications'], type='http', auth='user', website=True)
    def candidate_applications(self, submitted=0, **kwargs):
        """Displays candidate's applications table."""
        candidate = self._get_candidate_profile()
        if not candidate:
            return request.redirect('/jobs/login')
        if not self._is_profile_complete(candidate):
            return request.redirect('/my/candidate/profile?step=1&profile_required=1')

        domain = [
            '|',
            ('candidate_profile_id', '=', candidate.id),
            ('email_from', '=ilike', candidate.email or 'never_match_placeholder'),
            ('bunna_app_status', '!=', 'hired'),
            ('contract_created_new', '!=', True),
        ]
        raw_applications = request.env['hr.applicant'].sudo().search(domain, order='create_date desc')
        applications = raw_applications.filtered(lambda a: not self._is_hired_or_employee_applicant(a))

        # Auto-link candidate_profile_id on any apps matched by email but missing the link
        for app in applications:
            if not app.candidate_profile_id and candidate.email and app.email_from and app.email_from.lower() == candidate.email.lower():
                app.sudo().write({'candidate_profile_id': candidate.id})

        # Build ext_sel_map for applications page (same as dashboard)
        app_ids2 = [app.id for app in applications if app.id]
        ext_sel_recs2 = request.env['external.recruitment.selected.candidates'].sudo().search([
            ('applicant_name', 'in', app_ids2),
            ('active', '=', True),
        ])
        ext_sel_map2 = {}
        for rec in ext_sel_recs2:
            aid = rec.applicant_name.id if rec.applicant_name else False
            if aid and rec.selection_type:
                lbl = {'selected': 'Selected', 'reserved': 'Reserved', 'rejected': 'Rejected'}.get(rec.selection_type, rec.selection_type.capitalize())
                priority_order = {'Selected': 0, 'Reserved': 1, 'Rejected': 2}
                if aid not in ext_sel_map2 or priority_order.get(lbl, 99) < priority_order.get(ext_sel_map2[aid], 99):
                    ext_sel_map2[aid] = lbl
        if candidate.email:
            ext_sel_by_email2 = request.env['external.recruitment.selected.candidates'].sudo().search([
                ('applicant_email', '=ilike', candidate.email),
                ('active', '=', True),
            ])
            for rec in ext_sel_by_email2:
                if rec.applicant_name and rec.applicant_name.id not in ext_sel_map2:
                    ext_sel_map2[rec.applicant_name.id] = {'selected': 'Selected', 'reserved': 'Reserved', 'rejected': 'Rejected'}.get(rec.selection_type, rec.selection_type.capitalize())

        values = {
            'candidate': candidate,
            'applications': applications,
            'submitted': submitted,
            'ext_sel_map': ext_sel_map2,
        }
        return request.render('custom_recruitment.ats_candidate_applications_template', values)

    # ---------------------------------------------------------------
    # Candidate Job Offers Management (/my/candidate/offers)
    # ---------------------------------------------------------------
    @http.route(['/my/candidate/offers'], type='http', auth='user', website=True)
    def candidate_offers(self, offer_id=None, success=None, error=None, **kwargs):
        """Displays job offers extended to the selected candidate, with a 3-day acceptance window."""
        candidate = self._get_candidate_profile()
        if not candidate:
            return request.redirect('/jobs/login')
        if not self._is_profile_complete(candidate):
            return request.redirect('/my/candidate/profile?step=1&profile_required=1')

        cand_email = candidate.email or request.env.user.email or ''
        user_partner_id = request.env.user.partner_id.id

        # Trigger cron to ensure any offers past 3 days are auto-expired
        request.env['recruitment.offer.letter'].sudo()._cron_expire_pending_offers()

        cand_email = (candidate.email or request.env.user.email or '').strip().lower()
        user_partner_id = request.env.user.partner_id.id

        # Trigger cron to ensure any offers past deadline are auto-expired
        request.env['recruitment.offer.letter'].sudo()._cron_expire_pending_offers()

        domain = [
            '|', '|', '|', '|',
            ('candidate_email', '=ilike', cand_email),
            ('applicant_id.partner_id', '=', user_partner_id),
            ('applicant_id.email_from', '=ilike', cand_email),
            ('ext_candidate_id.applicant_name.partner_id', '=', user_partner_id),
            ('ext_candidate_id.applicant_name.email_from', '=ilike', cand_email),
        ]
        all_offers = request.env['recruitment.offer.letter'].sudo().search(domain, order='create_date desc')

        today = fields.Date.today()
        offers_data = []
        for off in all_offers:
            app = off.applicant_id or (off.ext_candidate_id.applicant_name if off.ext_candidate_id else False)
            # Remove / hide from candidate portal once Employee and Contract are created (hired)
            if app and (app.bunna_app_status == 'hired' or app.contract_created_new or (app.employee_id and app.contract_created_new)):
                continue

            # Remove from ATS candidate portal once the offer letter is accepted or rejected (declined)
            if off.state in ('accepted', 'declined'):
                continue

            days_left = None
            is_urgent = False
            deadline_val = off.deadline_date or off.expiry_date
            if off.state == 'sent' and deadline_val:
                delta = (deadline_val - today).days
                days_left = max(0, delta)
                is_urgent = days_left <= 1

            offers_data.append({
                'offer': off,
                'days_left': days_left,
                'is_urgent': is_urgent,
                'applicant': app,
                'deadline': deadline_val,
            })

        values = {
            'candidate': candidate,
            'offers_data': offers_data,
            'total_offers': len(offers_data),
            'success': success,
            'error': error,
            'today': today,
        }
        return request.render('custom_recruitment.ats_candidate_offers_template', values)

    @http.route(['/my/candidate/offers/download/<int:offer_id>', '/my/candidate/offers/preview/<int:offer_id>'], type='http', auth='user', website=True)
    def candidate_offer_download(self, offer_id, preview=False, **kwargs):
        """Allows candidate to preview or download their official Bunna Bank Employment Offer Letter PDF."""
        candidate = self._get_candidate_profile()
        if not candidate:
            return request.redirect('/jobs/login')

        offer = request.env['recruitment.offer.letter'].sudo().browse(int(offer_id))
        if not offer.exists():
            return request.redirect('/my/candidate/offers?error=Offer+not+found')

        cand_email = (candidate.email or request.env.user.email or '').strip().lower()
        off_email = (offer.candidate_email or '').strip().lower()
        app_partner = offer.applicant_id.partner_id.id if (offer.applicant_id and offer.applicant_id.partner_id) else (
            offer.ext_candidate_id.applicant_name.partner_id.id if (offer.ext_candidate_id and offer.ext_candidate_id.applicant_name) else False
        )
        app_email = (offer.applicant_id.email_from or '').strip().lower() if offer.applicant_id else (
            (offer.ext_candidate_id.applicant_name.email_from or '').strip().lower() if (offer.ext_candidate_id and offer.ext_candidate_id.applicant_name) else ''
        )

        has_access = (
            off_email == cand_email
            or app_email == cand_email
            or app_partner == request.env.user.partner_id.id
            or request.env.user.has_group('custom_recruitment.group_recruitment_user')
            or request.env.user.has_group('base.group_system')
        )
        if not has_access:
            return request.redirect('/my/candidate/offers?error=Unauthorized+access+to+offer')

        pdf_content, _dummy = request.env['ir.actions.report']._render_qweb_pdf('custom_recruitment.action_report_recruitment_offer_letter', [offer.id])
        filename = f"Bunna_Bank_Offer_Letter_{(offer.candidate_name or 'Candidate').replace(' ', '_')}.pdf"
        is_preview = preview or kwargs.get('preview') or request.httprequest.path.startswith('/my/candidate/offers/preview')
        disposition = 'inline' if is_preview else 'attachment'
        pdfhttpheaders = [
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf_content)),
            ('Content-Disposition', f'{disposition}; filename="{filename}"')
        ]
        return request.make_response(pdf_content, headers=pdfhttpheaders)

    @http.route(['/my/candidate/offers/respond'], type='http', auth='user', methods=['POST'], website=True)
    def candidate_offer_respond(self, offer_id, decision, reason='', **kwargs):
        """Candidate accepts or declines the job offer via the ATS Portal."""
        candidate = self._get_candidate_profile()
        if not candidate:
            return request.redirect('/jobs/login')

        offer = request.env['recruitment.offer.letter'].sudo().browse(int(offer_id))
        if not offer.exists():
            return request.redirect('/my/candidate/offers?error=Offer+not+found')

        cand_email = (candidate.email or request.env.user.email or '').strip().lower()
        off_email = (offer.candidate_email or '').strip().lower()
        app_partner = offer.applicant_id.partner_id.id if (offer.applicant_id and offer.applicant_id.partner_id) else (
            offer.ext_candidate_id.applicant_name.partner_id.id if (offer.ext_candidate_id and offer.ext_candidate_id.applicant_name) else False
        )
        app_email = (offer.applicant_id.email_from or '').strip().lower() if offer.applicant_id else (
            (offer.ext_candidate_id.applicant_name.email_from or '').strip().lower() if (offer.ext_candidate_id and offer.ext_candidate_id.applicant_name) else ''
        )

        has_access = (
            off_email == cand_email
            or app_email == cand_email
            or app_partner == request.env.user.partner_id.id
            or request.env.user.has_group('custom_recruitment.group_recruitment_user')
            or request.env.user.has_group('base.group_system')
        )
        if not has_access:
            return request.redirect('/my/candidate/offers?error=Unauthorized+access+to+offer')

        if offer.state != 'sent':
            return request.redirect(f'/my/candidate/offers?error=Offer+is+already+{offer.state}')

        if decision == 'accept':
            offer.action_accept()
            return request.redirect('/my/candidate/offers?success=accepted')
        elif decision == 'decline':
            offer.rejection_reason = reason or _("Declined by candidate via ATS Job Portal")
            offer.action_decline()
            return request.redirect('/my/candidate/offers?success=declined')

        return request.redirect('/my/candidate/offers')

    # ---------------------------------------------------------------
    # Master Electronic CV Profile Builder (7 Tabs)
    # ---------------------------------------------------------------
    @http.route('/my/candidate/profile', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def candidate_profile(self, **kwargs):
        """Allows candidate to maintain their master Electronic CV profile."""
        candidate = self._get_candidate_profile()
        if not candidate:
            return request.redirect('/jobs/login')

        step = int(kwargs.get('step', 1))

        if request.httprequest.method == 'POST':
            if step == 2:
                # Update Personal Information
                first_name = kwargs.get('first_name', '').strip()
                middle_name = kwargs.get('middle_name', '').strip()
                last_name = kwargs.get('last_name', '').strip()
                full_name = f"{first_name} {middle_name} {last_name}".strip()

                candidate.sudo().write({
                    'name': full_name or candidate.name,
                    'gender': kwargs.get('gender', candidate.gender),
                    'phone': kwargs.get('phone', candidate.phone),
                    'national_id': kwargs.get('national_id', candidate.national_id),
                    'secondary_id_type': kwargs.get('secondary_id_type', candidate.secondary_id_type),
                    'secondary_id_number': kwargs.get('secondary_id_number', candidate.secondary_id_number),
                    'dob': _clean_date(kwargs.get('dob')) or _clean_date(kwargs.get('birth_date')) or candidate.dob,
                    'place_of_birth': kwargs.get('place_of_birth', candidate.place_of_birth),
                    'city': kwargs.get('city', candidate.city),
                    'address': kwargs.get('address', candidate.address),
                })
                return request.redirect('/my/candidate/profile?step=3')

            elif step == 3:
                # Handle single edit or multiple new education entries
                edit_id = kwargs.get('edit_id')
                if edit_id:
                    # Single edit mode
                    edu_level = kwargs.get('education_level', 'bsc')
                    field_study = kwargs.get('field_of_study')
                    if field_study == 'Other':
                        field_study = kwargs.get('other_field_of_study') or 'Other'
                    inst = kwargs.get('institution')
                    if inst == 'Other':
                        inst = kwargs.get('other_institution') or 'Other'

                    has_cs = kwargs.get('has_cost_sharing') == '1'
                    cs_file = kwargs.get('cost_sharing_file')
                    cs_data, cs_filename, cs_err = _validate_uploaded_file(cs_file, max_mb=5, allowed_exts=['pdf', 'jpg', 'jpeg', 'png'], label='Cost Sharing Agreement / Document')
                    if cs_err:
                        return request.redirect('/my/candidate/profile?step=3&upload_error=' + urllib.parse.quote(cs_err))

                    edu_doc_file = kwargs.get('education_doc_file')
                    ed_data, ed_filename, ed_err = _validate_uploaded_file(edu_doc_file, max_mb=5, allowed_exts=['pdf', 'jpg', 'jpeg', 'png'], label='Degree / Diploma / Transcript Document')
                    if ed_err:
                        return request.redirect('/my/candidate/profile?step=3&upload_error=' + urllib.parse.quote(ed_err))

                    grad_year_input = kwargs.get('graduation_year')
                    grad_date = False
                    if grad_year_input and str(grad_year_input).strip():
                        s_val = str(grad_year_input).strip()
                        grad_date = f"{s_val}-01-01" if len(s_val) == 4 and s_val.isdigit() else s_val

                    vals = {
                        'education_level': edu_level,
                        'qualification_name': kwargs.get('qualification_name') or edu_level,
                        'field_of_study': field_study or '',
                        'other_field_of_study': kwargs.get('other_field_of_study', ''),
                        'institution': inst or '',
                        'other_institution': kwargs.get('other_institution', ''),
                        'program_type': kwargs.get('program_type', 'regular'),
                        'has_cost_sharing': has_cs,
                        'graduation_year': grad_date,
                        'cgpa': float(kwargs.get('cgpa', 0.0) or 0.0),
                    }
                    if cs_data:
                        vals['cost_sharing_file'] = cs_data
                        vals['cost_sharing_filename'] = cs_filename
                    if ed_data:
                        vals['education_doc_file'] = ed_data
                        vals['education_doc_filename'] = ed_filename

                    request.env['candidate.education'].sudo().browse(int(edit_id)).write(vals)
                else:
                    # Multi-entry creation mode
                    fields_list = request.httprequest.form.getlist('field_of_study')
                    inst_list = request.httprequest.form.getlist('institution')
                    level_list = request.httprequest.form.getlist('education_level')
                    prog_list = request.httprequest.form.getlist('program_type')
                    grad_list = request.httprequest.form.getlist('graduation_year')
                    cgpa_list = request.httprequest.form.getlist('cgpa')
                    other_f_list = request.httprequest.form.getlist('other_field_of_study')
                    other_i_list = request.httprequest.form.getlist('other_institution')
                    cs_files = request.httprequest.files.getlist('cost_sharing_file')
                    ed_files = request.httprequest.files.getlist('education_doc_file')

                    num_entries = max(len(fields_list), len(inst_list), 1)
                    for i in range(num_entries):
                        f_study = fields_list[i].strip() if i < len(fields_list) else (kwargs.get('field_of_study', '').strip() if i == 0 else '')
                        inst = inst_list[i].strip() if i < len(inst_list) else (kwargs.get('institution', '').strip() if i == 0 else '')
                        if not f_study and not inst:
                            continue

                        lvl = level_list[i] if i < len(level_list) else kwargs.get('education_level', 'bsc')
                        prog = prog_list[i] if i < len(prog_list) else kwargs.get('program_type', 'regular')
                        g_val = grad_list[i].strip() if i < len(grad_list) else str(kwargs.get('graduation_year', '')).strip()
                        grad_date = f"{g_val}-01-01" if len(g_val) == 4 and g_val.isdigit() else (g_val or False)
                        cgpa_val = cgpa_list[i] if i < len(cgpa_list) else kwargs.get('cgpa', '0.0')
                        other_f = other_f_list[i] if i < len(other_f_list) else kwargs.get('other_field_of_study', '')
                        other_i = other_i_list[i] if i < len(other_i_list) else kwargs.get('other_institution', '')

                        if f_study == 'Other' and other_f:
                            f_study = other_f
                        if inst == 'Other' and other_i:
                            inst = other_i

                        cs_file = cs_files[i] if i < len(cs_files) else (kwargs.get('cost_sharing_file') if i == 0 else None)
                        cs_data, cs_filename, _ = _validate_uploaded_file(cs_file, max_mb=5, allowed_exts=['pdf', 'jpg', 'jpeg', 'png'])

                        ed_file = ed_files[i] if i < len(ed_files) else (kwargs.get('education_doc_file') if i == 0 else None)
                        ed_data, ed_filename, _ = _validate_uploaded_file(ed_file, max_mb=5, allowed_exts=['pdf', 'jpg', 'jpeg', 'png'])

                        vals = {
                            'candidate_id': candidate.id,
                            'education_level': lvl,
                            'qualification_name': lvl,
                            'field_of_study': f_study,
                            'other_field_of_study': other_f,
                            'institution': inst,
                            'other_institution': other_i,
                            'program_type': prog,
                            'graduation_year': grad_date,
                            'cgpa': float(cgpa_val or 0.0),
                        }
                        if cs_data:
                            vals['cost_sharing_file'] = cs_data
                            vals['cost_sharing_filename'] = cs_filename
                            vals['has_cost_sharing'] = True
                        if ed_data:
                            vals['education_doc_file'] = ed_data
                            vals['education_doc_filename'] = ed_filename

                        request.env['candidate.education'].sudo().create(vals)

                return request.redirect('/my/candidate/profile?step=4')

            elif step == 4:
                # Handle single edit or multiple new experience entries
                edit_id = kwargs.get('edit_id')
                if edit_id:
                    pos = kwargs.get('position')
                    org = kwargs.get('organization')
                    is_curr = kwargs.get('is_current') == '1'

                    exp_file = kwargs.get('exp_file')
                    exp_data, exp_filename, exp_err = _validate_uploaded_file(exp_file, max_mb=5, allowed_exts=['pdf', 'docx', 'doc', 'jpg', 'jpeg', 'png'], label='Experience / Service Certificate')
                    if exp_err:
                        return request.redirect('/my/candidate/profile?step=4&upload_error=' + urllib.parse.quote(exp_err))

                    vals = {
                        'position': pos or '',
                        'organization': org or '',
                        'employment_type': kwargs.get('employment_type', 'full_time'),
                        'sector_type': kwargs.get('sector_type', 'banking'),
                        'start_date': _clean_date(kwargs.get('start_date')),
                        'end_date': False if is_curr else _clean_date(kwargs.get('end_date')),
                        'is_current': is_curr,
                        'responsibilities': kwargs.get('responsibilities', ''),
                    }
                    if exp_data:
                        vals['exp_file'] = exp_data
                        vals['exp_filename'] = exp_filename

                    request.env['candidate.experience'].sudo().browse(int(edit_id)).write(vals)
                else:
                    # Multi-entry creation mode
                    pos_list = request.httprequest.form.getlist('position')
                    org_list = request.httprequest.form.getlist('organization')
                    sector_list = request.httprequest.form.getlist('sector_type')
                    emp_type_list = request.httprequest.form.getlist('employment_type')
                    start_list = request.httprequest.form.getlist('start_date')
                    end_list = request.httprequest.form.getlist('end_date')
                    curr_list = request.httprequest.form.getlist('is_current')
                    resp_list = request.httprequest.form.getlist('responsibilities')
                    exp_files = request.httprequest.files.getlist('exp_file')

                    num_entries = max(len(pos_list), len(org_list), 1)
                    for i in range(num_entries):
                        pos = pos_list[i].strip() if i < len(pos_list) else (kwargs.get('position', '').strip() if i == 0 else '')
                        org = org_list[i].strip() if i < len(org_list) else (kwargs.get('organization', '').strip() if i == 0 else '')
                        if not pos and not org:
                            continue

                        sec = sector_list[i] if i < len(sector_list) else kwargs.get('sector_type', 'banking')
                        emp_t = emp_type_list[i] if i < len(emp_type_list) else kwargs.get('employment_type', 'full_time')
                        s_date = _clean_date(start_list[i]) if i < len(start_list) else _clean_date(kwargs.get('start_date'))
                        e_date_raw = end_list[i] if i < len(end_list) else kwargs.get('end_date')
                        is_c = (curr_list[i] == '1' if i < len(curr_list) else kwargs.get('is_current') == '1')
                        e_date = False if is_c else _clean_date(e_date_raw)
                        resp = resp_list[i] if i < len(resp_list) else kwargs.get('responsibilities', '')

                        exp_file = exp_files[i] if i < len(exp_files) else (kwargs.get('exp_file') if i == 0 else None)
                        exp_data, exp_filename, _ = _validate_uploaded_file(exp_file, max_mb=5, allowed_exts=['pdf', 'docx', 'doc', 'jpg', 'jpeg', 'png'])

                        vals = {
                            'candidate_id': candidate.id,
                            'position': pos,
                            'organization': org,
                            'employment_type': emp_t,
                            'sector_type': sec,
                            'start_date': s_date,
                            'end_date': e_date,
                            'is_current': is_c,
                            'responsibilities': resp,
                        }
                        if exp_data:
                            vals['exp_file'] = exp_data
                            vals['exp_filename'] = exp_filename

                        request.env['candidate.experience'].sudo().create(vals)

                return request.redirect('/my/candidate/profile?step=5')

            elif step == 5:
                # Handle single edit or multiple new certification entries
                edit_id = kwargs.get('edit_id')
                if edit_id:
                    name = kwargs.get('cert_name')
                    has_exp = kwargs.get('has_expiry') == '1'
                    cert_file = kwargs.get('cert_file')
                    cert_data, cert_filename, cert_err = _validate_uploaded_file(cert_file, max_mb=5, allowed_exts=['pdf', 'jpg', 'jpeg', 'png'], label='Certification Document')
                    if cert_err:
                        return request.redirect('/my/candidate/profile?step=5&upload_error=' + urllib.parse.quote(cert_err))

                    vals = {
                        'name': name or '',
                        'issuing_organization': kwargs.get('issuing_organization', ''),
                        'issue_date': _clean_date(kwargs.get('issue_date')),
                        'has_expiry': has_exp,
                        'expiry_date': _clean_date(kwargs.get('expiry_date')) if has_exp else False,
                        'cert_url': kwargs.get('cert_url', ''),
                    }
                    if cert_data:
                        vals['cert_file'] = cert_data
                        vals['cert_filename'] = cert_filename

                    request.env['candidate.certification'].sudo().browse(int(edit_id)).write(vals)
                else:
                    # Multi-entry creation mode
                    name_list = request.httprequest.form.getlist('cert_name')
                    org_list = request.httprequest.form.getlist('issuing_organization')
                    issue_list = request.httprequest.form.getlist('issue_date')
                    has_exp_list = request.httprequest.form.getlist('has_expiry')
                    exp_date_list = request.httprequest.form.getlist('expiry_date')
                    url_list = request.httprequest.form.getlist('cert_url')
                    cert_files = request.httprequest.files.getlist('cert_file')

                    num_entries = max(len(name_list), 1)
                    for i in range(num_entries):
                        name = name_list[i].strip() if i < len(name_list) else (kwargs.get('cert_name', '').strip() if i == 0 else '')
                        if not name:
                            continue

                        org = org_list[i].strip() if i < len(org_list) else kwargs.get('issuing_organization', '')
                        i_date = _clean_date(issue_list[i]) if i < len(issue_list) else _clean_date(kwargs.get('issue_date'))
                        has_e = (has_exp_list[i] == '1' if i < len(has_exp_list) else kwargs.get('has_expiry') == '1')
                        e_date = _clean_date(exp_date_list[i]) if (has_e and i < len(exp_date_list)) else (_clean_date(kwargs.get('expiry_date')) if has_e else False)
                        c_url = url_list[i].strip() if i < len(url_list) else kwargs.get('cert_url', '')

                        cert_file = cert_files[i] if i < len(cert_files) else (kwargs.get('cert_file') if i == 0 else None)
                        cert_data, cert_filename, _ = _validate_uploaded_file(cert_file, max_mb=5, allowed_exts=['pdf', 'jpg', 'jpeg', 'png'])

                        vals = {
                            'candidate_id': candidate.id,
                            'name': name,
                            'issuing_organization': org,
                            'issue_date': i_date,
                            'has_expiry': has_e,
                            'expiry_date': e_date,
                            'cert_url': c_url,
                        }
                        if cert_data:
                            vals['cert_file'] = cert_data
                            vals['cert_filename'] = cert_filename

                        request.env['candidate.certification'].sudo().create(vals)

                return request.redirect('/my/candidate/profile?step=6')

            elif step == 6:
                # Handle single edit or multiple new language entries
                edit_id = kwargs.get('edit_id')
                if edit_id:
                    lang_name = kwargs.get('lang_name')
                    request.env['candidate.language'].sudo().browse(int(edit_id)).write({
                        'name': lang_name,
                        'proficiency': kwargs.get('proficiency', 'fluent'),
                    })
                else:
                    # Multi-entry creation mode
                    lang_list = request.httprequest.form.getlist('lang_name')
                    prof_list = request.httprequest.form.getlist('proficiency')

                    num_entries = max(len(lang_list), 1)
                    for i in range(num_entries):
                        l_name = lang_list[i].strip() if i < len(lang_list) else (kwargs.get('lang_name', '').strip() if i == 0 else '')
                        if not l_name:
                            continue
                        prof = prof_list[i] if i < len(prof_list) else kwargs.get('proficiency', 'fluent')
                        request.env['candidate.language'].sudo().create({
                            'candidate_id': candidate.id,
                            'name': l_name,
                            'proficiency': prof,
                        })

                return request.redirect('/my/candidate/profile?step=7')

            elif step == 7:
                # Documents & Links
                write_vals = {
                    'linkedin_url': kwargs.get('linkedin_url', candidate.linkedin_url),
                    'portfolio_url': kwargs.get('portfolio_url', candidate.portfolio_url),
                    'github_url': kwargs.get('github_url', candidate.github_url),
                }

                cv_file = kwargs.get('cv_file')
                cv_data, cv_filename, cv_err = _validate_uploaded_file(cv_file, max_mb=5, allowed_exts=['pdf', 'docx', 'doc'], label='Curriculum Vitae (CV / Resume)')
                if cv_err:
                    return request.redirect('/my/candidate/profile?step=7&upload_error=' + urllib.parse.quote(cv_err))
                if cv_data:
                    write_vals['cv_file'] = cv_data
                    write_vals['cv_filename'] = cv_filename

                cl_file = kwargs.get('cover_letter_file')
                cl_data, cl_filename, cl_err = _validate_uploaded_file(cl_file, max_mb=5, allowed_exts=['pdf', 'docx', 'doc'], label='Cover Letter Document')
                if cl_err:
                    return request.redirect('/my/candidate/profile?step=7&upload_error=' + urllib.parse.quote(cl_err))
                if cl_data:
                    write_vals['cover_letter_file'] = cl_data
                    write_vals['cover_letter_filename'] = cl_filename

                candidate.sudo().write(write_vals)

                # Supporting Document entry (Tempo / Permits / IDs / Transcripts)
                doc_title = kwargs.get('doc_title')
                doc_file = kwargs.get('doc_file')
                doc_data, doc_filename, doc_err = _validate_uploaded_file(doc_file, max_mb=2, allowed_exts=['pdf', 'jpg', 'jpeg', 'png'], label='Tempo / Work ID / Supporting Document')
                if doc_err:
                    return request.redirect('/my/candidate/profile?step=7&upload_error=' + urllib.parse.quote(doc_err))

                if doc_title:
                    request.env['candidate.document'].sudo().create({
                        'candidate_id': candidate.id,
                        'name': doc_title,
                        'attachment': doc_data,
                        'filename': doc_filename,
                        'document_url': kwargs.get('document_url', ''),
                    })

                return request.redirect('/my/candidate/profile?step=1')

        # Split name for display
        names = (candidate.name or '').split(' ')
        first_name = names[0] if len(names) > 0 else ''
        middle_name = names[1] if len(names) > 1 else ''
        last_name = ' '.join(names[2:]) if len(names) > 2 else ''

        # Completeness calculation
        completeness = 20
        if candidate.cv_file: completeness += 16
        if candidate.education_ids: completeness += 16
        if candidate.experience_ids: completeness += 16
        if candidate.certification_ids: completeness += 16
        if candidate.document_ids: completeness += 16

        values = {
            'candidate': candidate,
            'step': step,
            'first_name': first_name,
            'middle_name': middle_name,
            'last_name': last_name,
            'completeness': min(100, completeness),
            'edit_edu': request.env['candidate.education'].sudo().browse(int(kwargs.get('edit_edu_id'))) if kwargs.get('edit_edu_id') else False,
            'edit_exp': request.env['candidate.experience'].sudo().browse(int(kwargs.get('edit_exp_id'))) if kwargs.get('edit_exp_id') else False,
            'edit_cert': request.env['candidate.certification'].sudo().browse(int(kwargs.get('edit_cert_id'))) if kwargs.get('edit_cert_id') else False,
            'edit_lang': request.env['candidate.language'].sudo().browse(int(kwargs.get('edit_lang_id'))) if kwargs.get('edit_lang_id') else False,
            'error_msg': kwargs.get('error') or kwargs.get('error_msg') or False,
        }
        return request.render('custom_recruitment.ats_candidate_profile_template', values)

    # ---------------------------------------------------------------
    # Section Delete Routes
    # ---------------------------------------------------------------
    @http.route('/my/candidate/profile/education/delete/<int:item_id>', type='http', auth='user', website=True)
    def delete_education(self, item_id, **kw):
        rec = request.env['candidate.education'].sudo().browse(item_id)
        if rec.exists() and rec.candidate_id.user_id.id == request.env.user.id:
            rec.unlink()
        return request.redirect('/my/candidate/profile?step=3')

    @http.route('/my/candidate/profile/experience/delete/<int:item_id>', type='http', auth='user', website=True)
    def delete_experience(self, item_id, **kw):
        rec = request.env['candidate.experience'].sudo().browse(item_id)
        if rec.exists() and rec.candidate_id.user_id.id == request.env.user.id:
            rec.unlink()
        return request.redirect('/my/candidate/profile?step=4')

    @http.route('/my/candidate/profile/certification/delete/<int:item_id>', type='http', auth='user', website=True)
    def delete_certification(self, item_id, **kw):
        rec = request.env['candidate.certification'].sudo().browse(item_id)
        if rec.exists() and rec.candidate_id.user_id.id == request.env.user.id:
            rec.unlink()
        return request.redirect('/my/candidate/profile?step=5')

    @http.route('/my/candidate/profile/language/delete/<int:item_id>', type='http', auth='user', website=True)
    def delete_language(self, item_id, **kw):
        rec = request.env['candidate.language'].sudo().browse(item_id)
        if rec.exists() and rec.candidate_id.user_id.id == request.env.user.id:
            rec.unlink()
        return request.redirect('/my/candidate/profile?step=6')

    @http.route('/my/candidate/profile/document/delete/<int:item_id>', type='http', auth='user', website=True)
    def delete_document(self, item_id, **kw):
        rec = request.env['candidate.document'].sudo().browse(item_id)
        if rec.exists() and rec.candidate_id.user_id.id == request.env.user.id:
            rec.unlink()
        return request.redirect('/my/candidate/profile?step=7')

    # ---------------------------------------------------------------
    # Document Download Endpoints
    # ---------------------------------------------------------------
    @http.route('/my/candidate/cv/download', type='http', auth='user', website=True)
    def download_cv(self, **kw):
        candidate = self._get_candidate_profile()
        if candidate and candidate.cv_file:
            filecontent = base64.b64decode(candidate.cv_file)
            filename = candidate.cv_filename or 'Master_CV.pdf'
            return request.make_response(filecontent, [
                ('Content-Type', 'application/octet-stream'),
                ('Content-Disposition', content_disposition(filename)),
            ])
        return request.notFound()

    @http.route('/my/candidate/cover_letter/download', type='http', auth='user', website=True)
    def download_cover_letter(self, **kw):
        candidate = self._get_candidate_profile()
        if candidate and candidate.cover_letter_file:
            filecontent = base64.b64decode(candidate.cover_letter_file)
            filename = candidate.cover_letter_filename or 'Cover_Letter.pdf'
            return request.make_response(filecontent, [
                ('Content-Type', 'application/octet-stream'),
                ('Content-Disposition', content_disposition(filename)),
            ])
        return request.notFound()

    @http.route('/my/candidate/education/cost_sharing/download/<int:edu_id>', type='http', auth='user', website=True)
    def download_cost_sharing(self, edu_id, **kw):
        edu = request.env['candidate.education'].sudo().browse(edu_id)
        if edu.exists() and edu.cost_sharing_file:
            filecontent = base64.b64decode(edu.cost_sharing_file)
            filename = edu.cost_sharing_filename or f"CostSharing_{edu.id}.pdf"
            return request.make_response(filecontent, [
                ('Content-Type', 'application/octet-stream'),
                ('Content-Disposition', content_disposition(filename)),
            ])
        return request.notFound()

    @http.route('/my/candidate/education/doc/download/<int:edu_id>', type='http', auth='user', website=True)
    def download_edu_doc(self, edu_id, **kw):
        edu = request.env['candidate.education'].sudo().browse(edu_id)
        if edu.exists() and edu.education_doc_file:
            filecontent = base64.b64decode(edu.education_doc_file)
            filename = edu.education_doc_filename or f"EducationDoc_{edu.id}.pdf"
            return request.make_response(filecontent, [
                ('Content-Type', 'application/octet-stream'),
                ('Content-Disposition', content_disposition(filename)),
            ])
        return request.notFound()

    @http.route('/my/candidate/exp/download/<int:exp_id>', type='http', auth='user', website=True)
    def download_exp_doc(self, exp_id, **kw):
        exp = request.env['candidate.experience'].sudo().browse(exp_id)
        if exp.exists() and exp.exp_file:
            filecontent = base64.b64decode(exp.exp_file)
            filename = exp.exp_filename or f"Experience_{exp.id}.pdf"
            return request.make_response(filecontent, [
                ('Content-Type', 'application/octet-stream'),
                ('Content-Disposition', content_disposition(filename)),
            ])
        return request.notFound()

    @http.route('/my/candidate/cert/download/<int:cert_id>', type='http', auth='user', website=True)
    def download_cert(self, cert_id, **kw):
        cert = request.env['candidate.certification'].sudo().browse(cert_id)
        if cert.exists() and cert.cert_file:
            filecontent = base64.b64decode(cert.cert_file)
            filename = cert.cert_filename or f"{cert.name}.pdf"
            return request.make_response(filecontent, [
                ('Content-Type', 'application/octet-stream'),
                ('Content-Disposition', content_disposition(filename)),
            ])
        return request.notFound()

    @http.route('/my/candidate/doc/download/<int:doc_id>', type='http', auth='user', website=True)
    def download_doc(self, doc_id, **kw):
        doc = request.env['candidate.document'].sudo().browse(doc_id)
        if doc.exists() and doc.attachment:
            filecontent = base64.b64decode(doc.attachment)
            filename = doc.filename or f"{doc.name}.pdf"
            return request.make_response(filecontent, [
                ('Content-Type', 'application/octet-stream'),
                ('Content-Disposition', content_disposition(filename)),
            ])
        return request.notFound()


    # ---------------------------------------------------------------
    # Candidate Change Password Route
    # ---------------------------------------------------------------
    @http.route(['/my/candidate/change_password', '/my/candidate/change-password'], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def candidate_change_password(self, **kwargs):
        candidate = self._get_candidate_profile()
        if not candidate:
            return request.redirect('/jobs/login')

        error = False
        success = False
        if request.httprequest.method == 'POST':
            old_pwd = kwargs.get('old_password', '')
            new_pwd = kwargs.get('new_password', '')
            confirm_pwd = kwargs.get('confirm_password', '')

            user = request.env.user
            try:
                user._check_credentials(old_pwd, {'interactive': True})
                if not new_pwd or new_pwd != confirm_pwd:
                    error = "New Password and Confirm Password do not match."
                elif len(new_pwd) < 6:
                    error = "New Password must be at least 6 characters long."
                else:
                    user.sudo().write({'password': new_pwd})
                    success = "Your password has been changed successfully!"
            except Exception:
                error = "The current password you entered is incorrect."

        values = {
            'candidate': candidate,
            'error': error,
            'success': success,
        }
        return request.render('custom_recruitment.ats_change_password_template', values)

    @http.route(['/my/candidate/applications/withdraw/<int:app_id>', '/my/candidate/applications/withdraw'], type='http', auth='user', website=True, methods=['GET', 'POST'], csrf=False)
    def withdraw_application(self, app_id=None, **kw):
        """Allows candidates to withdraw their job application via the ATS portal (BRD FR-ATS-026)."""
        target_id = app_id or kw.get('app_id')
        if not target_id:
            return request.redirect('/my/candidate/applications')
        try:
            target_id = int(target_id)
        except (ValueError, TypeError):
            return request.redirect('/my/candidate/applications')

        candidate = self._get_candidate_profile()
        user = request.env.user
        applicant = request.env['hr.applicant'].sudo().browse(target_id)

        if applicant.exists():
            cand_email = (candidate.email if candidate else user.email or '').strip().lower()
            app_email = (applicant.email_from or '').strip().lower()
            is_owner = (
                (candidate and applicant.candidate_profile_id and applicant.candidate_profile_id.id == candidate.id) or
                (applicant.partner_id and applicant.partner_id.id == user.partner_id.id) or
                (cand_email and app_email and cand_email == app_email)
            )
            if is_owner:
                applicant.sudo().write({
                    'bunna_app_status': 'rejected',
                    'rejection_reason': 'Withdrawn by Candidate via ATS Portal.',
                })
                try:
                    applicant.message_post(body=_("Application withdrawn by candidate via ATS Portal."))
                except Exception:
                    pass

        return request.redirect('/my/candidate/applications?withdrawn=1')

    @http.route('/my/candidate/profile/delete', type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def request_profile_deletion(self, **kw):
        """Allows candidates to request profile & data deletion in compliance with privacy regulations (BRD FR-ATS-009)."""
        candidate = self._get_candidate_profile()
        if candidate:
            user = request.env.user
            candidate.sudo().write({'active': False})
            user.sudo().write({'active': False})
            request.session.logout()
        return request.redirect('/jobs/login')

