"""
HikeAndMap: the steps of an ODX run, recognised in the task's console output while it runs, and a rough estimate of the
time left.

While a task runs, WebODM fetches its new console lines every few seconds (Task.process). record() looks for the line
that starts each step and stores, in the task's data folder (step_times.json), the processing time at which it first
appeared. estimate() turns that into: which step runs now, how far the run is, and how long it will still take.

The shares are those of two measured runs on our server (New Lucban, 5,463 photos, 49 h 42 min with the full bundle
adjustment; Alfonso Tabora, 6,277 photos, 59 h 25 min; see the run-timing page of the Mapanan Utilities documentation).
The vehicle and wire detection of [PATCH7] and [PATCH8] are counted per photo instead. A rough estimate: it improves as
steps finish, because the time the finished steps really took scales the rest.
"""
import json
import os
import re

VERSION = 1

# key, label, marker (regex on a console line), share of the run in % (None: seconds per photo instead)
STEPS = [
    ('dataset', 'Reading the photos', r'Running dataset stage', 0.2, None),
    ('features', 'Feature extraction', r'opensfm"?\s+detect_features', 3.0, None),
    ('matching', 'Feature matching', r'opensfm"?\s+match_features', 2.0, None),
    ('tracks', 'Merging the tracks', r'opensfm"?\s+create_tracks', 0.5, None),
    ('reconstruct', 'Reconstruction (bundle adjustment)', r'opensfm"?\s+reconstruct\b', 37.0, None),
    ('undistort', 'Statistics, undistorting the photos', r'opensfm"?\s+compute_statistics', 8.5, None),
    ('depthmaps', 'Depth maps', r'Running openmvs stage', 19.0, None),
    ('densefilter', 'Fusing and filtering the dense cloud', r'DensifyPointCloud"?\s+--filter-point-cloud', 3.0, None),
    ('filterpoints', 'Outlier filter', r'Running odm_filterpoints stage', 0.7, None),
    ('meshing', '2.5D mesh', r'Running odm_meshing stage', 0.8, None),
    ('texturing_start', 'Texturing: preparing', r'Running mvs_texturing stage', 0.1, None),
    ('vehicles', 'Finding vehicles and people (PATCH7)', r'\[PATCH7\] Looking for vehicles and people', None, 7.2),
    ('wires', 'Finding overhead wires (PATCH8)', r'\[PATCH8\] Looking for overhead wires', None, 0.4),
    ('texturing', 'Texturing', r'texrecon"?\s', 5.4, None),
    ('georeferencing', 'Georeferenced cloud, ground filter', r'Running odm_georeferencing stage', 1.5, None),
    ('entwine', 'Entwine tiles (3D viewer)', r'entwine build', 12.5, None),
    ('dem', 'DSM and DTM', r'Running odm_dem stage', 2.0, None),
    ('orthophoto', 'Orthophoto', r'Running odm_orthophoto stage', 3.5, None),
    ('report', 'Report', r'Running odm_report stage', 0.4, None),
    ('postprocess', 'Finishing', r'Running odm_postprocess stage', 0.5, None),
]
_MARKERS = [(k, re.compile(m)) for k, _, m, _, _ in STEPS]
_INDEX = {k: i for i, (k, _, _, _, _) in enumerate(STEPS)}

FILE_NAME = 'step_times.json'
MIN_MEASURED_SHARE = 3.0      # % of the run that must be finished (and measured) before an estimate is shown


def _path(task):
    return task.data_path(FILE_NAME)


def load(task):
    try:
        with open(_path(task), 'r') as f:
            d = json.load(f)
        if d.get('version') == VERSION and isinstance(d.get('starts'), dict):
            return d
    except Exception:
        pass
    return {'version': VERSION, 'starts': {}}


def reset(task):
    try:
        os.remove(_path(task))
    except Exception:
        pass


def detect(lines):
    """Step keys whose start marker appears in these console lines, in order of appearance."""
    found = []
    for line in lines:
        for key, rx in _MARKERS:
            if key not in found and rx.search(line):
                found.append(key)
    return found


def record(task, lines, processing_time_ms):
    """Called with each batch of new console lines: stores the start of every step seen for the first time."""
    if not lines or processing_time_ms is None or processing_time_ms < 0:
        return
    keys = detect(lines)
    first_time = not os.path.isfile(_path(task))
    if not keys and not first_time:
        return
    d = load(task)
    changed = first_time
    if first_time:
        # a task that was already running when this began to be recorded: the steps already in its console have
        # started, at a time that is not known (None); the new lines were just appended to the console
        try:
            everything = str(task.console).splitlines()
            for k in detect(everything[:max(0, len(everything) - len(lines))]):
                d['starts'][k] = None
        except Exception:
            pass
    for k in keys:
        if k not in d['starts']:
            d['starts'][k] = round(processing_time_ms / 1000.0, 1)
            changed = True
    if changed:
        try:
            os.makedirs(os.path.dirname(_path(task)), exist_ok=True)
            tmp = _path(task) + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(d, f)
            os.replace(tmp, _path(task))
        except Exception:
            pass


def _option(options, name):
    for o in options or []:
        if isinstance(o, dict) and o.get('name') == name:
            return o.get('value')
    return None


def estimate(starts, elapsed, photos, options=None):
    """
    starts: {step key: seconds since the start of the run at which it began}; elapsed: seconds now; photos: number of
    photos. Returns a dict with the current step, its number, the number of steps, percent, elapsed and remaining seconds
    (None when it cannot be estimated yet), or None when no step has been seen.
    """
    seen = [k for k, *_ in STEPS if k in starts]
    if not seen or elapsed is None:
        return None
    skip = set()
    if _option(options, 'orthophoto-keep-vehicles') in (True, 'true', 'True'):
        skip.add('vehicles')
    if _option(options, 'orthophoto-keep-wires') in (True, 'true', 'True'):
        skip.add('wires')
    # steps before the first one seen did not run in this run (a restart from a later stage)
    first = _INDEX[seen[0]]
    steps = [s for i, s in enumerate(STEPS) if i >= first and s[0] not in skip]
    current = max(seen, key=lambda k: _INDEX[k])
    ci = next(i for i, s in enumerate(steps) if s[0] == current)
    photos = max(0, int(photos or 0))

    def duration(i):
        """The real duration of a finished step (to the start of the next one that was seen)."""
        k = steps[i][0]
        if starts.get(k) is None:
            return None
        later = [s[0] for s in steps[i + 1:] if s[0] in starts]
        if not later:
            return elapsed - starts[k]
        nxt = starts[later[0]]
        return None if nxt is None else nxt - starts[k]

    # the scale: real time of the finished share steps against their share
    done_share, done_time = 0.0, 0.0
    for i in range(ci):
        k, _, _, share, _ = steps[i]
        d = duration(i)
        if share and d is not None:
            done_share += share
            done_time += d
    in_current = max(0.0, elapsed - starts[current]) if starts[current] is not None else 0.0
    cur_share, cur_per_photo = steps[ci][3], steps[ci][4]
    total_share = sum(s[3] for s in steps if s[3])

    # no estimate until finished steps make up MIN_MEASURED_SHARE % of the run (in practice: after feature extraction);
    # before that the figures jump about (tried on Alfonso Tabora: 9 h to 146 h in the first hour)
    per_share = None
    if done_share >= MIN_MEASURED_SHARE and done_time > 0:
        per_share = done_time / done_share

    remaining = None
    if per_share is not None:
        if cur_share:
            expected = cur_share * per_share
        else:
            expected = (cur_per_photo or 0) * photos
        cur_left = max(expected - in_current, in_current * 0.1)
        future = 0.0
        for k, _, _, share, per_photo in steps[ci + 1:]:
            future += share * per_share if share else (per_photo or 0) * photos
        remaining = cur_left + future

    percent = None
    if remaining is not None and elapsed + remaining > 0:
        percent = 100.0 * elapsed / (elapsed + remaining)
    labels = {k: l for k, l, *_ in STEPS}
    return {
        'step': current,
        'label': labels[current],
        'number': ci + 1,
        'count': len(steps),
        'elapsed': elapsed,
        'remaining': remaining,
        'percent': percent,
        'measured_share': round(100.0 * done_share / total_share, 1) if total_share else 0.0,
    }


def for_task(task):
    """The estimate of a running task, read from its step file."""
    d = load(task)
    elapsed = task.processing_time / 1000.0 if task.processing_time and task.processing_time > 0 else None
    return estimate(d['starts'], elapsed, task.images_count, task.options)
