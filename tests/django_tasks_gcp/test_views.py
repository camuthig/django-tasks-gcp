from __future__ import annotations

import json

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import SuspiciousOperation
from django.http import HttpRequest
from django.tasks import TaskResultStatus
from django.tasks import task
from django.tasks.signals import task_finished
from django.tasks.signals import task_started
from django.test import RequestFactory
from django.test import SimpleTestCase
from django.test import override_settings
from django.utils.module_loading import import_string

from django_tasks_gcp.authn import ViewAuth
from django_tasks_gcp.backend import CloudTasksBackend
from django_tasks_gcp.results import CloudTaskResult
from django_tasks_gcp.views import TaskView
from tests.django_tasks_gcp.utils import capture_signals


class DummyViewAuth(ViewAuth):
    def authenticate(self, request: HttpRequest):
        return request


class FailingViewAuth(ViewAuth):
    def authenticate(self, request: HttpRequest):
        return None


class DummyBackend(CloudTasksBackend):
    def get_view_authn(self):
        if self.options.get("VIEW_AUTHN") is None:
            return DummyViewAuth()
        else:
            return import_string(self.options.get("VIEW_AUTHN"))()

    def enqueue(self, task, args, kwargs):
        return


@task
def test_task():
    return True


@task
def failing_task():
    raise ValueError("boom")


def not_a_task():
    pass


@override_settings(
    TASKS={
        "default": {
            "BACKEND": "tests.django_tasks_gcp.test_views.DummyBackend",
            "QUEUES": [],
            "OPTIONS": {},
        },
        "failing_auth": {
            "BACKEND": "tests.django_tasks_gcp.test_views.DummyBackend",
            "QUEUES": [],
            "OPTIONS": {
                "VIEW_AUTHN": "tests.django_tasks_gcp.test_views.FailingViewAuth",
            },
        },
    }
)
class TaskViewTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()

    def test_it_executes_the_task(self):
        data = {"task_path": "tests.django_tasks_gcp.test_views.test_task", "args": [], "kwargs": {}}
        request = self.rf.post("/", data=json.dumps(data).encode(), content_type="application/json")

        view = TaskView()
        response = view.post(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"success": True})

    def test_it_returns_401_when_authn_fails(self):
        data = {"task_path": "tests.django_tasks_gcp.test_views.test_task", "args": [], "kwargs": {}}
        request = self.rf.post("/", data=json.dumps(data).encode(), content_type="application/json")

        view = TaskView(backend_name="failing_auth")
        response = view.post(request)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(json.loads(response.content), {"success": False})

    def test_it_returns_400_when_task_fails(self):
        data = {"task_path": "tests.django_tasks_gcp.test_views.failing_task", "args": [], "kwargs": {}}
        request = self.rf.post("/", data=json.dumps(data).encode(), content_type="application/json")

        view = TaskView()
        response = view.post(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content), {"success": False})

    def test_it_fails_if_the_task_path_cannot_be_imported(self):
        data = {"task_path": "not.a.path", "args": [], "kwargs": {}}
        request = self.rf.post("/", data=json.dumps(data).encode(), content_type="application/json")

        view = TaskView()
        with self.assertRaises(SuspiciousOperation):
            view.post(request)

    def test_it_fails_if_the_task_path_is_not_a_task(self):
        data = {"task_path": "tests.django_tasks_gcp.test_views.not_a_task", "args": [], "kwargs": {}}
        request = self.rf.post("/", data=json.dumps(data).encode(), content_type="application/json")

        view = TaskView()
        with self.assertRaises(SuspiciousOperation):
            view.post(request)

    @override_settings(
        TASKS={
            "default": {
                "BACKEND": "django.tasks.backends.dummy.DummyBackend",
                "QUEUES": [],
                "OPTIONS": {},
            },
        }
    )
    def test_it_fails_if_no_cloud_task_backends_are_configured(self):
        data = {"task_path": "tests.django_tasks_gcp.test_views.test_task", "args": [], "kwargs": {}}
        request = self.rf.post("/", data=json.dumps(data).encode(), content_type="application/json")
        view = TaskView()

        with self.assertRaises(ImproperlyConfigured):
            view.post(request)

    def test_it_fails_if_named_task_backend_is_not_configured(self):
        data = {"task_path": "tests.django_tasks_gcp.test_views.test_task", "args": [], "kwargs": {}}
        request = self.rf.post("/", data=json.dumps(data).encode(), content_type="application/json")
        view = TaskView(backend_name="not_configured")

        with self.assertRaises(ImproperlyConfigured):
            view.post(request)

    def test_it_sets_the_task_result_id_in_the_request(self):
        data = {"task_path": "tests.django_tasks_gcp.test_views.test_task", "args": [], "kwargs": {}}
        request = self.rf.post(
            "/",
            data=json.dumps(data).encode(),
            content_type="application/json",
            headers={"X-CloudTasks-TaskName": "test-task-id"},
        )

        view = TaskView()

        with capture_signals(task_started, task_finished) as signals:
            view.post(request)

            self.assertEqual(len(signals), 2)

            start_results = signals[0][1]["task_result"]
            self.assertIsInstance(start_results, CloudTaskResult)

            finished_results = signals[1][1]["task_result"]
            self.assertIsInstance(finished_results, CloudTaskResult)

            self.assertEqual(start_results, finished_results)

            self.assertEqual(finished_results.id, "test-task-id")
            self.assertEqual(finished_results.status, TaskResultStatus.SUCCESSFUL)
            self.assertEqual(finished_results.return_value, True)
            self.assertIsNotNone(finished_results.finished_at)
            self.assertIsNotNone(finished_results.started_at)
