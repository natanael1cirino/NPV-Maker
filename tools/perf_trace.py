"""Timing trace of a conversion (performance round 06/10/2026). Written only when the folder data/perf exists in the
plugin folder (create it to measure); otherwise nothing is recorded and subprocess.run is called unchanged.

install() replaces subprocess.run with a wrapper that records every WolvenKit call: verb, arguments, number of
files, time to the first output line, total time and the converter function that asked for it. mark() records a
step boundary; event() any other fact (cache hit, resource read). Nothing here changes what the converter writes:
the wrapper returns the same CompletedProcess (same text, same return code, same timeout behaviour).
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

_lock = threading.Lock()
_state = {"file": None, "t0": None, "mark": None, "seq": 0}
_original_run = subprocess.run
_TOOLS = os.path.dirname(os.path.abspath(__file__))


def _write(record: dict) -> None:
    stream = _state["file"]
    if stream is None:
        return
    with _lock:
        _state["seq"] += 1
        record = dict(seq=_state["seq"], t=round(time.perf_counter() - _state["t0"], 4), wall=time.time(), **record)
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()


def start(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _state["file"] = path.open("a", encoding="utf8")
    _state["t0"] = time.perf_counter()
    _write({"ev": "start", "pid": os.getpid(), "argv": sys.argv[1:]})


def mark(name: str, **data) -> None:
    _state["mark"] = name
    _write(dict(ev="mark", name=name, **data))


def event(_kind: str, **data) -> None:
    _write(dict(ev=_kind, mark=_state["mark"], **data))


def _callers() -> list[str]:
    names = []
    for frame in traceback.extract_stack()[:-3]:
        if os.path.dirname(os.path.abspath(frame.filename)) == _TOOLS and not frame.filename.endswith("perf_trace.py"):
            names.append(Path(frame.filename).stem + "." + frame.name)
    return names[-6:]


def _is_wolvenkit(args) -> bool:
    try:
        first = args[0] if isinstance(args, (list, tuple)) else args
        return str(first).lower().endswith("wolvenkit.cli.exe")
    except (IndexError, TypeError):
        return False


def _summary(args: list[str]) -> dict:
    rest = [str(a) for a in args[1:]]
    verb = " ".join(rest[:2]) if rest[:1] == ["convert"] else (rest[0] if rest else "")
    flags = {}
    for index, value in enumerate(rest):
        if value.startswith("--") and index + 1 < len(rest) and not rest[index + 1].startswith("--"):
            flags[value] = rest[index + 1]
    positional = []
    skip = False
    for value in rest[(2 if rest[:1] == ["convert"] else 1):]:
        if skip:
            skip = False
            continue
        if value.startswith("--"):
            skip = value not in ("--keep", "--list")
            continue
        positional.append(value)
    regex = flags.get("--regex", "")
    return {"verb": verb, "inputs": positional, "n_inputs": len(positional), "flags": flags,
            "regex_items": regex.count("|") + 1 if regex else 0}


def _traced_run(args, *popenargs, **kwargs):
    if _state["file"] is None or not _is_wolvenkit(args):
        return _original_run(args, *popenargs, **kwargs)
    timeout = kwargs.pop("timeout", None)
    if kwargs.pop("capture_output", False):
        kwargs["stdout"], kwargs["stderr"] = subprocess.PIPE, subprocess.PIPE
    info = _summary([str(a) for a in args])
    callers = _callers()
    begin = time.perf_counter()
    first = {"t": None, "lines": []}
    chunks = {"out": [], "err": []}

    def pump(stream, key):
        for line in stream:
            now = time.perf_counter()
            if first["t"] is None:
                first["t"] = now
            if len(first["lines"]) < 4:
                first["lines"].append([round(now - begin, 3), line.rstrip()[:160]])
            chunks[key].append(line)
        stream.close()
    process = subprocess.Popen(args, *popenargs, **kwargs)
    threads = [threading.Thread(target=pump, args=(process.stdout, "out"), daemon=True),
               threading.Thread(target=pump, args=(process.stderr, "err"), daemon=True)]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        for thread in threads:
            thread.join()
        process.wait()
        _write(dict(ev="wk", mark=_state["mark"], callers=callers, seconds=round(time.perf_counter() - begin, 3),
                    timeout=True, **info))
        raise subprocess.TimeoutExpired(args, timeout, output="".join(chunks["out"]), stderr="".join(chunks["err"]))
    for thread in threads:
        thread.join()
    end = time.perf_counter()
    out, err = "".join(chunks["out"]), "".join(chunks["err"])
    _write(dict(ev="wk", mark=_state["mark"], callers=callers, seconds=round(end - begin, 3),
                first_output=None if first["t"] is None else round(first["t"] - begin, 3),
                returncode=process.returncode, out_lines=out.count("\n") + err.count("\n"),
                first_lines=first["lines"], last_line=(out.strip().splitlines() or [""])[-1][:200], **info))
    return subprocess.CompletedProcess(args, process.returncode, out, err)


def install() -> None:
    subprocess.run = _traced_run
