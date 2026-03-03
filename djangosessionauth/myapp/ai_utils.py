"""
ai_utils.py — A³ Resume Intelligence
=====================================
Uses the CURRENT google-genai SDK (google.genai).
Install: pip install google-genai

All Gemini calls request strict JSON.
No regex-based parsing. No static fallback injection.
"""

import os
import json
import logging
import re

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Internal helper: safe JSON extraction
# Gemini sometimes wraps JSON in markdown fences.
# ──────────────────────────────────────────────
def _extract_json(raw: str) -> dict:
    """
    Strips markdown code fences (```json … ```) then parses JSON.
    Returns parsed dict, or raises ValueError on failure.
    """
    # Remove ```json ... ``` or ``` ... ``` wrappers
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    return json.loads(cleaned)


# ──────────────────────────────────────────────
# Internal helper: build Gemini client
# ──────────────────────────────────────────────
def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is not set.")
    return genai.Client(api_key=api_key)


# ══════════════════════════════════════════════
# PUBLIC: analyze_resume
# ══════════════════════════════════════════════
def analyze_resume(
    resume_text: str,
    target_role: str,
    experience_level: str,
    company_type: str,
) -> dict:
    """
    Sends resume text to Gemini and returns a fully structured result dict.

    Return schema (always):
    {
        "weighted_score":  float,
        "breakdown": {
            "Hard Skills & Keywords":     int,   # 0-100
            "Job Title & Level Matching":  int,
            "Education & Certifications":  int,
            "Formatting & Parseability":   int,
        },
        "matched_skills":  list[str],
        "missing_skills":  list[str],
        "weak_areas":      list[str],
        "recommendations": list[str],
        "raw_analysis":    str,           # full JSON string from Gemini
        "error":           str | None,    # populated only on failure
    }

    On any failure the numeric fields are 0, lists are [], and
    error contains the reason. No static fallback data is injected.
    """

    # ── 0. Validate input ──────────────────────────────────────
    empty_result = {
        "weighted_score":  0.0,
        "breakdown": {
            "Hard Skills & Keywords":     0,
            "Job Title & Level Matching":  0,
            "Education & Certifications":  0,
            "Formatting & Parseability":   0,
        },
        "matched_skills":  [],
        "missing_skills":  [],
        "weak_areas":      [],
        "recommendations": [],
        "raw_analysis":    "",
        "error":           None,
    }

    if not resume_text or not resume_text.strip():
        return {**empty_result, "error": "No readable text found in resume."}

    # ── 1. Build client ───────────────────────────────────────
    try:
        client = _get_client()
    except EnvironmentError as e:
        return {**empty_result, "error": str(e)}

    # ── 2. Prompt — forces strict JSON output ─────────────────
    #
    # IMPORTANT: The prompt instructs Gemini to return ONLY a JSON object
    # matching the schema below. No prose, no markdown, no explanation.
    #
    prompt = f"""
You are a professional ATS (Applicant Tracking System) evaluator.

Evaluate the resume below for:
- Target Role: {target_role}
- Experience Level: {experience_level}
- Company Type: {company_type}

You MUST respond with ONLY a valid JSON object — no markdown, no explanation,
no text outside the JSON. The JSON must exactly match this schema:

{{
  "scores": {{
    "hard_skills_and_keywords": <integer 0-100>,
    "job_title_and_level_matching": <integer 0-100>,
    "education_and_certifications": <integer 0-100>,
    "formatting_and_parseability": <integer 0-100>
  }},
  "matched_skills": [<string>, ...],
  "missing_skills": [<string>, ...],
  "weak_areas": [<string>, ...],
  "recommendations": [<string>, ...]
}}

Rules:
- matched_skills: list of specific technical skills/tools found in the resume that are relevant to the target role.
- missing_skills: list of specific technical skills/tools expected for the target role that are ABSENT from the resume.
- weak_areas: short phrases describing alignment gaps (max 10 words each).
- recommendations: actionable improvement steps (max 20 words each).
- All lists must contain real strings — never return null or empty strings inside a list.
- If a list has no items, return an empty array [].
- Return ONLY the JSON. No other text.

Resume Text:
\"\"\"
{resume_text}
\"\"\"
"""

    # ── 3. Call Gemini ────────────────────────────────────────
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                # Instruct the model to produce JSON
                response_mime_type="application/json",
            ),
        )
        raw_output = response.candidates[0].content.parts[0].text.strip()
        logger.debug("Gemini raw output: %s", raw_output[:500])

    except Exception as exc:
        logger.exception("Gemini API call failed")
        return {**empty_result, "error": f"Gemini API error: {exc}"}

    # ── 4. Parse JSON ─────────────────────────────────────────
    try:
        data = _extract_json(raw_output)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("JSON parse failed. Raw output: %s", raw_output[:800])
        return {
            **empty_result,
            "raw_analysis": raw_output,
            "error": f"JSON parse error: {exc}",
        }

    # ── 5. Validate schema ────────────────────────────────────
    scores = data.get("scores", {})
    if not isinstance(scores, dict):
        return {**empty_result, "raw_analysis": raw_output,
                "error": "Gemini returned malformed scores object."}

    def safe_int(val, default=0):
        try:
            return max(0, min(100, int(val)))
        except (TypeError, ValueError):
            return default

    def safe_list(val):
        if isinstance(val, list):
            return [str(item).strip() for item in val if str(item).strip()]
        return []

    hard       = safe_int(scores.get("hard_skills_and_keywords"))
    title      = safe_int(scores.get("job_title_and_level_matching"))
    education  = safe_int(scores.get("education_and_certifications"))
    formatting = safe_int(scores.get("formatting_and_parseability"))

    matched_skills  = safe_list(data.get("matched_skills"))
    missing_skills  = safe_list(data.get("missing_skills"))
    weak_areas      = safe_list(data.get("weak_areas"))
    recommendations = safe_list(data.get("recommendations"))

    # ── 6. Compute weighted score (backend-controlled) ────────
    weighted_score = round(
        0.40 * hard +
        0.30 * title +
        0.20 * education +
        0.10 * formatting,
        2,
    )

    breakdown = {
        "Hard Skills & Keywords":     hard,
        "Job Title & Level Matching":  title,
        "Education & Certifications":  education,
        "Formatting & Parseability":   formatting,
    }

    return {
        "weighted_score":  weighted_score,
        "breakdown":       breakdown,
        "matched_skills":  matched_skills,
        "missing_skills":  missing_skills,
        "weak_areas":      weak_areas,
        "recommendations": recommendations,
        "raw_analysis":    raw_output,
        "error":           None,
    }


# ══════════════════════════════════════════════
# PUBLIC: generate_resume_content
# ══════════════════════════════════════════════
def generate_resume_content(
    resume_text: str,
    survey_data: dict,
    analysis_text: str,
) -> str:
    """
    Uses Gemini to rewrite the resume as clean HTML.
    Returns an HTML string, or a safe error <p> on failure.
    """
    try:
        client = _get_client()
    except EnvironmentError as exc:
        logger.error("generate_resume_content: %s", exc)
        return "<p>AI configuration error: GEMINI_API_KEY not set.</p>"

    prompt = f"""
You are a professional resume writer.

Rewrite and optimise this resume for a candidate applying to software roles, using:
- Survey Data: {json.dumps(survey_data)}
- ATS Feedback summary: {analysis_text[:800]}

Requirements:
1. Single-page resume (~150-200 words max).
2. Standard sections: Contact, Summary, Skills, Work Experience, Projects, Education.
3. Use action verbs and quantify achievements where possible.
4. ATS-friendly: no tables, no columns, no images.
5. Return ONLY clean, complete HTML — no markdown, no backticks, no explanation.

Resume to rewrite:
\"\"\"
{resume_text}
\"\"\"
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        html = response.candidates[0].content.parts[0].text.strip()
        # Strip stray markdown fences
        html = re.sub(r"^```(?:html)?\s*", "", html, flags=re.IGNORECASE)
        html = re.sub(r"\s*```$", "", html.strip())
        return html
    except Exception as exc:
        logger.exception("generate_resume_content Gemini call failed")
        return f"<p>Resume generation failed: {exc}</p>"


# ══════════════════════════════════════════════
# PUBLIC: render_analysis_html
# ══════════════════════════════════════════════
def render_analysis_html(result: dict) -> str:
    """
    Builds the HTML block injected into #typing-output in analysis.html.
    Consumes ONLY data from the result dict — no static fallbacks.

    This HTML is parsed by analysis_dashboard.js (parseAnalysisHTML) which
    looks for <h3> headings followed by <ul><li> lists. The heading names
    MUST match the SEC_RE regexes in the JS exactly:
        matched     → /matched\s*(skills?|keywords?)?/i
        missing     → /missing\s*(skills?|keywords?)?/i
        weak        → /weak\s*(alignment)?/i
        improvement → /improvement/i
    """
    category_scores = result.get("breakdown", {})
    total_score     = result.get("weighted_score", 0)
    matched_skills  = result.get("matched_skills", [])
    missing_skills  = result.get("missing_skills", [])
    weak_areas      = result.get("weak_areas", [])
    recommendations = result.get("recommendations", [])
    error           = result.get("error")

    def _li_list(items: list, empty_msg: str) -> str:
        if items:
            return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"
        return f"<ul><li>{empty_msg}</li></ul>"

    error_block = ""
    if error:
        error_block = f'<div class="card error-card"><h3>Analysis Notice</h3><p>{error}</p></div>'

    html = f"""
{error_block}
<div class="analysis-section">

  <div class="card score-card">
    <h3>Final ATS Score</h3>
    <ul><li>Total Score: {total_score}/100</li></ul>
  </div>

  <div class="card category-card">
    <h3>Category Scores</h3>
    <ul>
      <li>Hard Skills &amp; Keywords: {category_scores.get("Hard Skills & Keywords", 0)}/100</li>
      <li>Job Title &amp; Level Matching: {category_scores.get("Job Title & Level Matching", 0)}/100</li>
      <li>Education &amp; Certifications: {category_scores.get("Education & Certifications", 0)}/100</li>
      <li>Formatting &amp; Parseability: {category_scores.get("Formatting & Parseability", 0)}/100</li>
    </ul>
  </div>

  <div class="card skills-card">
    <h3>Matched Skills ({len(matched_skills)})</h3>
    {_li_list(matched_skills, "No matched skills detected.")}

    <h3>Missing Skills ({len(missing_skills)})</h3>
    {_li_list(missing_skills, "No missing skills identified.")}
  </div>

  <div class="card weak-card">
    <h3>Weak Alignment Areas</h3>
    {_li_list(weak_areas, "No weak alignment areas identified.")}
  </div>

  <div class="card recommendations-card">
    <h3>Improvement Recommendations</h3>
    {_li_list(recommendations, "No specific recommendations available.")}
  </div>

</div>
"""
    return html