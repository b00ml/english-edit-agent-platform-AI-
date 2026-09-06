# app/errors.py —— 平台自定义异常
# 统一异常体系：业务异常继承 PlatformError，携带 status_code 与错误码 code，
# 由 main.py 的全局异常处理器映射为结构化 HTTP 响应，供前端按 code 分支。
from typing import Optional


class PlatformError(Exception):
    """平台业务异常基类。

    子类应设置 `status_code`（HTTP 状态码）与 `code`（机器可读错误码）。
    """

    status_code: int = 500
    code: str = "PLATFORM_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TemplateNotFoundError(PlatformError):
    """题型模板不存在或加载失败。"""

    status_code = 404
    code = "TEMPLATE_NOT_FOUND"


class StructuredOutputError(PlatformError):
    """结构化生成经多次重试后仍校验失败。"""

    status_code = 500
    code = "STRUCTURED_OUTPUT_FAILED"


class QualityCheckError(PlatformError):
    """自动质检所有采样均未返回有效结果。"""

    status_code = 500
    code = "QUALITY_CHECK_FAILED"


class ModelRoutingError(PlatformError):
    """模型路由降级后仍生成失败。"""

    status_code = 500
    code = "MODEL_ROUTING_FAILED"

    def __init__(self, message: str, last_error: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.last_error = last_error


class DuplicateTaskError(PlatformError):
    """相同题型与参数的生成任务已存在（去重拦截）。"""

    status_code = 409
    code = "DUPLICATE_TASK"

    def __init__(self, message: str, existing_task_id: str) -> None:
        super().__init__(message)
        self.existing_task_id = existing_task_id
