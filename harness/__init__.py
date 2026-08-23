"""Харнесс поверх browser-use: модель — любая, профиль — сменный, результат — проверяемый.

    from harness import run
    rep = run("cbr", "openai:gpt-5-mini")
    print(rep.verified, rep.problems)
"""
from harness.backends import BACKENDS, RunReport
from harness.models import available, make_model
from harness.profiles import PROFILES, Profile
from harness.runner import Matrix, run, run_matrix, save
from harness.task import Task, all_tasks, get as get_task, register

__all__ = [
    "BACKENDS", "Matrix", "PROFILES", "Profile", "RunReport", "Task",
    "all_tasks", "available", "get_task", "make_model", "register",
    "run", "run_matrix", "save",
]
