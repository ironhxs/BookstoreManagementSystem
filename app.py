from flask import Flask, render_template, redirect, url_for, request, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from db import execute_query, execute_update
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


app = Flask(__name__)
app.secret_key = 'your_secret_key'
login_manager = LoginManager(app)
login_manager.login_view = 'login'


class User(UserMixin):
    def __init__(self, username, role):
        self.id = username
        self.role = role


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
def admin_dashboard():
    return render_template('admin_dashboard.html')

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
    return render_template('admin_manage.html', table=table, columns=columns, columns_zh=columns_zh, rows=rows, table_map=table_map, msg=msg, search=search)

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
    return render_template('admin_users.html', users=users, msg=msg)

@app.route('/procurement')
@login_required
def procurement_dashboard():
    return render_template('procurement_dashboard.html')

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
def warehouse_dashboard():
    return render_template('warehouse_dashboard.html')

@app.route('/warehouse/inventory', methods=['GET', 'POST'])
@login_required
def warehouse_inventory():
    if current_user.role != 'warehouse_keeper':
        return '无权限', 403
    from db import execute_query, execute_update
    msg = None
    # 更新库存
    if request.method == 'POST':
        book_id = request.form.get('book_id')
        stock_quantity = request.form.get('stock_quantity')
        sql = "UPDATE inventory SET stock_quantity=%s, last_updated=NOW() WHERE book_id=%s"
        try:
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
def sales_dashboard():
    return render_template('sales_dashboard.html')

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
def finance_dashboard():
    return render_template('finance_dashboard.html')

@app.route('/finance/audit')
@login_required
def finance_audit():
    if current_user.role != 'finance_officer':
        return '无权限', 403
    from db import execute_query
    table = request.args.get('table', 'purchase_detail')
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
    if table not in table_map:
        table = 'purchase_detail'
    sql = f"SELECT * FROM {table}"
    rows = execute_query(sql)
    columns = table_map[table]
    columns_zh = table_zh[table]
    return render_template('finance_audit.html', table=table, columns=columns, columns_zh=columns_zh, rows=rows, table_map=table_map)

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
    return render_template('low_quantity_books.html', books=books, role='系统管理员')

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