# -*- coding: utf-8 -*-
import base64
import os
from odoo import api, models


class InternalRecruitmentMinuteReport(models.AbstractModel):
    _name = "report.custom_recruitment.report_internal_rec_minute"
    _description = "Internal Recruitment Selection Committee Minute Report"

    def _get_bunna_logo_data_uri(self):
        try:
            curr_dir = os.path.dirname(os.path.abspath(__file__))
            module_dir = os.path.dirname(curr_dir)
            logo_path = os.path.join(module_dir, 'bunna_logo.jpg')
            if not os.path.exists(logo_path):
                logo_path = os.path.join(module_dir, 'static', 'src', 'img', 'bunna_logo.jpg')
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    encoded = base64.b64encode(f.read()).decode('utf-8')
                    return f"data:image/jpeg;base64,{encoded}"
        except Exception:
            pass
        return False

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["new.internal.recruitment.selected"].browse(docids)
        doc_stats = {}
        doc_selected_candidates = {}
        doc_all_candidates = {}
        bunna_logo_data_uri = self._get_bunna_logo_data_uri()

        for doc in docs:
            all_cands = doc.new_int_rec_sel.filtered(lambda c: c.emp_name)

            selected_cands = all_cands.filtered(
                lambda c: c.selection_type in ("selected", "Selected")
            ).sorted(key=lambda c: c.rank or 9999)

            reserve_cands = all_cands.filtered(
                lambda c: c.selection_type in ("reserve", "Reserved")
            ).sorted(key=lambda c: c.rank or 9999)

            rejected_cands = all_cands.filtered(
                lambda c: c.selection_type in ("rejected", "Disqualified", "Rejected")
            )

            total_applicants = len(all_cands)
            shortlisted_applicants = len([c for c in all_cands if c.select_flag or c.select_flag is None])
            written_participants = len([c for c in all_cands if (c.written_exam_score or 0.0) > 0])
            written_absents = len([c for c in all_cands if not c.written_exam_score])
            written_passed = len([c for c in all_cands if (c.written_exam_score or 0.0) >= 50.0])
            interview_participants = len([c for c in all_cands if (c.interview_score or 0.0) > 0])
            interview_absents = len([c for c in all_cands if not c.interview_score])
            not_selected = len(rejected_cands)

            top_cand = selected_cands[0] if selected_cands else False
            top_cand_name = top_cand.emp_name.name if top_cand and top_cand.emp_name else "____________"
            top_cand_unit = top_cand.preferred_location or top_cand.current_work_unit if top_cand else "____________"

            if top_cand:
                gender_str = (top_cand.emp_gender or (top_cand.emp_name.gender if top_cand.emp_name else '') or '').lower()
                if gender_str in ('male', 'm'):
                    top_cand_salutation = "Ato"
                elif gender_str in ('female', 'f'):
                    top_cand_salutation = "Wy"
                else:
                    top_cand_salutation = "Ato/Wy"
            else:
                top_cand_salutation = "Ato/Wy"

            res_rank_start = reserve_cands[0].rank if reserve_cands else ""
            res_rank_end = reserve_cands[-1].rank if reserve_cands else ""

            doc_stats[doc.id] = {
                "total_applicants": total_applicants,
                "shortlisted_applicants": shortlisted_applicants,
                "written_participants": written_participants,
                "written_absents": written_absents,
                "written_passed": written_passed,
                "interview_participants": interview_participants,
                "interview_absents": interview_absents,
                "not_selected": not_selected,
                "top_cand_name": top_cand_name,
                "top_cand_salutation": top_cand_salutation,
                "top_cand_unit": top_cand_unit,
                "res_rank_start": res_rank_start,
                "res_rank_end": res_rank_end,
            }
            doc_selected_candidates[doc.id] = selected_cands
            doc_all_candidates[doc.id] = all_cands.sorted(key=lambda c: c.rank or 9999)

        return {
            "doc_ids": docids,
            "doc_model": "new.internal.recruitment.selected",
            "docs": docs,
            "doc_stats": doc_stats,
            "doc_selected_candidates": doc_selected_candidates,
            "doc_all_candidates": doc_all_candidates,
            "bunna_logo_data_uri": bunna_logo_data_uri,
            "data": data,
        }
