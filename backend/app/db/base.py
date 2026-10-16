"""SQLAlchemy 声明式基类。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。

    业务表**不**建外键到维表（规格 §5.6），因此 alembic 的自动生成不会因维表
    未加载而失败；只给从属关系建 FK 且 ``ON DELETE CASCADE``。
    """
