from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest
from django.template.loader import render_to_string
from django.conf import settings
import os
import re
import json
import logging

from .models import Resume, ResumeSurvey, ResumeAnalysis, GeneratedResume
from .resume_utils import extract_resume_text
from .ai_utils import analyze_resume, generate_resume_content, render_analysis_html

from weasyprint import HTML, CSS
from django.views.decorators.csrf import csrf_exempt
import google.generativeai as genai

logger = logging.getLogger(__name__)


# -----------------------------------
# Authentication page
# -----------------------------------
def auth_page(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form_type = request.POST.get("form_type")

        if form_type == "register":
            name     = request.POST.get("name")
            username = request.POST.get("username")
            email    = request.POST.get("email")
            password = request.POST.get("password")

            if User.objects.filter(username=username).exists():
                messages.error(request, "Username already taken")
                return redirect("auth")

            if User.objects.filter(email=email).exists():
                messages.error(request, "Email already registered")
                return redirect("auth")

            User.objects.create_user(
                username=username,
                email=email,
                first_name=name,
                password=password
            )
            messages.success(request, "Account created successfully")
            return redirect("auth")

        elif form_type == "login":
            username = request.POST.get("username")
            password = request.POST.get("password")
            user = authenticate(request, username=username, password=password)

            if user is None:
                messages.error(request, "Invalid username or password")
                return redirect("auth")

            login(request, user)
            return redirect("dashboard")

    return render(request, "auth.html")


# -----------------------------------
# Dashboard
# -----------------------------------
@login_required
def dashboard_view(request):
    if request.method == "POST":
        resume_file = request.FILES.get("resume")

        if not resume_file:
            messages.error(request, "No file uploaded.")
            return redirect("dashboard")

        ext = resume_file.name.split(".")[-1].lower()
        if ext not in ["pdf", "jpg", "jpeg", "png"]:
            messages.error(request, "Only PDF or image files are allowed.")
            return redirect("dashboard")

        Resume.objects.create(user=request.user, resume=resume_file)
        messages.success(request, "Resume uploaded successfully.")
        return redirect("dashboard")

    history = ResumeAnalysis.objects.filter(
        resume__user=request.user
    ).select_related("resume").order_by("-created_at")[:10]

    return render(request, "dashboard.html", {"history": history})


# -----------------------------------
# Resume Analysis
# -----------------------------------
@login_required
def resume_analysis_view(request):

    if request.method == "POST" and request.FILES.get("resume"):

        uploaded_file = request.FILES["resume"]

        # Save resume
        resume_instance = Resume.objects.create(
            user=request.user,
            resume=uploaded_file
        )

        # Save survey data
        survey = ResumeSurvey.objects.create(
            resume=resume_instance,
            target_role=request.POST.get("target_role"),
            experience_level=request.POST.get("experience_level"),
            company_type=request.POST.get("company_type")
        )

        # Extract resume text
        resume_text = extract_resume_text(resume_instance.resume.path)
        if not resume_text.strip():
            return HttpResponseBadRequest("Could not extract readable text from resume.")

        # Call AI — returns fully structured result
        raw_result = analyze_resume(
            resume_text=resume_text,
            target_role=survey.target_role,
            experience_level=survey.experience_level,
            company_type=survey.company_type
        )

        # =========================
        # SCORE EXTRACTION
        # All scores come from the structured result returned by analyze_resume().
        # No string scraping needed here.
        # =========================
        breakdown      = raw_result.get("breakdown", {})
        weighted_score = raw_result.get("weighted_score", 0)

        result = {
            "weighted_score": weighted_score,
            "breakdown":      breakdown,
            "raw_analysis":   raw_result.get("raw_analysis", ""),
        }

        # =========================
        # STRUCTURED SKILL LISTS
        # Comes directly from analyze_resume() — no static fallbacks.
        # =========================
        matched_skills  = raw_result.get("matched_skills", [])
        missing_skills  = raw_result.get("missing_skills", [])
        weak_areas      = raw_result.get("weak_areas", [])
        recommendations = raw_result.get("recommendations", [])

        # Build the HTML rendered into the analysis page
        # Pass the full result so render_analysis_html has all lists
        full_result_for_render = {
            **result,
            "matched_skills":  matched_skills,
            "missing_skills":  missing_skills,
            "weak_areas":      weak_areas,
            "recommendations": recommendations,
        }
        formatted_ai_text = render_analysis_html(full_result_for_render)

        # =========================
        # PERSIST TO DATABASE
        # Store all structured data in JSONField so chatbot and future
        # views can retrieve personalised context without re-parsing.
        # =========================
        analysis_payload = {
            "weighted_score":  weighted_score,
            "breakdown":       breakdown,
            "matched_skills":  matched_skills,
            "missing_skills":  missing_skills,
            "weak_areas":      weak_areas,
            "recommendations": recommendations,
            "raw_analysis":    raw_result.get("raw_analysis", ""),
        }

        ResumeAnalysis.objects.create(
            resume=resume_instance,
            final_score=weighted_score,
            full_analysis=analysis_payload   # JSONField stores full structured data
        )

        return render(request, "analysis.html", {
            "result":        result,
            "analysis_html": formatted_ai_text,
            "resume":        resume_instance,
        })

    # GET fallback
    return render(request, "analysis.html", {
        "result": {
            "weighted_score": 0,
            "breakdown": {
                "Hard Skills & Keywords":    0,
                "Job Title & Level Matching": 0,
                "Education & Certifications": 0,
                "Formatting & Parseability":  0,
            }
        }
    })


# -----------------------------------
# Generate Optimized Resume PDF
# -----------------------------------
@login_required
def generate_pdf(request, resume_id):
    resume = get_object_or_404(Resume, id=resume_id, user=request.user)

    survey = ResumeSurvey.objects.filter(resume=resume).first()
    if not survey:
        return HttpResponseBadRequest("Survey data not found.")

    if not resume.resume:
        return HttpResponseBadRequest("Resume file missing.")

    # Check cache
    generated_resume = GeneratedResume.objects.filter(resume=resume).first()
    if generated_resume:
        html_content = generated_resume.html_content
    else:
        resume_text = extract_resume_text(resume.resume.path)
        if not resume_text.strip():
            return HttpResponseBadRequest("Could not extract readable text.")

        analysis_obj = ResumeAnalysis.objects.filter(resume=resume).first()
        if not analysis_obj:
            return HttpResponseBadRequest("Analysis not found.")

        try:
            new_html_content = generate_resume_content(
                resume_text=resume_text,
                survey_data={
                    "target_role":      survey.target_role,
                    "experience_level": survey.experience_level,
                    "company_type":     survey.company_type,
                },
                analysis_text=analysis_obj.full_analysis.get("raw_analysis", "") if isinstance(analysis_obj.full_analysis, dict) else str(analysis_obj.full_analysis)
            )

            html_content = (
                new_html_content.get("html_content", "")
                if isinstance(new_html_content, dict)
                else new_html_content
            )
            html_content = html_content.replace("```", "")

        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e):
                return HttpResponseBadRequest("Free quota exceeded. Please try again later.")
            return HttpResponseBadRequest(f"AI generation failed: {str(e)}")

        GeneratedResume.objects.create(resume=resume, html_content=html_content)

    html_string = render_to_string("resume_temp.html", {"resume_html": html_content})

    try:
        pdf_file = HTML(string=html_string).write_pdf()
    except Exception as e:
        return HttpResponseBadRequest(f"PDF generation failed: {str(e)}")

    response = HttpResponse(pdf_file, content_type="application/pdf")
    response["Content-Disposition"] = "attachment; filename=optimized_resume.pdf"
    return response


# -----------------------------------
# Logout
# -----------------------------------
def logout_view(request):
    logout(request)
    request.session.flush()
    return redirect("auth")


# -----------------------------------
# Chatbot — Analysis-Aware & Personalised
# -----------------------------------
@csrf_exempt
@login_required
def chatbot(request):
    """
    Gemini-powered chatbot that is personalised to the user's latest resume analysis.

    Flow:
    1. Fetch the latest ResumeAnalysis for the logged-in user.
    2. Extract structured data from the JSONField.
    3. Inject this data into the system prompt so every answer is
       specific to *this* user's resume, role, and gaps.
    4. If no analysis exists, prompt the user to run an analysis first.
    """

    response_text = ""

    if request.method == "POST":
        user_input = request.POST.get("user_input", "").strip()
        if not user_input:
            return render(request, "chatbot.html", {"response": ""})

        # ── 1. Fetch latest analysis for this user ──
        latest_analysis = (
            ResumeAnalysis.objects
            .filter(resume__user=request.user)
            .order_by("-created_at")
            .first()
        )

        # ── 2. Build personalised context block ──
        if latest_analysis and isinstance(latest_analysis.full_analysis, dict):
            data = latest_analysis.full_analysis

            final_score     = data.get("weighted_score") or latest_analysis.final_score or 0
            breakdown       = data.get("breakdown", {})
            matched_skills  = data.get("matched_skills", [])
            missing_skills  = data.get("missing_skills", [])
            weak_areas      = data.get("weak_areas", [])
            recommendations = data.get("recommendations", [])

            # Retrieve target role from related survey if available
            survey = ResumeSurvey.objects.filter(
                resume=latest_analysis.resume
            ).first()
            target_role      = survey.target_role      if survey else "Not specified"
            experience_level = survey.experience_level if survey else "Not specified"
            company_type     = survey.company_type     if survey else "Not specified"

            # Format breakdown as readable string
            breakdown_text = "\n".join(
                f"  - {k}: {v}/100" for k, v in breakdown.items()
            ) if breakdown else "  Not available"

            personalisation_context = f"""
--- USER RESUME ANALYSIS CONTEXT ---
The user has completed a resume analysis. Use this data to give personalised advice.

ATS Score: {final_score}/100

Category Breakdown:
{breakdown_text}

Target Role: {target_role}
Experience Level: {experience_level}
Company Type: {company_type}

Matched Skills (already on resume):
{', '.join(matched_skills) if matched_skills else 'None detected'}

Missing Skills (gaps to address):
{', '.join(missing_skills) if missing_skills else 'None identified'}

Weak Alignment Areas:
{chr(10).join(f'  - {area}' for area in weak_areas) if weak_areas else '  None identified'}

Top Recommendations from ATS Engine:
{chr(10).join(f'  {i+1}. {rec}' for i, rec in enumerate(recommendations)) if recommendations else '  None available'}

--- END OF CONTEXT ---

When answering the user:
- Reference their ACTUAL matched and missing skills above.
- Tie advice to their specific target role ({target_role}) and experience level ({experience_level}).
- Prioritise recommendations from the context above.
- Help them improve their score from {final_score}/100.
- Do NOT invent skills not mentioned above.
"""
            no_analysis_mode = False

        else:
            # No analysis exists for this user
            personalisation_context = """
--- NO ANALYSIS FOUND ---
This user has not yet analyzed a resume on the platform.
If they ask for personalised advice, politely inform them:
"Please analyze a resume first to receive personalized insights."
You may still answer general resume and ATS questions.
"""
            no_analysis_mode = True

        # ── 3. Call Gemini with personalised system prompt ──
        try:
            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

            model = genai.GenerativeModel("gemini-2.5-flash-lite")

            response = model.generate_content("""
You are a specialized Resume Optimization Expert for the software industry.
Your purpose is to provide precise, technical, and ATS-focused guidance for resumes targeting software roles such as:
- Software Engineer
- Backend Developer
- Frontend Developer
- Full Stack Developer
- Android Developer
- DevOps Engineer
- Data Engineer

{personalisation_context}

You must:
- Provide direct, actionable resume advice.
- Focus on technical skills, project structuring, impact metrics, and keyword optimization.
- Explain how to improve resume bullet points for software roles.
- Suggest better phrasing using quantified achievements.
- Emphasize ATS-friendly formatting for technical resumes.
- Recommend relevant technical keyword categories (languages, frameworks, tools, cloud, CI/CD, databases).
- Reference the user's specific analysis data when available.

You must NOT:
- Ask the user to upload their resume.
- Ask for a job description.
- Request files or external documents.
- Provide motivational or generic career advice unrelated to the user's data.
- Answer questions unrelated to resume optimization.
- Invent skills or scores not present in the analysis context.

Keep responses:
- Structured
- Concise
- Technical
- Practical
- Software-industry specific
- Personalised to the user's analysis when available

Formatting rules:
- Do NOT use Markdown.
- Do NOT use **bold**, *, ###, backticks, or special formatting symbols.
- Do NOT use decorative characters.
- Use clean plain text only.
- Use numbered or hyphen bullet points only.
- Keep spacing simple and professional.

If a question is unrelated to resume improvement, redirect back to resume optimization.
"""
            )

            response = model.generate_content(user_input)
            response_text = response.text

        except Exception as e:
            response_text = f"Error: {str(e)}"

    return render(request, "chatbot.html", {"response": response_text})