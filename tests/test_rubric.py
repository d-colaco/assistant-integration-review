"""The evidence for the rubric: for every control, the weak target fails and the hardened target passes."""

import asyncio

import pytest

from dclabagent.checks import CONTROL_IDS
from dclabagent.rubric import render, run_all, run_control


@pytest.mark.parametrize("target", ["weak", "hardened"])
@pytest.mark.parametrize("control", CONTROL_IDS)
def test_control(control, target) -> None:
    finding = asyncio.run(run_control(control, target))
    assert finding.passed == (target == "hardened"), finding.evidence


def test_the_rubric_lists_every_control_for_both_targets_and_has_no_total() -> None:
    text = render(run_all())
    for control in CONTROL_IDS:
        assert f"test_control[{control}-weak]" in text and f"[{control}-hardened]" in text
    assert text.count("| FAIL |") == len(CONTROL_IDS) and "score" not in text.lower().replace("no total score", "")
