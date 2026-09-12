import os
import logging
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger("ConfigLoader")

# 1. 自动探测 .env 路径
current_file = Path(__file__).resolve()
# 尝试路径 A: PythonFor_AI_Learning/.env
path_a = current_file.parent.parent / ".env"
# 尝试路径 B: CodeofWork/.env
path_b = current_file.parent.parent.parent / ".env"

found_env = False
for env_path in [path_a, path_b]:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
        logger.info(f"--- [Config] 成功加载配置文件: {env_path} ---")
        found_env = True
        break

if not found_env:
    logger.error(f"--- [Config] 警告: 在以下位置均未找到 .env 文件: {[str(path_a), str(path_b)]} ---")

class Config:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    MODEL_NAME = os.getenv("DEFAULT_MODEL", "llama-3.3-70b-versatile")
    PROXY_URL = os.getenv("PROXY_URL")  # 不设默认值：多数环境不需要代理，需要的自己在 .env 里配
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 2. 强制校验（如果 Key 是空的，直接在这里报错，别等后面崩溃）
if not Config.GROQ_API_KEY:
    # 打印一个脱敏的调试信息
    logger.critical("--- [Config] 致命错误: GROQ_API_KEY 未定义！请检查 .env 文件内容 ---")
