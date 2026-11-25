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


def run(args, *, timeout=300, checkpoint=lambda: None, cwd=None, env=None, tick=None, on_line=None):
    with (
        tempfile.TemporaryDirectory(prefix="goodtake-process-") as directory,
        open(Path(directory) / "output.log", "w+b") as output,
        open(Path(directory) / "output.log", "rb") as reader,
    ):
        process = subprocess.Popen(
            [str(a) for a in args], stdout=output, stderr=output, cwd=cwd, env={**os.environ, **(env or {})}
        )
        started = time.monotonic()
        pending = b""

        def read_lines(final=False):
            nonlocal pending
            if not on_line:
                return
            pending += reader.read()
            lines = pending.split(b"\n")
            pending = lines.pop()
            for line in lines:
                on_line(line.decode(errors="replace"))
            if final and pending:
                on_line(pending.decode(errors="replace"))
                pending = b""

        try:
            while process.poll() is None:
                checkpoint()
                read_lines()
                if time.monotonic() - started > timeout:
                    raise TimeoutError(f"{Path(str(args[0])).name} exceeded its {timeout}s time limit.")
                if tick:
                    tick()
                time.sleep(0.3)
        except BaseException:
            kill_tree(process)
            raise
        read_lines(final=True)
        output.seek(0)
        text = output.read().decode(errors="replace")
        if process.returncode:
            raise RuntimeError(f"{Path(str(args[0])).name} failed: {text[-2000:]}")
        return text
