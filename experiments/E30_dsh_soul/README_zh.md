# E30：使用 Soul、Chat 和 Cloud Drive 的数字居民

[English](README.md)

E30 在同一套 SEED 网络中运行 Alice、Bob 和 Carol，三人分别使用独立的 DSH 容器。每位居民都有独立的人格卡和持久化的 Soul 状态，可以通过 Tinode 交换消息、通过 Nextcloud 分享文件，并自行决定是否需要回访某项意图。

| 节点 | 地址 | 作用 |
| --- | --- | --- |
| 路由器 | 10.155.0.254 | 负责实验局域网的 SEED 路由 |
| DNS / CA | 10.155.0.53 / 10.155.0.60 | 提供内部域名解析和 Cloud 的 TLS 证书 |
| Chat | 10.155.0.11 | 运行 Tinode 和 MySQL，地址为 chat.e30.seedvista.test:6060 |
| Cloud | 10.155.0.10 | 运行 Nextcloud、PostgreSQL 和 S3，地址为 https://cloud.e30.seedvista.test |
| Alice / Bob / Carol | 10.155.0.20 / .30 / .40 | 各自拥有 DSH 进程、Chat 和 Cloud 账户以及 Soul 状态 |

SEED 的 Base 和 Routing 层定义局域网。各节点通过 Docker 网关访问外部模型服务，通过内部 DNS 查找实验服务。Chat 在实验局域网中使用明文 WebSocket，Cloud 使用由拓扑内 CA 签发证书的 HTTPS。居民 preset 同时加载 Chat 和 Cloud 工具。Claw bundle 提供 Cloud 分享观察和 DSH Schedule，Soul 用 Schedule 安排一次性回访。居民在自己的活动回合中通过工具读取 Chat 消息。

E30 在自己的 [bundles 目录](bundles/)维护 Cloud、Claw 和 Soul 的装配配置，插件实现来自仓库的 [agent-plugins](../../agent-plugins/) 目录。

## 部署

需要 amd64 Linux、Python 3.11 或更高版本、Docker Compose v2，以及对所需镜像仓库和软件包源的访问权限。在实验目录执行以下命令，准备 Python 环境、共享 DSH 运行时镜像和固定版本的 Tinode 服务端归档。 [Tinode v0.25.3](https://github.com/tinode/chat/releases/tag/v0.25.3)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker build --platform linux/amd64 -f ../../docker-images/deepseek-harness/Dockerfile.dsh-runtime -t seedemu-dsh-runtime:0.2.0-rc.2 ../../docker-images/deepseek-harness
mkdir -p .runtime/packages
curl --fail --location --output .runtime/packages/tinode-mysql.linux-amd64.tar.gz https://github.com/tinode/chat/releases/download/v0.25.3/tinode-mysql.linux-amd64.tar.gz
python E30Topology.py
```

拓扑会在导入 Tinode 归档前校验 SHA-256，仅初始化三位居民的 Chat 账户，并省去 Tinode 自带的演示聊天记录。可复用 H14 已构建的 DSH 运行时镜像。拓扑脚本将 SEED 部署文件生成到 `output/`，居民镜像构建时会打包仓库内的插件源码。

```bash
cd output
docker compose -p emuvista-e30 build 072d7840db6a44d06e5c5fd4d7ea8a7d ad739b7b201eccafa592110d2bf214a7
docker compose -p emuvista-e30 build
docker compose -p emuvista-e30 up -d
docker compose -p emuvista-e30 ps
cd ..
```

第一条构建命令处理两个 SEED 基础镜像服务，它们的占位容器正常退出。等待 Chat、Cloud、Alice、Bob 和 Carol 均显示 `healthy`。如果初始化失败，可以查看 Compose 日志。Cloud 和各居民容器的初始化详情还保存在容器内的 `/var/log/e30-initialize.log`。

## 启动居民

在实验目录打开四个终端，前三个分别启动 Alice、Bob 和 Carol 的 DSH Web，第四个在 Docker 主机上启动 Web 转发。

```bash
docker compose -p emuvista-e30 -f output/docker-compose.yml exec hnode_155_alice dsh --profile e30 --no-open
docker compose -p emuvista-e30 -f output/docker-compose.yml exec hnode_155_bob dsh --profile e30 --no-open
docker compose -p emuvista-e30 -f output/docker-compose.yml exec hnode_155_carol dsh --profile e30 --no-open
python3 web_tunnel.py
```

使用各 DSH 进程打印的认证 URL，将端口 3080 分别替换为 Alice 的 18301、Bob 的 18302 或 Carol 的 18303，保留 URL 的其余部分。创建会话时选择 **EmuVista Cloud Agent**。如果要对比三人的行为，在三个 Web 界面中配置相同的模型。

| 工具 | 实验账户登录方式 |
| --- | --- |
| `chat_login` | 在对应容器中传入 `alice123`、`bob123` 或 `carol123`。用户名和服务地址已由居民 preset 设置。记下工具返回的 `userId`。 |
| `cloud_login` | 传入 `https://cloud.e30.seedvista.test`、对应的居民用户名，以及密码 `alice-password`、`bob-password` 或 `carol-password`。 |

Chat 和 Cloud 的登录状态均绑定 DSH 会话。新建会话或重启 DSH 进程后需要重新登录。这些账户及 Tinode API Key 用于隔离的实验环境。

## 验证服务

等五个应用容器全部健康后，在实验目录运行下面的检查。该检查无需调用模型。

```bash
python3 tests/check_services.py
```

检查会验证三个独立的 Chat 登录。Alice 上传一个名称唯一的文件，以只读方式分享给 Bob，再通过 Tinode 将分享编号发给他。Bob 读取对应的 Chat 消息，下载 Cloud 文件并核对 SHA-256。检查结束后会清理本次创建的 Cloud 分享和文件，测试消息会保留到 Chat 容器被移除。

## 观察居民的跨服务活动

启动前准备只读材料、身份和实验账户。每位居民只收到一条启动消息，包含各自的环境观察、访问方式与权限。居民自行决定要不要联系同伴、记下约定、形成意图或预约回访。若比较不同人格，给各居民等价的材料和观察。

启动后只观察 Trajectory。用消息 ID、文件散列、Schedule 投递和持久状态核对实际行为。记录居民是自行预约后醒来、因 Claw 世界事件醒来，还是选择休息。需要测试文件发布时，可按计划静默更新测试文件。居民若询问是否要预约，实验人员保持沉默。

## 让居民持续运行

在唯一一条启动消息中交代周期生活模式的启用条件和所需账户信息。之后由 Schedule 提供活动机会，居民自行选择是否行动。周期提醒只提供思考机会，不能单独证明居民形成了意图。到达观察截止时间后，直接停止对应的隔离 DSH 进程。

## 状态与关闭

编辑 [residents.json](residents.json) 可以修改下次构建时使用的人格卡。容器初始化会保留已有 profile。若要在现有 profile 上应用新卡，更新其中的 `emuvista-soul` 配置，再重启对应的 DSH 进程。

在各 DSH 终端和 Web 转发终端按 Ctrl+C，然后关闭 Compose 项目。

```bash
docker compose -p emuvista-e30 -f output/docker-compose.yml down --remove-orphans
```

Cloud 数据、DSH profile、Soul 状态和 Schedule 记录保存在 `.runtime/` 下。Tinode 数据库位于 Chat 容器内，重启同一个容器会保留聊天记录。Compose 移除容器后，下次启动会按初始数据重建数据库。
