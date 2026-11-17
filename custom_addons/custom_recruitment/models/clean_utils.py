# -*- coding: utf-8 -*-
import re
import ast
import json

def clean_job_position_name(val):
    """
    Cleans raw translated JSON or dictionary representations of job positions
    such as "{'en_US': 'Branch Sales and Service Supervisor-I'}" into pure text
    "Branch Sales and Service Supervisor-I".
    """
    if not val:
        return ""
    if hasattr(val, '_name'):
        if not val.exists() or len(val) == 0:
            return ""
        rec = val[0]
        name_val = rec.display_name if hasattr(rec, 'display_name') else (rec.name if hasattr(rec, 'name') else "")
        if name_val and not hasattr(name_val, '_name'):
            return clean_job_position_name(name_val)
        return ""
    if hasattr(val, 'display_name') and val.display_name and val.display_name != val:
        return clean_job_position_name(val.display_name)
    if hasattr(val, 'name') and val.name and val.name != val:
        return clean_job_position_name(val.name)
    if isinstance(val, dict):
        return str(val.get('en_US') or next(iter(val.values()), '')).strip()
    if isinstance(val, str):
        val_str = val.strip()
        if ('en_US' in val_str or val_str.startswith('{')) and (':' in val_str):
            m = re.search(r"['\"]en_US['\"]\s*:\s*['\"](.*?)['\"](?:\s*\}|$)", val_str)
            if m:
                return m.group(1).strip()
            try:
                parsed = ast.literal_eval(val_str) if val_str.startswith("{'") else json.loads(val_str)
                if isinstance(parsed, dict):
                    return str(parsed.get('en_US') or next(iter(parsed.values()), val_str)).strip()
            except Exception:
                pass
        return val_str
    return str(val).strip()
