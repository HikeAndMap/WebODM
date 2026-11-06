from app.plugins import PluginBase, Menu, MountPoint
from django.shortcuts import render
from django.http import JsonResponse
from django.template.defaultfilters import filesizeformat
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _

import json, shutil
import ctypes
import sys
import time

def get_memory_stats():
    """
    Get node total memory and memory usage.
    """
    try:
        if sys.platform == 'win32':
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]

            mem_status = MEMORYSTATUSEX()
            mem_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)

            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status)):
                return {}

            total = int(mem_status.ullTotalPhys)
            free = int(mem_status.ullAvailPhys)
            # The page file is RAM + page file on Windows; what is beyond the RAM is the "swap"
            swap_total = max(0, int(mem_status.ullTotalPageFile) - total)
            swap_free = max(0, int(mem_status.ullAvailPageFile) - free)

            return {
                'total': total,
                'free': free,
                'used': total - free,
                'swap_total': swap_total,
                'swap_free': swap_free,
                'swap_used': swap_total - swap_free,
            }

        with open('/proc/meminfo', 'r') as mem:
            ret = {}
            tmp = 0
            for i in mem:
                sline = i.split()
                if str(sline[0]) == 'MemTotal:':
                    ret['total'] = int(sline[1])
                elif str(sline[0]) in ('MemFree:', 'Buffers:', 'Cached:'):
                    tmp += int(sline[1])
                elif str(sline[0]) == 'SwapTotal:':
                    ret['swap_total'] = int(sline[1])
                elif str(sline[0]) == 'SwapFree:':
                    ret['swap_free'] = int(sline[1])
            ret['free'] = tmp
            ret['used'] = int(ret['total']) - int(ret['free'])
            ret.setdefault('swap_total', 0)
            ret.setdefault('swap_free', 0)
            ret['swap_used'] = ret['swap_total'] - ret['swap_free']

            for key in ('total', 'free', 'used', 'swap_total', 'swap_free', 'swap_used'):
                ret[key] *= 1024
        return ret
    except:
        return {}


def _cpu_times():
    """The first line of /proc/stat (all cores together) and the number of cores, or None."""
    with open('/proc/stat', 'r') as f:
        lines = f.read().splitlines()
    fields = [int(v) for v in lines[0].split()[1:]]
    cores = sum(1 for l in lines if l.startswith('cpu') and l[3:4].isdigit())
    # user nice system idle iowait irq softirq steal (guest time is already in user/nice)
    fields = (fields + [0] * 8)[:8]
    return fields, cores


def get_cpu_stats(interval=0.5):
    """
    HikeAndMap: how busy the processors are, measured over a short interval: busy cores, cores waiting for the disk
    (a sign of swapping) and idle cores, with 100 % per core; and the load average. The container sees the whole server here.
    """
    try:
        if sys.platform == 'win32':
            return {}
        first, cores = _cpu_times()
        time.sleep(interval)
        second, _ = _cpu_times()
        delta = [b - a for a, b in zip(first, second)]
        total = sum(delta)
        if total <= 0 or cores <= 0:
            return {}
        idle, iowait = delta[3], delta[4]
        busy = total - idle - iowait
        ret = {
            'cores': cores,
            'busy_cores': round(busy / total * cores, 1),
            'iowait_cores': round(iowait / total * cores, 1),
            'idle_cores': round(idle / total * cores, 1),
            'busy_percent': int(round(busy / total * cores * 100)),
            'all_percent': cores * 100,
        }
        try:
            with open('/proc/loadavg', 'r') as f:
                ret['load'] = [float(v) for v in f.read().split()[:3]]
        except Exception:
            pass
        return ret
    except Exception:
        return {}


def running_tasks(user):
    """HikeAndMap: the running tasks the user may see, with their current step and a rough estimate of the time left."""
    try:
        from guardian.shortcuts import get_objects_for_user
        from app.models import Project, Task
        from app.classes import step_times
        from nodeodm import status_codes
    except Exception:
        return []
    result = []
    try:
        projects = get_objects_for_user(user, 'app.view_project', Project, accept_global_perms=False)
        tasks = Task.objects.filter(project__in=projects, status=status_codes.RUNNING).select_related('project', 'processing_node').order_by('created_at')
        for t in tasks:
            entry = {
                'id': str(t.id),
                'name': t.name or str(t.id),
                'project': t.project.name,
                'project_id': t.project.id,
                'node': str(t.processing_node) if t.processing_node else '',
                'photos': t.images_count,
                'elapsed': t.processing_time / 1000.0 if t.processing_time and t.processing_time > 0 else None,
            }
            try:
                entry['estimate'] = step_times.for_task(t)
            except Exception:
                entry['estimate'] = None
            result.append(entry)
    except Exception:
        pass
    return result


def collect_stats():
    """Disk, memory, swap and CPU figures, for the page and for its refresh (HikeAndMap)."""
    # Disk space
    total_disk_space, used_disk_space, free_disk_space = shutil.disk_usage('./')

    stats = {
        'total_disk_space': total_disk_space,
        'used_disk_space': used_disk_space,
        'free_disk_space': free_disk_space
    }

    # Memory
    memory_stats = get_memory_stats()
    if 'free' in memory_stats:
        stats['free_memory'] = memory_stats['free']
        stats['used_memory'] = memory_stats['used']
        stats['total_memory'] = memory_stats['total']
        # Swap (virtual memory on disk), and RAM + swap together: what a processing node can use at most
        stats['swap_total'] = memory_stats.get('swap_total', 0)
        stats['swap_free'] = memory_stats.get('swap_free', 0)
        stats['swap_used'] = memory_stats.get('swap_used', 0)
        stats['all_total'] = memory_stats['total'] + stats['swap_total']
        stats['all_free'] = memory_stats['free'] + stats['swap_free']
        stats['all_used'] = memory_stats['used'] + stats['swap_used']

    # Processors (HikeAndMap)
    cpu_stats = get_cpu_stats()
    if 'cores' in cpu_stats:
        stats['cpu'] = cpu_stats
    return stats


SIZE_KEYS = ('total_disk_space', 'used_disk_space', 'free_disk_space', 'free_memory', 'used_memory', 'total_memory',
             'swap_total', 'swap_free', 'swap_used', 'all_total', 'all_free', 'all_used')


class Plugin(PluginBase):
    def main_menu(self):
        return [Menu(_("Diagnostic"), self.public_url(""), "fa fa-chart-pie fa-fw")]

    def app_mount_points(self):
        @login_required
        def diagnostic(request):
            template_args = collect_stats()
            template_args['title'] = 'Diagnostic'
            template_args['tasks_json'] = json.dumps(running_tasks(request.user))
            return render(request, self.template_path("diagnostic.html"), template_args)

        @login_required
        def stats(request):
            # HikeAndMap: the same figures as JSON, so that the page can refresh itself without reloading
            data = collect_stats()
            data['tasks'] = running_tasks(request.user)
            data['text'] = {k: filesizeformat(data[k]) for k in SIZE_KEYS if k in data}
            data['time'] = time.strftime('%H:%M:%S')
            return JsonResponse(data)

        return [
            MountPoint('$', diagnostic),
            MountPoint('stats/$', stats)
        ]


