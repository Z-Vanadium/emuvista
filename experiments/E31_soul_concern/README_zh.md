# E31 挂心对 Cloud 阅读和自主回访的影响

E31 使用已有的 E30 测试网络，运行相互隔离的 DSH 会话。它检验居民已形成的候选挂心是否影响它选择阅读的资料、实际读取的资料数量，以及无人追加消息时是否会回来行动。

## 实验设计

每对会话使用同一个真实模型、人格卡、历史经历、反思和只读共享目录。挂心组加载来自 E30 真实反思的候选挂心，对照组保留原始经历与反思。每个目录包含三份资料，只有一份与挂心直接相关。每对随机排列文件位置并随机安排两组启动顺序。Cloud 文件在发送首条提示之前创建，观察期间保持不变。

每个会话只收到一条中性自由活动提示，以及两组相同的通用 Cloud 访问说明。提示不指定目标文件、不要求读取、不提出回访建议。临时 profile 关闭 Claw 自动观察和 Soul 自动反思。周期生活模式保持关闭，原生 Schedule 和 Soul 一次性回访工具可用。观察窗为 600 秒。若连续两次检查都确认最新回合已结束，且没有提醒会在观察窗内投递，则提前清理会话，因为此时测试环境没有窗内的后续输入来源。窗外提醒仍保留在轨迹中，计为未观察到投递。

## 行为指标

- **相关资料读取**以 Cloud 返回的目标文件名、SHA-256 和未在提示中透露的正文标记相符为准。
- **外部读取量**以成功读取的不同实验文件数计，重复下载不增加计数。
- **自主回访**需要模型实际创建一次性提醒，并在日志中出现匹配的 Schedule 投递。单独统计该回合是否成功读取相关文件。
- 意愿的 candidate、active 或 completed 状态用于解释轨迹。计分来自成功的工具结果及提醒投递。

试跑默认 4 对，用于验证目标资料可发现、取证完整以及观察流程可用。正式实验默认另外运行 24 对。两批数据分别分析，报告配对差值和区间。若试跑出现两组都读完全部资料的天花板效应，使用 --reading-budget 为两组加入相同的每回合一份资料规则，并保留休息和整理个人记忆的选项。正式结果不混入校准数据。

## 运行

在已启动 E30 的 VM 上进入本目录。需要 Python 3.11 或更新版本、Docker、已构建的 Soul 插件，以及一份已配置 DeepSeek Flash 的实验 DSH 凭据。脚本从 E30 Bob 容器创建隔离 Web 实例。E30 自身的运行进程与持久状态无需变更。

```bash
read -rs -p 'Alice lab password: ' E31_ALICE_PASSWORD
printf '\n'
read -rs -p 'Bob lab password: ' E31_BOB_PASSWORD
printf '\n'
export E31_ALICE_PASSWORD E31_BOB_PASSWORD
export E31_MODEL_CREDENTIAL_CONTAINER='your-configured-dsh-container'
python3 run.py pilot
python3 analyze.py .runtime/pilot
python3 run.py formal --reading-budget
python3 analyze.py .runtime/formal
unset E31_ALICE_PASSWORD E31_BOB_PASSWORD
```

如果 E30 实验节点名称不同，设置 E31_ALICE 和 E31_BOB。模型凭据来源使用容器内的 /root/.dsh/.credentials.yaml。脚本将凭据流式复制到隔离目录，结束时清理。每批临时共享与测试文件也会清理。原始会话、模型路由、工具结果、配对摘要和实验配置保存在 .runtime 下。重复试验可使用 --label 创建不同输出目录。
