# app/errors.py —— 平台自定义异常
# 统一异常体系：业务异常继承 PlatformError，携带 status_code 与错误码 code，
# 由 main.py 的全局异常处理器映射为结构化 HTTP 响应，供前端按 code 分支。
from typing import Any, List, Optional


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


class InvalidTemplateParamsError(PlatformError):
    """模板参数校验失败。"""

    status_code = 422
    code = "INVALID_TEMPLATE_PARAMS"

    def __init__(self, message: str, field_path: List[Any], validation_keyword: str) -> None:
        super().__init__(message)
        self.field_path = field_path
        self.validation_keyword = validation_keyword


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


class ContentStateConflictError(PlatformError):
    """内容状态不满足操作前置条件。"""

    status_code = 409
    code = "CONTENT_STATE_CONFLICT"


class TenantScopeDeniedError(PlatformError):
    """资源不属于当前用户租户。"""

    status_code = 403
    code = "TENANT_SCOPE_DENIED"


class NotFoundError(PlatformError):
    """资源不存在。"""

    status_code = 404
    code = "NOT_FOUND"
