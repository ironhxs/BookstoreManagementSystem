import psycopg2
import json

CONFIG_FILE = 'config.json'

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)["db_conn"]

def execute_query(sql, params=None, fetchone=False):
    """执行查询语句，返回全部结果或单条结果"""
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                if fetchone:
                    return cursor.fetchone()
                return cursor.fetchall()
    except Exception as e:
        print(f"执行SQL语句 {sql} 时出现错误：{e}")
        raise

def execute_update(sql, params=None):
    """执行插入、更新、删除等写操作，返回受影响行数"""
    try:
        with psycopg2.connect(**config) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                affected = cursor.rowcount
            conn.commit()
            return affected
    except Exception as e:
        print(f"执行SQL更新语句 {sql} 时出现错误：{e}")
        raise

if __name__ == '__main__':
    print(execute_query('SELECT * FROM book'))