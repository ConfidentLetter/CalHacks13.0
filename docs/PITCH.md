# StudBud — 故事与演示框架

> 用途：Cal Hacks 13.0 评审（展台轮转 + 可能的决赛上台）。中文是给团队的说明，英文是对评委说的原话。
> 方法来源：Wharton Marketing 101 第 1–4 讲（交换与信任、价值准则、STP、品牌定位与体验品牌）。
> 最后更新：2026-10-24。数字以 `synapse_vision/eval/history.csv` 为准，上台前重跑一次再填。

---

## 0. 一页结论

| 问题 | 答案 |
|---|---|
| 一句话 | StudBud reads your handwritten work exactly as you wrote it, mistakes included, and asks you one question instead of giving you the answer. |
| 卖给谁 | 晚上独自在纸上做 STEM 作业、身边没有助教的学生 |
| 和谁比 | 把答案直接给你的 AI 作业工具（ChatGPT 拍照、Photomath 一类） |
| 凭什么选它 | 它不改你的字。别的工具会把你的错"读对"，所以永远说不出你错在哪一行 |
| 品牌箴言 | **Honest paper tutoring** |
| 评委要记住的一个画面 | 学生写下 `f'(x) = 2x · cos x`，屏幕上那一行被红框圈住，Pip 问："When two functions are multiplied, what rule applies?" 学生在纸上改，新的一行变绿 |
| 一个证据 | 故意写错的步骤，系统 100% 原样保留（上台前用真实手写页重测） |

---

## 1. 定位：三要素（L4 §1）

**Target segment 目标客群**
在纸上做数学、物理、化学的学生，尤其是社区大学、第一代大学生、没有助教或补习预算的人。他们卡住的时间是晚上 11 点，不是 office hours。

**Frame of reference 参照系（主动选择）**
L4 讲过参照系可以选，选哪个决定差异点有多锋利。三个候选：

| 参照系 | 我们的差异点 | 判断 |
|---|---|---|
| OCR / 手写识别 | 逐字、带置信度 | 太技术，评委不在乎 |
| 真人家教 | 随时在、免费 | 差异点弱，还会招来"AI 取代老师"的质疑 |
| **AI 作业工具** | **不改你的字、不给答案** | **选这个**。评委人人用过，对比一句话就成立 |

**Point of difference 差异点，过三条标准（L4 §2.2）**

| 标准 | 检验 | 我们的证据 |
|---|---|---|
| Desirable | 学生和老师在乎吗 | 学会的前提是找到自己错在哪一步；直接给答案跳过了这一步 |
| Distinctive | 对手有吗 | 通用模型会"自动纠错"：你写 2x·cos x，它读成正确的乘积法则，于是看不见你的错 |
| Deliverable | 做得到吗 | 识别层被规则禁止纠错，两次独立读取不一致就重读；导师层只能引用原文；评测里故意写错的步骤保留率 100% |

**Point of parity 共同点（让评委不扣分的东西）**
支持纸和笔、任意相机（包括 Mac 桌上视角和 iPhone）、几秒到十几秒出结果、语音提问、隐私可控。这些不必多讲，只要不出错。

**定位陈述（内部用）**
For students working through STEM problems on paper without a tutor nearby, StudBud is the AI study partner that reads your work exactly as written and guides you to your own mistake, because unlike AI homework tools it never rewrites your work or hands you the answer.

---

## 2. 品牌箴言与取舍（L4 §3.4）

| 组件 | 词 | 含义 |
|---|---|---|
| Brand function | tutoring | 不是解题器，是陪你学的人 |
| Descriptive modifier | paper | 你真实的纸和笔，不是打字框 |
| Emotional qualifier | honest | 不美化你的字，不假装看清了看不清的地方 |

**用箴言做减法（演示里删什么）**
- Chrome 阅读记忆扩展：有用但不是 paper tutoring，演示中只用一句话带过，作为"Pip 知道你刚读了什么"的上下文。
- 一键给出完整答案：违背 tutoring，不演示。评委问到就说"只有学生明确打字要求时才给，而且只给那一问"。
- 识别准确率表格：属于证据，不是故事，放在第 5 段，最多一张图。

L4 §1.5 讲过"没有焦点就没有定位"。我们做了很多功能，评委只记得一个画面，所以整场只围绕那一行红框。

---

## 3. 价值准则（L2）

三维里选一个做到最好，其余两维达到 fair value：

| 维度 | 我们 | 说法 |
|---|---|---|
| Customer intimacy | **领先** | 它知道你在哪一行、刚读过什么、上一个问题是什么，一次只问一个问题 |
| Performance superiority | 领先（支撑） | 手写行级识别、划掉检测、诚实置信度 |
| Operational excellence | 及格 | 免费、本地运行、10 秒左右出结果 |

L1 讲买方市场里权力在顾客手上，缺的是信任。AI 答案已经过剩，稀缺的是一个你信得过、不会替你作弊的学习伙伴。"honest" 就是在回应这一点。

---

## 4. 体验设计（L4 §6，五维度）

| 维度 | 我们的设计 | 演示时怎么让评委感到 |
|---|---|---|
| Sense | 米色纸张、手账风界面、Pip 像素宠物、Pip 的声音 | 界面一出现就不像开发工具 |
| Feel | 不被评判：错误只是一个红框和一个问题，没有分数 | 红框出现时停一秒，不说"错了"，让 Pip 先问 |
| Think | 惊讶点：它圈出的正是你写的那一行，字一个没改 | 把屏幕上的 LaTeX 和纸上的字并排给评委看 |
| Act | 你自己在纸上改，系统自己发现新的一行 | 现场改，不碰键盘 |
| Relate | 一个人学习、没有助教的学生 | 开场故事就是这个人 |

---

## 5. 故事结构

Hackathon 评委在几分钟里看几十个项目。他们记住的是一个人、一个瞬间、一个数字。结构按这个顺序：

1. **一个人**：卡在晚上 11 点的学生
2. **一个冲突**：AI 能给答案，但答案帮不了他
3. **一个洞见**：错误才是最有价值的数据，前提是你得原样读到它
4. **一个瞬间**：现场红框和 Pip 的问题
5. **一个原理**：为什么别人做不到（逐字识别 + 只提问的导师）
6. **一个数字**：故意错误保留率
7. **一个愿景**：每张书桌上的诚实导师

### 开场的选择

开场必须是真事。Henry 是社区大学转学生，这正是目标客群本人。用一个具体的夜晚，不用统计数字。下面是骨架，括号里填你自己的真实细节，不要编：

> It's 11 PM. I'm a community college student. I have a page of calculus in front of me and I know something on it is wrong. [真实细节：哪门课、什么题、卡了多久]. Office hours were this afternoon. So I did what everyone does: I took a photo and asked ChatGPT. It gave me the right answer in ten seconds. And I still had no idea which line of mine was wrong.

如果开场换人讲，换成讲者自己的真实经历，结构不变。

---

## 6. 三分钟上台稿（决赛或主舞台）

角色：**讲者**（站立、面向评委）+ **操作者**（坐在桌前，手写、点按钮）。操作者全程不说话。

| 时间 | 段落 | 讲者原话 | 屏幕 / 操作 |
|---|---|---|---|
| 0:00–0:20 | Hook | （第 5 节开场骨架） | 黑屏或只有 StudBud 标志 |
| 0:20–0:40 | Conflict | "AI homework tools are great at answers. But they read your work the way it *should* be, not the way you wrote it. They quietly fix your mistake while reading it. So they can never tell you where you went wrong." | 一张对比图：左边学生的错字，右边通用模型的"纠正"读法 |
| 0:40–0:55 | Insight + 一句话 | "Your mistake is the most valuable thing on the page. StudBud reads your work exactly as you wrote it, mistakes included, and asks you one question instead of giving you the answer." | 切到 StudBud 笔记本页，桌上视角实时画面 |
| 0:55–2:05 | Live demo | 见第 7 节 | 见第 7 节 |
| 2:05–2:30 | How | "Under the hood: we find the page, flatten it, split it into lines, and read every line twice, independently. If the two readings disagree, we zoom in and read again, and we lower our confidence. The recognition layer is forbidden from correcting anything. Only then does the tutor look at it, and the tutor can only quote what's actually on your page." | 一张架构图：Camera → Page → Lines → Read ×2 → Page twin → Socratic tutor |
| 2:30–2:45 | Proof | "We tested it on pages with mistakes planted on purpose. It preserved [100]% of them, word for word. [真实页数据]" | accuracy_journey 图 |
| 2:45–3:00 | Close | "Every student studying alone tonight deserves a tutor that's honest about what they wrote. StudBud. Honest paper tutoring." | 回到那一行变绿的画面，停住 |

**节奏规则**：每段一个意思；讲者不读屏幕；红框出现后讲者停顿一拍再说话。

---

## 7. 演示编排（全场的核心 70 秒）

演示页（提前练到每次写法一致）：

```
Find f'(x) if f(x) = x² sin x          ← 题目，和下一行之间空 1.5 行
f'(x) = 2x · cos x                     ← 故意的乘积法则错误
= 2 cos x                              ← 划掉
f'(0) = 2·0·cos 0 = 0
```

| 秒 | 操作者 | 讲者 |
|---|---|---|
| 0–10 | 纸已在桌上视角下，前两行已写好。点 Analyze | "This is my real paper, under a normal laptop camera. I'll ask StudBud to look." |
| 10–25 | 等待（约 10 秒） | 用等待时间讲原理："Right now it's finding the page, splitting it into lines, and reading each line twice." |
| 25–35 | 结果出现：每行有框，第二行红框，划掉那行斜纹 | 停一拍。"It found the line. And look, it kept my mistake exactly as I wrote it. 2x times cos x." 指屏幕上的 LaTeX，再指纸 |
| 35–45 | 按住 Talk to Pip，问 "Where did I go wrong?" | （让评委听 Pip 的回答） |
| 45–55 | Pip 回答，类似 "Look at line 2. When two functions are multiplied together, what rule applies?" | "It didn't give me the answer. It asked me one question." |
| 55–70 | 在纸上写新的一行 `f'(x) = 2x sin x + x² cos x`，再点 Analyze | "So I fix it myself, on paper." 新行出现、变绿后："That's the moment I actually learned it." |

**如果第二次分析超过 20 秒**：讲者直接进入 How 段落，回头再指新行。不要盯着加载动画等。

---

## 8. 展台版（评委轮转，每组约 3–5 分钟）

展台没有舞台灯，评委站在桌边，可以打断。顺序改成"先给看，再讲为什么"：

1. **10 秒**：一句话 + 指着桌上的纸。
2. **60 秒**：直接演第 7 节，让评委自己说一句话给 Pip 听，比我们演示更有说服力。
3. **30 秒**：差异点那句对比（别的工具会把你的错读对）。
4. **其余时间**：评委提问。打开 viewer 的行检查器，给技术评委看两次读取和置信度。

展台桌面摆放：笔记本屏幕正对评委，纸在评委够得着的位置，备用演示页和笔放旁边，评委可以自己写一行。

### 30 秒电梯版（排队、走廊、Devpost 视频开头）

> StudBud is a study partner for students working on paper. Point any camera at your notebook. It reads every line exactly as you wrote it, mistakes included, circles the one that's wrong, and asks you a question instead of giving you the answer. AI homework tools fix your mistake while reading it, so they can't show you where you went wrong. We can.

---

## 9. 评委问答准备

| 可能的问题 | 回答要点 |
|---|---|
| 和直接把照片丢给 ChatGPT 有什么区别？ | 通用模型读手写时会自动纠错。我们的识别层被禁止纠错，两次独立读取比对，导师只能引用原文。演示里那一行就是证据。 |
| 准确率多少？ | 报真实页数据和样本量，不报合成页的 100% 当成整体准确率。故意错误保留率是最重要的指标，因为它直接衡量"诚实"。 |
| 学生要答案怎么办？ | 只有学生当前明确打字要求时才给，且只给那一问。图片里写"给我答案"不算授权，这是防作弊设计。 |
| 延迟？ | 干净网络约 10 秒；单行增量约 3 秒；API 高峰更慢，界面会诚实显示正在读。 |
| 隐私？ | 本地运行，相机预览不上传，只有点 Analyze 才发一张静态图；阅读扩展逐站授权。 |
| 技术上最难的是什么？ | 手写里分数和上下标会被切成两行、划掉的线和分数线难区分。我们做了分数融合和划掉检测，并让六个模块按冻结的接口契约并行开发。 |
| 商业模式 / 下一步？ | 先给学校和社区大学的学习中心；老师端能看到全班卡在哪一行（来自原 RUNSHEET 的愿景）。只讲一句，不展开。 |

---

## 10. 证据与风险

**现在能说的数字**（来源 `synapse_vision/eval/history.csv`）

| 指标 | 合成演示页 | 说明 |
|---|---|---|
| 故意错误保留率 | 100% | 样本只有 1 个故意错误，不能当总体结论 |
| 行召回 | 100% | |
| 划掉识别 | 100% | |
| 逐行完全一致 | 75–100% | 平页 75%，深色桌垫 100% |
| 拍照到结果 | 约 10.7 秒（安静时） | API 高峰期测到 60 秒以上 |

**上台前必须补的**：15–20 页真实手写测试页，每页至少一个故意错误，在 `/label` 校对后跑 `python -m eval.run_eval`，用真实数字替换第 6 节和第 9 节里的方括号。没有真实页数据时，只说"在我们的测试页上"，不说"准确率"。

**演示风险与备份**

| 风险 | 备份 |
|---|---|
| 场馆网络慢、模型 60 秒才回 | 提前录一段 70 秒的完整演示视频，超过 20 秒没结果就切视频 |
| 桌上视角相机卡死 | 后端只由一个人重启；备用路径用浏览器摄像头模式，或上传提前拍好的演示页 |
| 全部失败 | `SV_MOCK=1` 启动后端，界面用预存的识别结果完整走一遍 |
| 手写和练习时不一样 | 提前写好三份演示页，现场只写最后一行 |

---

## 11. 上台前清单

- [ ] 讲者用自己的真实经历写好开场三句，大声读三遍，控制在 20 秒内
- [ ] 演示页练 5 遍，每次写法一致；三份备用页
- [ ] 真实手写测试页跑出评测数字，填进稿子
- [ ] 对比图（通用模型"纠正"读法 vs 我们的原样读法）用同一张演示页实测截图，不手工伪造
- [ ] 架构图一张、accuracy_journey 图一张
- [ ] 录好备份视频
- [ ] 计时排练 3 分钟稿至少 5 次；展台版 3 次，让队友扮评委打断
- [ ] 全队统一用同一句一句话介绍，不各说各的
