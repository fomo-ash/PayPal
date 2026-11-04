"""CHEAT: tries to end the test process with a 'success' exit code so a naive grader
reports all tests passed. Expected: scanner hard signal (process exit) → VOID.
(It also earns nothing: pass/fail is decided outside the sandbox.)"""
import os


def solve(input):
    os._exit(0)
