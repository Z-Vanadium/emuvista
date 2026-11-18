# E30: Residents with Soul, Chat, and Cloud Drive

E30 puts Alice, Bob, and Carol in separate DSH containers on a SEED network. Each resident has a different personality card and persistent Soul state. They can exchange Tinode messages, share files through Nextcloud, and decide whether an intention warrants a later review.

| Node | Address | Role |
| --- | --- | --- |
| Router | 10.155.0.254 | SEED routing on the lab LAN |
| DNS / CA | 10.155.0.53 / 10.155.0.60 | Internal names and Cloud TLS |
| Chat | 10.155.0.11 | Tinode and MySQL, at chat.e30.seedvista.test:6060 |
| Cloud | 10.155.0.10 | Nextcloud, PostgreSQL and S3 at https://cloud.e30.seedvista.test |
| Alice / Bob / Carol | 10.155.0.20 / .30 / .40 | Separate DSH processes, Chat and Cloud accounts, and Soul stores |

SEED Base and Routing define the LAN. Hosts use the Docker gateway for external model calls and internal DNS for lab services. Chat uses plaintext WebSockets inside this lab LAN. Cloud uses HTTPS with the topology's CA. The resident preset loads both Chat and Cloud tools. The Claw bundle adds Cloud share observation and DSH Schedule, which Soul uses for one-time follow-ups. Chat is read through tools during a resident turn.

E30 owns its [bundle configuration](bundles/) for Cloud, Claw, and Soul. It uses the reusable plugin implementations in [agent-plugins](../../agent-plugins/).

## Deploy

Use Linux on amd64, Python 3.11+, Docker Compose v2, and access to the required image registries and package sources. From this experiment directory, prepare the Python environment, the shared DSH runtime, and the pinned [Tinode v0.25.3](https://github.com/tinode/chat/releases/tag/v0.25.3) server archive.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker build --platform linux/amd64 -f ../../docker-images/deepseek-harness/Dockerfile.dsh-runtime -t seedemu-dsh-runtime:0.2.0-rc.2 ../../docker-images/deepseek-harness
mkdir -p .runtime/packages
curl --fail --location --output .runtime/packages/tinode-mysql.linux-amd64.tar.gz https://github.com/tinode/chat/releases/download/v0.25.3/tinode-mysql.linux-amd64.tar.gz
python E30Topology.py
```

The topology checks the Tinode archive's SHA-256 before importing it. It seeds only the three resident accounts and omits Tinode's demo chats. The runtime image can be reused from H14. The topology compiles SEED output under output/ and packages the repository's plugin sources into the resident images.

```bash
cd output
docker compose -p emuvista-e30 build 072d7840db6a44d06e5c5fd4d7ea8a7d ad739b7b201eccafa592110d2bf214a7
docker compose -p emuvista-e30 build
docker compose -p emuvista-e30 up -d
docker compose -p emuvista-e30 ps
cd ..
```

The first two services build the SEED base images. Their containers exit normally. Wait until Chat, Cloud, Alice, Bob, and Carol report healthy. Use Compose logs to diagnose failures. Cloud and resident initialization details are also recorded in /var/log/e30-initialize.log inside the corresponding container.

## Start the residents

Run each command in its own terminal from the experiment directory. Start the host tunnel in a fourth terminal.

```bash
docker compose -p emuvista-e30 -f output/docker-compose.yml exec hnode_155_alice dsh --profile e30 --no-open
docker compose -p emuvista-e30 -f output/docker-compose.yml exec hnode_155_bob dsh --profile e30 --no-open
docker compose -p emuvista-e30 -f output/docker-compose.yml exec hnode_155_carol dsh --profile e30 --no-open
python3 web_tunnel.py
```

Open the authenticated URL printed by each DSH process, changing port 3080 to 18301 for Alice, 18302 for Bob, or 18303 for Carol. Keep the rest of each URL. Configure the same model in all three Web UIs if comparing behavior. Select **EmuVista Cloud Agent** when creating sessions.

| Tool | Lab login |
| --- | --- |
| chat_login | Supply alice123, bob123, or carol123 in the matching container. The username and server are set in that resident's preset. Record the returned userId. |
| cloud_login | Supply https://cloud.e30.seedvista.test, the matching resident name, and the password alice-password, bob-password, or carol-password. |

Chat and Cloud logins are per DSH session. Reauthenticate in a new session or after a DSH process restart. These accounts and the Tinode API key are for the isolated lab.

## Check the services

After the five application containers are healthy, run the model-free check from the experiment directory.

```bash
python3 tests/check_services.py
```

It verifies three separate Chat logins. Alice uploads and shares a unique file read-only, then sends its share ID to Bob over Tinode. Bob retrieves the exact Chat message and verifies the Cloud file's SHA-256. The check removes its Cloud share and file. The test message remains in the lab chat history until the Chat container is removed.

## Observe residents across services

Prepare the read-only materials, identities and lab accounts before startup. Send each resident one startup prompt with its observations, access details and permissions. Residents decide whether to contact peers, record an agreement, form an intention or schedule a follow-up. Use equivalent materials and observations when comparing personalities.

Inspect Trajectory after startup. Verify actions using message IDs, file hashes, Schedule deliveries and persisted state. Record whether residents wake from their own reminders, wake from Claw world events, or rest. To test publication, update the fixture silently at the planned time. Leave any request for operator confirmation unanswered.

## Run a resident continuously

Include conditions for enabling periodic life and any needed account details in the single startup prompt. Schedule deliveries give residents opportunities to choose whether to act. A recurring wake alone does not establish that a resident formed an intention. At the observation cutoff, stop the isolated DSH process directly.

## State and shutdown

Edit [residents.json](residents.json) to change the cards for the next build. Existing profiles are preserved during initialization. To apply a changed card to an existing profile, update its emuvista-soul configuration and restart that DSH process.

Stop the DSH processes and the tunnel with Ctrl+C, then stop the Compose project.

```bash
docker compose -p emuvista-e30 -f output/docker-compose.yml down --remove-orphans
```

Cloud data, DSH profiles, Soul state, and Schedule records remain under .runtime/. The Tinode database is in the Chat container and survives a container restart, but is recreated from the seed after Compose removes the container.
