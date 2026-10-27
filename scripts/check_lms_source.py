"""Parse LMS Python/XML and verify manifest file references without Odoo."""

import ast
import pathlib
import sys
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_addons" / "learning_management"


def main():
    errors = []
    python_files = sorted(MODULE.rglob("*.py"))
    xml_files = sorted(MODULE.rglob("*.xml"))
    for path in python_files:
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (SyntaxError, UnicodeError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
    for path in xml_files:
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
    try:
        manifest = ast.literal_eval((MODULE / "__manifest__.py").read_text(encoding="utf-8-sig"))
        for entry in manifest.get("data", []):
            if not (MODULE / entry).is_file():
                errors.append(f"Manifest data file missing: {entry}")
        for entries in manifest.get("assets", {}).values():
            for entry in entries:
                if entry.startswith("learning_management/") and not (ROOT / "custom_addons" / entry).is_file():
                    errors.append(f"Manifest asset missing: {entry}")
    except (OSError, SyntaxError, ValueError) as exc:
        errors.append(f"Invalid LMS manifest: {exc}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Parsed {len(python_files)} Python and {len(xml_files)} XML files; manifest references exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

