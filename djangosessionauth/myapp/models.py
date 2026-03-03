from django.db import models
from django.contrib.auth.models import User


class Resume(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    resume = models.FileField(upload_to='resumes/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username


class ResumeSurvey(models.Model):

    ROLE_CHOICES = [
        ("backend",  "Backend Developer"),
        ("frontend", "Frontend Developer"),
        ("android",  "Android Developer"),
        ("ml",       "Machine Learning Engineer"),
        ("data",     "Data Analyst"),
    ]

    EXPERIENCE_CHOICES = [
        ("fresher", "Fresher"),
        ("junior",  "1-3 Years"),
        ("mid",     "3-5 Years"),
        ("senior",  "5+ Years"),
    ]

    COMPANY_CHOICES = [
        ("startup",  "Startup"),
        ("product",  "Product Based"),
        ("service",  "Service Based"),
        ("faang",    "FAANG"),
    ]

    resume           = models.OneToOneField(Resume, on_delete=models.CASCADE)
    target_role      = models.CharField(max_length=50, choices=ROLE_CHOICES)
    experience_level = models.CharField(max_length=50, choices=EXPERIENCE_CHOICES)
    company_type     = models.CharField(max_length=50, choices=COMPANY_CHOICES)
    created_at       = models.DateTimeField(auto_now_add=True)


class ResumeAnalysis(models.Model):
    """
    Stores the full structured result of an ATS analysis.

    full_analysis JSONField schema:
    {
        "weighted_score":  float,       # e.g. 72.5
        "breakdown": {
            "Hard Skills & Keywords":    int,   # 0-100
            "Job Title & Level Matching": int,
            "Education & Certifications": int,
            "Formatting & Parseability":  int
        },
        "matched_skills":  list[str],   # skills found on the resume
        "missing_skills":  list[str],   # skills the role expects but are absent
        "weak_areas":      list[str],   # alignment gaps identified by the AI
        "recommendations": list[str],   # actionable improvement suggestions
        "raw_analysis":    str          # full HTML output from Gemini
    }

    This schema is populated by analyze_resume() in ai_utils.py and consumed by:
    - resume_analysis_view()  → renders the analysis dashboard
    - render_analysis_html()  → builds the HTML card content
    - chatbot()               → injects personalised context into the system prompt
    """

    resume       = models.OneToOneField(Resume, on_delete=models.CASCADE)
    final_score  = models.FloatField()
    full_analysis = models.JSONField()  # see schema above
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.resume.user.username} - Score: {self.final_score}"


class GeneratedResume(models.Model):
    resume       = models.OneToOneField(Resume, on_delete=models.CASCADE)
    html_content = models.TextField()
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Generated Resume - {self.resume.user.username}"