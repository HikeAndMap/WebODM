"""
HikeAndMap: the text of the notification mails - a short summary, never the console itself.

- After a step (when "mail after every step" is on): which step finished, how long it took, the run so far and the rough
  estimate of the time left, the memory measured in it, and the few summary lines our ODX prints there.
- At the end (completed, failed): the time of every step, the memory of every stage and of the whole run, and for a
  failed task the step it failed in and WebODM's error.

The steps are those of app/classes/step_times.py (the Diagnostic page's estimate); the memory comes from the [PATCH5]
lines of our ODX (per stage), its texturing program ([PATCH9] Step lines) and the [PATCH7]/[PATCH8] summary lines.
Pure functions on plain values, so they can be tested without Django.
"""
import re

from app.classes import step_times

_PREFIX = re.compile(r'^\[(INFO|WARNING|ERROR|DEBUG)\]\s*')

_STAGE_MEMORY = re.compile(r'\[PATCH5\] Memory in the (\S+) stage: peak (\S+ GiB) RAM, (\S+ GiB) swap, (\S+ GiB) together '
                           r'\(this run so far: (\S+ GiB);')
_RUN_MEMORY = re.compile(r'\[PATCH5\] Peak memory of the run: (.*)')
_RUN_SO_FAR = re.compile(r'this run so far: (\S+ GiB)')
_TEXRECON_PEAK = re.compile(r'\[PATCH9\] Step: .*the most so far (\S+ GiB)')
_STAGE_TOOK = re.compile(r'\[PATCH9\] The \S+ stage took ')

# the summary lines worth a mail: results and timings our ODX prints once per stage or step (never progress lines)
_NOTES = [
    re.compile(r'\[PATCH9\] The \S+ stage took .*'),
    re.compile(r'\[PATCH9\] Adding photos done.*'),
    re.compile(r'\[PATCH9\] Final adjustment.*'),
    re.compile(r'\[PATCH9\] Time per stage recorded.*'),
    re.compile(r'\[PATCH7\] \d+ boxes in \d+ of \d+ photos.*'),  # not texrecon's own "... of ... views" line
    re.compile(r'\[PATCH8\] Overhead wires: \d+ masks on .*'),
    re.compile(r'\[PATCH8\] Ground grid of .*'),
    re.compile(r'\[PATCH8\] Roofs and roof edges left out.*'),
    re.compile(r'\[PATCH13\] Scene split .*'),
    re.compile(r'\[PATCH16\] .*'),
    re.compile(r'Fusing depthmaps for \d+ scenes'),
    re.compile(r'OpenMVS ran out of memory.*'),
    re.compile(r'Whole texturing procedure took: .*'),
]
MAX_NOTES = 20
MAX_LINE = 400

_LABELS = {k: label for k, label, *_ in step_times.STEPS}
_ORDER = [k for k, *_ in step_times.STEPS]
_MARKER = {k: re.compile(m) for k, _, m, *_ in step_times.STEPS}


def duration(seconds):
    """'2 h 05 min', '4 min 12 s', '12 s'; '-' when not known."""
    if seconds is None or seconds < 0:
        return "-"
    s = int(round(seconds))
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    if h:
        return "%d h %02d min" % (h, m)
    if m:
        return "%d min %02d s" % (m, s)
    return "%d s" % s


def _clean(line):
    line = _PREFIX.sub('', line.strip())
    return line if len(line) <= MAX_LINE else line[:MAX_LINE] + " ..."


def lines_of_step(console_lines, step):
    """The console lines from the last start of this step to the end (the step that has just finished), or [] when its
    start is not in the console."""
    rx = _MARKER.get(step)
    if rx is None:
        return []
    for i in range(len(console_lines) - 1, -1, -1):
        if rx.search(console_lines[i]):
            return console_lines[i:]
    return []


def memory_and_notes(lines, stage_times=True):
    """(memory lines, notes) found in these console lines; stage_times=False leaves the '[PATCH9] The ... stage took'
    lines out (the end mail lists the steps' times itself)."""
    memory, notes = [], []
    texrecon = None
    for raw in lines:
        m = _STAGE_MEMORY.search(raw)
        if m:
            memory.append("%s stage: peak %s together (RAM %s, swap %s)" % (m.group(1), m.group(4), m.group(2), m.group(3)))
            continue
        m = _RUN_MEMORY.search(raw)
        if m:
            memory.insert(0, "Peak of the whole run: " + _clean(m.group(1)))
            continue
        m = _TEXRECON_PEAK.search(raw)
        if m:
            texrecon = m.group(1)
            continue
        if not stage_times and _STAGE_TOOK.search(raw):
            continue
        if any(rx.search(raw) for rx in _NOTES):
            notes.append(_clean(raw))
    if texrecon is not None:
        memory.append("texturing program (texrecon): at most %s" % texrecon)
    if len(notes) > MAX_NOTES:
        notes = notes[:MAX_NOTES - 1] + ["... and %d more" % (len(notes) - MAX_NOTES + 1)]
    return memory, notes


def run_so_far(console_lines):
    """The last 'this run so far' memory figure in the console, or None."""
    for i in range(len(console_lines) - 1, -1, -1):
        m = _RUN_SO_FAR.search(console_lines[i])
        if m:
            return m.group(1)
    return None


def step_durations(starts, end_seconds):
    """[(key, label, seconds or None)] of the steps that ran, in order: each to the start of the next one seen, the
    last to end_seconds."""
    seen = [k for k in _ORDER if k in starts]
    out = []
    for i, k in enumerate(seen):
        start = starts.get(k)
        nxt = starts.get(seen[i + 1]) if i + 1 < len(seen) else end_seconds
        out.append((k, _LABELS[k], None if start is None or nxt is None else max(0.0, nxt - start)))
    return out


def _header(project, task_name, photos, node):
    extra = []
    if photos:
        extra.append("{:,} photos".format(photos))
    if node:
        extra.append("node " + node)
    return ["Project: %s" % project, "Task: %s%s" % (task_name, " (%s)" % ", ".join(extra) if extra else "")]


def step_mail(app_name, project, task_name, photos, node, finished, started, starts, estimate, console_lines):
    """(subject, body) for the step `finished`, which ended when `started` began."""
    est = estimate or {}
    count = est.get('count')
    # numbered among the steps that ran (a restart from a later stage, or detections reused, run fewer)
    seen = [k for k in _ORDER if k in starts]
    number = seen.index(finished) + 1 if finished in seen else None
    took = None
    if starts.get(finished) is not None and starts.get(started) is not None:
        took = starts[started] - starts[finished]
    label = _LABELS.get(finished, finished)
    of = " of %d" % count if count else ""

    subject = "%s - %s: step %s%s done, %s" % (app_name, task_name, number if number else "?", of, label)
    body = _header(project, task_name, photos, node)
    body.append("")
    body.append("Step %s%s done: %s, took %s" % (number if number else "?", of, label, duration(took)))
    body.append("Now running: %s" % _LABELS.get(started, started))
    elapsed = est.get('elapsed')
    remaining = est.get('remaining')
    body.append("Run so far: %s; time left: %s" % (
        duration(elapsed), ("about " + duration(remaining) + " (rough estimate)") if remaining is not None else "not estimated yet"))

    memory, notes = memory_and_notes(lines_of_step(console_lines, finished))
    body.append("")
    body.append("Memory")
    if memory:
        body += ["  " + m for m in memory]
    else:
        so_far = run_so_far(console_lines)
        body.append("  not measured in this step yet (our node measures per stage, at the end of the stage)")
        if so_far:
            body.append("  peak of the run so far: %s" % so_far)
    if notes:
        body.append("")
        body.append("Summary")
        body += ["  " + n for n in notes]
    return subject, "\n".join(body) + "\n"


def run_mail(app_name, project, task_name, photos, node, outcome, processing_seconds, starts, console_lines,
             error=None, failed_step=None):
    """(subject, body) at the end of a run. outcome: 'Completed', 'Failed' or 'Removed'."""
    subject = "%s - %s: %s" % (app_name, task_name, outcome.lower())
    body = _header(project, task_name, photos, node)
    body.append("")
    body.append("%s after %s" % (outcome, duration(processing_seconds)))
    if outcome == 'Failed':
        if failed_step:
            body.append("Failed during: %s" % _LABELS.get(failed_step, failed_step))
        if error:
            body.append("Error: %s" % _clean(error))

    steps = step_durations(starts or {}, processing_seconds)
    if steps:
        width = max(len(label) for _, label, _ in steps)
        body.append("")
        body.append("Steps")
        for i, (_, label, seconds) in enumerate(steps):
            body.append("  %2d  %s  %s" % (i + 1, label.ljust(width), duration(seconds)))

    memory, notes = memory_and_notes(console_lines or [], stage_times=False)  # the steps above already give the times
    if memory:
        body.append("")
        body.append("Memory")
        body += ["  " + m for m in memory]
    if notes:
        body.append("")
        body.append("Summary")
        body += ["  " + n for n in notes]
    return subject, "\n".join(body) + "\n"
