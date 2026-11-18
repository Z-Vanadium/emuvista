# E35 担忧水平与行动时机

每对会话使用同一人格、经历、挂心、授权工具和发布日期。两组启用相同的 Soul 情绪配置，担忧基线为 15，半衰期为 180 秒。实验组的起始担忧为 75，对照组为 15，挫败和愉悦分别同为 20 和 25。两组关闭挂心定时回顾。各居民只收到一次外部启动提示，之后由资料室发布正式版和一次世界状态更新，居民自行决定何时核对。

主要结果是世界更新到第一次成功下载正式版的秒数。正式版通过文件 SHA-256 和核对标记匹配；120 秒内没有成功的会话记为 120 秒。次要结果包括有效下载率、误读草稿和实际自设提醒唤醒。差值定义为对照组耗时减去实验组耗时，正值表示担忧组更快。比较配对均值及按场景分层的置信区间。正式试验的预设判断为至少提前 5 秒、95% 置信区间排除零、三种场景估计值同向。

先跑 12 对预试验，覆盖两种人格和三个场景。预试验用于检验评分和估计波动，正式样本量按预试验的配对标准差估算，组合按六的倍数取整。正式样本独立收集。

## 运行

复用 E30 的 Cloud 和 E32 的真实模型配置。将凭据通过环境变量传入，默认每批并行四对。

    python3 experiments/E35_soul_action_timing/run.py pilot --port 15000

正式运行使用独立样本。将 `<样本量>` 替换为预试验报告中的估计值。`--settle-early` 允许在世界事件处理完成、会话静默且窗口内没有可触发的提醒时提前回收会话。未出现有效操作的会话仍按完整窗口计分。

    python3 experiments/E35_soul_action_timing/run.py formal --pairs <样本量> --index 12 --port 15700 --jobs 2 --settle-early

运行结果位于 `.runtime/`。启动前的基础设施失败按相同人格和场景补跑，并保留原运行目录。若使用正式样本补跑，`formal-final/sources.json` 记录每个配对的实际运行来源。

## 禁止人工确认后的复测

使用启用自主运行阻断的 Soul 再采集 24 对独立正式样本。其他主要条件沿用原试验，旧结果单独保留。普通复测不要求 Agent 发出确认。单独的 `--autonomy-smoke` 验收使用启动提示中的测试样例，验证自然语言阻断和内部纠正确实发生。验收样本不进入时机统计。

    python3 experiments/E35_soul_action_timing/run.py autonomy-smoke --pairs 1 --autonomy-smoke --port 16870 --jobs 1 --settle-early
    python3 experiments/E35_soul_action_timing/run.py autonomy-rerun --pairs 24 --index 12 --port 16800 --jobs 4 --settle-early
