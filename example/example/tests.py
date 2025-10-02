from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from example.tasks import do_task


class TriggerTaskTestCase(TestCase):
    def test_task(self):
        """
        A simple test case to trigger our task.
        """
        do_task.using(run_after=timezone.now() + timedelta(seconds=10)).enqueue(1, b=2)
