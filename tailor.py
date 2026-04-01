#!/usr/bin/env python3
"""
tailor.py — AI-powered resume + cover letter tailoring pipeline.

Flow:
  1. Parse job description  → structured JSON (company, role, keywords, quals)
  2. Tailor master resume   → tailored resume JSON
  3. Generate cover letter  → plain text
  4. Build both .docx files via build_docs.py

Usage:
    python tailor.py "<job description text>"
    python tailor.py --file jd.txt

Requires: ANTHROPIC_API_KEY environment variable
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

import anthropic

from build_docs import build_cover_letter, build_resume
from drive_upload import upload_application
from sheets_log import log_application

MODEL            = "claude-sonnet-4-6"
MASTER_RESUME    = Path("master_resume.json")
OUT_DIR          = Path("output")


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit("ERROR: ANTHROPIC_API_KEY environment variable is not set.")
    return anthropic.Anthropic(api_key=key)


def _ask(client: anthropic.Anthropic, system: str, user: str,
         max_tokens: int = 2048) -> str:
    """Single-turn Claude call, returns raw text."""
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.BadRequestError as e:
        print(f"ERROR 400 — full response body:\n{e.response.text}\n", file=sys.stderr)
        raise
    return msg.content[0].text.strip()


def _parse_json(text: str) -> dict | list:
    """Strip markdown fences and parse JSON from a Claude response."""
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```$",          "", text.strip(), flags=re.MULTILINE)
    return json.loads(text.strip())


# ══════════════════════════════════════════════════════════════════════════════
# Step 1 — Parse job description
# ══════════════════════════════════════════════════════════════════════════════

def parse_jd(client: anthropic.Anthropic, jd_text: str) -> dict:
    """
    Returns:
        {
            "company":        str,
            "role":           str,
            "keywords":       [str, ...],   # 10-15 items
            "qualifications": [str, ...],   # 3-5 items
        }
    """
    system = (
        "You are a recruiting analyst. Extract structured information from job "
        "descriptions. Return only valid JSON — no prose, no markdown fences."
    )
    user = f"""Analyze this job description and return a JSON object with exactly these keys:

- "company":        the employer's name (string)
- "role":           the job title as written in the posting (string)
- "keywords":       10 to 15 skills, tools, or concepts explicitly mentioned or strongly implied
                    (list of strings, most critical first)
- "qualifications": 3 to 5 required or strongly preferred qualifications as brief phrases
                    (list of strings)
- "why_exciting":   1-2 sentences capturing what makes this specific company or role genuinely
                    distinctive — a specific product, mission detail, initiative, or challenge
                    mentioned in the posting that a motivated candidate would find compelling
                    (string)
- "location":       city and state (or "Remote") where the job is based (string)
- "work_type":      one of "On-site", "Remote", or "Hybrid" (string)

Job description:
\"\"\"
{jd_text}
\"\"\"
"""
    raw = _ask(client, system, user)
    result = _parse_json(raw)
    result["_raw_jd"] = jd_text   # stash for cover letter prompt
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Step 2 — Tailor resume
# ══════════════════════════════════════════════════════════════════════════════

def tailor_resume(client: anthropic.Anthropic,
                  master: dict, jd: dict) -> dict:
    """
    Returns a complete tailored resume dict in the same schema as master_resume.json.
    """
    system = (
        "You are an expert resume writer specializing in ATS optimization. "
        "You rewrite resumes to match specific job descriptions. "
        "You never fabricate experience, metrics, or credentials. "
        "Return only valid JSON — no prose, no markdown fences.\n\n"

        "STRICT ONE-PAGE RULES:\n"
        "- Summary: 2 sentences maximum. Lead with the role title (use the JD's exact title wording) "
        "+ company name + 1-2 top keywords. Second sentence: top 2-3 tools/skills only. "
        "No fluff, no 'I am excited', no repeating the job title.\n"
        "- Skills: reorder categories so the most JD-relevant appear first. Remove any skill not "
        "mentioned in the experience bullets or the JD. Never add skills the candidate hasn't "
        "demonstrated. Keep each category to 5-6 items max.\n"
        "- Experience bullets: keep ALL existing entries but trim each bullet to 1 line where "
        "possible. Never add new bullets. Never expand existing bullets. Only lightly rephrase "
        "1-2 words per bullet to insert a missing keyword — do not rewrite entire sentences.\n"
        "- Never add new experience entries, new projects, or new skills that don't exist in "
        "the master resume.\n"
        "- The output JSON must produce a resume that fits on exactly 1 US Letter page with "
        "0.75 inch side margins, 0.6 inch top margin, and 0.5 inch bottom margin when rendered "
        "in Arial 11pt.\n\n"

        "STRICT ATS RULES:\n"
        "- Embed keywords naturally — never stuff. If a keyword already appears in a bullet, "
        "do not repeat it in the same entry.\n"
        "- Include both acronym AND full form only on first use in the skills section "
        "(e.g. 'Security Orchestration Automation and Response (SOAR)'). In experience bullets, "
        "use the short form only.\n"
        "- Do not add Java, C++, Go, or any programming language the candidate has not used "
        "in a real project.\n"
        "- Do not list PowerShell, Node.js, or any tool as a skill unless it appears in at "
        "least one experience bullet.\n"
        "- Do not add vague filler skills: 'Software Engineering Concepts', 'SDLC', "
        "'teamwork', 'communication'.\n"
        "- Skills section: hard skills only, grouped by category. Certifications and Languages "
        "are separate categories.\n"
        "- Never fabricate metrics. If a bullet has a number (40%, 70%, 30-50 events), keep it "
        "exactly as-is. Do not invent new numbers.\n"
        "- Job title alignment: rephrase the summary role title to match the JD's exact title "
        "wording, but never change actual job titles in the experience section."
    )

    user = f"""Tailor the resume below for this role and return the complete tailored resume as JSON.

TARGET ROLE: {jd['role']} at {jd['company']}
KEY KEYWORDS: {', '.join(jd['keywords'])}
REQUIRED QUALIFICATIONS: {'; '.join(jd['qualifications'])}

TAILORING RULES:
1. summary: Exactly 2 sentences. Sentence 1: role title (JD wording) + company name + 1-2 top keywords.
   Sentence 2: top 2-3 tools/skills from the JD. No filler. No third sentence.

2. skills: Reorder categories so the most JD-relevant appear first. Within each category, move
   JD-matching items to the front. Remove items with zero relevance or not backed by experience bullets.
   Max 5-6 items per category. Same dict structure: {{"Category Name": ["item1", "item2", ...]}}.

3. experience.bullets: Keep every existing bullet. Trim to 1 line where possible.
   Only rephrase 1-2 words per bullet to surface a missing keyword — no rewrites, no new bullets,
   no expanded bullets. Do not change dates, titles, company names, or any existing metric.

4. education: Return unchanged.

5. contact + name: Return unchanged.

ALLOWED SKILLS (exhaustive list from master resume — do not add any item outside this list):
{json.dumps({cat: items for cat, items in master['skills'].items()}, indent=2)}

MASTER RESUME JSON:
{json.dumps(master, indent=2)}

Return the complete tailored resume as a single JSON object with keys:
name, contact, summary, skills, experience, education
"""

    raw = _ask(client, system, user, max_tokens=4096)
    return _parse_json(raw)


# ══════════════════════════════════════════════════════════════════════════════
# Step 3 — Generate cover letter
# ══════════════════════════════════════════════════════════════════════════════

def generate_cover_letter(client: anthropic.Anthropic,
                          tailored: dict, jd: dict) -> str:
    """
    Returns plain cover letter text (no salutation header — build_docs adds that).
    """
    system = """You are a senior recruitment director at Robert Half who reads 500+ cover letters per week and instantly knows the difference between a forgettable template and one that makes you pick up the phone to schedule an interview.

Write a cover letter that makes the hiring manager stop scrolling and start scheduling. Follow these rules exactly:

- Opening hook: a specific first sentence connecting the candidate's experience to the company's current challenge. NEVER start with "I am writing to apply for"

- Company research proof: reference a specific product, initiative, or mission detail from the job description proving research was done

- Value match paragraph: the 3 specific capabilities the candidate brings that directly solve what the job posting is really asking for

- Spotlight achievement: one quantified accomplishment proving the candidate has already done this job's most important task

- Cultural fit signal: connect the candidate's work style to the company's mission without sounding rehearsed

- Specific contribution: name one concrete initiative the candidate would work on in the first 90 days based on the role

- Confident closing: end with a clear next step that assumes the interview will happen

- Length: 250-300 words maximum

- Tone: confident, direct, human — genuine excitement without pleading or over-flattering"""

    top_3 = _score_bullets(tailored["experience"], jd["keywords"], n=3)
    contact = tailored.get("contact", {})

    user = f"""Job description:
{jd.get('_raw_jd', '')}

Candidate's 3 most relevant achievements:
{top_3}

One thing that genuinely excites the candidate about this company:
{jd.get('why_exciting', '')}

Write the cover letter for: {tailored['name']}, {contact.get('email', '')}, {contact.get('phone', '')}

Return ONLY the letter body as plain text — no subject line, no address block, no markdown.
Paragraphs separated by blank lines. End with exactly:

Sincerely,
Azat Shakirov"""

    return _ask(client, system, user, max_tokens=1200)


def _score_bullets(experience: list, keywords: list[str], n: int = 3) -> str:
    """
    Score each bullet by how many JD keywords it contains (case-insensitive),
    break ties by length (longer = more metrics). Return top n as formatted string.
    """
    kw_lower = [k.lower() for k in keywords]
    scored = []
    for entry in experience:
        for b in entry.get("bullets", []):
            b_lower = b.lower()
            score = sum(1 for kw in kw_lower if kw in b_lower)
            scored.append((score, len(b), entry["title"], b))
    scored.sort(reverse=True)
    return "\n".join(f"- [{title}] {b}" for _, _, title, b in scored[:n])


# ══════════════════════════════════════════════════════════════════════════════
# Main pipeline
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(jd_text: str, verbose: bool = True) -> tuple[str, str]:
    """
    Full pipeline. Returns (company_slug, drive_link).
    """
    if not MASTER_RESUME.exists():
        sys.exit(f"ERROR: {MASTER_RESUME} not found. Run parse_resume.py first.")

    OUT_DIR.mkdir(exist_ok=True)
    master  = json.loads(MASTER_RESUME.read_text())
    client  = _client()

    # ── Step 1: Parse JD ──────────────────────────────────────────────────────
    print("[ 1/4 ] Parsing job description...")
    jd = parse_jd(client, jd_text)
    print(f"        Company      : {jd['company']}")
    print(f"        Role         : {jd['role']}")
    print(f"        Keywords     : {', '.join(jd['keywords'])}")
    print(f"        Why exciting : {jd.get('why_exciting', '')}")

    # ── Step 2: Tailor resume ─────────────────────────────────────────────────
    print("[ 2/4 ] Tailoring resume...")
    tailored = tailor_resume(client, master, jd)

    if verbose:
        print("\n── Tailored summary ──────────────────────────────────────────")
        print(tailored["summary"])
        print("\n── First 3 skill lines ───────────────────────────────────────")
        for cat, items in list(tailored["skills"].items())[:3]:
            print(f"  {cat}: {', '.join(items)}")
        print()

    # ── Step 3: Cover letter ──────────────────────────────────────────────────
    print("[ 3/4 ] Generating cover letter...")
    cover_text = generate_cover_letter(client, tailored, jd)

    if verbose:
        print("\n── Cover letter ──────────────────────────────────────────────")
        for line in cover_text.split("\n"):
            print(" ", line)
        print()

    # ── Step 4: Build .docx files ─────────────────────────────────────────────
    print("[ 4/4 ] Building documents...")
    contact     = tailored.get("contact", master.get("contact", {}))
    company_slug = re.sub(r"[^\w]", "", jd["company"])   # strip spaces/punctuation

    # Save tailored JSON for debugging / audit
    tailored_json_path = OUT_DIR / f"tailored_{company_slug}.json"
    tailored_json_path.write_text(json.dumps(tailored, indent=2))

    resume_path = build_resume(tailored, company_slug)
    cl_path     = build_cover_letter(
        cover_text, company_slug,
        name     = tailored.get("name", master.get("name", "")),
        email    = contact.get("email", ""),
        phone    = contact.get("phone", ""),
        location = contact.get("location", ""),
    )

    # ── Step 5: Upload to Google Drive ────────────────────────────────────────
    print("[ 5/6 ] Uploading to Google Drive...")
    drive_link = upload_application(company_slug)

    # ── Step 6: Log to job tracker sheet ──────────────────────────────────────
    print("[ 6/6 ] Logging to job tracker...")
    log_application(jd, drive_link)

    print(f"\nDone.")
    print(f"  Resume       → {resume_path}")
    print(f"  Cover letter → {cl_path}")
    print(f"  Tailored JSON→ {tailored_json_path}")
    print(f"  Drive folder → {drive_link}")
    # Emit structured result for n8n / programmatic callers
    print(f"\nPIPELINE_RESULT: {json.dumps({'company': company_slug, 'drive_link': drive_link})}")
    return company_slug, drive_link


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="AI resume tailoring pipeline")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("jd",       nargs="?", help="Job description text (inline)")
    group.add_argument("--file",   "-f",      help="Path to a .txt file with the job description")
    args = parser.parse_args()

    if args.file:
        jd_text = Path(args.file).read_text()
    else:
        jd_text = args.jd

    run_pipeline(jd_text)


# ══════════════════════════════════════════════════════════════════════════════
# Test block — Rivian Summer 2026 Internship
# ══════════════════════════════════════════════════════════════════════════════

RIVIAN_JD = """
Rivian | Cybersecurity Intern – Vehicle & Enterprise Security (Summer 2026)
Location: Normal, IL / Palo Alto, CA (hybrid)
Team: Information Security

About the role:
Rivian's Information Security team is looking for a Cybersecurity Intern to support
threat detection, incident response, and security automation initiatives across our
vehicle and enterprise environments. You'll work alongside senior SOC analysts and
security engineers to monitor our SIEM platform, investigate alerts, and contribute
to SOAR playbook development.

Responsibilities:
- Monitor and triage security events from SIEM (Splunk) and EDR platforms
- Assist in incident response investigations — from initial triage through
  containment and root-cause documentation
- Contribute to the development and improvement of SOAR automation playbooks
  using Python and n8n
- Participate in threat hunting exercises using MITRE ATT&CK framework
- Document security incidents, runbooks, and process improvements
- Collaborate with cross-functional teams on vulnerability management and
  patch prioritization

Required qualifications:
- Currently enrolled in a BS/BA program in Computer Science, Cybersecurity,
  Information Systems, or related field
- Hands-on experience with SIEM platforms (Splunk or ELK Stack)
- Familiarity with incident response processes and SOC workflows
- Scripting ability in Python or Bash for automation tasks
- Strong written communication skills for documentation

Preferred qualifications:
- Experience with SOAR tools (n8n, Splunk SOAR, Palo Alto XSOAR)
- Exposure to EDR tools (CrowdStrike, SentinelOne, or similar)
- Understanding of network security fundamentals (TCP/IP, DNS, firewalls)
- Google IT Support Professional Certificate or similar certification
- GPA of 3.5 or higher
"""

if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        print("No arguments given — running Rivian test case.\n")
        run_pipeline(RIVIAN_JD)
