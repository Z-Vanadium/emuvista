"""Prepare each paired trial from the service-managed profile."""
from dataclasses import asdict
import json
import os
import runpy
import subprocess

import yaml

from topology import HERE, PROJECT
from services.DshAgentService import DshAgentRuntime


def main():
    runtime = DshAgentRuntime.from_compose(HERE / "output/docker-compose.yml", project=PROJECT)
    bob = runtime.agent("bob")
    metadata = bob.metadata()
    home, profile = metadata["home"], metadata["profile"]

    def prepare_profile(dex, work, case, arm):
        dex("bash", "-c", 'set -eu; umask 077; mkdir -p "$1/home/profiles"; cp -a "$2/profiles/$3" "$1/home/profiles/"',
            "bash", work, home, profile, timeout=90)
        if not os.getenv("E32_MODEL_BASE_URL"):
            source = os.getenv("E32_MODEL_CREDENTIAL_CONTAINER")
            if source:
                with subprocess.Popen(["docker", "exec", source, "cat", "/root/.dsh/.credentials.yaml"],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as credentials:
                    subprocess.run(
                        ["docker", "exec", "-i", bob.container, "bash", "-c",
                         'umask 077; cat > "$1/home/.credentials.yaml"', "bash", work],
                        stdin=credentials.stdout, check=True, capture_output=True,
                    )
                    credentials.stdout.close()
                    if credentials.wait():
                        raise RuntimeError("Could not read the configured model credentials")
            else:
                dex("cp", home + "/.credentials.yaml", work + "/home/.credentials.yaml")
        patch = f"{work}/home/profiles/{profile}/cordis.patch.yml"
        config = yaml.safe_load(dex("cat", patch))
        soul = {"residentId": "bob", "card": case["card"], "autoReflection": case.get("reviewConcerns", False)}
        soul.update(case.get("soulConfigByArm", {}).get(arm, {}))
        config.append({"id": "soul", "config": soul})
        if url := os.getenv("E32_MODEL_BASE_URL"):
            route = "e32-gateway"
            config.extend([
                {"id": "llm-pi-ai", "config": {"providers": {route: {
                    "api": "openai-completions", "baseURL": url, "apiKeyEnv": "E32_MODEL_API_KEY",
                    "models": [{"id": os.environ["E32_MODEL_ID"], "contextWindow": 65536, "maxTokens": 8192}],
                    "compat": {"supportsDeveloperRole": False, "supportsStore": False, "maxTokensField": "max_tokens"},
                }}}},
                {"id": "agent-default-model", "config": {"provider": route, "model": os.environ["E32_MODEL_ID"]}},
            ])
        dex("sh", "-c", 'cat > "$1"', "sh", patch, body=yaml.safe_dump(config))

    def after_start(port, log):
        plugins = bob.for_process(port=port, log=log).plugins
        required = {"base", "soul", "cloud-tools", "chat-tools", "e33-world-release"}
        states = {bundle.name: bundle for bundle in plugins.list()}
        missing = sorted(name for name in required if name not in states or states[name].status != "active")
        if missing:
            raise RuntimeError("Inactive protocol bundles: " + ", ".join(missing))
        return [asdict(plugins.disable("claw"))]

    runpy.run_path(str(HERE.parent / "E32_soul_followthrough/trial.py"), run_name="__main__", init_globals={
        "prepare_profile": prepare_profile, "agent_preset": "resident", "profile_name": profile,
        "after_start": after_start,
    })


if __name__ == "__main__":
    main()
