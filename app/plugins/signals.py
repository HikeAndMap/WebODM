import django.dispatch

task_completed = django.dispatch.Signal(providing_args=["task_id"])
task_removing = django.dispatch.Signal(providing_args=["task_id"])
task_removed = django.dispatch.Signal(providing_args=["task_id"])
task_failed = django.dispatch.Signal(providing_args=["task_id"])
task_resizing_images = django.dispatch.Signal(providing_args=["task_id"])
task_duplicated = django.dispatch.Signal(providing_args=["task_id"])

processing_node_removed = django.dispatch.Signal(providing_args=["processing_node_id"])

# HikeAndMap: a step of an ODX run began (app/classes/step_times.py); previous_step is the step that ran before it and has
# now finished (None for the first step of a run)
task_step_started = django.dispatch.Signal(providing_args=["task_id", "step", "previous_step"])
