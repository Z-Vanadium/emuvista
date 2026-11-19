# E36a 挂心回顾与对外履约

E36a 用 DshAgentService 安装居民并组合插件，用运行时 Python API 控制每个实验会话加载的 Bundle。实验沿用 E36 的配对分组、唯一启动公告、正式版发布窗口及计分规则。只有从正式版读到正确字段、并在截止前通过 Tinode 发给指定同伴，才算完成履约。 [E36 实验协议](../E36_soul_review_delivery/README_zh.md)

需要 amd64 Linux、Docker Engine、Compose v2、Python 3.11+，以及可访问的镜像、软件包仓库和模型服务。从本目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e 'git+https://github.com/Z-Vanadium/seed-emulator.git@7c42ab9c5f475a9faced749768efe50bc407cc2a#egg=seedemu'
docker build --platform linux/amd64 -f ../../docker_images/deepseek-harness/Dockerfile.dsh-runtime -t seedemu-dsh-runtime:0.2.0-rc.2 ../../docker_images/deepseek-harness
mkdir -p .runtime/packages
curl -fL -o .runtime/packages/tinode-mysql.linux-amd64.tar.gz https://github.com/tinode/chat/releases/download/v0.25.3/tinode-mysql.linux-amd64.tar.gz
python topology.py --tinode .runtime/packages/tinode-mysql.linux-amd64.tar.gz
cd output
docker compose -p emuvista-e36a build 072d7840db6a44d06e5c5fd4d7ea8a7d ad739b7b201eccafa592110d2bf214a7
docker compose -p emuvista-e36a build
docker compose -p emuvista-e36a up -d
docker compose -p emuvista-e36a ps
cd ..
```

等待 Cloud 和 Chat 健康，并确认 Bob 的 Profile 初始化完成。实验脚本为两组分别启动隔离的 DSH Web 进程，自动通过运行时 API 停用各自的 Claw Bundle，然后再创建实验会话。Schedule 和发布观察器保持启用。

```bash
docker compose -p emuvista-e36a -f output/docker-compose.yml exec hnode_156_bob test -f /var/lib/dshagent/bob/profiles/dshagent/cordis.patch.yml
```

通过环境提供 E32_ALICE_PASSWORD（Cloud Alice 密码）以及 E36_CHAT_ALICE_PASSWORD、E36_CHAT_BOB_PASSWORD（Chat 实验账户密码）。按 E36 的同一模型配置提供 E32_MODEL_BASE_URL、E32_MODEL_API_KEY、E32_MODEL_ID 和 E32_MODEL_NO_PROXY，或通过 E32_MODEL_CREDENTIAL_CONTAINER 选择已有的 DSH 模型凭据来源。省略这两项模型来源时，脚本读取 E36a Bob 的 DSH_HOME 中已配置的模型凭据。默认模型是 deepseek-flash，发布及对照设置与 E36 一致。

先运行一个配对检查部署和计分链路，再按需要采集独立样本：

```bash
python run.py smoke --pairs 1 --jobs 1 --port 15200 --settle-early
python run.py pilot --port 15210
python run.py formal --pairs 48 --index 12 --port 16100 --jobs 2 --settle-early
```

正式样本量应按预试验结果确定。输出保存在 .runtime，每个组的证据包含实际 Bundle 变更、会话轨迹和 Tinode 收件记录。实验结束后可用 Compose down 关闭该项目。保留 .runtime 可复用居民 Profile 和实验产物。
