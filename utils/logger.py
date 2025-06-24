from loguru import logger

logger.remove()

logger.add(
    sink=lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True
)

__all__ = ["logger"]
