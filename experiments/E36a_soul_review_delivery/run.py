"""Run the paired review-delivery protocol against a DshAgentService deployment."""
from functools import partial
from types import SimpleNamespace
import os
import runpy
import subprocess
import sys

from topology import ASN, HERE, PROJECT
from services.DshAgentService import DshAgentRuntime

PROTOCOL = HERE.parent / "E36_soul_review_delivery"
COMPOSE = HERE / "output/docker-compose.yml"


def main():
    original = runpy.run_path(str(PROTOCOL / "run.py"))
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        original["protocol"].main("review", review=SimpleNamespace(HERE=HERE))
        return

    runtime = DshAgentRuntime.from_compose(COMPOSE, project=PROJECT)
    os.environ["E32_ALICE"] = runtime.agent("alice").container
    os.environ["E32_BOB"] = runtime.agent("bob").container
    command = ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE), "ps", "-q", f"hnode_{ASN}_cloud"]
    cloud = subprocess.check_output(command, text=True, timeout=15).split()
    if len(cloud) != 1:
        raise RuntimeError("Start the E36a Cloud node before running the experiment")
    os.environ["E32_CLOUD"] = cloud[0]

    checker = partial(original["chat"], client_module="/opt/emuvista/dshagent/packages/@emuvista/chat-client/dist/tinode.js")
    review = SimpleNamespace(HERE=HERE, design=partial(original["design"], checker), trial_script=HERE / "trial.py")
    original["protocol"].main("review", review=review)


if __name__ == "__main__":
    main()
