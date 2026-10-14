import sqlite3, json

conn = sqlite3.connect('storage/companion.db')
conn.row_factory = sqlite3.Row

print('=== users 表（Agent 读画像）===')
rows = conn.execute('SELECT user_id, profile FROM users').fetchall()
for r in rows:
    p = json.loads(r['profile'])
    print(f"  {r['user_id']}: name={p.get('name')}, age={p.get('age')}, interests={p.get('interests')}")

print()
print('=== elderly_profiles 表（前端写的）===')
try:
    rows = conn.execute('SELECT user_id, name, age, interests FROM elderly_profiles').fetchall()
    for r in rows:
        print(f"  {r['user_id']}: name={r['name']}, age={r['age']}, interests={r['interests']}")
except Exception as e:
    print(f'  查询失败: {e}')

print()
print('=== 所有表 ===')
for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    print(f"  {r['name']}")

conn.close()
