"""Exercise deployment replacement and rollback with fake Git/Docker commands."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/deploy.sh"
FAKE_COMMAND = r'''
import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
args = sys.argv[1:]
state_path = Path(os.environ["FAKE_STATE"])
state = json.loads(state_path.read_text())
state["events"].append([command, *args])
result = 0
current = "mexc-market-scraper-container"
previous = "mexc-market-scraper-previous"
scenario = os.environ["SCENARIO"]
if command == "docker":
    if args[0] == "build" and scenario == "build_failure":
        result = 1
    elif args[:2] == ["container", "inspect"]:
        result = 0 if args[2] in state["containers"] else 1
    elif args[0] == "stop":
        state["containers"][args[-1]]["running"] = False
    elif args[0] == "rename":
        state["containers"][args[2]] = state["containers"].pop(args[1])
    elif args[0] == "run" and "-d" in args:
        state["containers"][current] = {"version": "new", "running": True}
        if scenario == "run_failure":
            result = 1
    elif args[0] == "inspect":
        print("running" if "State.Status" in args[2] else
              ("unhealthy" if scenario == "unhealthy" else "healthy"))
    elif args[0] == "rm":
        state["containers"].pop(args[-1], None)
    elif args[0] == "start":
        state["containers"][args[-1]]["running"] = True
state_path.write_text(json.dumps(state))
sys.exit(result)
'''


@pytest.mark.parametrize("scenario", ["success", "build_failure", "run_failure", "unhealthy"])
def test_deploy_and_rollback(tmp_path, scenario):
    commands = tmp_path / "bin"
    commands.mkdir()
    for command in ["git", "docker", "sleep"]:
        path = commands / command
        path.write_text(f"#!{sys.executable}\n" + FAKE_COMMAND)
        path.chmod(0o755)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"containers": {
        "mexc-market-scraper-container": {"version": "old", "running": True},
        "mexc-unrelated": {"version": "unrelated", "running": True},
    }, "events": []}))
    result = subprocess.run(["sh", str(SCRIPT)], text=True, capture_output=True, env={
        **os.environ, "PATH": f"{commands}:{os.environ['PATH']}", "DEPLOY_DIR": str(tmp_path),
        "DEPLOY_SHA": "a" * 40, "TG_BOT_TOKEN": "test-token", "SCENARIO": scenario,
        "FAKE_STATE": str(state_path),
    })
    state = json.loads(state_path.read_text())
    assert (result.returncode == 0) == (scenario == "success"), result.stderr
    assert state["containers"]["mexc-market-scraper-container"] == {
        "version": "new" if scenario == "success" else "old", "running": True}
    assert state["containers"]["mexc-unrelated"]["running"] is True
    assert "mexc-market-scraper-previous" not in state["containers"]
    if scenario == "build_failure":
        assert not any(event[:2] == ["docker", "stop"] for event in state["events"])
    else:
        build = next(i for i, event in enumerate(state["events"]) if event[:2] == ["docker", "build"])
        stop = next(i for i, event in enumerate(state["events"]) if event[:2] == ["docker", "stop"])
        assert build < stop
