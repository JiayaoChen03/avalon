# LLM 并发测试

[2026-09-17 本地真实 API 测试报告](20260917-local/report.md)包含串行、2 路、4 路并发的完整结果与适用边界。

测试脚本：`scripts/benchmark_llm_concurrency.py`。默认只检查配置并预览测试计划；传入 `--live` 后才调用当前项目配置的真实 API。

```sh
.venv/bin/python scripts/benchmark_llm_concurrency.py
.venv/bin/python scripts/benchmark_llm_concurrency.py --live --repeats 3
```

每批重放相同的四个合法游戏快照，每模式轮换次序重复测量。任务之间复制角色及策略状态，使用生产模型传输和校验代码。它用于测量独立工作并发时的吞吐，不能代表互相依赖的实时对话表现。结果按任务完成持续写入 `requests.jsonl`，每批更新 `summary.json`；单次失败会按项目现有重试参数处理。

每次实测默认包含四个预热任务及 36 个正式任务，重试会增加 HTTP 请求数。原始记录不包含 API 密钥、原始响应、私有概率或模型内部推理。运行目录包含已通过校验的候选公开台词，其中 PASS 行动的台词并未实际发布，需检查 `speech_published_by_action`。

仅运行本地测试服务的检查：

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_llm_benchmark.py' -v
```
