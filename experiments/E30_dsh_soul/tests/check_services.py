#!/usr/bin/env python3
"""Verify the E30 chat-to-cloud handoff without making model requests."""
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

HERE = Path(__file__).resolve().parent
COMPOSE = ["docker", "compose", "-p", "emuvista-e30", "-f", str(HERE.parent / "output/docker-compose.yml")]
WORKER = (HERE / "worker.mjs").read_text()


def call(resident, action, **args):
    command = COMPOSE + ["exec", "-T", "hnode_155_" + resident, "node", "--input-type=module", "--eval", WORKER]
    result = subprocess.run(command, input=json.dumps({
        "username": resident, "chatPassword": resident + "123",
        "cloudPassword": resident + "-password", "action": action, **args,
    }), text=True, stdout=subprocess.PIPE, check=True, timeout=100)
    return json.loads(result.stdout)


def main():
    residents = {role: call(role, "identify")["userId"] for role in ("alice", "bob", "carol")}
    assert len(set(residents.values())) == 3
    path = "/e30-check-" + uuid.uuid4().hex + ".txt"
    content = "E30: Alice shared this file and sent Bob its share ID through Tinode."
    share_id = None
    try:
        share_id = str(call("alice", "share", path=path, content=content)["shareId"])
        message = f"E30 check: read-only Cloud share {share_id} for {path}."
        sent = call("alice", "notify", recipient=residents["bob"], message=message)
        assert sent["sequence"] is not None
        received = call("bob", "receive", sender=residents["alice"], message=message, shareId=share_id)
        assert received["sha256"] == hashlib.sha256(content.encode()).hexdigest()
        print(json.dumps({"residents": list(residents), **received}, indent=2))
    finally:
        if share_id is not None:
            call("alice", "cleanup", path=path, shareId=share_id)


if __name__ == "__main__":
    main()
