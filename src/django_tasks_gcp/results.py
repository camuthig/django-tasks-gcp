from dataclasses import dataclass

from django.tasks import TaskResult


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudTaskResult(TaskResult):
    retry_count: int

    @property
    def attempts(self):
        return self.retry_count + 1