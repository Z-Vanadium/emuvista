#!/usr/bin/env python3
"""SEED topology for the E30 DSH Soul experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from seedemu.core import Action, Binding, Emulator, Filter
from seedemu.layers import Base, Routing
from seedemu.services import CAService, DomainNameService, RootCAStore
from services.ChatService import ChatService
from services.ChatService.ChatServer import DEFAULT_API_KEY
from services.CloudDriveService import CloudDriveService

ASN = 155
PREFIX = "10.155.0."
ZONE = "e30.seedvista.test"
RUNTIME = HERE / ".runtime"
DSH_IMAGE = "seedemu-dsh-runtime:0.2.0-rc.2"
TINODE_SHA256 = "77fe75a4d7bd50afbfc7d8616f9f684b4f09c8302bb27bf41eb0486351de5ee1"
PLUGIN_DIR = "/opt/emuvista/agent-plugins"
BUNDLES = HERE / "bundles"
PLUGIN_PACKAGES = ("cloud-client", "claw", "chat-client", "dsh-soul")
BUNDLE_PACKAGES = ("cloud-bundle", "claw-bundle")


def chat_seed_data(archive: Path, residents: dict) -> str:
    if not archive.is_file():
        raise SystemExit(f"Missing Tinode archive: {archive}. See README.md.")
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != TINODE_SHA256:
            raise SystemExit("Tinode archive does not match the pinned v0.25.3 SHA-256.")
    with tarfile.open(archive, "r:gz") as source:
        stream = source.extractfile("./data.json")
        if stream is None:
            raise SystemExit("Tinode archive is missing data.json.")
        data = json.load(stream)
    # Keep only the experiment residents. Exclude Tinode demo conversations and
    # imported contacts so that chat observations start with E30 activity.
    users = []
    for user in data["users"]:
        if user["username"] in residents:
            user.pop("addressBook", None)
            user.pop("status", None)
            users.append(user)
    if {user["username"] for user in users} != set(residents):
        raise SystemExit("The pinned Tinode archive is missing a resident account.")
    return json.dumps({"users": users})


def profile_patch(resident: str, card: dict) -> str:
    cloud_bundle = BUNDLES / "cloud-bundle/cordis.patch.yml"
    preset = yaml.safe_load(cloud_bundle.read_text())[0]["insert"][0]
    config = preset["config"]
    config["plugins"][0]["config"]["includeRuntimeContext"] = True
    config["plugins"].append({
        "id": "emuvista-chat",
        "name": "@emuvista/chat-client",
        "config": {
            "endpoint": f"ws://chat.{ZONE}:6060",
            "apiKey": DEFAULT_API_KEY,
            "username": resident,
        },
    })
    return yaml.safe_dump([
        {"id": "agent-preset-registry", "config": {
            "default": config["id"], "selectedDefault": config["id"],
        }},
        {"id": preset["id"], "config": config},
        {"id": "emuvista-soul", "disabled": False, "config": {
            "residentId": resident, "card": card,
        }},
    ], sort_keys=False, allow_unicode=True)


def initialize(node, role: str) -> None:
    destination = f"/opt/emuvista/initialize-{role}.sh"
    node.importFile(str(HERE / f"initialize-{role}.sh"), destination)
    node.appendStartCommand("mkdir -p /run/emuvista && rm -f /run/emuvista/e30-ready")
    node.appendStartCommand(
        f"bash {destination} >/var/log/e30-initialize.log 2>&1 "
        "&& awk '{print $22}' /proc/1/stat >/run/emuvista/e30-ready "
        "|| { cat /var/log/e30-initialize.log >&2; false; }",
        isPostConfigCommand=True,
    )
    node.addDockerCommand(
        "HEALTHCHECK --interval=3s --timeout=3s --start-period=300s --retries=3 "
        "CMD test \"$(cat /run/emuvista/e30-ready 2>/dev/null)\" = \"$(awk '{print $22}' /proc/1/stat)\""
    )


def install_resident(node, resident: str, card: dict) -> None:
    node.addSoftware("curl ca-certificates netcat-openbsd")
    node.addDockerCommand(f"COPY --from={DSH_IMAGE} /usr/local/ /usr/local/")
    for package in (*PLUGIN_PACKAGES, *BUNDLE_PACKAGES):
        source_name = "soul" if package == "dsh-soul" else package
        source_root = BUNDLES if package in BUNDLE_PACKAGES else ROOT / "agent-plugins"
        src = source_root / source_name
        for path in [src / name for name in ("package.json", "pnpm-lock.yaml", "tsconfig.json", "cordis.patch.yml")] + sorted((src / "src").glob("*.ts")):
            if path.is_file() and not (package == "dsh-soul" and path.name == "package.json"):
                node.importFile(str(path), f"{PLUGIN_DIR}/{package}/{path.relative_to(src)}")
        directory = f"{PLUGIN_DIR}/{package}"
        if package == "dsh-soul":
            # E30 supplies the bundle metadata at packaging time. Keep the link
            # target stable for existing E30 profiles.
            manifest = json.loads((src / "package.json").read_text())
            manifest["dsh"] = {"bundle": {"patch": "./cordis.patch.yml"}}
            node.setFile(f"{directory}/package.json", json.dumps(manifest, indent=2) + "\n")
            node.importFile(str(BUNDLES / "soul.patch.yml"), f"{directory}/cordis.patch.yml")
        node.addBuildCommandAtEnd(f"cd {directory} && pnpm install --frozen-lockfile --ignore-workspace")
        if package in PLUGIN_PACKAGES:
            node.addBuildCommandAtEnd(f"cd {directory} && pnpm run build")
    home = RUNTIME / "residents" / resident
    home.mkdir(parents=True, exist_ok=True)
    node.addSharedFolder("/root/.dsh", str(home))
    node.setFile("/opt/emuvista/e30.patch.yml", profile_patch(resident, card))
    initialize(node, "agent")


def build(archive: Path, output: Path, *, resident_layer=None, runtime=RUNTIME, asn=ASN) -> None:
    prefix = f"10.{asn}.0."
    residents = json.loads((HERE / "residents.json").read_text())
    chat_data = chat_seed_data(archive, residents)
    temp = runtime / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(temp)
    tempfile.tempdir = str(temp)
    emulator = Emulator()
    base, routing = Base(), Routing()
    asys = base.createAutonomousSystem(asn)
    asys.createNetwork("net0")
    asys.setNameServers([prefix + "53"])
    router = asys.createRouter("router0").joinNetwork("net0", address=prefix + "254")
    addresses = {"cloud": 10, "chat": 11, "alice": 20, "bob": 30, "carol": 40, "dns": 53, "ca": 60}
    nodes = {name: asys.createHost(name).joinNetwork("net0", address=prefix + str(address))
             for name, address in addresses.items()}
    for node in (router, *nodes.values()):
        node.appendStartCommand(f"ip route replace default via {prefix}1 dev net0", isPostConfigCommand=True)
    if resident_layer is None:
        for resident, card in residents.items():
            install_resident(nodes[resident], resident, card)
    else:
        resident_layer(emulator, nodes, residents, asn)

    dns = DomainNameService()
    dns.install("e30-dns").addZone(ZONE + ".")
    for host, vnode in (("cloud", "e30-drive"), ("chat", "e30-chat"), ("ca", "e30-ca")):
        dns.getZone(ZONE + ".").resolveToVnode(host, vnode)
    ca = CAService()
    ca_server = ca.install("e30-ca")
    ca_server.setCAStore(RootCAStore(caDomain=f"ca.{ZONE}")).setCertDuration("2160h").installCACert()
    cloud = CloudDriveService(saveState=True, savePath=str(runtime / "cloud"))
    cloud.createDatabase("e30-db").setDatabasePassword("e30-lab-postgres-password")
    cloud.createObjectStorage("e30-objects").setCredentials("S3RVER", "S3RVER")
    drive = cloud.createDrive("e30-drive")
    drive.setDatabase("e30-db").setObjectStorage("e30-objects")
    drive.setAdminCredentials("admin", "e30-lab-admin-password")
    drive.setServerNames([f"cloud.{ZONE}"]).setCAServer(ca_server).enableHTTPS()
    initialize(nodes["cloud"], "cloud")
    chat = ChatService(tinode_pkg=str(archive))
    chat.setDbPassword("e30-lab-tinode-password")
    chat.installServer("e30-chat")
    nodes["chat"].addSoftware("curl")
    nodes["chat"].setFile("/opt/emuvista/tinode-data.json", chat_data)
    nodes["chat"].addDockerCommand(
        "HEALTHCHECK --interval=3s --timeout=3s --start-period=120s --retries=3 "
        "CMD curl --noproxy '*' -fsS http://127.0.0.1:6060/ >/dev/null"
    )
    for vnode, host in (("e30-dns", "dns"), ("e30-ca", "ca"), ("e30-drive", "cloud"), ("e30-chat", "chat")):
        emulator.addBinding(Binding(vnode, action=Action.FIRST, filter=Filter(asn=asn, nodeName=f"^{host}$")))
    for layer in (base, routing, dns, ca, chat, cloud):
        emulator.addLayer(layer)
    emulator.render()
    # ChatService extracts the release before this override is appended.
    nodes["chat"].addBuildCommandAtEnd("cp /opt/emuvista/tinode-data.json /root/data.json")
    nodes["dns"].setFile("/etc/bind/named.conf.options", """options {
    directory "/var/cache/bind";
    recursion yes;
    allow-query { 127.0.0.0/8; 10.ASN.0.0/24; };
    allow-recursion { 127.0.0.0/8; 10.ASN.0.0/24; };
    dnssec-validation no;
    empty-zones-enable no;
    forward only;
    forwarders { 127.0.0.11; };
};
""".replace("ASN", str(asn)))
    for (_, kind, _), node in emulator.getRegistry().getAll().items():
        if kind in {"rs", "rnode", "hnode", "csnode"}:
            commands = node.getBuildCommands()
            commands[:] = [command for command in commands
                           if "github.com/smallstep/cli/releases/download/" not in command]
            node.addDockerCommand("COPY --from=smallstep/step-cli:0.26.1 /usr/local/bin/step /usr/local/bin/step")
    emulator.compile(Docker(platform=Platform.AMD64, internetMapEnabled=False), str(output), override=True)
    print(f"E30 topology compiled to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tinode", type=Path, default=RUNTIME / "packages/tinode-mysql.linux-amd64.tar.gz")
    parser.add_argument("--output", type=Path, default=HERE / "output")
    args = parser.parse_args()
    build(args.tinode.resolve(), args.output.resolve())
