"""
Repository 层基类
职责：提供通用 CRUD 操作、查询构建、Session 管理
"""

from typing import Any, Generic, List, Optional, Type, TypeVar

from sqlalchemy import func
from sqlalchemy.orm import Session

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    """泛型 Repository 基类，提供标准 CRUD 操作。"""

    def __init__(self, model: Type[ModelType], db: Session):
        self.model = model
        self.db = db

    def get_by_id(self, id: Any) -> Optional[ModelType]:
        """根据主键获取单条记录。"""
        return self.db.query(self.model).filter(self.model.id == id).first()

    def list_all(self, skip: int = 0, limit: int = 100) -> List[ModelType]:
        """列表查询（分页）。"""
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def count(self) -> int:
        """统计总数。"""
        return self.db.query(func.count(self.model.id)).scalar()

    def create(self, **kwargs) -> ModelType:
        """创建记录（不提交）。"""
        instance = self.model(**kwargs)
        self.db.add(instance)
        return instance

    def update(self, instance: ModelType, **kwargs) -> ModelType:
        """更新记录（不提交）。"""
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        return instance

    def delete(self, instance: ModelType) -> None:
        """删除记录（不提交）。"""
        self.db.delete(instance)

    def commit(self) -> None:
        """提交事务（通常由 Service 层调用）。"""
        self.db.commit()

    def refresh(self, instance: ModelType) -> ModelType:
        """刷新实例（从数据库重新加载）。"""
        self.db.refresh(instance)
        return instance
