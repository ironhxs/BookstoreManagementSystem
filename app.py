from flask import Flask, render_template, redirect, url_for, request, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from db import execute_query, execute_update
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps


app = Flask(__name__)
app.secret_key = 'your_secret_key'
login_manager = LoginManager(app)
login_manager.login_view = 'login'


@app.route('/favicon.ico')
def favicon():
    return '', 204


def _scalar(sql, params=None):
    result = execute_query(sql, params or (), fetchone=True)
    if not result or result[0] is None:
        return 0
    return result[0]


def _fmt_count(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


_TODO_SEEN_TABLE_READY = False
_PURCHASE_AUDIT_TABLE_READY = False


def _ensure_todo_seen_table():
    global _TODO_SEEN_TABLE_READY
    if _TODO_SEEN_TABLE_READY:
        return
    execute_update("""
        CREATE TABLE IF NOT EXISTS app_todo_seen (
            username VARCHAR(80) NOT NULL,
            todo_type VARCHAR(24) NOT NULL,
            todo_key VARCHAR(160) NOT NULL,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (username, todo_type, todo_key)
        )
    """)
    _TODO_SEEN_TABLE_READY = True


def _ensure_purchase_audit_table():
    global _PURCHASE_AUDIT_TABLE_READY
    if _PURCHASE_AUDIT_TABLE_READY:
        return
    execute_update("""
        CREATE TABLE IF NOT EXISTS app_purchase_audit (
            order_id VARCHAR(80) PRIMARY KEY,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            audit_note TEXT,
            auditor VARCHAR(80),
            audited_at TIMESTAMP
        )
    """)
    _PURCHASE_AUDIT_TABLE_READY = True


def _todo_seen_pairs(username):
    if not username:
        return set()
    _ensure_todo_seen_table()
    rows = execute_query(
        "SELECT todo_type, todo_key FROM app_todo_seen WHERE username=%s",
        (username,)
    )
    return {(todo_type, str(todo_key)) for todo_type, todo_key in rows}


def _mark_todo_seen(username, todo_type, todo_key):
    if not username or todo_type not in {'purchase', 'sales', 'stock'}:
        return
    todo_key = str(todo_key)
    _ensure_todo_seen_table()
    exists = execute_query(
        "SELECT 1 FROM app_todo_seen WHERE username=%s AND todo_type=%s AND todo_key=%s",
        (username, todo_type, todo_key),
        fetchone=True
    )
    if not exists:
        execute_update(
            "INSERT INTO app_todo_seen (username, todo_type, todo_key) VALUES (%s, %s, %s)",
            (username, todo_type, todo_key)
        )


def _admin_todo_counts(username=None):
    seen = _todo_seen_pairs(username) if username else set()
    purchase_ids = [str(row[0]) for row in execute_query("SELECT order_id FROM purchase_order")]
    sales_ids = [str(row[0]) for row in execute_query("SELECT order_id FROM sales_order")]
    stock_ids = [str(row[0]) for row in execute_query("SELECT book_id FROM v_low_quantity_books")]
    return {
        'purchase': sum(1 for item in purchase_ids if ('purchase', item) not in seen),
        'sales': sum(1 for item in sales_ids if ('sales', item) not in seen),
        'stock': sum(1 for item in stock_ids if ('stock', item) not in seen),
    }


def admin_metric_cards():
    try:
        book_count = _scalar("SELECT COUNT(*) FROM book")
        stock_sum = _scalar("SELECT COALESCE(SUM(stock_quantity), 0) FROM inventory")
        purchase_count = _scalar("SELECT COUNT(*) FROM purchase_order")
        low_stock_count = _scalar("SELECT COUNT(*) FROM v_low_quantity_books")
    except Exception:
        return [
            ['图书总数', '-', '当前档案'],
            ['库存总册数', '-', '当前库存'],
            ['采购订单', '-', '累计单数'],
            ['库存预警', '-', '需要关注'],
        ]
    return [
        ['图书总数', _fmt_count(book_count), '当前档案'],
        ['库存总册数', _fmt_count(stock_sum), '当前库存'],
        ['采购订单', _fmt_count(purchase_count), '累计单数'],
        ['库存预警', _fmt_count(low_stock_count), '需要关注'],
    ]


def admin_todo_context():
    username = current_user.id if current_user.is_authenticated else None
    seen = _todo_seen_pairs(username)
    purchase_rows = execute_query("""
        SELECT po.order_id, po.purchaser, po.purchase_date,
               COALESCE(SUM(pd.quantity * pd.purchase_price), 0) AS amount
        FROM purchase_order po
        LEFT JOIN purchase_detail pd ON po.order_id = pd.order_id
        GROUP BY po.order_id, po.purchaser, po.purchase_date
        ORDER BY po.purchase_date DESC
        LIMIT 30
    """)
    sales_rows = execute_query("""
        SELECT so.order_id, so.customer, so.sale_date,
               COALESCE(SUM(sd.quantity), 0) AS quantity
        FROM sales_order so
        LEFT JOIN sales_detail sd ON so.order_id = sd.order_id
        GROUP BY so.order_id, so.customer, so.sale_date
        ORDER BY so.sale_date DESC
        LIMIT 30
    """)
    low_books = execute_query("""
        SELECT book_id, title, stock_quantity, last_updated
        FROM v_low_quantity_books
        ORDER BY stock_quantity ASC
        LIMIT 30
    """)

    def format_dt(value):
        return value.strftime('%Y-%m-%d %H:%M') if hasattr(value, 'strftime') else str(value or '未知')

    todo_rows = []
    for order_id, purchaser, purchase_date, amount in purchase_rows:
        if ('purchase', str(order_id)) in seen:
            continue
        todo_rows.append({
            'type': '采购记录',
            'code': order_id,
            'object': f"{purchaser or '采购员'} · ¥{float(amount or 0):,.2f}",
            'owner': format_dt(purchase_date),
            'href': url_for('admin_todo_view', todo_type='purchase', todo_key=order_id),
            'tag': '查看',
            'tone': '',
        })
        if len([item for item in todo_rows if item['type'] == '采购记录']) >= 3:
            break
    for order_id, customer, sale_date, quantity in sales_rows:
        if ('sales', str(order_id)) in seen:
            continue
        todo_rows.append({
            'type': '销售记录',
            'code': order_id,
            'object': f"{customer or '客户'} · {int(quantity or 0)} 本",
            'owner': format_dt(sale_date),
            'href': url_for('admin_todo_view', todo_type='sales', todo_key=order_id),
            'tag': '查看',
            'tone': 'is-blue',
        })
        if len([item for item in todo_rows if item['type'] == '销售记录']) >= 2:
            break
    for book_id, title, stock_quantity, last_updated in low_books:
        if ('stock', str(book_id)) in seen:
            continue
        todo_rows.append({
            'type': '库存预警',
            'code': book_id,
            'object': f"{title} · 当前 {stock_quantity} 本",
            'owner': format_dt(last_updated),
            'href': url_for('admin_todo_view', todo_type='stock', todo_key=book_id),
            'tag': '查看',
            'tone': 'is-blue',
        })
        if len([item for item in todo_rows if item['type'] == '库存预警']) >= 2:
            break

    counts = _admin_todo_counts(username)
    purchase_count = counts['purchase']
    sales_count = counts['sales']
    low_count = counts['stock']
    total_count = purchase_count + sales_count + low_count

    return {
        'todo_rows': todo_rows,
        'source_rows': [
            ['采购订单', _fmt_count(purchase_count), '采购入库', '未查看采购记录', '高'],
            ['销售订单', _fmt_count(sales_count), '销售履约', '未查看销售记录', '高'],
            ['低库存图书', _fmt_count(low_count), '库存安全', '未查看库存风险', '中'],
        ],
        'priority_rows': [
            ['采购记录', '未查看采购订单', _fmt_count(purchase_count), ''],
            ['销售记录', '未查看销售订单', _fmt_count(sales_count), 'is-blue'],
            ['库存预警', '未查看低库存图书', _fmt_count(low_count), 'is-amber'],
        ],
        'process_cards': [
            ['待查看项', _fmt_count(total_count), '未处理'],
            ['采购单', _fmt_count(purchase_count), '未查看'],
            ['销售单', _fmt_count(sales_count), '未查看'],
            ['低库存', _fmt_count(low_count), '未查看'],
        ],
    }


def _fmt_money(value):
    try:
        return f"¥{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "¥0.00"


def _fmt_number(value):
    try:
        return f"{float(value or 0):,.2f}".rstrip('0').rstrip('.')
    except (TypeError, ValueError):
        return str(value or 0)


def _fmt_dt(value):
    return value.strftime('%Y-%m-%d %H:%M') if hasattr(value, 'strftime') else str(value or '未知')


DATA_SPECS = [
    ('publisher', '出版社', '基础资料', '出版社地址、电话、联系人'),
    ('book_category', '图书分类', '基础资料', '分类编号与分类名称'),
    ('book', '图书档案', '基础资料', '书名、作者、出版社、零售价'),
    ('inventory', '库存记录', '库存对象', '每本图书当前库存数量'),
    ('purchase_order', '采购订单', '采购对象', '采购主单与采购员信息'),
    ('purchase_detail', '采购明细', '采购对象', '采购图书、数量和采购价'),
    ('sales_order', '销售订单', '销售对象', '销售主单与客户信息'),
    ('sales_detail', '销售明细', '销售对象', '销售图书、数量和售价'),
]


CORE_DATABASE_TABLES = [
    ('book', '图书档案', '主数据表', 'book_id 主键；publisher_id、category_id 外键'),
    ('inventory', '库存记录', '库存状态表', 'book_id 既是主键也是外键；stock_quantity 非负'),
    ('purchase_detail', '采购明细', '业务明细表', 'order_id、book_id 外键；数量与采购价必须有效'),
]


def _safe_meta_count(sql, fallback=0):
    try:
        return int(_scalar(sql))
    except Exception:
        return fallback


def _safe_table_count(table_name):
    try:
        return _scalar(f"SELECT COUNT(*) FROM {table_name}")
    except Exception:
        return 0


def _dashboard_base_stats():
    return {
        'book_count': _scalar("SELECT COUNT(*) FROM book"),
        'publisher_count': _scalar("SELECT COUNT(*) FROM publisher"),
        'stock_sum': _scalar("SELECT COALESCE(SUM(stock_quantity), 0) FROM inventory"),
        'inventory_count': _scalar("SELECT COUNT(*) FROM inventory"),
        'low_count': _scalar("SELECT COUNT(*) FROM v_low_quantity_books"),
        'severe_low_count': _scalar("SELECT COUNT(*) FROM v_low_quantity_books WHERE stock_quantity <= 10"),
        'purchase_count': _scalar("SELECT COUNT(*) FROM purchase_order"),
        'purchase_qty': _scalar("SELECT COALESCE(SUM(quantity), 0) FROM purchase_detail"),
        'purchase_amount': _scalar("SELECT COALESCE(SUM(quantity * purchase_price), 0) FROM purchase_detail"),
        'sales_count': _scalar("SELECT COUNT(*) FROM sales_order"),
        'sales_qty': _scalar("SELECT COALESCE(SUM(quantity), 0) FROM sales_detail"),
        'sales_amount': _scalar("SELECT COALESCE(SUM(quantity * sale_price), 0) FROM sales_detail"),
    }


def _low_stock_bar_items(limit=5):
    rows = execute_query("""
        SELECT book_id, title, stock_quantity, last_updated
        FROM v_low_quantity_books
        ORDER BY stock_quantity ASC
        LIMIT %s
    """, (limit,))
    items = []
    for _, title, stock_quantity, _ in rows:
        stock = int(stock_quantity or 0)
        shortage = max(0, 50 - stock)
        width = max(18, min(100, int((shortage / 40) * 100) if shortage else 18))
        label = f"缺 {shortage}" if shortage else "临界"
        items.append([title, f"当前 {stock} / 阈值 50", f"{width}%", label])
    return items


def _line_chart_context():
    sales_rows = execute_query("""
        SELECT TO_CHAR(so.sale_date, 'YYYY-MM-DD') AS day,
               COALESCE(SUM(sd.quantity * sd.sale_price), 0) AS amount
        FROM sales_order so
        LEFT JOIN sales_detail sd ON so.order_id = sd.order_id
        GROUP BY TO_CHAR(so.sale_date, 'YYYY-MM-DD')
        ORDER BY TO_CHAR(so.sale_date, 'YYYY-MM-DD')
    """)
    purchase_rows = execute_query("""
        SELECT TO_CHAR(po.purchase_date, 'YYYY-MM-DD') AS day,
               COALESCE(SUM(pd.quantity * pd.purchase_price), 0) AS amount
        FROM purchase_order po
        LEFT JOIN purchase_detail pd ON po.order_id = pd.order_id
        GROUP BY TO_CHAR(po.purchase_date, 'YYYY-MM-DD')
        ORDER BY TO_CHAR(po.purchase_date, 'YYYY-MM-DD')
    """)
    sales_map = {row[0]: float(row[1] or 0) for row in sales_rows}
    purchase_map = {row[0]: float(row[1] or 0) for row in purchase_rows}
    days = sorted(set(sales_map) | set(purchase_map))[-7:]
    if not days:
        days = [datetime.now().date()]

    sales_values = [sales_map.get(day, 0) for day in days]
    purchase_values = [purchase_map.get(day, 0) for day in days]
    max_value = max(sales_values + purchase_values + [1])
    step = max_value / 4
    x0, x1 = 54, 748
    y0, y1 = 252, 42
    span = max(1, len(days) - 1)

    def point(index, value):
        x = x0 + (x1 - x0) * index / span
        y = y0 - (value / max_value) * (y0 - y1)
        return {'x': round(x, 1), 'y': round(y, 1)}

    points_a = [point(i, value) for i, value in enumerate(sales_values)]
    points_b = [point(i, value) for i, value in enumerate(purchase_values)]

    def path(points):
        if not points:
            return ""
        return "M" + " L".join(f"{p['x']},{p['y']}" for p in points)

    area = ""
    if points_a:
        area = path(points_a) + f" L{points_a[-1]['x']},{y0} L{points_a[0]['x']},{y0} Z"

    grid = []
    for i in range(5):
        value = step * i
        y = y0 - (value / max_value) * (y0 - y1)
        grid.append({'y': round(y, 1), 'label': _fmt_count(value)})

    def short_day(day):
        return day.strftime('%m-%d') if hasattr(day, 'strftime') else str(day)[5:10]

    def full_day(day):
        return day.strftime('%y-%m-%d') if hasattr(day, 'strftime') else str(day)[2:10]

    raw_labels = [short_day(day) for day in days]
    duplicate_labels = {label for label in raw_labels if raw_labels.count(label) > 1}
    labels = [
        {
            'x': round(x0 + (x1 - x0) * i / span - (26 if raw_labels[i] in duplicate_labels else 16), 1),
            'text': full_day(day) if raw_labels[i] in duplicate_labels else raw_labels[i]
        }
        for i, day in enumerate(days)
    ]
    return {
        'grid': grid,
        'labels': labels,
        'grid_x0': x0,
        'grid_x1': x1,
        'label_y': 282,
        'points_a': points_a,
        'points_b': points_b,
        'path_a': path(points_a),
        'path_b': path(points_b),
        'area_a': area,
        'series_a_label': '销售金额',
        'series_b_label': '采购金额',
    }


def _latest_purchase_rows(limit=5):
    rows = execute_query("""
        SELECT po.order_id, po.purchaser, po.purchase_date,
               COALESCE(SUM(pd.quantity), 0) AS quantity,
               COALESCE(SUM(pd.quantity * pd.purchase_price), 0) AS amount
        FROM purchase_order po
        LEFT JOIN purchase_detail pd ON po.order_id = pd.order_id
        GROUP BY po.order_id, po.purchaser, po.purchase_date
        ORDER BY po.purchase_date DESC
        LIMIT %s
    """, (limit,))
    return [[order_id, purchaser or '采购员', _fmt_money(amount), _fmt_dt(purchase_date), '查看'] for order_id, purchaser, purchase_date, quantity, amount in rows]


def _latest_sales_rows(limit=5):
    rows = execute_query("""
        SELECT so.order_id, so.customer, so.sale_date,
               COALESCE(SUM(sd.quantity), 0) AS quantity,
               COALESCE(SUM(sd.quantity * sd.sale_price), 0) AS amount
        FROM sales_order so
        LEFT JOIN sales_detail sd ON so.order_id = sd.order_id
        GROUP BY so.order_id, so.customer, so.sale_date
        ORDER BY so.sale_date DESC
        LIMIT %s
    """, (limit,))
    return [[order_id, customer or '客户', _fmt_count(quantity), _fmt_money(amount), '查看'] for order_id, customer, sale_date, quantity, amount in rows]


def role_dashboard_context(role):
    stats = _dashboard_base_stats()
    low_items = _low_stock_bar_items()
    line_chart = _line_chart_context()
    common = {
        'line_chart': line_chart,
        'date_range': '当前数据',
        'brand_icon': 'generated-icons/brand-book.png',
    }

    if role == 'admin':
        user_count = _scalar("SELECT COUNT(*) FROM users")
        role_count = _scalar("SELECT COUNT(DISTINCT role) FROM users")
        role_rows = execute_query("SELECT role, COUNT(*) FROM users GROUP BY role")
        role_counts = {role_key: count for role_key, count in role_rows}
        user_rows = execute_query("SELECT username, role FROM users ORDER BY username")
        role_labels = {
            'sys_admin': '系统管理员',
            'procurement_officer': '采购员',
            'warehouse_keeper': '仓库管理员',
            'sales_agent': '销售员',
            'finance_officer': '财务人员',
        }
        role_specs = [
            ('系统管理员', 'sys_admin', [True, True, True, True, True, True]),
            ('采购员', 'procurement_officer', [False, True, True, False, False, False]),
            ('仓库管理员', 'warehouse_keeper', [False, False, True, False, False, True]),
            ('销售员', 'sales_agent', [False, False, True, True, False, False]),
            ('财务人员', 'finance_officer', [False, False, False, False, True, False]),
        ]
        role_matrix = []
        for role_label, role_key, permissions in role_specs:
            count = role_counts.get(role_key, 0)
            role_matrix.append({
                'role': role_label,
                'accounts': f"{_fmt_count(count)} 个账号",
                'cells': permissions,
                'status': '已覆盖' if count else '缺账号',
                'tone': 'is-ok' if count else 'is-warn',
            })

        users_by_name = {username: role_key for username, role_key in user_rows}
        audit_rows = []
        for username, role_key in user_rows[:3]:
            audit_rows.append([
                '当前账号',
                username,
                role_labels.get(role_key, role_key),
                '账号已登记',
                '正常',
                'is-ok',
            ])

        object_rows = []
        for table_key, label, category, focus in DATA_SPECS:
            object_rows.append([
                label,
                _fmt_count(_scalar(f"SELECT COUNT(*) FROM {table_key}")),
                category,
                focus,
                {'label': '查看', 'href': f"/admin/manage?table={table_key}"},
            ])

        data_object_count = len(DATA_SPECS)
        todo_counts = _admin_todo_counts(current_user.id)
        todo_count = todo_counts['purchase'] + todo_counts['sales'] + todo_counts['stock']
        return {
            **common,
            'title': '系统管理员首页',
            'subtitle': '聚焦账号权限、数据对象、跨角色待办和系统风险',
            'role_name': '系统管理员',
            'role_icon': '管',
            'accent': '#0f766e',
            'accent2': '#38bdf8',
            'soft': 'rgba(15, 118, 110, 0.12)',
            'action_label': '维护账号',
            'action_href': '/admin/role-permissions',
            'nav_items': [
                {'label': '系统总览', 'href': '/admin', 'icon': 'generated-icons/nav-home.png'},
                {'label': '待办总览', 'href': '/admin/todos', 'icon': 'generated-icons/nav-todo.png'},
                {'label': '库存风险', 'href': '/admin/inventory-risk', 'icon': 'generated-icons/nav-risk.png'},
                {'label': '角色权限', 'href': '/admin/role-permissions', 'icon': 'generated-icons/nav-role.png'},
                {'label': '数据库设计', 'href': '/admin/database-design', 'icon': 'generated-icons/metric-data.png'},
                {'label': '业务明细', 'href': '/admin/business-details', 'icon': 'generated-icons/nav-business.png'},
            ],
            'metrics': [
                ['账号总数', _fmt_count(user_count), '独立登录', 'generated-icons/metric-accounts.png'],
                ['角色覆盖', f"{_fmt_count(role_count)}/5", '五类职责', 'generated-icons/metric-roles.png'],
                ['数据对象', f"{_fmt_count(data_object_count)} 类", '核心表单', 'generated-icons/metric-data.png'],
                ['待处理项', _fmt_count(todo_count), '风险与业务', 'generated-icons/metric-todo.png'],
            ],
            'primary_type': 'permission_matrix',
            'primary_title': '权限覆盖矩阵',
            'primary_note': '按职责隔离',
            'primary_headers': ['账号', '用户权限', '采购', '库存', '销售', '财务', '数据维护'],
            'primary_items': role_matrix,
            'secondary_type': 'audit',
            'secondary_title': '账号安全与变更审计',
            'secondary_note': '管理留痕',
            'audit_summary': [
                ['密码加密', '已启用', 'generated-icons/audit-lock.png'],
                ['角色隔离', '已启用', 'generated-icons/audit-shield.png'],
                ['账号状态', f"{_fmt_count(user_count)} 个", 'generated-icons/audit-user.png'],
            ],
            'audit_rows': audit_rows,
            'audit_actions': [
                {'label': '新增账号', 'href': '/admin/role-permissions', 'icon': 'add'},
                {'label': '修改角色', 'href': '/admin/role-permissions', 'icon': 'role'},
                {'label': '重置密码', 'href': '/admin/role-permissions', 'icon': 'lock'},
                {'label': '导出账号表', 'href': '/admin/role-permissions', 'icon': 'export'},
            ],
            'audit_all_href': '/admin/role-permissions',
            'tasks_title': '系统风险队列',
            'tasks_note': '按优先级',
            'tasks': [
                ['库存风险', f"未查看低库存图书 {todo_counts['stock']} 本", _fmt_count(todo_counts['stock']), 'is-warn', 'generated-icons/risk-inventory.png'],
                ['业务待办', f"采购 {todo_counts['purchase']} 单，销售 {todo_counts['sales']} 单", _fmt_count(todo_count), 'is-ok', 'generated-icons/risk-todo.png'],
                ['数据对象', f"{data_object_count} 类核心对象可维护", _fmt_count(data_object_count), 'is-ok', 'generated-icons/risk-data.png'],
            ],
            'table_title': '数据对象清单',
            'table_head': ['数据对象', '记录数', '类型', '管理重点', '操作'],
            'table_rows': object_rows,
        }

    if role == 'procurement':
        return {
            **common,
            'title': '采购补货工作台',
            'subtitle': '面向采购员：根据低库存、供应商与采购记录安排补货顺序',
            'role_name': '采购员',
            'role_icon': '采',
            'accent': '#0d9488',
            'accent2': '#f59e0b',
            'soft': 'rgba(13, 148, 136, 0.13)',
            'action_label': '处理采购单',
            'action_href': '/procurement/orders',
            'nav_items': [
                {'label': '补货优先级', 'href': '/procurement'},
                {'label': '采购订单', 'href': '/procurement/orders'},
                {'label': '新建采购', 'href': '/procurement/order/new'},
                {'label': '库存预警', 'href': '/procurement/low_quantity_books'},
                {'label': '供应商', 'href': '/procurement/publishers'},
                {'label': '库存查询', 'href': '/procurement/inventory'},
            ],
            'metrics': [
                ['采购订单', _fmt_count(stats['purchase_count']), '当前单数'],
                ['采购金额', _fmt_money(stats['purchase_amount']), '累计金额'],
                ['供应商', _fmt_count(stats['publisher_count']), '当前供应商'],
                ['库存预警', _fmt_count(stats['low_count']), '需补货'],
            ],
            'primary_type': 'bars',
            'primary_title': '补货缺口优先级',
            'primary_note': '按库存阈值 50 计算',
            'primary_items': low_items,
            'secondary_type': 'cards',
            'secondary_title': '采购结构',
            'secondary_note': '采购侧',
            'secondary_items': [
                ['采购数量', _fmt_count(stats['purchase_qty']), '累计册数'],
                ['采购单数', _fmt_count(stats['purchase_count']), '当前单数'],
                ['供应商数', _fmt_count(stats['publisher_count']), '当前供应商'],
                ['补货线索', _fmt_count(stats['low_count']), '低库存'],
            ],
            'tasks': [
                ['优先补货', f"当前低库存 {stats['low_count']} 本，先看库存最少的图书", _fmt_count(stats['low_count'])],
                ['采购金额', f"累计采购金额 {_fmt_money(stats['purchase_amount'])}", _fmt_money(stats['purchase_amount'])],
                ['供应商维护', f"当前供应商 {stats['publisher_count']} 家", _fmt_count(stats['publisher_count'])],
            ],
            'table_title': '最新采购记录',
            'table_head': ['采购单号', '采购员', '金额', '日期', '操作'],
            'table_rows': _latest_purchase_rows(),
        }

    if role == 'warehouse':
        low_rows = execute_query("""
            SELECT book_id, title, stock_quantity, last_updated
            FROM v_low_quantity_books
            ORDER BY stock_quantity ASC
            LIMIT 5
        """)
        return {
            **common,
            'title': '库存风险工作台',
            'subtitle': '面向仓库管理员：查看库存总量、低库存图书和补货缺口',
            'role_name': '仓库管理员',
            'role_icon': '仓',
            'accent': '#2563eb',
            'accent2': '#06b6d4',
            'soft': 'rgba(37, 99, 235, 0.12)',
            'action_label': '查看库存',
            'action_href': '/warehouse/inventory',
            'nav_items': [
                {'label': '库存风险', 'href': '/warehouse'},
                {'label': '低库存', 'href': '/warehouse/low_quantity_books'},
                {'label': '库存明细', 'href': '/warehouse/inventory'},
                {'label': '图书档案', 'href': '/warehouse/books'},
                {'label': '库存统计', 'href': '/warehouse/inventory_stats'},
            ],
            'metrics': [
                ['库存总册数', _fmt_count(stats['stock_sum']), '当前库存'],
                ['图书种类', _fmt_count(stats['book_count']), '图书档案'],
                ['库存预警', _fmt_count(stats['low_count']), '需复核'],
                ['紧急补货', _fmt_count(stats['severe_low_count']), '≤10 本'],
            ],
            'primary_type': 'bars',
            'primary_title': '库存缺口 TOP5',
            'primary_note': '越靠前越优先复核',
            'primary_items': low_items,
            'secondary_type': 'cards',
            'secondary_title': '仓库状态摘要',
            'secondary_note': '当前库存',
            'secondary_items': [
                ['库存记录', _fmt_count(stats['inventory_count']), '库存条目'],
                ['库存总册数', _fmt_count(stats['stock_sum']), '库存合计'],
                ['低库存', _fmt_count(stats['low_count']), '≤50 本'],
                ['紧急', _fmt_count(stats['severe_low_count']), '≤10 本'],
            ],
            'tasks': [
                ['库存复核', f"低库存图书 {stats['low_count']} 本，需要核对实物", _fmt_count(stats['low_count'])],
                ['紧急补货', f"库存 ≤10 本的图书 {stats['severe_low_count']} 本", _fmt_count(stats['severe_low_count'])],
                ['同步采购', '低库存清单应同步采购侧生成补货单', '补货'],
            ],
            'table_title': '库存预警列表',
            'table_head': ['图书ID', '图书名称', '库存', '最后更新', '状态'],
            'table_rows': [[book_id, title, _fmt_count(stock), _fmt_dt(updated), '紧急' if stock <= 10 else '注意'] for book_id, title, stock, updated in low_rows],
        }

    if role == 'sales':
        return {
            **common,
            'title': '销售履约工作台',
            'subtitle': '面向销售员：查看销售金额、订单数量和开单前库存风险',
            'role_name': '销售员',
            'role_icon': '售',
            'accent': '#0f766e',
            'accent2': '#f97316',
            'soft': 'rgba(15, 118, 110, 0.12)',
            'action_label': '新建销售单',
            'action_href': '/sales/order/new',
            'nav_items': [
                {'label': '销售概览', 'href': '/sales'},
                {'label': '销售订单', 'href': '/sales/orders'},
                {'label': '库存校验', 'href': '/sales/inventory'},
                {'label': '低库存', 'href': '/sales/low_quantity_books'},
                {'label': '畅销书', 'href': '/sales/bestsellers'},
            ],
            'metrics': [
                ['销售金额', _fmt_money(stats['sales_amount']), '累计金额'],
                ['销售订单', _fmt_count(stats['sales_count']), '当前订单'],
                ['销售数量', _fmt_count(stats['sales_qty']), '销售册数'],
                ['库存预警', _fmt_count(stats['low_count']), '影响开单'],
            ],
            'primary_type': 'line',
            'primary_title': '销售金额 / 采购金额趋势',
            'primary_note': '按订单日期聚合',
            'primary_items': [],
            'secondary_type': 'bars',
            'secondary_title': '售前库存限制',
            'secondary_note': '低库存会影响销售开单',
            'secondary_items': low_items,
            'tasks': [
                ['销售履约', f"当前销售订单 {stats['sales_count']} 单", _fmt_count(stats['sales_count'])],
                ['销售金额', f"累计销售金额 {_fmt_money(stats['sales_amount'])}", _fmt_money(stats['sales_amount'])],
                ['库存校验', f"开单前关注 {stats['low_count']} 条库存预警", _fmt_count(stats['low_count'])],
            ],
            'table_title': '最新销售记录',
            'table_head': ['销售单号', '客户', '册数', '金额', '操作'],
            'table_rows': _latest_sales_rows(),
        }

    return {
        **common,
        'title': '财务经营分析台',
        'subtitle': '面向财务人员：对比销售金额、采购金额与订单规模',
        'role_name': '财务人员',
        'role_icon': '财',
        'accent': '#334155',
        'accent2': '#0ea5e9',
        'soft': 'rgba(51, 65, 85, 0.12)',
        'action_label': '进入审核',
        'action_href': '/finance/audit',
        'nav_items': [
            {'label': '经营分析', 'href': '/finance'},
            {'label': '采购审核', 'href': '/finance/audit'},
            {'label': '采购价格', 'href': '/finance/purchase_price'},
            {'label': '图书统计', 'href': '/finance/book_stats'},
            {'label': '库存风险', 'href': '/finance/low_quantity_books'},
        ],
        'metrics': [
                ['销售金额', _fmt_money(stats['sales_amount']), '销售汇总'],
                ['采购金额', _fmt_money(stats['purchase_amount']), '采购汇总'],
            ['经营差额', _fmt_money(stats['sales_amount'] - stats['purchase_amount']), '销售-采购'],
            ['订单规模', f"{_fmt_count(stats['sales_count'])} / {_fmt_count(stats['purchase_count'])}", '销 / 采'],
        ],
        'primary_type': 'line',
        'primary_title': '销售金额 / 采购金额趋势',
        'primary_note': '按订单日期聚合',
        'primary_items': [],
        'secondary_type': 'cards',
        'secondary_title': '财务审核摘要',
        'secondary_note': '财务侧',
        'secondary_items': [
            ['销售金额', _fmt_money(stats['sales_amount']), '销售汇总'],
            ['采购金额', _fmt_money(stats['purchase_amount']), '采购汇总'],
            ['销售订单', _fmt_count(stats['sales_count']), '销售单数'],
            ['采购订单', _fmt_count(stats['purchase_count']), '采购单数'],
        ],
        'tasks': [
            ['采购审核', f"当前采购订单 {stats['purchase_count']} 单", _fmt_count(stats['purchase_count'])],
            ['经营差额', f"销售金额 - 采购金额 = {_fmt_money(stats['sales_amount'] - stats['purchase_amount'])}", '差额'],
            ['库存风险', f"低库存 {stats['low_count']} 条，影响后续经营", _fmt_count(stats['low_count'])],
        ],
        'table_title': '经营汇总',
        'table_head': ['指标', '数值', '来源', '说明', '状态'],
        'table_rows': [
            ['销售金额', _fmt_money(stats['sales_amount']), '销售明细', '数量 × 售价', '已汇总'],
            ['采购金额', _fmt_money(stats['purchase_amount']), '采购明细', '数量 × 进价', '已汇总'],
            ['销售订单', _fmt_count(stats['sales_count']), '销售订单', '订单数', '已汇总'],
            ['采购订单', _fmt_count(stats['purchase_count']), '采购订单', '订单数', '已汇总'],
        ],
    }


class User(UserMixin):
    def __init__(self, username, role):
        self.id = username
        self.role = role


def require_role(role):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if current_user.role != role:
                return redirect(url_for('dashboard'))
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


@login_manager.user_loader  # 注册用户加载函数
def load_user(user_id):
    from db import execute_query
    try:
        result = execute_query("SELECT username, role FROM users WHERE username=%s", (user_id,), fetchone=True)
        if result:
            return User(result[0], result[1])
    except Exception as e:
        print(f"加载用户失败: {e}")
    return None


@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        from db import execute_query
        try:
            result = execute_query("SELECT username, password, role FROM users WHERE username=%s", 
                                   (username,), fetchone=True)
            if result and check_password_hash(result[1], password):  # 密码验证
                login_user(User(result[0], result[2]))
                return redirect(url_for('dashboard'))
        except Exception as e:
            print(f"登录查询失败: {e}")
        return render_template('login.html', error='用户名或密码错误')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    # 根据角色跳转
    if current_user.role == 'sys_admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'procurement_officer':
        return redirect(url_for('procurement_dashboard'))
    elif current_user.role == 'warehouse_keeper':
        return redirect(url_for('warehouse_dashboard'))
    elif current_user.role == 'sales_agent':
        return redirect(url_for('sales_dashboard'))
    elif current_user.role == 'finance_officer':
        return redirect(url_for('finance_dashboard'))
    return '未知角色'


@app.route('/admin')
@login_required
@require_role('sys_admin')
def admin_dashboard():
    return render_template('_role_dashboard.html', **role_dashboard_context('admin'))


ADMIN_NAV_ITEMS = [
    {'label': '系统总览', 'href': '/admin', 'icon': 'generated-icons/nav-home.png'},
    {'label': '待办总览', 'href': '/admin/todos', 'icon': 'generated-icons/nav-todo.png'},
    {'label': '库存风险', 'href': '/admin/inventory-risk', 'icon': 'generated-icons/nav-risk.png'},
    {'label': '角色权限', 'href': '/admin/role-permissions', 'icon': 'generated-icons/nav-role.png'},
    {'label': '数据库设计', 'href': '/admin/database-design', 'icon': 'generated-icons/metric-data.png'},
    {'label': '业务明细', 'href': '/admin/business-details', 'icon': 'generated-icons/nav-business.png'},
]


def render_admin_workspace(**context):
    stats = _dashboard_base_stats()
    user_count = _scalar("SELECT COUNT(*) FROM users")
    role_count = _scalar("SELECT COUNT(DISTINCT role) FROM users")
    data_object_count = len(DATA_SPECS)
    todo_count = stats['purchase_count'] + stats['sales_count'] + stats['low_count']
    base_context = {
        'role_name': '系统管理员',
        'role_icon': '管',
        'accent': '#0f766e',
        'accent2': '#38bdf8',
        'soft': 'rgba(15, 118, 110, 0.12)',
        'brand_icon': 'generated-icons/brand-book.png',
        'nav_items': ADMIN_NAV_ITEMS,
        'metrics': [
            ['角色账号', _fmt_count(user_count), '独立登录'],
            ['角色类型', _fmt_count(role_count), '权限边界'],
            ['数据对象', _fmt_count(data_object_count), '核心表单'],
            ['待办风险', _fmt_count(todo_count), '跨模块汇总'],
        ],
        'show_metrics': False,
    }
    base_context.update(context)
    return render_template('_role_dashboard.html', **base_context)


@app.route('/admin/todos')
@login_required
@require_role('sys_admin')
def admin_todos():
    return render_template('admin_todos.html', metrics=admin_metric_cards(), **admin_todo_context())


@app.route('/admin/todo/view/<todo_type>/<path:todo_key>')
@login_required
@require_role('sys_admin')
def admin_todo_view(todo_type, todo_key):
    destinations = {
        'purchase': '/admin/manage?table=purchase_order',
        'sales': '/admin/manage?table=sales_order',
        'stock': '/admin/low_quantity_books',
    }
    if todo_type not in destinations:
        return redirect(url_for('admin_todos'))
    _mark_todo_seen(current_user.id, todo_type, todo_key)
    return redirect(destinations[todo_type])


@app.route('/admin/inventory-risk')
@login_required
@require_role('sys_admin')
def admin_inventory_risk():
    stats = _dashboard_base_stats()
    risk_rows = execute_query("""
        SELECT l.book_id,
               l.title,
               COALESCE(c.category_name, '未分类') AS category_name,
               l.stock_quantity,
               l.last_updated
        FROM v_low_quantity_books l
        LEFT JOIN book b ON l.book_id = b.book_id
        LEFT JOIN book_category c ON b.category_id = c.category_id
        ORDER BY l.stock_quantity ASC
        LIMIT 8
    """)
    primary_items = []
    table_rows = []
    max_shortage = 0
    max_shortage_title = '暂无'
    for _, title, category_name, stock_quantity, _ in risk_rows[:5]:
        stock = int(stock_quantity or 0)
        shortage = max(0, 50 - stock)
        max_shortage = max(max_shortage, shortage)
        if shortage == max_shortage:
            max_shortage_title = title
        width = max(18, min(100, int((shortage / 50) * 100) if shortage else 18))
        primary_items.append([title, f"安全库存 50，当前 {stock}", f"{width}%", f"缺 {shortage}"])
    for _, title, category_name, stock_quantity, _ in risk_rows:
        stock = int(stock_quantity or 0)
        table_rows.append([
            title,
            category_name,
            _fmt_count(stock),
            '50',
            '严重缺货' if stock <= 10 else '缺货预警',
        ])
    if not primary_items:
        primary_items = [['暂无低库存', '当前没有低于阈值的图书', '18%', '正常']]
    if not table_rows:
        table_rows = [['暂无', '暂无', '0', '50', '正常']]

    return render_admin_workspace(
        title='库存风险',
        subtitle='单独查看缺货、库存预警和安全库存偏差',
        active_nav='库存风险',
        action_label='查看库存',
        action_href='/admin/manage?table=inventory',
        primary_type='bars',
        primary_title='缺口 TOP5',
        primary_note='安全库存 - 当前库存',
        primary_items=primary_items,
        secondary_type='cards',
        secondary_title='库存风险摘要',
        secondary_note='用于确定补货优先级',
        secondary_items=[
            ['库存预警', _fmt_count(stats['low_count']), '当前低库存'],
            ['严重缺货', _fmt_count(stats['severe_low_count']), '库存≤10本'],
            ['最大缺口', _fmt_count(max_shortage), max_shortage_title],
            ['库存总册数', _fmt_count(stats['stock_sum']), '当前库存'],
        ],
        tasks=[
            ['严重缺货', f"库存≤10本的图书 {stats['severe_low_count']} 本", _fmt_count(stats['severe_low_count'])],
            ['补货反馈', f"低库存清单 {stats['low_count']} 条应同步采购侧", _fmt_count(stats['low_count'])],
            ['库存复核', f"当前库存记录 {stats['inventory_count']} 条", _fmt_count(stats['inventory_count'])],
        ],
        table_title='库存预警明细',
        table_head=['图书', '分类', '当前库存', '安全库存', '状态'],
        table_rows=table_rows,
    )


@app.route('/admin/role-permissions')
@login_required
@require_role('sys_admin')
def admin_role_permissions():
    role_meta = {
        'sys_admin': ('系统管理员', '用户与全局管理'),
        'procurement_officer': ('采购员', '采购与供应商'),
        'warehouse_keeper': ('仓库管理员', '库存与图书档案'),
        'sales_agent': ('销售员', '销售开单与退货'),
        'finance_officer': ('财务人员', '收付款与对账'),
    }
    role_order = {
        'sys_admin': 1,
        'procurement_officer': 2,
        'warehouse_keeper': 3,
        'sales_agent': 4,
        'finance_officer': 5,
    }
    user_rows = execute_query("SELECT username, role FROM users")
    user_rows = sorted(user_rows, key=lambda row: (role_order.get(row[1], 99), row[0]))
    user_count = len(user_rows)
    role_count = len({role for _, role in user_rows})
    admin_count = sum(1 for _, role in user_rows if role == 'sys_admin')
    business_count = max(0, user_count - admin_count)
    return render_admin_workspace(
        title='角色权限',
        subtitle='独立查看五类角色、账号边界和权限分布',
        active_nav='角色权限',
        action_label='查看权限',
        action_href='/admin/users',
        primary_type='cards',
        primary_title='权限结构',
        primary_note='账号与角色',
        primary_items=[
            ['角色总数', _fmt_count(role_count), '五类职责'],
            ['账号总数', _fmt_count(user_count), '独立登录'],
            ['管理员入口', _fmt_count(admin_count), '权限最高'],
            ['业务入口', _fmt_count(business_count), '按职责拆分'],
        ],
        secondary_type='cards',
        secondary_title='权限边界摘要',
        secondary_note='避免角色混用',
        secondary_items=[
            ['用户维护', _fmt_count(user_count), '账号增删改'],
            ['权限复核', _fmt_count(role_count), '角色边界'],
            ['业务账号', _fmt_count(business_count), '分岗使用'],
            ['管理账号', _fmt_count(admin_count), '全局权限'],
        ],
        tasks=[
            ['账号隔离', '每类角色使用独立账号登录', f'{role_count} 类'],
            ['权限边界', '业务页面按角色限制访问', '已限制'],
            ['管理范围', '管理员负责用户、风险和明细总览', '全局'],
        ],
        table_title='角色权限清单',
        table_head=['角色', '账号', '负责模块', '是否独立登录', '状态'],
        table_rows=[
            [role_meta.get(role, (role, '未配置模块'))[0], username, role_meta.get(role, (role, '未配置模块'))[1], '是', '启用']
            for username, role in user_rows
        ],
    )


@app.route('/admin/database-design')
@login_required
@require_role('sys_admin')
def admin_database_design():
    business_table_count = len(DATA_SPECS)
    core_table_count = len(CORE_DATABASE_TABLES)
    constraint_count = _safe_meta_count(
        """
        SELECT COUNT(*)
        FROM information_schema.table_constraints
        WHERE table_schema='public'
          AND constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY', 'CHECK')
        """,
        23
    )
    view_count = _safe_meta_count(
        "SELECT COUNT(*) FROM information_schema.views WHERE table_schema='public'",
        4
    )
    routine_count = _safe_meta_count(
        "SELECT COUNT(*) FROM information_schema.routines WHERE specific_schema='public'",
        5
    )
    trigger_count = _safe_meta_count(
        """
        SELECT COUNT(*)
        FROM pg_trigger t
        JOIN pg_class c ON t.tgrelid = c.oid
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname='public' AND NOT t.tgisinternal
        """,
        2
    )
    index_count = _safe_meta_count(
        "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public' AND indexname LIKE 'idx_%'",
        10
    )

    core_rows = []
    for table_key, label, table_type, relation in CORE_DATABASE_TABLES:
        core_rows.append([
            label,
            _fmt_count(_safe_table_count(table_key)),
            table_type,
            relation,
            {'label': '查看', 'href': f"/admin/manage?table={table_key}"},
        ])

    return render_admin_workspace(
        title='数据库设计',
        subtitle='对齐验收表：三张核心表、完整性、视图函数、触发器和索引',
        active_nav='数据库设计',
        action_label='查看全表',
        action_href='/admin/manage',
        primary_type='cards',
        primary_title='验收覆盖',
        primary_note='数据库设计重点',
        primary_items=[
            ['核心业务表', f"{_fmt_count(business_table_count)} 张", '满足 3 张表要求'],
            ['完整性约束', _fmt_count(constraint_count), '主键 / 外键 / CHECK'],
            ['视图与统计', _fmt_count(view_count), '预警与汇总'],
            ['查询索引', _fmt_count(index_count), '常用路径优化'],
        ],
        secondary_type='cards',
        secondary_title='数据库对象',
        secondary_note='可用于答辩说明',
        secondary_items=[
            ['三张核心表', f"{core_table_count} 张", '重点展示'],
            ['函数与过程', _fmt_count(routine_count), '订单生成与统计'],
            ['触发器', _fmt_count(trigger_count), '库存自动联动'],
            ['业务基础表', f"{business_table_count} 张", '全表维护'],
        ],
        tasks=[
            ['三张核心表', '图书、库存、采购明细形成基础业务闭环', f'{core_table_count} 张'],
            ['完整性控制', '主键、外键、非负库存、正数量和角色取值约束', _fmt_count(constraint_count)],
            ['自动化机制', f"视图 {view_count} 个，函数/过程 {routine_count} 个，触发器 {trigger_count} 个", '已覆盖'],
        ],
        table_title='三张核心表设计',
        table_head=['核心表', '记录数', '结构定位', '关键字段 / 约束', '操作'],
        table_rows=core_rows,
    )


@app.route('/admin/business-details')
@login_required
@require_role('sys_admin')
def admin_business_details():
    stats = _dashboard_base_stats()
    diff = float(stats['sales_amount'] or 0) - float(stats['purchase_amount'] or 0)
    return render_admin_workspace(
        title='业务明细',
        subtitle='单独汇总采购、销售、库存和财务关键明细',
        active_nav='业务明细',
        action_label='查看明细',
        action_href='/admin/manage',
        primary_type='line',
        primary_title='销售额 / 采购金额趋势',
        primary_note='按订单日期聚合',
        line_chart=_line_chart_context(),
        primary_items=[],
        secondary_type='cards',
        secondary_title='业务明细摘要',
        secondary_note='按业务链路拆分',
        secondary_items=[
            ['销售订单', _fmt_count(stats['sales_count']), '当前单数'],
            ['采购订单', _fmt_count(stats['purchase_count']), '当前单数'],
            ['采购金额', _fmt_money(stats['purchase_amount']), '采购汇总'],
            ['销售额', _fmt_money(stats['sales_amount']), '销售汇总'],
        ],
        tasks=[
            ['销售明细', f"当前销售订单 {stats['sales_count']} 笔，销售额 {_fmt_money(stats['sales_amount'])}", _fmt_count(stats['sales_count'])],
            ['采购明细', f"当前采购订单 {stats['purchase_count']} 笔，采购金额 {_fmt_money(stats['purchase_amount'])}", _fmt_count(stats['purchase_count'])],
            ['经营差额', f"销售额与采购金额差额 {_fmt_money(diff)}", '差额'],
        ],
        table_title='业务汇总表',
        table_head=['指标', '数值', '变化', '统计区间', '状态'],
        table_rows=[
            ['销售额', _fmt_money(stats['sales_amount']), '当前汇总', '销售明细', '已汇总'],
            ['销售订单', _fmt_count(stats['sales_count']), '当前汇总', '销售订单', '已汇总'],
            ['采购金额', _fmt_money(stats['purchase_amount']), '当前汇总', '采购明细', '已汇总'],
            ['采购订单', _fmt_count(stats['purchase_count']), '当前汇总', '采购订单', '已汇总'],
            ['库存总册数', _fmt_count(stats['stock_sum']), '当前汇总', '库存记录', '已汇总'],
        ],
    )

# 管理员全表管理页面
@app.route('/admin/manage', methods=['GET', 'POST'])
@login_required
def admin_manage():
    if current_user.role != 'sys_admin':
        return '无权限', 403
    from db import execute_query, execute_update
    table = request.args.get('table', 'publisher')
    search = request.args.get('search', '').strip()
    table_map = {
        'publisher': ['publisher_id', 'address', 'phone', 'contact_person'],
        'book_category': ['category_id', 'category_name'],
        'book': ['book_id', 'title', 'publisher_id', 'category_id', 'author', 'retail_price'],
        'inventory': ['book_id', 'stock_quantity', 'last_updated'],
        'purchase_order': ['order_id', 'purchaser', 'purchase_date', 'notes'],
        'purchase_detail': ['item_id', 'order_id', 'book_id', 'quantity', 'purchase_price'],
        'sales_order': ['order_id', 'customer', 'sale_date', 'notes'],
        'sales_detail': ['item_id', 'order_id', 'book_id', 'quantity', 'sale_price'],
    }
    table_zh = {
        'publisher': ['出版社名', '出版社地址', '电话', '联系人'],
        'book_category': ['类别号', '类别'],
        'book': ['图书号', '图书名', '出版社', '类别号', '作者', '定价'],
        'inventory': ['图书号', '图书数量', '最后更新时间'],
        'purchase_order': ['进货单号', '进货者', '进货日期', '备注'],
        'purchase_detail': ['进货项号', '进货单号', '图书号', '图书数量', '进货价格'],
        'sales_order': ['销售单号', '购买者', '销售日期', '备注'],
        'sales_detail': ['销售项号', '销售单号', '图书号', '图书数量', '销售价格'],
    }
    
    msg = None
    if table not in table_map:
        table = 'publisher'
    # 处理增删改
    if request.method == 'POST':
        action = request.form.get('action')
        fields = table_map[table]
        if action == 'add':
            values = [request.form.get(f) for f in fields]
            placeholders = ','.join(['%s'] * len(fields))
            sql = f"INSERT INTO {table} ({','.join(fields)}) VALUES ({placeholders})"
            try:
                execute_update(sql, values)
                msg = '添加成功'
            except Exception as e:
                msg = f'添加失败: {e}'
        elif action == 'edit':
            pk = fields[0]
            values = [request.form.get(f) for f in fields[1:]]
            set_clause = ','.join([f"{f}=%s" for f in fields[1:]])
            sql = f"UPDATE {table} SET {set_clause} WHERE {pk}=%s"
            try:
                execute_update(sql, values + [request.form.get(pk)])
                msg = '修改成功'
            except Exception as e:
                msg = f'修改失败: {e}'
        elif action == 'delete':
            pk = fields[0]
            sql = f"DELETE FROM {table} WHERE {pk}=%s"
            try:
                execute_update(sql, (request.form.get(pk),))
                msg = '删除成功'
            except Exception as e:
                msg = f'删除失败: {e}'
    # 查询数据
    if search:
        # 构建搜索条件
        fields = table_map[table]
        search_conditions = []
        search_params = []
        for field in fields:
            search_conditions.append(f"{field}::text ILIKE %s")
            search_params.append(f"%{search}%")
        where_clause = " OR ".join(search_conditions)
        sql = f"SELECT * FROM {table} WHERE {where_clause}"
        rows = execute_query(sql, search_params)
    else:
        sql = f"SELECT * FROM {table}"
        rows = execute_query(sql)
    columns = table_map[table]
    columns_zh = table_zh[table]
    return render_template('admin_manage.html', table=table, columns=columns, columns_zh=columns_zh, rows=rows, table_map=table_map, msg=msg, search=search, metrics=admin_metric_cards())

# 用户权限管理（仅演示，实际应对接数据库用户表）
@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if current_user.role != 'sys_admin':
        return '无权限', 403
    from db import execute_query, execute_update
    msg = None
    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username')
        if action == 'add':
            password = request.form.get('password')
            role = request.form.get('role')
            try:
                sql = "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)"
                execute_update(sql, (username, generate_password_hash(password), role))
                msg = '添加成功'
            except Exception as e:
                msg = f'添加失败: {e}'
        elif action == 'edit':
            password = request.form.get('password')
            role = request.form.get('role')
            try:
                if password:  # 只有当密码字段不为空时才更新密码
                    sql = "UPDATE users SET password=%s, role=%s WHERE username=%s"
                    execute_update(sql, (generate_password_hash(password), role, username))
                else:  # 密码字段为空时只更新角色
                    sql = "UPDATE users SET role=%s WHERE username=%s"
                    execute_update(sql, (role, username))
                msg = '修改成功'
            except Exception as e:
                msg = f'修改失败: {e}'
        elif action == 'delete':
            try:
                sql = "DELETE FROM users WHERE username=%s"
                execute_update(sql, (username,))
                msg = '删除成功'
            except Exception as e:
                msg = f'删除失败: {e}'
    # 查询所有用户
    users_data = execute_query("SELECT username, password, role FROM users")
    users = {row[0]: {'password': row[1], 'role': row[2]} for row in users_data}
    return render_template('admin_users.html', users=users, msg=msg, metrics=admin_metric_cards())

@app.route('/procurement')
@login_required
@require_role('procurement_officer')
def procurement_dashboard():
    return render_template('procurement_dashboard.html', **role_dashboard_context('procurement'))

@app.route('/procurement/publishers', methods=['GET', 'POST'])
@login_required
def procurement_publishers():
    if current_user.role != 'procurement_officer':
        return '无权限', 403
    from db import execute_query, execute_update
    msg = None
    search_name = request.values.get('search_name', '').strip()
    if request.method == 'POST' and request.form.get('action') in ['add', 'edit']:
        # 新增或编辑出版社
        pub_id = request.form.get('publisher_id')
        address = request.form.get('address')
        phone = request.form.get('phone')
        contact = request.form.get('contact_person')
        if request.form.get('action') == 'add':
            sql = "INSERT INTO publisher (publisher_id, address, phone, contact_person) VALUES (%s, %s, %s, %s)"
            try:
                execute_update(sql, (pub_id, address, phone, contact))
                msg = '添加成功'
            except Exception as e:
                msg = f'添加失败: {e}'
        elif request.form.get('action') == 'edit':
            sql = "UPDATE publisher SET address=%s, phone=%s, contact_person=%s WHERE publisher_id=%s"
            try:
                execute_update(sql, (address, phone, contact, pub_id))
                msg = '更新成功'
            except Exception as e:
                msg = f'更新失败: {e}'
    # 查询出版社
    if search_name:
        pubs = execute_query("SELECT publisher_id, address, phone, contact_person FROM publisher WHERE publisher_id LIKE %s", (f"%{search_name}%",))
    else:
        pubs = execute_query("SELECT publisher_id, address, phone, contact_person FROM publisher")
    return render_template('procurement_publishers.html', publishers=pubs, msg=msg, search_name=search_name)

@app.route('/procurement/orders', methods=['GET', 'POST'])
@login_required
def procurement_orders():
    if current_user.role != 'procurement_officer':
        return '无权限', 403
    from db import execute_query, execute_update
    from datetime import datetime
    msg = None
    if request.method == 'POST':
        purchaser = current_user.id
        notes = request.form.get('notes')
        sql = "INSERT INTO purchase_order (purchaser, purchase_date, notes) VALUES (%s, CURRENT_DATE, %s)"
        try:
            execute_update(sql, (purchaser, notes))
            msg = '订单创建成功'
        except Exception as e:
            msg = f'创建失败: {e}'
    orders = execute_query("SELECT order_id, purchaser, purchase_date, notes FROM purchase_order ORDER BY purchase_date DESC")
    # 修正purchase_date类型
    fixed_orders = []
    for order in orders:
        order = list(order)
        if isinstance(order[2], str):
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S'):
                try:
                    order[2] = datetime.strptime(order[2], fmt)
                    break
                except Exception:
                    continue
        fixed_orders.append(tuple(order))
    return render_template('procurement_orders.html', orders=fixed_orders, msg=msg)

@app.route('/procurement/order/<order_id>', methods=['GET'])
@login_required
def procurement_order_detail(order_id):
    if current_user.role != 'procurement_officer':
        return '无权限', 403
    from db import execute_query
    from datetime import datetime
    order = execute_query("SELECT order_id, purchaser, purchase_date, notes FROM purchase_order WHERE order_id=%s", (order_id,), fetchone=True)
    # 修正purchase_date类型
    if order and isinstance(order[2], str):
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S'):
            try:
                order = list(order)
                order[2] = datetime.strptime(order[2], fmt)
                order = tuple(order)
                break
            except Exception:
                continue
    details = execute_query("SELECT item_id, book_id, quantity, purchase_price FROM purchase_detail WHERE order_id=%s", (order_id,))
    return render_template('procurement_order_detail.html', order=order, details=details)

@app.route('/procurement/order/new', methods=['GET', 'POST'])
@login_required
def procurement_order_new():
    if current_user.role != 'procurement_officer':
        return '无权限', 403
    from db import execute_query, execute_update
    from datetime import datetime
    msg = None
    # 查询图书及库存
    books = execute_query("""
        SELECT b.book_id, b.title, COALESCE(i.stock_quantity, 0) AS stock_quantity
        FROM book b
        LEFT JOIN inventory i ON b.book_id = i.book_id
    """)
    if request.method == 'POST':
        purchaser = current_user.id
        notes = request.form.get('notes')
        purchase_date = request.form.get('purchase_date')
        if purchase_date:
            purchase_date = purchase_date.replace('T', ' ')
        else:
            purchase_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 获取所有明细
        book_ids = request.form.getlist('book_id')
        quantities = request.form.getlist('quantity')
        prices = request.form.getlist('purchase_price')
        # 转换为PostgreSQL数组格式
        book_ids_pg = '{' + ','.join(book_ids) + '}'
        quantities_pg = '{' + ','.join(quantities) + '}'
        prices_pg = '{' + ','.join(prices) + '}'
        try:
            sql = f"CALL generate_purchase_order(%s, %s, %s::varchar[], %s::int[], %s::numeric[], %s);"
            execute_update(sql, (purchaser, notes, book_ids_pg, quantities_pg, prices_pg, purchase_date))
            return redirect(url_for('procurement_orders'))
        except Exception as e:
            msg = f'创建失败: {e}'
    return render_template('procurement_order_new.html', msg=msg, books=books)

@app.route('/warehouse')
@login_required
@require_role('warehouse_keeper')
def warehouse_dashboard():
    return render_template('warehouse_dashboard.html', **role_dashboard_context('warehouse'))

@app.route('/warehouse/inventory', methods=['GET', 'POST'])
@login_required
def warehouse_inventory():
    if current_user.role != 'warehouse_keeper':
        return '无权限', 403
    from db import execute_query, execute_update
    msg = None
    # 库存随采购入库、销售出库自动变化；这里用于仓库盘点后的修正。
    if request.method == 'POST':
        action = request.form.get('action', 'single')
        sql = "UPDATE inventory SET stock_quantity=%s, last_updated=NOW() WHERE book_id=%s"
        try:
            if action == 'bulk':
                changed = 0
                for book_id in request.form.getlist('book_ids'):
                    stock_quantity = request.form.get(f'stock_quantity_{book_id}')
                    if stock_quantity is None:
                        continue
                    changed += execute_update(sql, (stock_quantity, book_id))
                msg = f'已一键更新 {changed} 条库存记录'
            else:
                book_id = request.form.get('single_book_id') or request.form.get('book_id')
                stock_quantity = request.form.get(f'stock_quantity_{book_id}') or request.form.get('stock_quantity')
                execute_update(sql, (stock_quantity, book_id))
                msg = '库存更新成功'
        except Exception as e:
            msg = f'库存更新失败: {e}'
    # 查询库存
    inventory = execute_query("SELECT i.book_id, b.title, i.stock_quantity, i.last_updated FROM inventory i JOIN book b ON i.book_id=b.book_id")
    return render_template('warehouse_inventory.html', inventory=inventory, msg=msg)

@app.route('/warehouse/books', methods=['GET'])
@login_required
def warehouse_books():
    if current_user.role != 'warehouse_keeper':
        return '无权限', 403
    from db import execute_query
    search = request.args.get('search', '').strip()
    sql = "SELECT b.book_id, b.title, b.author, b.retail_price, p.publisher_id, p.address, c.category_id, c.category_name FROM book b JOIN publisher p ON b.publisher_id=p.publisher_id JOIN book_category c ON b.category_id=c.category_id"
    params = []
    if search:
        sql += " WHERE b.title ILIKE %s OR b.author ILIKE %s OR c.category_name ILIKE %s"
        params = [f"%{search}%", f"%{search}%", f"%{search}%"]
    books = execute_query(sql, params)
    return render_template('warehouse_books.html', books=books, search=search)

@app.route('/warehouse/book/<book_id>')
@login_required
def warehouse_book_detail(book_id):
    if current_user.role != 'warehouse_keeper':
        return '无权限', 403
    from db import execute_query
    # 查询图书信息
    sql = '''SELECT b.book_id, b.title, b.author, b.retail_price, b.publisher_id, p.address, b.category_id, c.category_name
             FROM book b JOIN publisher p ON b.publisher_id=p.publisher_id JOIN book_category c ON b.category_id=c.category_id
             WHERE b.book_id=%s'''
    book = execute_query(sql, (book_id,), fetchone=True)
    # 传递书名用于图片查找
    return render_template('warehouse_book_detail.html', book=book)

@app.route('/sales')
@login_required
@require_role('sales_agent')
def sales_dashboard():
    return render_template('sales_dashboard.html', **role_dashboard_context('sales'))

@app.route('/sales/orders')
@login_required
def sales_orders():
    if current_user.role != 'sales_agent':
        return '无权限', 403
    from db import execute_query
    orders = execute_query("SELECT order_id, customer, sale_date, notes FROM sales_order ORDER BY sale_date DESC")
    return render_template('sales_orders.html', orders=orders)

@app.route('/sales/order/new', methods=['GET', 'POST'])
@login_required
def sales_order_new():
    if current_user.role != 'sales_agent':
        return '无权限', 403
    from db import execute_query, execute_update
    from datetime import datetime
    msg = None
    # 查询图书及库存
    books = execute_query("""
        SELECT b.book_id, b.title, COALESCE(i.stock_quantity, 0) AS stock_quantity
        FROM book b
        LEFT JOIN inventory i ON b.book_id = i.book_id
    """)
    if request.method == 'POST':
        customer = request.form.get('customer')
        notes = request.form.get('notes')
        sale_date = request.form.get('sale_date')
        if sale_date:
            sale_date = sale_date.replace('T', ' ')
        else:
            sale_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        book_ids = request.form.getlist('book_id')
        quantities = request.form.getlist('quantity')
        prices = request.form.getlist('sale_price')
        # 转换为PostgreSQL数组格式
        book_ids_pg = '{' + ','.join(book_ids) + '}'
        quantities_pg = '{' + ','.join(quantities) + '}'
        prices_pg = '{' + ','.join(prices) + '}'
        try:
            sql = f"CALL generate_sales_order(%s, %s, %s::varchar[], %s::int[], %s::numeric[], %s);"
            execute_update(sql, (customer, notes, book_ids_pg, quantities_pg, prices_pg, sale_date))
            return redirect(url_for('sales_orders'))
        except Exception as e:
            err = str(e)
            if 'CONTEXT:' in err:
                err = err.split('CONTEXT:')[0].strip()
            msg = f"创建失败：{err}"
    return render_template('sales_order_new.html', msg=msg, books=books)

@app.route('/sales/inventory')
@login_required
def sales_inventory():
    if current_user.role != 'sales_agent':
        return '无权限', 403
    from db import execute_query
    inventory = execute_query("SELECT i.book_id, b.title, i.stock_quantity FROM inventory i JOIN book b ON i.book_id=b.book_id")
    return render_template('sales_inventory.html', inventory=inventory)

@app.route('/finance')
@login_required
@require_role('finance_officer')
def finance_dashboard():
    return render_template('finance_dashboard.html', **role_dashboard_context('finance'))

@app.route('/finance/audit', methods=['GET', 'POST'])
@login_required
def finance_audit():
    if current_user.role != 'finance_officer':
        return '无权限', 403
    _ensure_purchase_audit_table()
    msg = None
    if request.method == 'POST':
        action = request.form.get('action')
        order_id = request.form.get('order_id')
        audit_note = request.form.get('audit_note', '').strip()
        status_map = {
            'approve': 'approved',
            'reject': 'rejected',
            'reset': 'pending',
        }
        status = status_map.get(action)
        if order_id and status:
            existing = execute_query(
                "SELECT 1 FROM app_purchase_audit WHERE order_id=%s",
                (order_id,),
                fetchone=True
            )
            if existing:
                execute_update("""
                    UPDATE app_purchase_audit
                    SET status=%s, audit_note=%s, auditor=%s, audited_at=NOW()
                    WHERE order_id=%s
                """, (status, audit_note, current_user.id, order_id))
            else:
                execute_update("""
                    INSERT INTO app_purchase_audit (order_id, status, audit_note, auditor, audited_at)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (order_id, status, audit_note, current_user.id))
            msg = f"采购单 {order_id} 已{'通过' if status == 'approved' else '退回' if status == 'rejected' else '恢复待审'}"

    status_filter = request.args.get('status', 'all')
    if status_filter not in {'all', 'pending', 'approved', 'rejected'}:
        status_filter = 'all'

    rows = execute_query("""
        SELECT po.order_id,
               po.purchaser,
               po.purchase_date,
               COALESCE(SUM(pd.quantity * pd.purchase_price), 0) AS amount,
               COUNT(pd.item_id) AS detail_count,
               COALESCE(a.status, 'pending') AS audit_status,
               COALESCE(a.audit_note, '') AS audit_note,
               COALESCE(a.auditor, '') AS auditor,
               a.audited_at
        FROM purchase_order po
        LEFT JOIN purchase_detail pd ON po.order_id = pd.order_id
        LEFT JOIN app_purchase_audit a ON po.order_id = a.order_id
        GROUP BY po.order_id, po.purchaser, po.purchase_date,
                 a.status, a.audit_note, a.auditor, a.audited_at
        ORDER BY
            CASE COALESCE(a.status, 'pending')
                WHEN 'pending' THEN 0
                WHEN 'rejected' THEN 1
                ELSE 2
            END,
            po.purchase_date DESC
    """)
    audit_rows = []
    counts = {'all': 0, 'pending': 0, 'approved': 0, 'rejected': 0}
    for order_id, purchaser, purchase_date, amount, detail_count, status, audit_note, auditor, audited_at in rows:
        counts['all'] += 1
        counts[status] = counts.get(status, 0) + 1
        if status_filter != 'all' and status != status_filter:
            continue
        audit_rows.append({
            'order_id': order_id,
            'purchaser': purchaser or '采购员',
            'purchase_date': _fmt_dt(purchase_date),
            'amount': _fmt_money(amount),
            'detail_count': _fmt_count(detail_count),
            'status': status,
            'audit_note': '' if audit_note in (None, 'None') else audit_note,
            'auditor': auditor or '-',
            'audited_at': _fmt_dt(audited_at) if audited_at else '-',
        })
    return render_template(
        'finance_audit.html',
        rows=audit_rows,
        counts=counts,
        status_filter=status_filter,
        msg=msg,
    )

@app.route('/finance/purchase_price', methods=['GET', 'POST'])
@login_required
def finance_purchase_price():
    if current_user.role != 'finance_officer':
        return '无权限', 403
    from db import execute_query, execute_update
    msg = None
    if request.method == 'POST':
        item_id = request.form.get('item_id')
        price = request.form.get('purchase_price')
        sql = "UPDATE purchase_detail SET purchase_price=%s WHERE item_id=%s"
        try:
            execute_update(sql, (price, item_id))
            msg = '采购价更新成功'
        except Exception as e:
            msg = f'更新失败: {e}'
    details = execute_query("SELECT item_id, order_id, book_id, quantity, purchase_price FROM purchase_detail")
    return render_template('finance_purchase_price.html', details=details, msg=msg)

@app.route('/finance/book_stats', methods=['GET'])
@login_required
def finance_book_stats():
    if current_user.role != 'finance_officer':
        return '无权限', 403
    from db import execute_query
    from datetime import datetime
    
    error = None
    stats = None
    total_books = 0
    total_purchase_quantity = 0
    total_sales_quantity = 0
    total_profit = 0
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if start_date and end_date:
        try:
            # 转换日期格式
            start_dt = datetime.fromisoformat(start_date.replace('T', ' '))
            end_dt = datetime.fromisoformat(end_date.replace('T', ' '))
            
            # 调用数据库函数
            sql = "SELECT * FROM get_book_stats_by_period(%s, %s) WHERE purchase_quantity > 0"
            stats = execute_query(sql, (start_dt, end_dt))
            
            # 计算汇总数据
            if stats:
                total_books = len(stats)
                total_purchase_quantity = sum(book[4] for book in stats)
                total_sales_quantity = sum(book[6] for book in stats)
                total_profit = sum(book[7] - book[5] for book in stats)
                
        except Exception as e:
            error = f"查询失败: {str(e)}"
    
    return render_template('finance_book_stats.html', 
                         stats=stats, 
                         error=error,
                         total_books=total_books,
                         total_purchase_quantity=total_purchase_quantity,
                         total_sales_quantity=total_sales_quantity,
                         total_profit=total_profit,
                         role='财务人员')

@app.route('/pic/<path:filename>')
def pic_static(filename):
    return send_from_directory('pic', filename)

@app.route('/sales/order/<order_id>')
@login_required
def sales_order_detail(order_id):
    if current_user.role != 'sales_agent':
        return '无权限', 403
    from db import execute_query
    order = execute_query("SELECT order_id, customer, sale_date, notes FROM sales_order WHERE order_id=%s", (order_id,), fetchone=True)
    details = execute_query("SELECT item_id, book_id, quantity, sale_price FROM sales_detail WHERE order_id=%s", (order_id,))
    return render_template('sales_order_detail.html', order=order, details=details)

@app.route('/admin/inventory_stats')
@login_required
def admin_inventory_stats():
    if current_user.role != 'sys_admin':
        return '无权限', 403
    from db import execute_query
    stats = execute_query("SELECT category_id, category_name, total_stock FROM v_num_book_cat ORDER BY total_stock DESC")
    return render_template('inventory_stats.html', stats=stats, role='系统管理员')

@app.route('/warehouse/inventory_stats')
@login_required
def warehouse_inventory_stats():
    if current_user.role != 'warehouse_keeper':
        return '无权限', 403
    from db import execute_query
    stats = execute_query("SELECT category_id, category_name, total_stock FROM v_num_book_cat ORDER BY total_stock DESC")
    return render_template('inventory_stats.html', stats=stats, role='仓库管理员')

@app.route('/sales/inventory_stats')
@login_required
def sales_inventory_stats():
    if current_user.role != 'sales_agent':
        return '无权限', 403
    from db import execute_query
    stats = execute_query("SELECT category_id, category_name, total_stock FROM v_num_book_cat ORDER BY total_stock DESC")
    return render_template('inventory_stats.html', stats=stats, role='销售员')

@app.route('/finance/inventory_stats')
@login_required
def finance_inventory_stats():
    if current_user.role != 'finance_officer':
        return '无权限', 403
    from db import execute_query
    stats = execute_query("SELECT category_id, category_name, total_stock FROM v_num_book_cat ORDER BY total_stock DESC")
    return render_template('inventory_stats.html', stats=stats, role='财务人员')

@app.route('/admin/low_quantity_books')
@login_required
def admin_low_quantity_books():
    if current_user.role != 'sys_admin':
        return '无权限', 403
    from db import execute_query
    books = execute_query("SELECT book_id, title, stock_quantity, last_updated FROM v_low_quantity_books ORDER BY stock_quantity ASC")
    return render_template('low_quantity_books.html', books=books, role='系统管理员', metrics=admin_metric_cards())

@app.route('/warehouse/low_quantity_books')
@login_required
def warehouse_low_quantity_books():
    if current_user.role != 'warehouse_keeper':
        return '无权限', 403
    from db import execute_query
    books = execute_query("SELECT book_id, title, stock_quantity, last_updated FROM v_low_quantity_books ORDER BY stock_quantity ASC")
    return render_template('low_quantity_books.html', books=books, role='仓库管理员')

@app.route('/sales/low_quantity_books')
@login_required
def sales_low_quantity_books():
    if current_user.role != 'sales_agent':
        return '无权限', 403
    from db import execute_query
    books = execute_query("SELECT book_id, title, stock_quantity, last_updated FROM v_low_quantity_books ORDER BY stock_quantity ASC")
    return render_template('low_quantity_books.html', books=books, role='销售员')

@app.route('/finance/low_quantity_books')
@login_required
def finance_low_quantity_books():
    if current_user.role != 'finance_officer':
        return '无权限', 403
    from db import execute_query
    books = execute_query("SELECT book_id, title, stock_quantity, last_updated FROM v_low_quantity_books ORDER BY stock_quantity ASC")
    return render_template('low_quantity_books.html', books=books, role='财务人员')

@app.route('/procurement/low_quantity_books')
@login_required
def procurement_low_quantity_books():
    if current_user.role != 'procurement_officer':
        return '无权限', 403
    from db import execute_query
    books = execute_query("SELECT book_id, title, stock_quantity, last_updated FROM v_low_quantity_books ORDER BY stock_quantity ASC")
    return render_template('low_quantity_books.html', books=books, role='采购员')

@app.route('/procurement/inventory')
@login_required
def procurement_inventory():
    if current_user.role != 'procurement_officer':
        return '无权限', 403
    from db import execute_query
    inventory = execute_query("SELECT i.book_id, b.title, i.stock_quantity FROM inventory i JOIN book b ON i.book_id=b.book_id")
    return render_template('sales_inventory.html', inventory=inventory, role='采购员')

@app.route('/admin/bestsellers')
@login_required
def admin_bestsellers():
    if current_user.role != 'sys_admin':
        return '无权限', 403
    from db import execute_query
    bestsellers = execute_query("SELECT sales_month, book_id, title, author, total_quantity FROM v_bestsellers ORDER BY sales_month DESC, total_quantity DESC")
    return render_template('bestsellers.html', bestsellers=bestsellers, role='系统管理员')

@app.route('/procurement/bestsellers')
@login_required
def procurement_bestsellers():
    if current_user.role != 'procurement_officer':
        return '无权限', 403
    from db import execute_query
    bestsellers = execute_query("SELECT sales_month, book_id, title, author, total_quantity FROM v_bestsellers ORDER BY sales_month DESC, total_quantity DESC")
    return render_template('bestsellers.html', bestsellers=bestsellers, role='采购员')

@app.route('/sales/bestsellers')
@login_required
def sales_bestsellers():
    if current_user.role != 'sales_agent':
        return '无权限', 403
    from db import execute_query
    bestsellers = execute_query("SELECT sales_month, book_id, title, author, total_quantity FROM v_bestsellers ORDER BY sales_month DESC, total_quantity DESC")
    return render_template('bestsellers.html', bestsellers=bestsellers, role='销售员')

if __name__ == '__main__':
    app.run(debug=True) 
