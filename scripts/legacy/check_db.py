import sqlite3
import json

conn = sqlite3.connect('storage/companion.db')

# 检查所有表
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print('数据库中的表:', tables)

# 检查 elderly_profiles 表
if 'elderly_profiles' in tables:
    cursor = conn.execute('SELECT COUNT(*) FROM elderly_profiles')
    print('\nelderly_profiles 记录数:', cursor.fetchone()[0])

    cursor = conn.execute('SELECT user_id, name, age FROM elderly_profiles LIMIT 5')
    print('elderly_profiles 数据:')
    for row in cursor.fetchall():
        print(f'  user_id: {row[0]}, name: {row[1]}, age: {row[2]}')
else:
    print('\nelderly_profiles 表不存在')

# 检查 users 表
if 'users' in tables:
    cursor = conn.execute('SELECT COUNT(*) FROM users')
    print('\nusers 记录数:', cursor.fetchone()[0])

    cursor = conn.execute('SELECT user_id, profile FROM users LIMIT 3')
    print('users 数据:')
    for row in cursor.fetchall():
        profile = json.loads(row[1])
        print(f'  user_id: {row[0]}, name: {profile.get("name", "N/A")}')

conn.close()
