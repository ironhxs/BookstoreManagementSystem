# 数据库导出与还原

本目录是从当前可连接的远程 GaussDB 中导出的 `public` 业务对象，用于把项目还原到自己的 GaussDB 实例。

## 文件说明

- `01_schema.sql`：序列、表、约束、注释。
- `02_data.sql`：演示数据与序列当前位置。
- `03_routines_views_triggers.sql`：存储过程、函数、视图、触发器。
- `04_acceptance_optimization.sql`：验收补强脚本，补充 CHECK 完整性约束与常用查询索引。
- `export_summary.md`：本次导出对象与行数摘要。
- `target_config.example.json`：目标数据库连接配置模板。
- `restore_to_target.py`：按顺序执行上述 SQL 的还原脚本。

## 还原步骤

1. 在自己的华为云 GaussDB 中创建数据库，例如 `BookStoreManagement`。
2. 复制 `target_config.example.json` 为 `target_config.json`，填入自己的目标库连接信息。
3. 使用项目虚拟环境执行：

```powershell
.\.venv\Scripts\python.exe .\database\restore_to_target.py --config .\database\target_config.json --yes
```

4. 还原成功后，把项目根目录 `config.json` 改为自己的数据库连接信息，再启动 Flask。

## 注意

- 还原脚本会删除目标库 `public` schema 中同名业务对象，建议在空库或专门用于课程设计的库中执行。
- 存储过程、函数、触发器需要目标账号具备相应 DDL 权限；普通只读/业务账号可能无法创建。
- 数据库设计至少包含 `book`、`inventory`、`purchase_order` / `purchase_detail` 等 3 类以上核心业务表；系统实际导出 9 张基础表，并额外包含视图、过程、函数、触发器和索引。
- 不要把真实公网地址和密码提交到公开仓库。
