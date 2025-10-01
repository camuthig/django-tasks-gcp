# Django Tasks – Google Cloud Tasks Backend

A backend for Django’s built-in [Tasks framework](https://docs.djangoproject.com/en/6.0/topics/tasks/) (introduced in 
Django 6.0) powered by Google Cloud Tasks.

This package provides:
- A Django Tasks backend that enqueues tasks to Google Cloud Tasks.
- A Django view to receive HTTP callbacks from Cloud Tasks and execute work securely.

Note: This backend follows the evolving Django Tasks feature in Django 6.x and may change as the upstream feature evolves.

## Requirements

- Python 3.12+
- Django 6.0+
- A Google Cloud project with Cloud Tasks enabled and a service account you control

## Installation

Using uv:

```bash
uv add django-tasks-gcp
```

## Django Configuration

```python
from google.oauth2 import service_account
import os

GCP_KEY_PATH = os.path.join(BASE_DIR, "path_to_gcp_key.json")
GCP_KEY = service_account.Credentials.from_service_account_file(GCP_KEY_PATH)
GCP_PROJECT_ID = GCP_KEY.project_id
TASKS = {
    "default": {
        "BACKEND": "django_tasks_gcp.backend.CloudTasksBackend", 
        "QUEUES": [],
        "OPTIONS": {
            "CREDENTIALS": GCP_KEY, 
            "PROJECT_ID": GCP_PROJECT_ID, 
            "LOCATION": "gcp_region",
            "DEFAULT_TARGET": "https://example.com",
            "ENQUEUE_ON_COMMIT": True, 
            "VIEW_AUTHN": "django_tasks_gcp.authn.OIDCTokenAuth",
            "VIEW_AUTHN_PARAMS": {"service_account_email": None}, 
        }, 
    }
}
```

**Note on credentials:** If using a key file for credentials, ensure it is stored securely and not committed to source control. 
If possible, use a service account with workload identity or metadata-based credentials, instead.

### Options

- CREDENTIALS (optional): Google auth credentials to call Cloud Tasks. If not included, the backend will attempt to use any machine-level service account credentials.
- PROJECT_ID (required): Your Google Cloud project ID.
- LOCATION (required): The Google Cloud region for your queue(s) (e.g., us-central1).
- DEFAULT_TARGET (required): Default HTTPS endpoint used when creating tasks. Even if the queue has HTTP overrides, Cloud Tasks requires a target on task creation. This acts as the default for queues without overrides.
- VIEW_AUTHN (required): Dotted path to the authentication backend for the receiving view. Set to None to disable (not recommended).
- VIEW_AUTHN_PARAMS (optional): Dict of parameters for the view auth backend (e.g., `{"service_account_email": "..."}`).
- ENQUEUE_ON_COMMIT (optional): If true, tasks enqueue only after the surrounding DB transaction commits. Defaults to false.

## View handling

### URL configuration

Expose the endpoint that Cloud Tasks will call:

```python
urlpatterns = [
    # ... your other URLs
    path("cloud_tasks", include("django_tasks_gcp.urls")),
]
```

If this backend is not your default, you can bind the view explicitly:

```python
path("", csrf_exempt(views.TaskView.as_view(backend_name="cloud_tasks"))),
```

### Authentication

Cloud Tasks invokes your endpoint over HTTP, so you must secure it. The default view auth backend is 
`django_tasks_gcp.authn.OIDCTokenAuth`.

By default, it validates the OIDC JWT presented in the Authorization header, as sent by Cloud Tasks when you configure
an OIDC service account on the queue. If `VIEW_AUTHN_PARAMS` includes `service_account_email`, the backend also asserts
the token’s subject matches that service account.

## Cloud Tasks queue configuration

If you would like to use more queues than the default, you will need to configure them as overrides on the Cloud Tasks
queues.

Additionally, you will need to configure the service account OIDC on the queue to use the `OIDCTokenAuth` view auth
backend. Using the `gcloud` CLI tool to create or update your queue:

```bash
gcloud tasks queues update <queue_name> \
    --location=<region> \
    --http-uri-override=scheme:"https",host:"your.domain",path:"/cloud_tasks",mode:"ALWAYS" \
    --http-oidc-service-account-email-override=<service_account>@<project>.iam.gserviceaccount.com
```
