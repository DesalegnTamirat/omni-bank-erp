# -*- coding: utf-8 -*-
from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)

class HrExitInterviewDashboard(models.AbstractModel):
    _name = 'hr.exit.interview.dashboard'
    _description = 'Exit Interview Dashboard Data'

    @api.model
    def get_dashboard_data(self):
        # Base domain for completed interviews
        domain = [('state', '=', 'done')]
        interviews = self.env['hr.exit.interview'].search(domain)
        
        total_responses = len(interviews)
        
        if total_responses == 0:
            return {
                'total_responses': 0,
                'raised_concerns': '0%',
                'avg_manager_rating': '0/5',
                'would_recommend': '0%',
                'main_reasons': [],
                'next_sectors': [],
                'sentiment_scores': []
            }
            
        lines = self.env['hr.exit.interview.line'].search([('interview_id', 'in', interviews.ids)])
        
        # 1. Raised concerns before leaving
        # Assuming question name contains "Did you raise any concerns"
        concerns_lines = lines.filtered(lambda l: 'raise any concerns' in l.question_name.lower())
        raised_count = len([l for l in concerns_lines if 'yes' in (l.answer or '').lower()])
        raised_percent = round((raised_count / len(concerns_lines) * 100)) if concerns_lines else 0
        
        # 2. Avg "manager supported me"
        manager_lines = lines.filtered(lambda l: 'manager supported' in l.question_name.lower() and l.question_type == 'rating')
        manager_sum = sum(float(l.rating_value) for l in manager_lines if l.rating_value and l.rating_value.isdigit())
        avg_manager = round((manager_sum / len(manager_lines)), 1) if manager_lines else 0.0
        
        # 3. Would recommend Bunna Bank
        recommend_lines = lines.filtered(lambda l: 'recommend' in l.question_name.lower())
        recommend_count = len([l for l in recommend_lines if 'yes' in (l.answer or '').lower()])
        recommend_percent = round((recommend_count / len(recommend_lines) * 100)) if recommend_lines else 0
        
        # 4. Main reason for leaving (Checkbox aggregated)
        reason_lines = lines.filtered(lambda l: 'main reason' in l.question_name.lower() and l.question_type == 'checkbox')
        reasons_tally = {}
        for l in reason_lines:
            for option in l.choice_ids:
                reasons_tally[option.name] = reasons_tally.get(option.name, 0) + 1
                
        # Convert to percentage
        main_reasons = []
        for name, count in reasons_tally.items():
            pct = round((count / total_responses) * 100)
            main_reasons.append({'label': name, 'value': pct})
        main_reasons.sort(key=lambda x: x['value'], reverse=True)
        
        # 5. Where they're headed (Radio aggregated)
        sector_lines = lines.filtered(lambda l: 'sector' in l.question_name.lower())
        sector_tally = {}
        for l in sector_lines:
            if l.choice_id:
                sector_tally[l.choice_id.name] = sector_tally.get(l.choice_id.name, 0) + 1
        
        next_sectors = []
        for name, count in sector_tally.items():
            next_sectors.append({'label': name, 'value': count})
            
        # 6. Sentiment Questions (Average of Ratings)
        sentiment_questions = [
            'Performance evaluated fairly',
            'Manager supported me',
            'Experienced respect at work',
            'Good team collaboration',
            'Bank acted responsibly',
            'High performance supported',
            'Encouraged to innovate',
            'Pay fair vs. market',
            'Efforts recognized'
        ]
        
        sentiment_scores = []
        for q_text in sentiment_questions:
            q_lines = lines.filtered(lambda l: q_text.lower() in l.question_name.lower() and l.question_type == 'rating')
            if q_lines:
                q_sum = sum(float(l.rating_value) for l in q_lines if l.rating_value and l.rating_value.isdigit())
                avg = round(q_sum / len(q_lines), 1)
                sentiment_scores.append({'label': q_text, 'value': avg})
            else:
                # Add default or placeholder
                sentiment_scores.append({'label': q_text, 'value': round(3.0, 1)})
                
        return {
            'total_responses': total_responses,
            'raised_concerns': f"{raised_percent}%",
            'avg_manager_rating': f"{avg_manager}/5",
            'would_recommend': f"{recommend_percent}%",
            'main_reasons': main_reasons,
            'next_sectors': next_sectors,
            'sentiment_scores': sentiment_scores
        }