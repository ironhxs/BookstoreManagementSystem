# 图书进销存管理系统

本项目为数据库课程设计演示项目，使用 Flask + GaussDB/openGauss 实现书店图书采购、库存、销售、财务审核和系统管理等流程。

## 功能概览

- 五类角色独立登录：系统管理员、采购员、仓库管理员、销售员、财务人员
- 图书、出版社、分类、库存、采购订单、销售订单等业务数据管理
- 采购入库、销售出库、低库存预警、畅销图书统计
- 财务审核、采购价格查看、图书统计分析
- 数据库包含表、视图、触发器、函数、存储过程和索引优化脚本

## 目录说明

```text
app.py                    原版 Flask 入口
db.py                     数据库连接封装
templates/                原版页面模板
pic/                      原版图片资源
frontend_variant/         改版演示界面
database/                 数据库建表、数据、视图、触发器、函数和还原脚本
beamer_report_sxhfut/     Beamer 汇报 PPT 源码与导出 PDF
template_demos/           两个 Beamer 模板 demo
requirements.txt          Python 依赖
config.example.json       数据库连接配置示例
```

## 数据库要求

项目使用 `psycopg2` 连接数据库，目标数据库建议使用 GaussDB 或 openGauss。

当前 SQL 中包含 openGauss/GaussDB 风格语法，例如：

```sql
pg_systimestamp()
CREATE OR REPLACE PROCEDURE ...
NOT FENCED NOT SHIPPABLE
```

因此不建议直接使用 MySQL 或 SQLite。原生 PostgreSQL 可能需要调整少量 SQL 方言。

## 本地运行

1. 创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. 准备数据库配置：

```powershell
Copy-Item .\config.example.json .\config.json
Copy-Item .\database\target_config.example.json .\database\target_config.json
```

然后按自己的 openGauss/GaussDB 实例修改 `config.json` 和 `database/target_config.json`。

3. 导入数据库：

```powershell
.\.venv\Scripts\python.exe .\database\restore_to_target.py --config .\database\target_config.json --yes
```

4. 启动原版系统：

```powershell
.\.venv\Scripts\python.exe app.py
```

访问：

```text
http://127.0.0.1:5000/login
```

5. 启动改版演示系统：

```powershell
cd frontend_variant
D:\BookstoreManagementSystem\.venv\Scripts\python.exe app.py
```

访问：

```text
http://127.0.0.1:5001/login
```

## 演示账号

```text
系统管理员：admin1 / admin123
采购员：proc1 / proc123
仓库管理员：ware1 / ware123
销售员：sale1 / sale123
财务人员：fin1 / fin123
销售员备用：sales2 / sales123
```

## 注意事项

- `config.json`、`frontend_variant/config.json` 和 `database/target_config.json` 是本地配置文件，不提交到仓库。
- GitHub 中只保留 `config.example.json`、`frontend_variant/config.example.json` 和 `database/target_config.example.json`。
- 数据库服务本身不能通过 GitHub 传输，另一台电脑需要单独安装 openGauss/GaussDB 并导入 `database/` 中的 SQL。
- `.venv/`、日志、截图输出和 LaTeX 编译中间文件不需要提交。
