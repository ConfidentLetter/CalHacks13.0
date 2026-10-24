# HANDOFF — 给接手的 AI（GPT / Claude / 人）

> 最后更新：2026-10-24 13:55 PT（Cal Hacks 13.0 现场，H+8）。由 Henry 的 Claude Code integrator 会话维护。
> 读完这份文件 + `prompts/RUNSHEET.md` + `head -5 NOTES_T*.md`，你就能接着当 integrator。

## 项目一句话
Synapse Vision：相机俯拍学生手写数学推导 → 每行逐字 LaTeX「page twin」（错误原样保留、绝不纠正；划掉的行标出；置信度诚实）→ HTTP/WebSocket 交给 Tutor 队。详见 `README.md`、`contracts/`。

## 运行方式
- 六个 Claude Code 终端并行（T6 UI 在 H+9 加入，团队已同意改前端），各写各的文件夹：T4 `app/ eval/`、T1 `capture/ hardware/`、T2 `layout/`、T3 `transcribe/`、**T5 `bridge/ docs/CONNECTIONS.md`（H+6 新增：对接队友前端）**。首条消息在 `launch_T*.txt`，顺序 T4→T1→T2→T3→T5。
- 队友 Micha 的前端/扩展在仓库根 `../frontend/`、`../extension/`，契约在 `../docs/BACKEND_INTEGRATION.md` + `BACKEND_CONTRACT.md`（PR #1 已合入 main）。前端只认 `http://localhost:8000/api/*`，T5 的 `bridge.server:app` 导入并扩展 T4 的 app 后接管 8000 端口。
- 只有 Henry（或接手的 integrator）跑 git；AI 终端禁止 git（`.claude/settings.json` 已 deny）。
- 环境：`source .venv/bin/activate && source env.sh`（env.sh 不入库，从 shell 取 ANTHROPIC_API_KEY）。
- integrator 循环（每 30–60 分钟）：`head -5 NOTES_T*.md` → `grep -A8 "For other terminals" NOTES_T*.md` → 写 `relay/H+N_to_T*.txt` 让 Henry 贴到对应窗口 → `pytest -q` → `git add -A && git commit && git push`。
- 只有 integrator 改 `contracts/`、`config/vision.yaml`、`main.py`；每次改动写进 `contracts/CHANGELOG.md`。

## 当前状态（H+8）
| 终端 | 进度 | 下一步 |
|---|---|---|
| T4 | 全完成；eval 9 行，合成页干净跑 10.7 s（预算 15） | 等真实照片 → prelabel → /label → run_eval |
| T6 | H+9 新增（prompts/T6_ui.md）：在 `../frontend/` 内把笔记本页围绕识别结果重设计（页面图 + 行框 + 逐行 LaTeX + 置信度 + 行检查器），保留 Micha 文具风；只写 frontend/src、docs/UI_DESIGN.md、NOTES_T6.md | Step 1 设计说明 → 识别视图 → 全站打磨 → 端到端验证 |
| T5 | Steps 1–3 完成：`docs/CONNECTIONS.md`（模块分析 + 13 端点映射 + 19 个缺口），`bridge/` 实现前端全部 `/api/*`（含本地 faster-whisper 语音）。**13:50 起 bridge 接管 :8000**（`uvicorn bridge.server:app --host 0.0.0.0 --port 8000`，日志 runtime/server.log） | 装 Chrome 扩展验证阅读记录；维护 CONNECTIONS.md |
| T3 | 全完成；H+7 查出延迟根因（每次调用都重发 8 张示例图，改为文本示例后 3 s/次） | 等真实照片 |
| T1 | Steps 1–4 全完成（检测/去畸变/质量门/tiling，合成 100/100） | Step 5 在真实照片上调参 |
| T2 | Steps 1–4 全完成（行分割 + 划掉检测，合成 49/52 命中、0 误报） | Step 6 真实页调参 |

全量 `pytest -q`：275 通过，3 失败（T2 正在做的透印测试，进行中）（T4 有 1 个写死预算值的测试需改成读 config）。

## 已做的整合者决策
- `budget_ms` 提到首次 15 s / 增量 8 s（Sonnet 5.5 单次往返 4–9 s，旧值不可达）。
- `transcribe.*` 加入 T3 的可调项（effort/thinking/empty_ink_density/page_pass_skip_below/sdk_max_retries）。
- H+3：`capture.webcam_index` 0→2，`page.blur_threshold` 80→1500（按 T1 实测）。
- `eval/runs/` git-ignore。模型保持 `claude-sonnet-5-5`；演示嫌慢再试 haiku。

## 已知问题 / 待传话（见 relay/H+2_*.txt）
- T1：平页问题已修（method=flat，局部眩光）。合成演示页端到端：行召回 100 %、划掉 100 %、故意错误保留 100 %、逐行精确 75 %（题目行被 page pass 多加了一个撇号，已传话给 T3）。/upload 17 s 超 15 s 预算，T3 在查。
- T2：叠式分数切行问题已做分数融合；划掉检测 H+4 已完成（status_hint 现在会给 crossed_out）。
- T4：已修；服务器已切真实模式 http://10.0.6.238:8000（无真实 twin 前 /twin/latest 返回带 _fallback 的 mock）。

## 还没做的（硬件/人工，瓶颈）
- 相机支架 35–45 cm 垂直俯拍，深色桌垫，台灯前侧斜照，纸压平（`hardware/README.md`）。
- 15–20 页手写测试页（每页至少一个故意错误；含划掉行、分数多、铅笔、眩光各一页）→ `eval/testset/<n>.jpg`；10 张普通页 → `eval/calibration/`。
- 演示页：`f(x)=x^2 sin x` / `f'(x)=2x·cos x`（故意错）/ 划掉一行 / 下一行。练到每次写一样。
- 把 `app/API.md` + mock 地址发给 Tutor 队（会场 IP 会变）。

## 旧版
`../benchmate/` 是被否决的第一版（面包板接线检查），保留未删，与本项目无关。
