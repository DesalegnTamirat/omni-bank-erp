# -*- coding: utf-8 -*-

from odoo import http, fields, _
from odoo.http import request


class ResultPortalController(http.Controller):
    """
    Anonymized Assessment Result Portal (FR-EXM-071 - FR-EXM-085)
    ============================================================
    Provides candidate self-service lookup of published results.
    STRICT PRIVACY: Candidate names are NEVER exposed on the portal;
    identification is strictly by Candidate ID / Employee ID.
    """

    @http.route("/portal/assessment/results", type="http", auth="public", website=True, sitemap=False)
    def render_result_portal(self, candidate_code=None, **kwargs):
        results = []
        searched = False
        
        # Query active published batches
        active_publications = request.env["assessment.result.publication"].sudo().search([
            ("state", "=", "published")
        ])

        if candidate_code:
            searched = True
            cleaned_code = candidate_code.strip()
            
            # Search across active published lines
            matching_lines = request.env["assessment.result.publication.line"].sudo().search([
                ("publication_id", "in", active_publications.ids),
                ("candidate_code", "=ilike", cleaned_code)
            ])

            for line in matching_lines:
                results.append({
                    "publication_title": line.publication_id.name,
                    "job_title": line.publication_id.job_id.name,
                    "candidate_code": line.candidate_code,
                    "exam_score": line.exam_score,
                    "interview_score": line.interview_score,
                    "pms_score": line.pms_score,
                    "total_score": line.total_score,
                    "rank": line.rank,
                    "status": dict(line._fields["status"].selection).get(line.status, line.status),
                    "publication_date": line.publication_id.publication_date,
                })
                
                # Log view tracking (FR-EXM-085)
                request.env["assessment.publication.view.log"].sudo().create({
                    "publication_id": line.publication_id.id,
                    "candidate_code": cleaned_code,
                    "ip_address": request.httprequest.remote_addr,
                    "view_datetime": fields.Datetime.now(),
                })

        return request.render("assessment_system.portal_results_dashboard", {
            "searched": searched,
            "candidate_code": candidate_code or "",
            "results": results,
            "publications": active_publications,
        })
