# 1. 标准库导入
import json
import logging
from typing import Iterable, Iterator
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.services.llm_service import LLMService, LLMResult

# 获取在 llm_service 中配置过的 logger
logger = logging.getLogger("APIRoot")

app = FastAPI(title="AI Learning API")

# 确保在启动时尝试初始化，如果有致命错误直接报错
try:
    llm_service = LLMService()
except Exception as e:
    logger.critical(f"致命错误:应用无法启动,LLM 服务初始化失败: {e}")
    # 注意：在 Uvicorn 环境下，这里的 raise 会导致进程退出，符合 Tier 1-D 审计要求
    raise

class ChatRequest(BaseModel):
    message: str

# error_type -> HTTP 状态码。放在 API 层而不是 llm_service 里，
# 因为"该返回哪个状态码"是 HTTP 语义，service 层不该知道 HTTP 是什么。
ERROR_STATUS_MAP = {
    "connection": 503,    # 服务不可用
    "rate_limit": 429,    # 请求过多，客户端该退避重试
    "api_error": 502,     # 上游 API 返回了业务错误
    "system_error": 500,  # 未预期的崩溃
}

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    logger.info(f"收到请求: {request.message[:20]}...")
    
    if not request.message.strip():
        logger.warning("收到空消息请求")
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    result = llm_service.get_ai_response(request.message)

    if not result.success:
        status_code = ERROR_STATUS_MAP.get(result.error_type, 500)
        logger.error(f"处理请求时发生逻辑错误: {result.error_message}")
        raise HTTPException(status_code=status_code, detail=result.error_message)

    return {"status": "success", "data": result.content}


def _sse_events(results: Iterable[LLMResult]) -> Iterator[str]:
    """把 LLMResult 流翻译成 SSE 文本行。

    和 ERROR_STATUS_MAP 同一个道理：`data:` 前缀和空行分隔是 SSE 的传输
    格式，属于 HTTP 语义，留在 API 层，service 层不该知道。
    """
    for result in results:
        if result.success:
            payload = {"type": "chunk", "content": result.content}
        else:
            payload = {
                "type": "error",
                "error_type": result.error_type,
                "message": result.error_message,
            }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    logger.info(f"收到流式请求: {request.message[:20]}...")

    # 这一步还能正常返回 4xx；一旦第一块数据发出，状态码就定死 200 了，
    # 之后的失败只能作为流里的 error 事件发出去（见 _sse_events）。
    if not request.message.strip():
        logger.warning("收到空消息请求")
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    return StreamingResponse(
        _sse_events(llm_service.stream_ai_response(request.message)),
        media_type="text/event-stream",
    )
