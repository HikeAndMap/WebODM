"""
HikeAndMap: Task Notification is built into our WebODM again (coreplugins/tasknotification), with SSL, short summaries
and an optional mail after every step. Migration 0053 had downloaded WebODM's own copy into the plugins folder of the
media directory, and plugins there are loaded BEFORE the built-in ones: a plugin of the same name in coreplugins is then
skipped ("Duplicate plugin name found"). So the downloaded copy is removed here, once. The plugin's database entry
(enabled or not) and its settings (plugin data store, keys "tasknotification::...") are kept: they go by the plugin's
name, which is the same.
"""
import os
import shutil

from django.db import migrations
from webodm import settings

NAME = "tasknotification"


def remove_downloaded_copy(apps, schema_editor):
    builtin = os.path.join(settings.BASE_DIR, "coreplugins", NAME)
    downloaded = os.path.join(settings.MEDIA_ROOT, "plugins", NAME)
    if os.path.isdir(builtin) and os.path.isdir(downloaded):
        shutil.rmtree(downloaded, ignore_errors=True)
        print("Removed the downloaded {} plugin: the built-in one (HikeAndMap) is used instead".format(NAME))


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0053_update_plugins'),
    ]

    operations = [
        migrations.RunPython(remove_downloaded_copy, migrations.RunPython.noop),
    ]
