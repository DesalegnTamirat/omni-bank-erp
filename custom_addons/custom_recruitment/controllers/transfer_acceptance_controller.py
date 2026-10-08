# -*- coding: utf-8 -*-

import html
import logging
from markupsafe import Markup
from odoo import http, fields, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class TransferAcceptanceController(http.Controller):

    @http.route('/recruitment/transfer_acceptance/<int:candidate_id>', type='http', auth='user', website=False)
    def transfer_acceptance_page(self, candidate_id, **kw):
        """
        Direct landing portal page for candidates to review their Lateral Transfer / Internal Promotion offer
        and formally Accept or Decline.
        """
        candidate = request.env['new.internal.recruitment.selected.candidates'].sudo().browse(candidate_id)
        if not candidate.exists():
            return request.not_found()

        user = request.env.user
        user_emp = user.employee_id or request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        # Access check: Must be the candidate employee or an authorized HR officer / administrator
        is_hr = (
            user.has_group('custom_recruitment.group_recruitment_officer') or
            user.has_group('custom_recruitment.group_recruitment_manager') or
            user.has_group('base.group_system')
        )
        is_candidate_user = user_emp and candidate.emp_name and user_emp.id == candidate.emp_name.id

        if not is_candidate_user and not is_hr:
            return request.make_response(
                """<!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">
                    <title>Access Restricted</title>
                    <style>
                        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f8f9fa; }
                        .card { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); max-width: 500px; text-align: center; }
                        h2 { color: #541718; margin-top: 0; }
                        p { color: #555; font-size: 15px; line-height: 1.6; margin-bottom: 24px; }
                        .btn { display: inline-block; padding: 10px 22px; background: #541718; color: white; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; }
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h2>Access Restricted</h2>
                        <p>This transfer offer response portal is only accessible to the selected candidate or HR administrators.</p>
                        <a href="/web" class="btn">Return to Odoo</a>
                    </div>
                </body>
                </html>""",
                headers=[('Content-Type', 'text/html;charset=utf-8')]
            )

        parent_sel = candidate.new_int_sel_cand
        vac = False
        if parent_sel and parent_sel.vacancy_id:
            vac = request.env['job.vacancy'].sudo().browse(parent_sel.vacancy_id)
        elif parent_sel and parent_sel.vacancy_reference:
            vac = request.env['job.vacancy'].sudo().search([('reference', '=', parent_sel.vacancy_reference)], limit=1)

        emp_name = candidate.emp_name.name if candidate.emp_name else _('Candidate')
        current_pos = candidate.emp_position or (candidate.emp_name.job_title if candidate.emp_name else _('Current Position'))
        current_loc = candidate.current_work_unit or (
            candidate.emp_name.default_operating_unit_id.name if (candidate.emp_name and candidate.emp_name.default_operating_unit_id) else _('Current Unit')
        )

        target_pos = (
            (parent_sel.job_position.name if (parent_sel and parent_sel.job_position) else False) or
            (vac.job_position.name if (vac and vac.job_position) else _('Target Position'))
        )
        target_loc = (
            parent_sel.job_location or
            (vac.operating_unit_id.name if (vac and vac.operating_unit_id) else _('Target Unit'))
        )
        vac_ref = parent_sel.vacancy_reference or (vac.reference if vac else _('N/A'))

        is_lateral = (
            (vac and getattr(vac, 'internal_movement_type', False) in ('lateral', 'transfer'))
            or 'LAT' in vac_ref.upper()
            or (vac and getattr(vac, 'transfer_eval_mode', False) == 'transfer_matrix_only')
            or (parent_sel and getattr(parent_sel, 'transfer_eval_mode', False) == 'transfer_matrix_only')
        )
        movement_title = _("Lateral Transfer Offer") if is_lateral else _("Internal Promotion Offer")

        status = candidate.acceptance_status or 'pending'
        resp_date = candidate.acceptance_date or ''
        reason = candidate.rejection_reason or ''

        return request.make_response(
            self._render_portal_html(
                candidate_id=candidate.id,
                movement_title=movement_title,
                is_lateral=is_lateral,
                emp_name=emp_name,
                current_pos=current_pos,
                current_loc=current_loc,
                target_pos=target_pos,
                target_loc=target_loc,
                vac_ref=vac_ref,
                status=status,
                resp_date=str(resp_date),
                reason=reason,
                csrf_token=request.csrf_token(),
            ),
            headers=[('Content-Type', 'text/html;charset=utf-8')]
        )

    @http.route('/recruitment/transfer_acceptance/<int:candidate_id>/accept', type='http', auth='user', methods=['POST'], website=False)
    def accept_transfer(self, candidate_id, **kw):
        candidate = request.env['new.internal.recruitment.selected.candidates'].sudo().browse(candidate_id)
        if not candidate.exists():
            return request.not_found()

        if candidate.acceptance_status != 'accepted':
            candidate.action_accept_promotion()

        return request.redirect(f'/recruitment/transfer_acceptance/{candidate_id}')

    @http.route('/recruitment/transfer_acceptance/<int:candidate_id>/decline', type='http', auth='user', methods=['POST'], website=False)
    def decline_transfer(self, candidate_id, **kw):
        candidate = request.env['new.internal.recruitment.selected.candidates'].sudo().browse(candidate_id)
        if not candidate.exists():
            return request.not_found()

        reason = kw.get('rejection_reason', '').strip()
        if not reason:
            return request.make_response(
                """<!DOCTYPE html>
                <html><head><meta charset="utf-8"><title>Reason Required</title>
                <style>body{font-family:sans-serif;text-align:center;padding:50px;background:#f8f9fa;}
                .card{background:white;padding:30px;border-radius:8px;display:inline-block;box-shadow:0 2px 10px rgba(0,0,0,0.1);}
                h3{color:#d9534f;}
                .btn{display:inline-block;padding:8px 18px;background:#541718;color:white;text-decoration:none;border-radius:4px;font-weight:600;}
                </style></head><body><div class="card">
                <h3>Reason Required</h3>
                <p>Please provide a specific reason when declining an offer.</p>
                <a href="javascript:history.back()" class="btn">Go Back</a>
                </div></body></html>""",
                headers=[('Content-Type', 'text/html;charset=utf-8')]
            )

        candidate.confirm_decline_promotion(reason)
        return request.redirect(f'/recruitment/transfer_acceptance/{candidate_id}')

    def _render_portal_html(self, candidate_id, movement_title, is_lateral, emp_name, current_pos, current_loc, target_pos, target_loc, vac_ref, status, resp_date, reason, csrf_token):
        emp_name_escaped = html.escape(emp_name)
        current_pos_escaped = html.escape(current_pos)
        current_loc_escaped = html.escape(current_loc)
        target_pos_escaped = html.escape(target_pos)
        target_loc_escaped = html.escape(target_loc)
        vac_ref_escaped = html.escape(vac_ref)
        reason_escaped = html.escape(reason)

        offer_name = "Lateral Transfer" if is_lateral else "Internal Promotion"
        offer_name_lower = offer_name.lower()

        decision_html = ""
        if status == 'accepted':
            decision_html = f"""
            <div class="status-banner banner-accepted">
                <div class="banner-icon">✓</div>
                <div>
                    <h3 style="margin:0 0 4px 0; color:#15803d; font-size:18px;">Offer Accepted</h3>
                    <p style="margin:0; font-size:14px; color:#166534;">
                        You have formally <b>Accepted</b> this {offer_name_lower} offer on <b>{resp_date}</b>.
                        HR Operations has been notified and will proceed with the placement documentation.
                    </p>
                </div>
            </div>
            <div style="margin-top:24px; text-align:center;">
                <a href="/web" class="btn btn-secondary">Return to Odoo Portal</a>
            </div>
            """
        elif status == 'rejected':
            decision_html = f"""
            <div class="status-banner banner-rejected">
                <div class="banner-icon">✕</div>
                <div>
                    <h3 style="margin:0 0 4px 0; color:#b91c1c; font-size:18px;">Offer Declined</h3>
                    <p style="margin:0 0 8px 0; font-size:14px; color:#991b1b;">
                        You declined this {offer_name_lower} offer on <b>{resp_date}</b>.
                    </p>
                    <div style="background:white; padding:10px 14px; border-radius:6px; border:1px solid #fca5a5; font-size:13px; color:#374151;">
                        <b>Recorded Reason:</b> {reason_escaped}
                    </div>
                </div>
            </div>
            <div style="margin-top:24px; text-align:center;">
                <a href="/web" class="btn btn-secondary">Return to Odoo Portal</a>
            </div>
            """
        else:
            accept_btn_label = f"✓ Accept {offer_name} Offer"
            decline_btn_label = f"✕ Decline {offer_name} Offer"
            decision_html = f"""
            <div class="action-box">
                <h3 style="margin-top:0; color:#1e293b; font-size:18px;">Respond to {offer_name} Offer</h3>
                <p style="color:#64748b; font-size:14px; line-height:1.5;">
                    Please confirm your formal decision below. If declining, you must provide a reason so that HR can properly audit candidate selection.
                </p>

                <div class="button-row">
                    <!-- Accept Form -->
                    <form action="/recruitment/transfer_acceptance/{candidate_id}/accept" method="POST" style="margin:0;" onsubmit="return confirm('Are you sure you want to ACCEPT this {offer_name_lower} offer?');">
                        <input type="hidden" name="csrf_token" value="{csrf_token}"/>
                        <button type="submit" class="btn btn-accept">
                            {accept_btn_label}
                        </button>
                    </form>

                    <!-- Decline Button (triggers modal) -->
                    <button type="button" class="btn btn-decline" onclick="document.getElementById('declineModal').style.display='flex';">
                        {decline_btn_label}
                    </button>
                </div>
            </div>

            <!-- Decline Modal -->
            <div id="declineModal" class="modal-overlay" style="display:none;">
                <div class="modal-card">
                    <h3 style="margin-top:0; color:#b91c1c;">Decline {offer_name} Offer</h3>
                    <p style="color:#64748b; font-size:14px;">
                        Please state the reason why you are declining this {offer_name_lower} offer. Once submitted, this cannot be undone and the next ranked candidate will be considered.
                    </p>
                    <form action="/recruitment/transfer_acceptance/{candidate_id}/decline" method="POST">
                        <input type="hidden" name="csrf_token" value="{csrf_token}"/>
                        <div style="margin-bottom:16px;">
                            <label style="display:block; font-size:13px; font-weight:600; color:#334155; margin-bottom:6px;">
                                Reason for Declining <span style="color:#ef4444;">*</span>:
                            </label>
                            <textarea name="rejection_reason" required rows="4" style="width:100%; box-sizing:border-box; padding:10px; border-radius:6px; border:1px solid #cbd5e1; font-family:inherit; font-size:14px;" placeholder="e.g. Current location preference, personal/family constraints, etc."></textarea>
                        </div>
                        <div style="display:flex; justify-content:flex-end; gap:10px;">
                            <button type="button" class="btn btn-secondary" onclick="document.getElementById('declineModal').style.display='none';">Cancel</button>
                            <button type="submit" class="btn btn-decline">Confirm &amp; Decline Offer</button>
                        </div>
                    </form>
                </div>
            </div>
            """

        return f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{movement_title} - Bunna Bank</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    background-color: #f1f5f9;
                    margin: 0;
                    padding: 40px 20px;
                    color: #0f172a;
                }}
                .container {{
                    max-width: 680px;
                    margin: 0 auto;
                }}
                .header-card {{
                    background: linear-gradient(135deg, #541718 0%, #3d1011 100%);
                    color: white;
                    padding: 28px 32px;
                    border-radius: 12px 12px 0 0;
                    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                }}
                .header-card h1 {{
                    margin: 0 0 6px 0;
                    font-size: 24px;
                    font-weight: 700;
                    letter-spacing: -0.5px;
                }}
                .header-card p {{
                    margin: 0;
                    opacity: 0.85;
                    font-size: 14px;
                }}
                .main-card {{
                    background: white;
                    padding: 32px;
                    border-radius: 0 0 12px 12px;
                    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
                }}
                .comparison-grid {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 16px;
                    margin: 24px 0;
                }}
                @media (max-width: 580px) {{
                    .comparison-grid {{ grid-template-columns: 1fr; }}
                }}
                .placement-box {{
                    padding: 18px;
                    border-radius: 8px;
                    border: 1px solid #e2e8f0;
                    background-color: #f8fafc;
                }}
                .placement-box.new-target {{
                    border-color: #C17540;
                    background-color: #fffbf7;
                }}
                .placement-box h4 {{
                    margin: 0 0 10px 0;
                    font-size: 13px;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    color: #64748b;
                }}
                .placement-box.new-target h4 {{
                    color: #C17540;
                }}
                .placement-title {{
                    font-size: 16px;
                    font-weight: 700;
                    color: #1e293b;
                    margin-bottom: 4px;
                }}
                .placement-unit {{
                    font-size: 14px;
                    color: #475569;
                }}
                .meta-row {{
                    display: flex;
                    justify-content: space-between;
                    padding: 12px 0;
                    border-bottom: 1px solid #e2e8f0;
                    font-size: 14px;
                }}
                .meta-label {{
                    color: #64748b;
                    font-weight: 500;
                }}
                .meta-val {{
                    color: #1e293b;
                    font-weight: 600;
                }}
                .action-box {{
                    margin-top: 28px;
                    padding: 22px;
                    background-color: #f8fafc;
                    border-radius: 8px;
                    border: 1px solid #e2e8f0;
                }}
                .button-row {{
                    display: flex;
                    gap: 12px;
                    margin-top: 18px;
                }}
                @media (max-width: 500px) {{
                    .button-row {{ flex-direction: column; }}
                }}
                .btn {{
                    display: inline-block;
                    padding: 12px 24px;
                    border-radius: 6px;
                    font-weight: 600;
                    font-size: 14px;
                    cursor: pointer;
                    text-decoration: none;
                    border: none;
                    text-align: center;
                    transition: all 0.15s ease;
                }}
                .btn-accept {{
                    background-color: #16a34a;
                    color: white;
                    flex: 1;
                }}
                .btn-accept:hover {{
                    background-color: #15803d;
                }}
                .btn-decline {{
                    background-color: #dc2626;
                    color: white;
                    flex: 1;
                }}
                .btn-decline:hover {{
                    background-color: #b91c1c;
                }}
                .btn-secondary {{
                    background-color: #64748b;
                    color: white;
                }}
                .btn-secondary:hover {{
                    background-color: #475569;
                }}
                .status-banner {{
                    display: flex;
                    align-items: flex-start;
                    gap: 16px;
                    padding: 20px;
                    border-radius: 8px;
                    margin-top: 24px;
                }}
                .banner-accepted {{
                    background-color: #f0fdf4;
                    border: 1px solid #bbf7d0;
                }}
                .banner-rejected {{
                    background-color: #fef2f2;
                    border: 1px solid #fecaca;
                }}
                .banner-icon {{
                    width: 32px;
                    height: 32px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-weight: bold;
                    font-size: 16px;
                    flex-shrink: 0;
                }}
                .banner-accepted .banner-icon {{
                    background-color: #22c55e;
                    color: white;
                }}
                .banner-rejected .banner-icon {{
                    background-color: #ef4444;
                    color: white;
                }}
                .modal-overlay {{
                    position: fixed;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    background: rgba(0,0,0,0.5);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                    z-index: 1000;
                }}
                .modal-card {{
                    background: white;
                    padding: 28px;
                    border-radius: 10px;
                    max-width: 480px;
                    width: 100%;
                    box-shadow: 0 20px 25px -5px rgba(0,0,0,0.2);
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header-card">
                    <h1>Bunna Bank</h1>
                    <p>{movement_title} Notice</p>
                </div>
                <div class="main-card">
                    <div class="meta-row">
                        <span class="meta-label">Candidate Name:</span>
                        <span class="meta-val">{emp_name_escaped}</span>
                    </div>
                    <div class="meta-row">
                        <span class="meta-label">Vacancy Reference:</span>
                        <span class="meta-val">{vac_ref_escaped}</span>
                    </div>
                    <div class="meta-row" style="border-bottom:none;">
                        <span class="meta-label">Movement Type:</span>
                        <span class="meta-val" style="color:#C17540;">{movement_title}</span>
                    </div>

                    <div class="comparison-grid">
                        <div class="placement-box">
                            <h4>Current Assignment</h4>
                            <div class="placement-title">{current_pos_escaped}</div>
                            <div class="placement-unit">📍 {current_loc_escaped}</div>
                        </div>
                        <div class="placement-box new-target">
                            <h4>Target Placement</h4>
                            <div class="placement-title">{target_pos_escaped}</div>
                            <div class="placement-unit">📍 {target_loc_escaped}</div>
                        </div>
                    </div>

                    {decision_html}
                </div>
            </div>
        </body>
        </html>"""
