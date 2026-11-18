"""Generate the review-delivery experiment with native DshAgentService bindings."""
import argparse
from pathlib import Path
import sys

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORLD = HERE.parent / "E30_dsh_soul"
RUNTIME = HERE / ".runtime"
ASN = 156
PROJECT = "emuvista-e36a"
sys.path.insert(0, str(ROOT))

from seedemu.core import Binding, Filter
from services.DshAgentService import DshAgentService


def residents(emu, nodes, cards, asn):
    agents = DshAgentService()
    for name, card in cards.items():
        config = RUNTIME / "config" / f"{name}.yml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(yaml.safe_dump({
            "plugins": {"soul": {"config": {"card": card}}, "chat": {"config": {"username": name}}},
        }, allow_unicode=True))
        state = RUNTIME / "residents" / name
        state.mkdir(parents=True, exist_ok=True)
        nodes[name].addSharedFolder(f"/var/lib/dshagent/{name}", str(state))
        bundles = [HERE / "bundles/cloud-tools.yml", HERE / "bundles/chat-tools.yml"]
        if name == "bob":
            bundles.append(HERE.parent / "E33_soul_review/world-release")
        agents.install(name, bundles=bundles, config=config)
        emu.addBinding(Binding(name, filter=Filter(asn=asn, nodeName=f"^{name}$")))
    emu.addLayer(agents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tinode", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "output")
    args = parser.parse_args()
    sys.path.insert(0, str(WORLD))
    from E30Topology import build
    build(args.tinode.resolve(), args.output.resolve(), resident_layer=residents, runtime=RUNTIME, asn=ASN)


if __name__ == "__main__":
    main()
