import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

DATA_DIR = os.environ.get("ERP_DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "erp.db")

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """
    性能优化(小内存服务器场景)：
    - WAL 模式：读写可以并发进行，不会互相阻塞——这套系统有后台定时任务(轨迹同步/
      订单归档)和网页请求同时访问数据库，WAL 能明显减少 "database is locked" 的概率。
    - synchronous=NORMAL：WAL 模式下这个级别足够安全，比默认 FULL 减少磁盘同步次数。
    - busy_timeout：并发写入冲突时等待重试，而不是直接报错。
    - cache_size 给到 ~20MB：8GB 内存的机器完全负担得起，减少磁盘IO。
    - temp_store=MEMORY：临时表/排序放内存，避免小磁盘IO抖动。
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA cache_size=-20000")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def auto_migrate():
    """
    极简自动迁移：SQLite 里 SQLAlchemy 的 create_all() 只会创建"不存在的表"，
    不会给"已存在的表"自动加新列。这个项目开发过程中模型字段一直在增量调整
    （比如 Shop 加发件人预设字段、LogisticsProvider 加 source_key、
    Order 加包裹长宽高等），如果只用 create_all()，老数据库文件重启后会因为
    缺列直接报 500 (no such column: xxx)。

    这里在每次启动时自动对比"模型定义的列" vs "数据库里实际的列"，把缺的列用
    ALTER TABLE ... ADD COLUMN 补上（只加列，不删列、不改类型，不会丢数据）。
    必须在 Base.metadata.create_all() 之后调用，这样全新表已经带齐所有列，
    这里只需要处理老表缺列的情况。
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # 全新表，create_all() 已经建好并带齐所有列
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                try:
                    col_type = column.type.compile(engine.dialect)
                    ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                    conn.execute(text(ddl))
                except Exception as e:
                    # 单个列加失败不影响其它列/表，打印出来方便排查
                    print(f"[auto_migrate] 补列失败 {table.name}.{column.name}: {e}")
