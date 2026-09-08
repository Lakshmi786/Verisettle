import os

import requests

CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", "http://control-plane:8000")


def heartbeat(agent: str, thread_id: str):
    """Best-effort liveness ping for control-plane's watchdog. Never blocks
    the run - a failed heartbeat post must not itself stop anything."""
    try:
        requests.post(
            f"{CONTROL_PLANE_URL}/heartbeat",
            json={"agent": agent, "thread_id": thread_id},
            timeout=5,
        )
    except requests.RequestException:
        pass


TERMINAL_TASK_STATES = {"settled", "rejected", "blocked", "failed"}


def pause_thread(thread_id: str, reason: str):
    """Excludes this thread from the missed-heartbeat watchdog. Best-effort."""
    try:
        requests.post(f"{CONTROL_PLANE_URL}/threads/{thread_id}/pause", json={"reason": reason}, timeout=5)
    except requests.RequestException:
        pass


def unpause_thread(thread_id: str):
    try:
        requests.post(f"{CONTROL_PLANE_URL}/threads/{thread_id}/unpause", timeout=5)
    except requests.RequestException:
        pass


class SessionHalted(Exception):
    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        super().__init__(f"session {thread_id!r} is halted by the kill-switch")


def kill_switch_status() -> dict:
    """Fails open (all-clear) on a control-plane outage - it must not
    itself block every run."""
    try:
        resp = requests.get(f"{CONTROL_PLANE_URL}/status", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return {"global_stop": False, "paused_agents": [], "halted_sessions": [], "frozen_tools": []}


def ensure_not_halted(thread_id: str):
    """A halted *session* has no Cedar resource to attach to (unlike
    global_stop/paused_agents/frozen_tools, checked by policy-service on
    every tool call), so graph entry points check it directly here."""
    if thread_id in kill_switch_status().get("halted_sessions", []):
        raise SessionHalted(thread_id)
