import json
from datetime import timedelta, datetime, UTC

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.tasks import TaskResult, TaskResultStatus, Task
from django.tasks.backends.base import BaseTaskBackend
from django.tasks.signals import task_enqueued
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.module_loading import import_string
from google import auth
from google.cloud.tasks_v2 import CloudTasksClient, HttpMethod


class CloudTasksBackend(BaseTaskBackend):
    supports_defer = True

    def __init__(self, alias, params):
        super().__init__(alias, params)

        self.client = None

    def get_view_authn(self):
        authn_class = self.options.get("VIEW_AUTHN", -1)
        if authn_class == -1:
            raise ImproperlyConfigured(
                "The view authentication class must be specified. To turn off authentication, set VIEW_AUTHN to None."
            )

        if authn_class is None:
            return None

        authn_class = import_string(authn_class)

        return authn_class(**self.options.get("VIEW_AUTHN_PARAMS"))

    def get_project_id(self):
        return self.options.get("PROJECT_ID")

    def get_location(self):
        return self.options.get("LOCATION")

    def get_credentials(self):
        if hasattr(self, "_credentials"):
            return self._credentials

        configured_credentials = self.options.get("CREDENTIALS")
        if configured_credentials:
            self._credentials = configured_credentials
        else:
            self._credentials, _ = auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )

        return self._credentials

    def get_default_target(self):
        target = self.options.get("DEFAULT_TARGET")

        if target is None:
            raise ImproperlyConfigured("The default target must be specified.")

        return target

    def get_client(self):
        if not self.client:
            self.client = CloudTasksClient(credentials=self.get_credentials())

        return self.client

    def get_parent_path(self, queue_name: str) -> str:
        return self.get_client().queue_path(self.get_project_id(), self.get_location(), queue_name)

    def get_task_path(self, queue_name: str, task_id: str) -> str:
        return self.get_client().task_path(self.get_project_id(), self.get_location(), queue_name, task_id)

    def get_enqueue_on_commit(self, task: Task):
        return self.options.get("ENQUEUE_ON_COMMIT", False)

    def enqueue(self, task: Task, args, kwargs):
        self.validate_task(task)

        # Create the task
        task_result = TaskResult(
            task=task,
            id=get_random_string(32),
            status=TaskResultStatus.READY,
            enqueued_at=None,
            started_at=None,
            last_attempted_at=None,
            finished_at=None,
            args=args,
            kwargs=kwargs,
            backend=self.alias,
            errors=[],
            worker_ids=[],
        )

        task_data = {
            "task_path": task.module_path,
            "args": args,
            "kwargs": kwargs,
        }

        cloud_task = {
            "http_request": {
                "http_method": HttpMethod.POST,
                "url": self.get_default_target(), # TODO Require a safe fallback here
                "headers": {"Content-type": "application/json"},
                "body": json.dumps(task_data).encode(),
            },
            "name": self.get_task_path(task.queue_name, task_result.id),
        }

        def _enqueue():
            nonlocal cloud_task

            if task.run_after:
                run_after = task.run_after
                if isinstance(task.run_after, timedelta):
                    run_after = timezone.now() + task.run_after

                cloud_task["schedule_time"] = run_after

            self.client.create_task(
                request={
                    "parent": self.get_parent_path(task.queue_name),
                    "task": cloud_task,
                }
            )

            object.__setattr__(task_result, "enqueued_at", timezone.now())
            task_enqueued.send(type(self), task_result=task_result)

        if self.get_enqueue_on_commit(task):
            transaction.on_commit(_enqueue)
        else:
            _enqueue()

        return task_result
