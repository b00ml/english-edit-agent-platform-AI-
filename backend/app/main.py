# app/main.py —— FastAPI 应用入口
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import settings
from app.database import SessionLocal, engine
from app.errors import PlatformError
from app.models import Base, ModelProfile
from app.seed import seed_default_admin
from app.template_loader import load_all_templates

logger = logging.getLogger("app.main")

# 基础日志配置：结构化输出到 stderr（避免污染流式通道）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _seed_model_profiles(session) -> None:
    """若模型档案表为空，则按配置写入默认档案（避免新库无模型可用）。"""
    if session.query(ModelProfile).count() > 0:
        return
    session.add(
        ModelProfile(
            name="standard",
            provider="deepseek",
            model_name=settings.LLM_MODEL_NAME,
            cost_tier="standard",
            is_default=True,
        )
    )
    session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建表并加载题型模板与模型档案。"""
    # 初始化数据库表（生产环境建议改用 Alembic 迁移）
    Base.metadata.create_all(bind=engine)

    # 加载题型模板（按 type_id upsert 入库）
    session = SessionLocal()
    try:
        loaded = load_all_templates(session)
        logger.info("已加载 %d 个题型模板", loaded)
    except Exception as exc:  # noqa: BLE001 —— 模板加载失败不应阻断服务启动
        logger.warning("题型模板加载失败: %s", exc)
    finally:
        session.close()

    # 种子默认模型档案（新库无档案时写入）
    session = SessionLocal()
    try:
        _seed_model_profiles(session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("模型档案种子写入失败: %s", exc)
    finally:
        session.close()

    # 种子默认管理员账号（新库无用户时写入）
    session = SessionLocal()
    try:
        seed_default_admin(session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("默认管理员种子写入失败: %s", exc)
    finally:
        session.close()

    yield


def create_app() -> FastAPI:
    """构建 FastAPI 应用。"""
    app = FastAPI(
        title="英语教研 AI 内容生成平台 2.0",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS 配置（允许前端开发服务器跨域访问）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 全局异常处理：PlatformError -> 结构化错误响应（含错误码）
    @app.exception_handler(PlatformError)
    async def platform_error_handler(request: Request, exc: PlatformError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "detail": exc.message},
        )

    # 兜底异常处理：未捕获异常统一返回 500，避免暴露堆栈
    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("未处理异常 %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"code": "INTERNAL_ERROR", "detail": "服务器内部错误"},
        )

    app.include_router(router)
    return app


app = create_app()
