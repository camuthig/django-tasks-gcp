from django.tasks import task


@task(queue_name="test-1")
def do_task(a: int, *, b: int = 1):
    print(a, b)
    print("Doing task")
