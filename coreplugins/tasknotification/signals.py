import logging
import threading

from django.dispatch import receiver
from app.plugins.signals import task_completed, task_failed, task_removing, task_step_started
from app.plugins.functions import get_current_plugin
from app.classes import step_times
from . import email as notification
from . import config
from . import summary
from app.models import Task, Setting

logger = logging.getLogger('app.logger')

# HikeAndMap: the mails carry a short summary (step times, memory, the summary lines of our ODX), not the console - the
# console of a large task runs to tens of thousands of lines. A mail after every step is optional (notify_each_step).


def _details(task):
    """The values every mail uses."""
    node = str(task.processing_node) if task.processing_node else None
    try:
        lines = task.console.output().split('\n')
    except Exception:
        lines = []
    try:
        starts = step_times.load(task)['starts']
    except Exception:
        starts = {}
    seconds = task.processing_time / 1000.0 if task.processing_time and task.processing_time > 0 else None
    return node, lines, starts, seconds


def _app_name(config_data):
    return config_data.get('notification_app_name') or Setting.objects.first().app_name


def _run_mail(task_id, outcome, config_data):
    task = Task.objects.get(id=task_id)
    node, lines, starts, seconds = _details(task)
    failed_step = None
    if outcome == 'Failed':
        try:
            estimate = step_times.for_task(task)
            failed_step = estimate['step'] if estimate else None
        except Exception:
            failed_step = None
    subject, body = summary.run_mail(_app_name(config_data), task.project.name, task.name or str(task), task.images_count, node,
                                     outcome, seconds, starts, lines, error=task.last_error, failed_step=failed_step)
    notification.send(subject, body, config_data)


@receiver(task_completed)
def handle_task_completed(sender, task_id, **kwargs):
    if get_current_plugin(only_active=True) is None:
        return
    logger.info("TaskNotification: Task Completed")
    config_data = config.load()
    if config_data.get("notify_task_completed") == True:
        _run_mail(task_id, 'Completed', config_data)


@receiver(task_removing)
def handle_task_removed(sender, task_id, **kwargs):
    if get_current_plugin(only_active=True) is None:
        return
    logger.info("TaskNotification: Task Removed")
    config_data = config.load()
    if config_data.get("notify_task_removed") == True:
        _run_mail(task_id, 'Removed', config_data)


@receiver(task_failed)
def handle_task_failed(sender, task_id, **kwargs):
    if get_current_plugin(only_active=True) is None:
        return
    logger.info("TaskNotification: Task Failed")
    config_data = config.load()
    if config_data.get("notify_task_failed") == True:
        _run_mail(task_id, 'Failed', config_data)


@receiver(task_step_started)
def handle_task_step_started(sender, task_id, step, previous_step, **kwargs):
    """HikeAndMap: a step of the run began, so the one before it finished - a short mail about that one."""
    if get_current_plugin(only_active=True) is None:
        return
    config_data = config.load()
    if config_data.get("notify_each_step") != True or not previous_step:
        return

    task = Task.objects.get(id=task_id)
    node, lines, starts, _ = _details(task)
    try:
        estimate = step_times.for_task(task)
    except Exception:
        estimate = None
    subject, body = summary.step_mail(_app_name(config_data), task.project.name, task.name or str(task), task.images_count, node,
                                      previous_step, step, starts, estimate, lines)

    # sent beside the task's processing, so that a slow or unreachable mail server never holds the run up
    def send():
        try:
            notification.send(subject, body, config_data)
        except Exception as e:
            logger.warning("TaskNotification: cannot send the mail about step {} of {}: {}".format(previous_step, task_id, str(e)))

    threading.Thread(target=send, name='tasknotification-step', daemon=True).start()
