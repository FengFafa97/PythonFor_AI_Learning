# PythonFor_AI_Learning

A small FastAPI service backed by Groq's LLM API, plus a hand-written Agent execution
loop (tool calling, permission checks, multi-turn conversation) built from scratch to
understand how an agent loop actually works under the hood.

## Architecture

```
app/
├── main.py              FastAPI layer: HTTP endpoint, request validation,
│                         maps internal error types to HTTP status codes
├── config.py             Loads .env, exposes typed config (API key, model, proxy)
└── services/
    └── llm_service.py    Talks to Groq, returns a structured LLMResult

AgentLoopExec.py           Agent execution loop: multi-turn tool calling,
                            role-based permission checks, tool registry
```

The API layer and the service layer are intentionally separate. `llm_service.py`
only knows how to call Groq and report what happened — it has no idea it is
being called from an HTTP endpoint. `main.py` is the only place that translates
an internal result into an HTTP response. Today it serves a FastAPI endpoint;
if it were called from a CLI or a scheduled job tomorrow, the service layer
would not need to change.

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Create a `.env` file in this directory:

```
GROQ_API_KEY=your_key_here
DEFAULT_MODEL=llama-3.3-70b-versatile   # optional, this is the default
```

Run the API:

```bash
uvicorn app.main:app --reload
```

`POST /chat` with `{"message": "..."}` returns `{"status": "success", "data": "..."}`
on success, or an HTTP error (429/502/503/500, see below) with a human-readable
message on failure.

## Design decision: structured error signals, not string prefixes

The first version of `llm_service.py` reported failures as plain strings —
each `except` branch returned a Chinese-language error message, and the caller
decided success or failure by checking whether the string started with `"错误:"`.

That wasn't just inelegant, it was actively wrong about half the time:

| Exception | Returned string | Caught by `startswith("错误:")`? |
|---|---|---|
| `APIConnectionError` | `"错误: ..."` | ✓ correctly flagged as failure |
| `RateLimitError` | `"错误: ..."` | ✓ correctly flagged as failure |
| `GroqError` | `"AI 服务异常: ..."` | ✗ **silently treated as success** |
| `Exception` (catch-all) | `"系统内部错误..."` | ✗ **silently treated as success** |

The last two got wrapped into `{"status": "success", ...}` and returned to the
caller — the service had crashed, but the client received a 200. The catch-all
branch, specifically added to capture *unexpected* crashes, was the one most
likely to be silently swallowed.

The root cause: four branches happened to share a string prefix by coincidence,
not by any enforced contract. Change one error message's wording and the
success/failure judgment silently breaks — nothing catches it at compile time.

**Fix**: move the success/failure signal from *string content* to a *typed field*.

```python
ErrorType = Literal["connection", "rate_limit", "api_error", "system_error"]

@dataclass
class LLMResult:
    success: bool
    content: Optional[str] = None
    error_type: Optional[ErrorType] = None
    error_message: Optional[str] = None
```

Three deliberate choices behind this shape:

1. **Not a single `is_error: bool`.** A bool can only say success/failure — it
   can't distinguish "rate limited" from "network unreachable," and the correct
   response to each is different (back off and retry vs. treat upstream as down).
2. **Not one bool per error type** (`is_rate_limit_error`, etc.). Independent
   booleans can't express mutual exclusivity — nothing stops two of them being
   `True` at once, or all four being `False`. A single field with a closed set
   of values (`Literal`) makes invalid states unrepresentable, and a typo in the
   value is caught by the type checker instead of at runtime.
3. **HTTP status mapping lives in `main.py`, not in the service.** "Which status
   code" is an HTTP concern. The service's job is to call the LLM and report
   honestly what happened — it shouldn't need to know it's being called over
   HTTP at all.

The same pattern (a small dataclass with a `success` flag and a `Literal`
error-type field, instead of a raw string or an unstructured dict) is reused in
`AgentLoopExec.py`'s `AgentRunResult`, for the same reason: the caller should
never have to guess.

## The Agent loop (`AgentLoopExec.py`)

A hand-written, from-scratch Agent execution loop — not built on LangChain or
any agent framework — covering:

- **Multi-turn tool calling** against the OpenAI/Groq function-calling protocol
  (`tool_calls` as a distinct field, `arguments` as a JSON string that must be
  parsed defensively — models don't always emit valid JSON)
- **A small tool registry** (`Tools`) that exposes function schemas to the model
  and dispatches calls by name
- **Role-based permission checks** (`PermissionManager`) — a tool call is
  checked against the current user's role before it runs, and a check failure
  fails closed (denied), not open
- Two example tools (querying and "purchasing" a movie ticket against an
  in-memory fake data source) used to exercise the registry and the permission
  tiers end to end
