from datetime import datetime

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

        applications = request.env['hr.applicant'].sudo().search([
            '|',
            ('candidate_profile_id', '=', candidate.id),
            ('email_from', '=ilike', candidate.email or 'never_match_placeholder'),
        ], order='create_date desc')

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

        applications = request.env['hr.applicant'].sudo().search([
            '|',
            ('candidate_profile_id', '=', candidate.id),
            ('email_from', '=ilike', candidate.email or 'never_match_placeholder'),
        ], order='create_date desc')

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
                # Add/Update Education
                edit_id = kwargs.get('edit_id')
                edu_level = kwargs.get('education_level', 'bsc')
                field_study = kwargs.get('field_of_study')
                if field_study == 'Other':
                    field_study = kwargs.get('other_field_of_study') or 'Other'
                
                inst = kwargs.get('institution')
                if inst == 'Other':
                    inst = kwargs.get('other_institution') or 'Other'

                has_cs = kwargs.get('has_cost_sharing') == '1'
                cs_file = kwargs.get('cost_sharing_file')
                cs_data, cs_filename = False, False
                if cs_file and hasattr(cs_file, 'read'):
                    c = cs_file.read()
                    if c:
                        cs_data = base64.b64encode(c)
                        cs_filename = cs_file.filename

                edu_doc_file = kwargs.get('education_doc_file')
                ed_data, ed_filename = False, False
                if edu_doc_file and hasattr(edu_doc_file, 'read'):
                    c = edu_doc_file.read()
                    if c:
                        ed_data = base64.b64encode(c)
                        ed_filename = edu_doc_file.filename

                grad_year_input = kwargs.get('graduation_year')
                grad_date = False
                if grad_year_input and str(grad_year_input).strip():
                    s_val = str(grad_year_input).strip()
                    if len(s_val) == 4 and s_val.isdigit():
                        grad_date = f"{s_val}-01-01"
                    else:
                        grad_date = s_val

                vals = {
                    'candidate_id': candidate.id,
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

                if edit_id:
                    request.env['candidate.education'].sudo().browse(int(edit_id)).write(vals)
                elif field_study and inst:
                    request.env['candidate.education'].sudo().create(vals)

                return request.redirect('/my/candidate/profile?step=4')

            elif step == 4:
                # Add/Update Experience
                edit_id = kwargs.get('edit_id')
                pos = kwargs.get('position')
                org = kwargs.get('organization')
                is_curr = kwargs.get('is_current') == '1'

                exp_file = kwargs.get('exp_file')
                exp_data, exp_filename = False, False
                if exp_file and hasattr(exp_file, 'read'):
                    c = exp_file.read()
                    if c:
                        exp_data = base64.b64encode(c)
                        exp_filename = exp_file.filename

                candidate.sudo().write({
                    'worked_in_bunna_earlier': kwargs.get('worked_in_bunna_earlier', candidate.worked_in_bunna_earlier),
                    'last_position_held': kwargs.get('last_position_held', candidate.last_position_held),
                    'last_department': kwargs.get('last_department', candidate.last_department),
                    'reporting_manager': kwargs.get('reporting_manager', candidate.reporting_manager),
                    'length_of_service': float(kwargs.get('length_of_service', 0.0) or 0.0),
                    'termination_reason': kwargs.get('termination_reason', candidate.termination_reason),
                    'supervisory_experience': float(kwargs.get('supervisory_experience', 0.0) or 0.0),
                })

                vals = {
                    'candidate_id': candidate.id,
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

                if edit_id:
                    request.env['candidate.experience'].sudo().browse(int(edit_id)).write(vals)
                elif pos and org:
                    request.env['candidate.experience'].sudo().create(vals)

                return request.redirect('/my/candidate/profile?step=5')

            elif step == 5:
                # Add/Update Certification
                edit_id = kwargs.get('edit_id')
                name = kwargs.get('cert_name')
                has_exp = kwargs.get('has_expiry') == '1'

                cert_file = kwargs.get('cert_file')
                cert_data, cert_filename = False, False
                if cert_file and hasattr(cert_file, 'read'):
                    c = cert_file.read()
                    if c:
                        cert_data = base64.b64encode(c)
                        cert_filename = cert_file.filename

                vals = {
                    'candidate_id': candidate.id,
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

                if edit_id:
                    request.env['candidate.certification'].sudo().browse(int(edit_id)).write(vals)
                elif name:
                    request.env['candidate.certification'].sudo().create(vals)

                return request.redirect('/my/candidate/profile?step=6')

            elif step == 6:
                # Add/Update Language
                edit_id = kwargs.get('edit_id')
                lang_name = kwargs.get('lang_name')
                if edit_id:
                    request.env['candidate.language'].sudo().browse(int(edit_id)).write({
                        'name': lang_name,
                        'proficiency': kwargs.get('proficiency', 'fluent'),
                    })
                elif lang_name:
                    request.env['candidate.language'].sudo().create({
                        'candidate_id': candidate.id,
                        'name': lang_name,
                        'proficiency': kwargs.get('proficiency', 'fluent'),
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
                if cv_file and hasattr(cv_file, 'read'):
                    c = cv_file.read()
                    if c:
                        write_vals['cv_file'] = base64.b64encode(c)
                        write_vals['cv_filename'] = cv_file.filename

                cl_file = kwargs.get('cover_letter_file')
                if cl_file and hasattr(cl_file, 'read'):
                    c = cl_file.read()
                    if c:
                        write_vals['cover_letter_file'] = base64.b64encode(c)
                        write_vals['cover_letter_filename'] = cl_file.filename

                candidate.sudo().write(write_vals)

                # Supporting Document entry
                doc_title = kwargs.get('doc_title')
                doc_file = kwargs.get('doc_file')
                doc_data, doc_filename = False, False
                if doc_file and hasattr(doc_file, 'read'):
                    c = doc_file.read()
                    if c:
                        doc_data = base64.b64encode(c)
                        doc_filename = doc_file.filename

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

    @http.route('/my/candidate/applications/withdraw/<int:app_id>', type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def withdraw_application(self, app_id, **kw):
        """Allows candidates to withdraw their job application before closing date (BRD FR-ATS-026)."""
        candidate = self._get_candidate_profile()
        if not candidate:
            return request.redirect('/jobs/login')

        applicant = request.env['hr.applicant'].sudo().browse(app_id)
        if applicant.exists() and applicant.candidate_profile_id.id == candidate.id:
            vacancy = applicant.app_reference
            today = fields.Date.today()
            if not vacancy or not vacancy.last_date_to_apply or vacancy.last_date_to_apply >= today:
                applicant.sudo().write({
                    'bunna_app_status': 'rejected',
                    'rejection_reason': 'Withdrawn by Candidate prior to vacancy closing date.',
                })
                applicant.message_post(body=_("Application withdrawn by candidate."))

        return request.redirect('/my/candidate/applications')

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

