import requests
import json

# 1. 注册老人
r = requests.post('http://127.0.0.1:8000/api/v1/auth/register', json={
    'username': 'test_sync',
    'password': 'pwd12345',
    'role': 'elderly',
    'name': '测试奶奶'
})
token = r.json()['access_token']
user_id = r.json()['user_id']
print(f'注册成功: user_id={user_id}')

# 2. 保存画像（用新 API）
headers = {'Authorization': f'Bearer {token}'}
r = requests.put('http://127.0.0.1:8000/api/v1/profile', json={
    'name': '王奶奶',
    'age': 83,
    'interests': ['下棋', '养花']
}, headers=headers)
print(f'保存画像: {r.status_code}')
print(f'返回: {r.json()}')

# 3. 检查 users 表（Agent 读的地方）
import sqlite3
conn = sqlite3.connect('storage/companion.db')
conn.row_factory = sqlite3.Row
row = conn.execute('SELECT profile FROM users WHERE user_id = ?', (user_id,)).fetchone()
if row:
    p = json.loads(row['profile'])
    print(f'\n=== users 表（Agent 读）===')
    print(f'name={p.get("name")}, age={p.get("age")}, interests={p.get("interests")}')
else:
    print(f'\nusers 表没有 user_id={user_id}')

# 4. 检查 elderly_profiles 表（前端写的地方）
row = conn.execute('SELECT name, age, interests FROM elderly_profiles WHERE user_id = ?', (user_id,)).fetchone()
if row:
    print(f'\n=== elderly_profiles 表（前端写）===')
    print(f'name={row["name"]}, age={row["age"]}, interests={row["interests"]}')
else:
    print(f'\nelderly_profiles 表没有 user_id={user_id}')

conn.close()
