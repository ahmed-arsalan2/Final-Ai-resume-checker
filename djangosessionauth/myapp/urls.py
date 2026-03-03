# Import required modules
from django.contrib import admin
from django.urls import path
from myapp.views import *
from django.conf import settings
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.conf.urls.static import static


# Define URL patterns
urlpatterns = [
    path("", auth_page, name="auth"),               # auth page
    path("dashboard/", dashboard_view, name="dashboard"),# dashboard page
    # path('resume/', upload_resume, name='upload_resume'),# upload resume
    path('analysis/', resume_analysis_view, name='analysis'),# upload resume
    path('logout/', logout_view, name='logout'),
    path("generate/<int:resume_id>/", generate_pdf, name="generate_pdf"),
    path ("chatbot/", chatbot, name='chatbot'),
    path("login/", auth_page, name="login"),]

# Serve media files in development mode
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Serve static files
urlpatterns += staticfiles_urlpatterns()