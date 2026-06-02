"""
Sandbox PARENT side.

Spawns the embedded python on _child.py, feeds it one job as JSON on stdin,
enforces a wall-clock timeout + a memory cap, and parses the single RunReport
JSON the child prints on stdout. NEVER imports torch and never execs candidate
code -- that all happens in the child (self-verification-model.md 9.3).

Memory cap: primary = a Windows Job Object (win32job) with a per-process memory
limit + KILL_ON_JOB_CLOSE so the whole child tree dies when we close the job
handle. Fallback = a psutil RSS watchdog thread that kills the child on breach.
We detect which path is active at import and log it once.

Wall clock: subprocess communicate(timeout=) -- which also drains the pipes so a
chatty child cannot deadlock on a full PIPE -- then kill on TimeoutExpired. This
directly kills the queue-hang failure mode documented in the brain.
"""
import os
import sys
import json
import time
import shutil
import tempfile
import threading
import subprocess

from . import records

# the ComfyUI embedded python -- same torch/CUDA the live server uses, and keeps
# torch out of THIS process.
EMBEDDED_PYTHON = os.environ.get(
    "NODEFORGE_PYTHON",
    r"F:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\python_embeded\python.exe",
)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # ...\ComfyUI-NodeForge
_CHILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_child.py")

DEFAULT_WALL_S = 30.0
DEFAULT_MEM_MB = 4096

try:
    import win32job
    import win32api
    _HAVE_JOB = True
except Exception:
    _HAVE_JOB = False

try:
    import psutil
    _HAVE_PSUTIL = True
except Exception:
    _HAVE_PSUTIL = False


def mem_cap_backend():
    if _HAVE_JOB:
        return "win32job"
    if _HAVE_PSUTIL:
        return "psutil-watchdog"
    return "none (wall-clock only)"


def _make_job_object(mem_mb):
    job = win32job.CreateJobObject(None, "")
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] = (
        win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    info["ProcessMemoryLimit"] = int(mem_mb) * 1024 * 1024
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    return job


def _assign_to_job(job, pid):
    PROCESS_ALL_ACCESS = 0x1F0FFF
    h = win32api.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    win32job.AssignProcessToJobObject(job, h)


def _psutil_watchdog(proc, mem_mb, stop_evt, flags):
    """Poll the child (+children) RSS; kill on breach. Sets flags['oom']."""
    limit = mem_mb * 1024 * 1024
    try:
        p = psutil.Process(proc.pid)
    except Exception:
        return
    peak = 0
    while not stop_evt.wait(0.1):
        try:
            rss = p.memory_info().rss
            for c in p.children(recursive=True):
                try:
                    rss += c.memory_info().rss
                except Exception:
                    pass
            peak = max(peak, rss)
            if rss > limit:
                flags["oom"] = True
                flags["peak_rss_mb"] = peak // (1024 * 1024)
                proc.kill()
                return
        except psutil.NoSuchProcess:
            break
        except Exception:
            break
    flags["peak_rss_mb"] = max(flags.get("peak_rss_mb", 0), peak // (1024 * 1024))


def run_job(job: dict, wall_s: float = DEFAULT_WALL_S, mem_mb: int = DEFAULT_MEM_MB) -> records.RunReport:
    """Execute one sandbox job and return a RunReport. Always returns a report --
    on timeout / OOM / crash it synthesizes one rather than raising."""
    job_id = job.get("job_id", "job")
    job_json = json.dumps(job)
    workdir = tempfile.mkdtemp(prefix="nodeforge_sbx_")

    # env: child needs to import the nodeforge package (fixtures) -> put the repo
    # root on PYTHONPATH. Scrub nothing else (embedded python is already minimal).
    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["CUDA_VISIBLE_DEVICES"] = env.get("CUDA_VISIBLE_DEVICES", "") if job.get("allow_gpu") else ""

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.Popen(
        [EMBEDDED_PYTHON, _CHILD],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=workdir, env=env, text=True, encoding="utf-8", creationflags=creationflags,
    )

    job_handle = None
    flags = {"oom": False, "peak_rss_mb": 0}
    watchdog = None
    stop_evt = threading.Event()

    try:
        if _HAVE_JOB:
            try:
                job_handle = _make_job_object(mem_mb)
                _assign_to_job(job_handle, proc.pid)
            except Exception as e:
                # fall back to watchdog if job assignment fails
                job_handle = None
                sys.stderr.write(f"[nodeforge.sandbox] job-object failed ({e}); using watchdog\n")
        if job_handle is None and _HAVE_PSUTIL:
            watchdog = threading.Thread(
                target=_psutil_watchdog, args=(proc, mem_mb, stop_evt, flags), daemon=True)
            watchdog.start()

        t0 = time.time()
        timed_out = False
        try:
            out, err = proc.communicate(input=job_json, timeout=wall_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            timed_out = True
        wall_ms = int((time.time() - t0) * 1000)
    finally:
        stop_evt.set()
        if watchdog is not None:
            watchdog.join(timeout=1.0)
        if job_handle is not None:
            try:
                win32api.CloseHandle(job_handle)   # KILL_ON_JOB_CLOSE reaps the tree
            except Exception:
                pass
        shutil.rmtree(workdir, ignore_errors=True)

    # parse the child's single JSON line; recover if it died mid-write
    report = _parse_report(out, job_id)
    report.timed_out = report.timed_out or timed_out
    report.oom = report.oom or flags.get("oom", False)
    report.peak_rss_mb = max(report.peak_rss_mb, flags.get("peak_rss_mb", 0))
    if not report.wall_ms:
        report.wall_ms = wall_ms
    if (timed_out or flags.get("oom")) and not report.stderr_tail:
        report.stderr_tail = (err or "")[-1500:]
    if report.stderr_tail == "" and err:
        report.stderr_tail = err[-1500:]
    return report


def render(fixtures, out_dir, candidate=None, wall_s=60.0):
    """Render fixture INPUTs (and, if `candidate` given, that candidate's OUTPUTs)
    to PNGs in out_dir, via a sandbox child. Returns {key: abspath} for PNGs
    actually written on disk -- 'in_<example_id>' always, 'out_<example_id>' when a
    candidate is supplied. Best-effort: a fixture or candidate that fails to render
    is simply absent from the returned map (it never raises).

    `fixtures` is the same [{"example_id","input_spec"}] list the run mode takes;
    `candidate` is {"id","source","class_name"}. The parent stays torch-free and
    never execs candidate code -- all of that happens in the child."""
    os.makedirs(out_dir, exist_ok=True)
    out_dir = os.path.abspath(out_dir)
    job = {"job_id": "render", "mode": "render", "allow_gpu": False,
           "candidates": [candidate] if candidate else [],
           "batteries": [], "example_fixtures": list(fixtures),
           "render_dir": out_dir}
    run_job(job, wall_s=wall_s)
    rendered = {}
    for f in fixtures:
        eid = f["example_id"]
        p_in = os.path.join(out_dir, f"in_{eid}.png")
        if os.path.exists(p_in):
            rendered[f"in_{eid}"] = p_in
        if candidate:
            p_out = os.path.join(out_dir, f"out_{eid}.png")
            if os.path.exists(p_out):
                rendered[f"out_{eid}"] = p_out
    return rendered


def _parse_report(stdout_text, job_id):
    """Pull the last JSON object out of stdout (the child prints exactly one, but
    be defensive about stray prints)."""
    text = (stdout_text or "").strip()
    if text:
        # try whole-text first, then last line
        for cand in (text, text.splitlines()[-1] if text.splitlines() else ""):
            try:
                d = json.loads(cand)
                if isinstance(d, dict) and "job_id" in d:
                    return records.RunReport.from_dict(d)
            except Exception:
                pass
    # child produced no parseable report (killed mid-write / hard crash)
    return records.RunReport(job_id=job_id, stderr_tail="(no parseable report from child)")
