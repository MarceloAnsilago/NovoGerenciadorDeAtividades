"""Reconcile Fly web Machines with weekday office hours in Rondonia."""

import copy
import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

RONDONIA = timezone(timedelta(hours=-4))


def business_hours(now):
    local = now.astimezone(RONDONIA)
    minute = local.hour * 60 + local.minute
    return local.weekday() < 5 and 450 <= minute < 825


def desired_config(config, active):
    updated = copy.deepcopy(config)
    for service in updated.get("services", []):
        service.update(autostart=True, autostop="stop", min_machines_running=int(active))
    return updated


class FlyAPI:
    def __init__(self, app, token):
        self.base = f"https://api.machines.dev/v1/apps/{app}/machines"
        self.token = token

    def request(self, path="", payload=None):
        request = Request(
            self.base + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=60) as response:
                body = response.read()
                return json.loads(body) if body else None
        except HTTPError as error:
            # Never print request/config bodies: they can contain app secrets.
            raise RuntimeError(f"Fly API: HTTP {error.code} at {path or '/'}") from None

    def stable(self, machine_id):
        for _ in range(60):
            machine = self.request(f"/{machine_id}")
            if machine["state"] in {"started", "stopped", "suspended", "created"}:
                return machine
            time.sleep(3)
        raise RuntimeError(f"Machine {machine_id} did not reach a stable state")


def reconcile(api, now, closing_event=False):
    active = business_hours(now)
    machines = [m for m in api.request() if m.get("config", {}).get("services")]
    if not machines:
        raise RuntimeError("No web Machines found; no changes made")
    print(f"Rondonia: {now.astimezone(RONDONIA).isoformat()}; business_hours={active}")
    for listed in machines:
        machine_id = listed["id"]
        machine = api.stable(machine_id)
        original = machine["config"]
        was_active = any(s.get("min_machines_running", 0) > 0 for s in original["services"])
        updated = desired_config(original, active)
        if updated != original:
            api.request(f"/{machine_id}", {
                "config": updated,
                "current_version": machine["instance_id"],
                "skip_launch": not active,
            })
            machine = api.stable(machine_id)
        if active and machine["state"] != "started":
            api.request(f"/{machine_id}/start", {})
        elif not active and (closing_event or was_active) and machine["state"] == "started":
            api.request(f"/{machine_id}/stop", {})
        machine = api.stable(machine_id)
        for service in machine["config"]["services"]:
            if (service.get("autostart") is not True
                    or service.get("autostop") not in (True, "stop")
                    or service.get("min_machines_running") != int(active)):
                raise RuntimeError(f"Machine {machine_id}: service configuration verification failed")
        if active and machine["state"] != "started":
            raise RuntimeError(f"Machine {machine_id}: failed to start")
        print(f"Machine {machine_id}: {machine['state']}; minimum={int(active)}; autostart=true")


if __name__ == "__main__":
    token = os.environ.get("FLY_API_TOKEN")
    if not token:
        raise SystemExit("Configure the GitHub Actions secret FLY_API_TOKEN first")
    reconcile(
        FlyAPI(os.environ.get("FLY_APP_NAME", "novogerenciadordeatividades"), token),
        datetime.now(timezone.utc),
        closing_event=os.environ.get("FLY_SCHEDULE") == "45 17 * * 1-5",
    )
