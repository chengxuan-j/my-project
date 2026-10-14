import urllib.request
import json
import time

def do_req(path, data=None, method=None, token=None):
    url = f'http://127.0.0.1:8000{path}'
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if data is None:
        req = urllib.request.Request(url, headers=headers, method=method or 'GET')
    else:
        body = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers=headers, method=method or 'POST')
    resp = urllib.request.urlopen(req)
    text = resp.read().decode('utf-8')
    return json.loads(text) if text else {}

# 1. 注册
reg = do_req('/api/v1/auth/register', {
    'username': 'debug_u1', 'password': 'pwd12345', 'role': 'elderly', 'name': '王阿姨'
})
print('=== 注册响应 ===')
print(json.dumps(reg, ensure_ascii=False, indent=2))
token = reg['access_token']

# 2. 邀请码
print()
print('=== GET /auth/invite-code ===')
ic = do_req('/api/v1/auth/invite-code', token=token)
print(ic)

# 3. 聊天（让AI记住点东西）
print()
print('=== POST /chat ===')
chat = do_req('/api/v1/chat', {'message': '我女儿叫小芳，她在北京工作。'}, token=token)
print('AI reply:', chat.get('reply', '')[:60])
print('recalled_memories:', len(chat.get('recalled_memories', [])))

# 4. 等后台异步记忆提取
time.sleep(5)

# 5. 查记忆
print()
print('=== GET /profile/memories ===')
mems = do_req('/api/v1/profile/memories', token=token)
print(f'记忆总数: {len(mems)}')
for m in mems:
    print(f"  [{m['memory_type']}] {m['content']}")
