# E34 挂心触发反思与情绪向量

E34 在已经启动的 E30 拓扑中运行两项配对试验。每个居民收到一次启动公告，随后可以观察世界事件、使用授权工具、自行设提醒或选择等待。实验者不回答居民的请求，也不代设提醒。正式版发布属于世界状态变化，经 SHA-256 验证后才送达一次状态更新。

- **挂心触发反思**。两组有相同人格、旧经历、未采纳的挂心和已处理到末尾的经历游标，都启用新经历触发的反思。实验组额外启用 20 秒的挂心回顾。记录发布前是否触发了真实模型反思，以及后来是否实际读取草稿、下载正式版、主动设提醒、醒来或保存核对结果。
- **情绪向量**。两组使用相同人格、经历、挂心和预置情绪状态，实验组可以感知随时间回落的向量并评估新事件。观察世界事件后的下载耗时、自设提醒醒来次数和实际保存结果。成功的事件评估用于确认事件能否改变情绪。两组均关闭自动反思。

每项试验各有三对，覆盖三个场景。小样本用于检查机制和记录行为差异。正式下载要求工具结果同时匹配正式内容的 SHA-256 和核对标记，核对保存还要求成功写入包含两个正确字段的记忆。

自由开局可观察居民是否先采纳挂心再自行安排活动。加入 `--quiet-start` 时，唯一的启动公告说明发布前为闭馆等候阶段，并提示先结束这一轮，让两组都保留尚未采纳的挂心。正式版发布时的世界事件和可用工具相同。--appraisal-smoke 单独验证真实模型能成功调用情绪评估工具，启动公告包含一次明确的工具验收要求，该运行的数据单独保留。

## 运行

按照 E30 文档启动拓扑，准备 E32 实验使用的 Cloud 所有者凭据与模型环境变量。运行结果保存在本实验的 `.runtime` 目录。每对在结束后清理隔离的账号、目录和会话。

    cd agent-plugins/soul
    pnpm install --frozen-lockfile
    pnpm test
    cd ../..
    python3 experiments/E34_soul_affect/run.py review local --port 14850
    python3 experiments/E34_soul_affect/run.py review quiet --quiet-start --port 14870
    python3 experiments/E34_soul_affect/run.py emotion local --port 14890
    python3 experiments/E34_soul_affect/run.py emotion appraisal --appraisal-smoke --port 14910

[环境与拓扑准备](../E30_dsh_soul/README_zh.md) · [实验运行环境](../E32_soul_followthrough/README_zh.md)
