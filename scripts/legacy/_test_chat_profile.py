import requests
import json

# 1. 注册老人
r = requests.post('http://127.0.0.1:8000/api/v1/auth/register', json={
    'username': 'test_chat_sync',
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

# 3. 聊天，问 AI 是否知道画像
r = requests.post('http://127.0.0.1:8000/api/v1/chat', json={
    'message': '你还记得我叫什么名字吗？我有什么爱好？'
}, headers=headers)
print(f'\n聊天响应:')
print(f'  name: {r.json().get("name")}')
print(f'  reply: {r.json().get("reply")}')
