"""Клиент к песочнице Cloudflare Computer, поднятой локально через wrangler dev.

Песочница — Durable Object с SQLite-файловой системой и shell'ом (just-bash),
который крутится в Dynamic Worker. Наружу торчит HTTP из cfcomputer/src/index.ts.
Сети у песочницы нет: globalOutbound динамического воркера закрыт, curl не собран.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKER_DIR = ROOT / "cfcomputer"
DEFAULT_PORT = int(os.getenv("CFBOX_PORT", "8788"))


class BoxError(RuntimeError):
    pass


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    status: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class Box:
    """Один воркспейс. Имя — ключ Durable Object, разные имена не видят файлы друг друга."""

    def __init__(self, name: str, port: int | None = None, timeout: float = 120.0):
        self.name = name
        self.base = f"http://127.0.0.1:{port or DEFAULT_PORT}/box/{name}"
        self.timeout = timeout

    def _call(self, path: str, method: str = "GET", body: bytes | None = None,
              ctype: str | None = None) -> tuple[int, bytes]:
        req = urllib.request.Request(self.base + path, data=body, method=method)
        if ctype:
            req.add_header("content-type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def exec(self, command: str, cwd: str = "/workspace") -> ExecResult:
        code, raw = self._call(
            "/exec", "POST",
            json.dumps({"command": command, "cwd": cwd}).encode(),
            "application/json",
        )
        d = json.loads(raw)
        if code != 200:
            raise BoxError(d.get("error", raw.decode(errors="replace")))
        return ExecResult(
            exit_code=int(d.get("exitCode", -1)),
            stdout=d.get("stdout") or "",
            stderr=d.get("stderr") or "",
            status=d.get("status") or "",
        )

    def write(self, path: str, content: str | bytes) -> None:
        data = content.encode() if isinstance(content, str) else content
        code, raw = self._call(f"/file{_abs(path)}", "PUT", data, "application/octet-stream")
        if code != 204:
            raise BoxError(raw.decode(errors="replace"))

    def read(self, path: str) -> str:
        code, raw = self._call(f"/file{_abs(path)}")
        if code != 200:
            raise BoxError(raw.decode(errors="replace"))
        return raw.decode(errors="replace")

    def tree(self) -> list[str]:
        code, raw = self._call("/tree")
        if code != 200:
            raise BoxError(raw.decode(errors="replace"))
        return json.loads(raw)["files"]

    def reset(self) -> None:
        self._call("", "DELETE")


def _abs(path: str) -> str:
    p = path if path.startswith("/") else f"/workspace/{path}"
    if p != "/workspace" and not p.startswith("/workspace/"):
        raise BoxError(f"путь должен лежать под /workspace, дано {path}")
    return p


class Server:
    """wrangler dev как контекстный менеджер.

    Если порт уже занят живой песочницей — переиспользуем её и ничего не гасим:
    чужие процессы не наши, останавливаем только то, что запустили сами.
    """

    def __init__(self, port: int | None = None, quiet: bool = True):
        self.port = port or DEFAULT_PORT
        self.quiet = quiet
        self.proc: subprocess.Popen | None = None
        self.reused = False

    def healthy(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/health", timeout=2
            ) as r:
                return json.load(r).get("ok") is True
        except Exception:
            return False

    def start(self, wait: float = 120.0) -> "Server":
        if self.healthy():
            self.reused = True
            return self
        if _port_open(self.port):
            raise BoxError(
                f"порт {self.port} занят, но это не наша песочница — "
                f"освободите его или задайте CFBOX_PORT"
            )
        if not (WORKER_DIR / "node_modules").exists():
            raise BoxError(f"не установлены зависимости воркера: cd {WORKER_DIR} && npm install")
        npx = shutil.which("npx")
        if not npx:
            raise BoxError("не найден npx — нужен Node.js")
        out = subprocess.DEVNULL if self.quiet else None
        self.proc = subprocess.Popen(
            [npx, "wrangler", "dev", "--port", str(self.port), "--log-level", "warn"],
            cwd=WORKER_DIR, stdout=out, stderr=out,
        )
        deadline = time.time() + wait
        while time.time() < deadline:
            if self.healthy():
                return self
            if self.proc.poll() is not None:
                raise BoxError(f"wrangler dev упал с кодом {self.proc.returncode}")
            time.sleep(1.0)
        self.stop()
        raise BoxError(f"песочница не поднялась за {wait:.0f}с")

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None

    def __enter__(self) -> "Server":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
