"""Department tickets' technician dropdown (frontend/src/lib/assigneeOptions.js):
a ticket owned by a technician outside the manager's department shows that
owner (disabled), never "Unassigned". Runs the module under Node (skipped
without it)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "lib" / "assigneeOptions.js"
TECHS = [{"staff_id": "STF-1", "name": "Priya"}, {"staff_id": "STF-2", "name": "Arun"}]


def _options(ticket):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = (f"import {{ assigneeOptions }} from {json.dumps(MODULE.as_uri())};\n"
              f"console.log(JSON.stringify(assigneeOptions({json.dumps(ticket)}, {json.dumps(TECHS)})));")
    res = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_owner_outside_the_department_is_shown_and_disabled():
    options = _options({"assigned_technician_id": "STF-9", "technician_name": "Dev Outsider"})
    assert [o["value"] for o in options] == ["", "STF-1", "STF-2", "STF-9"]
    assert options[-1] == {"value": "STF-9", "label": "Dev Outsider (outside your department)", "disabled": True}
    assert not any(o["disabled"] for o in options[:-1])


def test_department_owner_or_unassigned_adds_nothing():
    for ticket in ({"assigned_technician_id": "STF-2", "technician_name": "Arun"},
                   {"assigned_technician_id": None, "technician_name": None}):
        assert [o["value"] for o in _options(ticket)] == ["", "STF-1", "STF-2"]
