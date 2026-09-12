# 设计说明：为什么错误信号要用结构化返回

> 2026-09-08 重构记录。这一段是 README 里「工程决策」章节的素材。

## 改之前：用字符串前缀当错误信号

`get_ai_response()` 的 4 个 `except` 分支各返回一句中文提示，调用方 `main.py` 靠
`result.startswith("错误:")` 判断这次调用成没成功。

问题不是"不优雅"，是**它真的漏判了一半**：

| 异常 | 返回的字符串 | `startswith("错误:")` |
|---|---|---|
| `APIConnectionError` | `"错误: 无法连接到 AI 服务器…"` | ✓ 判为失败 |
| `RateLimitError` | `"错误: 请求过于频繁…"` | ✓ 判为失败 |
| `GroqError` | `"AI 服务异常: …"` | ✗ **被当成成功** |
| `Exception`（兜底） | `"系统内部错误，请联系管理员。"` | ✗ **被当成成功** |

后两种会被包装成 `{"status": "success", "data": "系统内部错误，请联系管理员。"}`
返回给调用方——**服务端崩溃了，客户端收到的却是 200 成功**。尤其第 4 条是
`except Exception` 兜底分支，专门接未预期的崩溃（日志里用了 `exc_info=True` 记完整堆栈），
偏偏它是唯一被伪装成成功的那个。

根因：4 个分支里有 2 个碰巧共享了同一个前缀，2 个没有，而**没有任何机制强制它们保持一致**。
以后改一句错误提示的措辞（比如产品觉得"系统内部错误"太生硬要换个说法），这个判断就会
悄悄跟着变，编译器和类型检查器都看不出来。

## 改之后：判断依据从"内容"挪到"字段"

```python
ErrorType = Literal["connection", "rate_limit", "api_error", "system_error"]

@dataclass
class LLMResult:
    success: bool
    content: Optional[str] = None
    error_type: Optional[ErrorType] = None
    error_message: Optional[str] = None
```

三个关键取舍：

**1. 为什么不是只加一个 `is_error: bool`**
布尔值只能表达"成功/失败"，分不出"被限流"和"连不上网"。而这两者调用方的正确反应完全不同：
限流该退避重试（429），网络不通是上游不可用（503）。信息量不够，调用方只能退回去猜。

**2. 为什么不是给每种错误各加一个 bool（`is_rate_limit_error` 之类）**
因为那样**无法表达互斥**。一次调用只可能踩中 4 种失败里的恰好一种，但 4 个独立布尔字段
允许"两个同时为 True"和"全部为 False"这类根本不存在的状态存在。用一个字段承载封闭取值集合，
非法状态从一开始就写不出来。`Literal` 让类型检查器在**编码阶段**就能发现拼错的取值，
而不是等运行时才炸——这正是原方案最缺的那一环。

**3. 为什么 HTTP 状态码映射放在 `main.py` 而不是 `llm_service.py`**
"该返回哪个状态码"是 HTTP 语义。service 层的职责是"调用 LLM 并如实报告结果"，
它不该知道自己被谁调用、更不该知道 HTTP 是什么。今天它服务于一个 FastAPI 接口，
明天可能被 CLI 或定时任务调用，那时 503/429 毫无意义。把映射留在 API 层，
service 层就能保持可复用。

## 保持不变的部分

4 级异常捕获（`APIConnectionError` / `RateLimitError` / `GroqError` / `Exception`）
和全部日志调用一行未动。这次只改**返回什么**，不改**捕获什么**。

`except` 的顺序也保持原样且不可调整：`APIConnectionError` 和 `RateLimitError` 都是
`GroqError` 的子类，具体异常必须排在 `GroqError` 之前，否则前两个分支会变成永远进不去的死代码。
