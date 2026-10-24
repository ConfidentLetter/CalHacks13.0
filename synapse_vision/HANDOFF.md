# HANDOFF — 给接手的 AI（GPT / Claude / 人）

> 最后更新：2026-10-23 23:10 PT（Cal Hacks 13.0 现场，H+2 左右）。由 Henry 的 Claude Code integrator 会话维护。
> 读完这份文件 + `prompts/RUNSHEET.md` + `head -5 NOTES_T*.md`，你就能接着当 integrator。

## 项目一句话
Synapse Vision：相机俯拍学生手写数学推导 → 每行逐字 LaTeX「page twin」（错误原样保留、绝不纠正；划掉的行标出；置信度诚实）→ HTTP/WebSocket 交给 Tutor 队。详见 `README.md`、`contracts/`。

## 运行方式
- 四个 Claude Code 终端并行，各写各的文件夹：T4 `app/ eval/`、T1 `capture/ hardware/`、T2 `layout/`、T3 `transcribe/`。首条消息在 `launch_T*.txt`，顺序 T4→T1→T2→T3。
- 只有 Henry（或接手的 integrator）跑 git；AI 终端禁止 git（`.claude/settings.json` 已 deny）。
- 环境：`source .venv/bin/activate && source env.sh`（env.sh 不入库，从 shell 取 ANTHROPIC_API_KEY）。
- integrator 循环（每 30–60 分钟）：`head -5 NOTES_T*.md` → `grep -A8 "For other terminals" NOTES_T*.md` → 写 `relay/H+N_to_T*.txt` 让 Henry 贴到对应窗口 → `pytest -q` → `git add -A && git commit && git push`。
- 只有 integrator 改 `contracts/`、`config/vision.yaml`、`main.py`；每次改动写进 `contracts/CHANGELOG.md`。

## 当前状态（H+2）
| 终端 | 进度 | 下一步 |
|---|---|---|
| T4 | Steps 1–5 全完成；mock 服务器 `SV_MOCK=1` 在 :8000；viewer `/`、标注页 `/label`、`eval/run_eval.py`、`eval/accuracy_journey.png` 都有 | 等真实照片 → `python -m eval.prelabel` → Henry 在 /label 校对 → 每个 checkpoint 跑 run_eval |
| T3 | Steps 1–5 全完成；真实 `build_page_twin`（T1→T2→T3）；60 tests | 等真实照片；用真实切片替换合成示例库；调 agreement_threshold |
| T1 | Step 2 完成（源、稳定触发） | Step 3 页面检测 + 去畸变 + 质量门 |
| T2 | Step 2 完成（合成页生成器） | Step 3 经典行分割；Step 4 划掉检测 |

全量 `pytest -q`：181 通过（T4 有 1 个写死预算值的测试需改成读 config）。

## 已做的整合者决策
- `budget_ms` 提到首次 15 s / 增量 8 s（Sonnet 5.5 单次往返 4–9 s，旧值不可达）。
- `transcribe.*` 加入 T3 的可调项（effort/thinking/empty_ink_density/page_pass_skip_below/sdk_max_retries）。
- `eval/runs/` git-ignore。模型保持 `claude-sonnet-5-5`；演示嫌慢再试 haiku。

## 已知问题 / 待传话（见 relay/H+2_*.txt）
- T1：平整白纸（无深色垫）被判 `no_page`、glare 0.99 → 全页置信度封顶 0.4。必须接受已展平页面。
- T2：叠式分数被切成两行（分母单独成行）；划掉的行 status_hint 给的是 `active`，T3 只在 `unsure` 时问模型，所以演示页划掉行不会显示划掉。
- T4：latency 抽屉阈值要读 config；test_config 写死 8000。

## 还没做的（硬件/人工，瓶颈）
- 相机支架 35–45 cm 垂直俯拍，深色桌垫，台灯前侧斜照，纸压平（`hardware/README.md`）。
- 15–20 页手写测试页（每页至少一个故意错误；含划掉行、分数多、铅笔、眩光各一页）→ `eval/testset/<n>.jpg`；10 张普通页 → `eval/calibration/`。
- 演示页：`f(x)=x^2 sin x` / `f'(x)=2x·cos x`（故意错）/ 划掉一行 / 下一行。练到每次写一样。
- 把 `app/API.md` + mock 地址发给 Tutor 队（会场 IP 会变）。

## 旧版
`../benchmate/` 是被否决的第一版（面包板接线检查），保留未删，与本项目无关。
