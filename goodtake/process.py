"""Bounded subprocesses with cancellation of the entire renderer process tree."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

import psutil


class Cancelled(RuntimeError):
    pass


def kill_tree(process):
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        _, alive = psutil.wait_procs([*children, parent], timeout=3)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    process.wait(timeout=10)


def run(args, *, timeout=300, checkpoint=lambda: None, cwd=None, env=None, tick=None):
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            [str(a) for a in args], stdout=output, stderr=output, cwd=cwd, env={**os.environ, **(env or {})}
        )
        started = time.monotonic()
        try:
            while process.poll() is None:
                checkpoint()
                if time.monotonic() - started > timeout:
                    raise TimeoutError(f"{Path(str(args[0])).name} exceeded its {timeout}s time limit.")
                if tick:
                    tick()
                time.sleep(0.3)
        except BaseException:
            kill_tree(process)
            raise
        output.seek(0)
        text = output.read().decode(errors="replace")
        if process.returncode:
            raise RuntimeError(f"{Path(str(args[0])).name} failed: {text[-2000:]}")
        return text
