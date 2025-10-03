import json
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.tasks import task
from django.tasks.signals import task_enqueued
from django.test import SimpleTestCase
from django.test import TransactionTestCase
from django.utils import timezone

from django_tasks_gcp.backend import CloudTasksBackend
from tests.django_tasks_gcp.utils import capture_signals


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.tasks = []

    def create_task(self, *args, **kwargs):
        self.tasks.append((args, kwargs))

    def queue_path(self, project_id, location, queue_name):
        return f"projects/{project_id}/locations/{location}/queues/{queue_name}"

    def task_path(self, project_id, location, queue_name, task_id):
        return f"projects/{project_id}/locations/{location}/queues/{queue_name}/tasks/{task_id}"


class FakeCloudTasksBackend(CloudTasksBackend):
    def get_client(self):
        if self.client is None:
            self.client = FakeClient()

        return self.client


@task
def test_task():
    pass


def build_settings(**kwargs):
    default_settings = {
        "PROJECT_ID": "test-project",
        "LOCATION": "us-central1",
        "CREDENTIALS": None,
        "DEFAULT_TARGET": "https://example.com/task-handler",
        "VIEW_AUTHN": None,
        "VIEW_AUTHN_PARAMS": {},
        "ENQUEUE_ON_COMMIT": False,
    }

    settings = {**default_settings, **kwargs}

    return {
        "QUEUES": [],
        "OPTIONS": settings,
    }


class CloudTasksBackendTests(SimpleTestCase):
    def test_it_gathers_project_id(self):
        settings = build_settings(PROJECT_ID="my-project")
        backend = CloudTasksBackend("default", params=settings)
        self.assertEqual(backend.get_project_id(), "my-project")

        settings = build_settings()
        del settings["OPTIONS"]["PROJECT_ID"]
        backend = CloudTasksBackend("default", params=settings)
        with self.assertRaises(ImproperlyConfigured):
            backend.get_project_id()

    def test_it_gathers_location(self):
        settings = build_settings(LOCATION="us-east1")
        backend = CloudTasksBackend("default", params=settings)
        self.assertEqual(backend.get_location(), "us-east1")

        settings = build_settings()
        del settings["OPTIONS"]["LOCATION"]
        backend = CloudTasksBackend("default", params=settings)
        with self.assertRaises(ImproperlyConfigured):
            backend.get_location()

    def test_it_gathers_credentials(self):
        settings = build_settings(CREDENTIALS="my-credentials")
        backend = CloudTasksBackend("default", params=settings)
        self.assertEqual(backend.get_credentials(), "my-credentials")

    @mock.patch("django_tasks_gcp.backend.auth.default")
    def test_it_gathers_machine_credentials(self, mock_auth_default):
        settings = build_settings()
        del settings["OPTIONS"]["CREDENTIALS"]
        backend = CloudTasksBackend("default", params=settings)

        mock_auth_default.return_value = ("machine-credentials", None)

        self.assertEqual(backend.get_credentials(), "machine-credentials")

    @mock.patch("django_tasks_gcp.backend.auth.default")
    def test_it_fails_to_gather_credentials(self, mock_auth_default):
        settings = build_settings()
        del settings["OPTIONS"]["CREDENTIALS"]
        backend = CloudTasksBackend("default", params=settings)

        # Simulate no machine credentials available
        mock_auth_default.return_value = (None, None)

        with self.assertRaises(ImproperlyConfigured):
            backend.get_credentials()

    def test_it_gathers_default_target(self):
        settings = build_settings(DEFAULT_TARGET="https://test.com/task-handler")
        backend = CloudTasksBackend("default", params=settings)
        self.assertEqual(backend.get_default_target(), "https://test.com/task-handler")

        settings = build_settings()
        del settings["OPTIONS"]["DEFAULT_TARGET"]
        backend = CloudTasksBackend("default", params=settings)
        with self.assertRaises(ImproperlyConfigured):
            backend.get_default_target()



    def test_it_enqueues_the_task(self):
        backend = FakeCloudTasksBackend("default", params=build_settings())

        with capture_signals(task_enqueued) as signals:
            result = backend.enqueue(test_task, [1], {"a": "b"})

        self.assertIsNotNone(result.id)

        self.assertEqual(1, len(backend.get_client().tasks))

        task_request = backend.get_client().tasks[0][1]["request"]

        expected_content = {
            "task_path": "tests.django_tasks_gcp.test_backend.test_task",
            "args": [1],
            "kwargs": {"a": "b"},
        }

        self.assertEqual(
            task_request["parent"],
            "projects/test-project/locations/us-central1/queues/default",
        )
        self.assertEqual(
            task_request["task"]["http_request"]["url"],
            "https://example.com/task-handler",
        )
        self.assertEqual(
            task_request["task"]["http_request"]["body"],
            json.dumps(expected_content).encode(),
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0][1]["task_result"].id, result.id)

    # WIP Test run_after
    def test_it_enqueues_the_task_with_run_after(self):
        backend = FakeCloudTasksBackend("default", params=build_settings())
        task = test_task

        # Avoid validation errors because I'm not overriding settings and set the run after directly.
        run_after = timezone.now() + timedelta(seconds=10)
        object.__setattr__(task, "run_after", run_after)

        backend.enqueue(task, [1], {"a": "b"})

        self.assertEqual(1, len(backend.get_client().tasks))

        task_request = backend.get_client().tasks[0][1]["request"]

        self.assertEqual(
            task_request["task"]["schedule_time"],
            run_after,
        )


class EnqueueOnCommitTests(TransactionTestCase):
    def test_it_enqueues_the_task_on_commit(self):
        backend = FakeCloudTasksBackend("default", params=build_settings(ENQUEUE_ON_COMMIT=True))

        with capture_signals(task_enqueued) as signals:
            with transaction.atomic():
                backend.enqueue(test_task, [1], {"a": "b"})

                self.assertEqual(len(signals), 0)

            self.assertEqual(len(signals), 1)
