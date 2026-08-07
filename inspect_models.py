print("=== HR EMPLOYEE FIELDS ===")
emp_model = env['hr.employee']
for f_name, f_obj in sorted(emp_model._fields.items()):
    if not f_name.startswith('_'):
        print(f"  {f_name}: {f_obj.type} (string='{f_obj.string}')")

print("\n=== DISCIPLINE MODELS ===")
disc_models = [m for m in env if 'discipline' in m]
print("Discipline models found:", disc_models)
for dm in disc_models:
    print(f"\n--- {dm} ---")
    m = env[dm]
    for f_name, f_obj in sorted(m._fields.items()):
        print(f"  {f_name}: {f_obj.type} (string='{f_obj.string}')")
