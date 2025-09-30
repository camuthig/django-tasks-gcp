from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from django_tasks_gcp import views

urlpatterns = [
    path("", csrf_exempt(views.TaskView.as_view())),
]
