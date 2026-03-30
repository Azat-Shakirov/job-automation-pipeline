#!/usr/bin/env python3
"""
Parse master-resume.docx → master_resume.json

Detects structure by:
  - ALL-CAPS bold paragraph  → section heading
  - Para containing \t       → entry header (experience / education)
  - Style "List Paragraph"   → bullet under current entry
  - Para 0                   → name
  - Para 1 (contains ●)      → contact line
  - SKILLS section lines     → "Category: items" split into dict
"""

import json
import re
import sys
from pathlib import Path

from docx import Document

DOCX = Path("master-resume.docx")
OUT  = Path("master_resume.json")

SECTION_NAMES = {"SUMMARY", "SKILLS", "EXPERIENCE", "EDUCATION",
                 "PROJECTS", "CERTIFICATIONS", "AWARDS", "PUBLICATIONS",
                 "LANGUAGES", "VOLUNTEER", "INTERESTS", "REFERENCES"}


def is_section_heading(p) -> bool:
    text = p.text.strip()
    if not text:
        return False
    # All-caps, no tab, short
    return (text == text.upper()
            and "\t" not in text
            and len(text) <= 30
            and text in SECTION_NAMES)


def parse_contact(text: str) -> dict:
    """Split '●'-delimited contact line into fields."""
    parts = [x.strip() for x in text.split("●") if x.strip()]
    out = {"phone": "", "email": "", "linkedin": "", "location": "", "other": []}
    for part in parts:
        if re.match(r"[\+\d][\d\s\-\(\)\.]{6,}", part):
            out["phone"] = part
        elif "@" in part:
            out["email"] = part
        elif "linkedin.com" in part.lower():
            out["linkedin"] = part
        elif re.search(r"\b[A-Z][a-z]+,\s*[A-Z]{2}\b", part):
            out["location"] = part
        else:
            out["other"].append(part)
    return out


def parse_experience_header(text: str) -> dict:
    """
    'Title  |  Company - Location\tDates'  or
    'Title  |  Company | Location\tDates'
    """
    parts = text.split("\t", 1)
    dates = parts[1].strip() if len(parts) > 1 else ""
    left  = parts[0]
    segments = [s.strip() for s in re.split(r"\|", left)]
    title   = segments[0] if len(segments) > 0 else left
    company = segments[1] if len(segments) > 1 else ""
    location= segments[2] if len(segments) > 2 else ""
    # location may be embedded after a dash in company
    if not location and " - " in company:
        company, _, location = company.partition(" - ")
        company  = company.strip()
        location = location.strip()
    return {"title": title.strip(), "company": company.strip(),
            "location": location.strip(), "dates": dates.strip(), "bullets": []}


def parse_education_header(text: str) -> dict:
    """
    'Degree   -   School  GPA: X.X\tDates'
    """
    parts = text.split("\t", 1)
    dates = parts[1].strip() if len(parts) > 1 else ""
    left  = parts[0].strip()
    # Split on " - " or "–"
    seg   = re.split(r"\s+[-–]\s+", left, maxsplit=1)
    degree = seg[0].strip() if seg else left
    school_part = seg[1].strip() if len(seg) > 1 else ""
    # Extract GPA
    gpa_m  = re.search(r"GPA:\s*([\d.]+)", school_part, re.I)
    gpa    = gpa_m.group(1) if gpa_m else ""
    school = re.sub(r"\s*GPA:.*", "", school_part, flags=re.I).strip()
    return {"degree": degree, "school": school, "gpa": gpa,
            "dates": dates.strip(), "bullets": []}


def parse_skills(lines: list[str]) -> dict:
    """'Category: item1, item2, ...' → {category: [items]}"""
    result = {}
    for line in lines:
        if ":" in line:
            cat, _, rest = line.partition(":")
            result[cat.strip()] = [x.strip() for x in rest.split(",") if x.strip()]
        else:
            result.setdefault("Other", []).append(line.strip())
    return result


def main():
    if not DOCX.exists():
        sys.exit(f"ERROR: {DOCX} not found in {Path.cwd()}")

    doc = Document(DOCX)
    paras = doc.paragraphs

    # ── Name & contact (always paras 0 and 1) ────────────────────────────────
    name    = paras[0].text.strip()
    contact = parse_contact(paras[1].text)

    # ── Walk remaining paragraphs ─────────────────────────────────────────────
    current_section = None
    summary_lines   = []
    skill_lines     = []
    experience      = []   # list of entry dicts
    education       = []
    current_entry   = None

    for p in paras[2:]:
        text  = p.text.strip()
        style = p.style.name if p.style else ""

        if not text:
            continue

        # Section heading?
        if is_section_heading(p):
            current_section = text.upper()
            current_entry   = None
            continue

        # ── SUMMARY ──────────────────────────────────────────────────────────
        if current_section == "SUMMARY":
            summary_lines.append(text)

        # ── SKILLS ───────────────────────────────────────────────────────────
        elif current_section == "SKILLS":
            skill_lines.append(text)

        # ── EXPERIENCE ───────────────────────────────────────────────────────
        elif current_section == "EXPERIENCE":
            if style == "List Paragraph":
                if current_entry is not None:
                    current_entry["bullets"].append(text)
            elif "\t" in text:          # entry header
                current_entry = parse_experience_header(text)
                experience.append(current_entry)
            else:
                # Continuation text without a tab (rare) — attach to entry
                if current_entry is not None:
                    current_entry["bullets"].append(text)

        # ── EDUCATION ────────────────────────────────────────────────────────
        elif current_section == "EDUCATION":
            if "\t" in text:
                current_entry = parse_education_header(text)
                education.append(current_entry)
            elif style == "List Paragraph" and current_entry is not None:
                current_entry["bullets"].append(text)

    resume = {
        "name":       name,
        "contact":    contact,
        "summary":    " ".join(summary_lines),
        "skills":     parse_skills(skill_lines),
        "experience": experience,
        "education":  education,
    }

    OUT.write_text(json.dumps(resume, indent=2, ensure_ascii=False))
    print(f"Written → {OUT}")

    # ── Quick sanity print ────────────────────────────────────────────────────
    print(f"  name      : {resume['name']}")
    print(f"  email     : {resume['contact']['email']}")
    print(f"  phone     : {resume['contact']['phone']}")
    print(f"  linkedin  : {resume['contact']['linkedin']}")
    print(f"  location  : {resume['contact']['location']}")
    print(f"  skills    : {list(resume['skills'].keys())}")
    print(f"  experience: {len(resume['experience'])} entries")
    for e in resume['experience']:
        print(f"    - {e['title']} @ {e['company']}  [{e['dates']}]  ({len(e['bullets'])} bullets)")
    print(f"  education : {len(resume['education'])} entries")
    for e in resume['education']:
        print(f"    - {e['degree']}  [{e['dates']}]")


if __name__ == "__main__":
    main()
