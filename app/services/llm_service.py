import logging
import httpx
from dataclasses import dataclass
from typing import Iterator, Literal, Optional
from groq import Groq, GroqError, APIConnectionError, RateLimitError           
from app.config import Config    # 导入我们写好的配置类（拿钥匙）

# 配置日志格式
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("LLMService")

# 4 种失败互斥，用一个字段的封闭取值表达"4选1"，而不是 4 个独立 bool——
# 后者无法阻止"同时两个 True"或"全部 False"这种不合法状态。
ErrorType = Literal["connection", "rate_limit", "api_error", "system_error"]

@dataclass
class LLMResult:
    """get_ai_response 的结构化返回：调用方靠字段判断，不用再猜字符串前缀。"""
    success: bool
    content: Optional[str] = None            # 成功时有值
    error_type: Optional[ErrorType] = None   # 失败时有值，四选一
    error_message: Optional[str] = None      # 失败时的人类可读描述

class LLMService:
    def __init__(self):
        try:
            proxy_url = Config.PROXY_URL
            self.http_client = httpx.Client(
                proxy=proxy_url,
                timeout=httpx.Timeout(20.0, connect=10.0) 
            )
            
            self.client = Groq(
                api_key=Config.GROQ_API_KEY,
                http_client=self.http_client
            )
            
            # --- 必须加上这一行 ---
            self.model = Config.MODEL_NAME 
            # ---------------------
            
            logger.info(f"LLMService 初始化成功，模型: {self.model}，使用代理: {proxy_url}")
        except Exception as e:
            logger.error(f"LLMService 初始化失败: {str(e)}")
            raise

    def get_ai_response(self, text: str) -> LLMResult:
        logger.info(f"正在请求 AI 响应，输入长度: {len(text)}")
        """
        核心业务方法：负责把用户的话发给 AI 并拿回结果
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": text}]
            )
            content = response.choices[0].message.content
            logger.info("AI 响应获取成功")
            return LLMResult(success=True, content=content)

        except APIConnectionError as e:
            logger.error(f"网络连接失败（请检查代理设置）: {e}")
            return LLMResult(
                success=False,
                error_type="connection",
                error_message="无法连接到 AI 服务器，请检查网络代理。",
            )
        except RateLimitError:
            logger.warning("触发 Groq 速率限制")
            return LLMResult(
                success=False,
                error_type="rate_limit",
                error_message="请求过于频繁，请稍后再试。",
            )
        except GroqError as e:
            logger.error(f"Groq API 业务错误: {e}")
            return LLMResult(
                success=False,
                error_type="api_error",
                error_message=f"AI 服务异常: {str(e)}",
            )
        except Exception as e:
            logger.critical(f"未预期的崩溃: {str(e)}", exc_info=True)
            return LLMResult(
                success=False,
                error_type="system_error",
                error_message="系统内部错误，请联系管理员。",
            )

    def stream_ai_response(self, text: str) -> Iterator[LLMResult]:
        """流式版本：逐块 yield LLMResult，供 SSE 端点消费。

        错误分类沿用 get_ai_response 的四类，变的只是传递通道——流式下
        HTTP 状态码在第一块发出时就定死了，失败只能作为流里的一个事件
        发出去，不能再靠状态码表达。
        """
        logger.info(f"正在请求 AI 流式响应，输入长度: {len(text)}")
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": text}],
                stream=True,
            )
            # try 要包住整个迭代：异常可能在 create() 抛，也可能迭代到第 N 块才抛。
            for chunk in stream:
                piece = chunk.choices[0].delta.content
                if not piece:   # 首块可能是 ""，收尾块是 None，两种都跳过
                    continue
                yield LLMResult(success=True, content=piece)
            logger.info("AI 流式响应正常结束")

        except APIConnectionError as e:
            logger.error(f"网络连接失败（请检查代理设置）: {e}")
            yield LLMResult(
                success=False,
                error_type="connection",
                error_message="无法连接到 AI 服务器，请检查网络代理。",
            )
        except RateLimitError:
            logger.warning("触发 Groq 速率限制")
            yield LLMResult(
                success=False,
                error_type="rate_limit",
                error_message="请求过于频繁，请稍后再试。",
            )
        except GroqError as e:
            logger.error(f"Groq API 业务错误: {e}")
            yield LLMResult(
                success=False,
                error_type="api_error",
                error_message=f"AI 服务异常: {str(e)}",
            )
        except Exception as e:
            logger.critical(f"未预期的崩溃: {str(e)}", exc_info=True)
            yield LLMResult(
                success=False,
                error_type="system_error",
                error_message="系统内部错误，请联系管理员。",
            )
