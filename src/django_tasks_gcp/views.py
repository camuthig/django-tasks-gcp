import json
from typing import TypedDict

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import SuspiciousOperation, ImproperlyConfigured
from django.http import JsonResponse, HttpRequest
from django.tasks import Task, TaskResult, TaskContext, TaskResultStatus, task_backends
from django.tasks.base import TaskError
from django.tasks.signals import task_started, task_finished
from django.utils import timezone
from django.utils.module_loading import import_string
from django.views import View

from django_tasks_gcp.authn import ViewAuth
from django_tasks_gcp.backend import CloudTasksBackend
from django_tasks_gcp.results import CloudTaskResult
from django_tasks_gcp.utils import get_module_path, get_exception_traceback


class Input(TypedDict):
    task_path: str
    args: list[str]
    kwargs: dict[str, str]


class TaskView(View):
    backend_name: str | None = None

    def __init__(self, **kwargs):
        self.backend_name = kwargs.pop("backend_name", None)

        super().__init__(**kwargs)

    def post(self, request):
        identity = self.authenticate(request)

        if identity is None:
            self.fail_authentication()
            return JsonResponse({"success": False}, status=401)

        data = self.parse_content(request)

        data = self.validate_input(data)

        task = self.get_task(data)

        task_result = self.get_task_result(request, data, task)

        self.run_task(task_result, data)

        if task_result.status == TaskResultStatus.FAILED:
            return JsonResponse({"success": False}, status=400)

        return JsonResponse({"success": True})

    def authenticate(self, request: HttpRequest):
        """
        Authenticate the request.

        This authentication is done without parsing the task first. This is purposeful since we are working with an
        endpoint that could be open to the world. By only using configurations on the application, we help avoid DDoS
        attacks passing in large JSON payloads.

        If the view was configured with a backend explicitly, then that will
        be used for authentication. Otherwise, the first CloudTasksBackend found in the list of configured backends will
        be used instead.

        To configure an explicit backend, register the view was `TaskView.as_view(backend_name="my_backend")`.
        """
        backend = None
        if self.backend_name:
            backend = task_backends[self.backend_name]

            if backend is None:
                raise ImproperlyConfigured(f"Task backend '{self.backend_name}' is not configured.")
        else:
            for task_backend in task_backends.all():
                if isinstance(task_backend, CloudTasksBackend):
                    backend = task_backend
                    break

            if backend is None:
                raise ImproperlyConfigured("No CloudTasksBackend is configured.")

        authn = backend.get_view_authn()

        if authn is None:
            return AnonymousUser()

        if not isinstance(authn, ViewAuth):
            raise ImproperlyConfigured("View authentication must be a subclass of ViewAuth.")

        return authn.authenticate(request)

    def fail_authentication(self):
        pass

    def parse_content(self, request: HttpRequest) -> dict:
        return json.loads(request.body)

    def validate_input(self, data: dict) -> Input:
        if "task_path" not in data:
            raise ValueError("Missing task_path in request body.")

        if not isinstance(data["task_path"], str):
            raise ValueError("task_path must be a string.")

        if "args" not in data:
            raise ValueError("Missing args in request body.")

        if not isinstance(data["args"], list):
            raise ValueError("args must be a list.")

        if "kwargs" not in data:
            raise ValueError("Missing kwargs in request body.")

        if not isinstance(data["kwargs"], dict):
            raise ValueError("kwargs must be a dict.")

        return Input(**data)

    def get_task(self, data: Input) -> Task:
        task = import_string(data["task_path"])

        if not isinstance(task, Task):
            raise SuspiciousOperation(f"{data['task_path']} is not a valid task.")

        return task

    def get_task_result(self, request: HttpRequest, data: Input, task: Task):
        task_id = request.headers.get("X-Cloudtasks-Taskname")
        retry_count = int(request.headers.get("X-CloudTasks-TaskRetryCount", 0)) # 0 for the first attempt

        return CloudTaskResult(
            task=task,
            id=task_id,
            status=TaskResultStatus.RUNNING,
            started_at=timezone.now(),
            finished_at=None,
            backend=task.get_backend(),
            args=data.get("args", []),
            kwargs=data.get("kwargs", {}),
            retry_count=retry_count,
            # The following arguments are not supported by this library
            enqueued_at=None,
            last_attempted_at=None,
            errors=[],
            worker_ids=[],
        )

    def get_task_context(self, task_result: TaskResult) -> TaskContext:
        return TaskContext(task_result=task_result)

    def run_task(self, task_result: TaskResult, data: Input):
        task = task_result.task

        task_started.send(sender=task.get_backend(), task_result=task_result)

        try:
            if task.takes_context:
                return_value = task.call(self.get_task_context(task_result), *data["args"], **data["kwargs"])
            else:
                return_value = task.call(*data["args"], **data["kwargs"])

            object.__setattr__(task_result, "_return_value", return_value)
            object.__setattr__(task_result, "status", TaskResultStatus.SUCCESSFUL)
            object.__setattr__(task_result, "finished_at", timezone.now())

            task_finished.send(sender=task.get_backend(), task_result=task_result)
        except BaseException as e:
            task_result.errors.append(
                TaskError(
                    exception_class_path=get_module_path(type(e)),
                    traceback=get_exception_traceback(e),
                )
            )

            object.__setattr__(task_result, "finished_at", timezone.now())
            object.__setattr__(task_result, "status", TaskResultStatus.FAILED)

            task_finished.send(sender=task.get_backend(), task_result=task_result)
