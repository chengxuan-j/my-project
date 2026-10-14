"""测试画像保存后聊天是否能正确使用用户信息"""
import asyncio
import httpx
import sqlite3

async def test():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', timeout=30) as client:
        # 1. 注册新账号
        print('1. 注册新账号...')
        resp = await client.post('/api/v1/auth/register', json={
            'username': 'test_profile_chat',
            'password': '123456',
            'role': 'elderly'
        })
        if resp.status_code != 200:
            print(f'   注册失败: {resp.status_code} {resp.text}')
            return
        data = resp.json()
        user_id = data['user_id']
        token = data['access_token']
        print(f'   注册成功: user_id={user_id}')

        # 2. 保存画像
        print('2. 保存画像...')
        headers = {'Authorization': f'Bearer {token}'}
        resp = await client.put('/api/v1/profile', json={
            'name': '张大妈',
            'age': 75,
            'gender': '女',
            'interests': ['唱歌']
        }, headers=headers)
        print(f'   保存状态: {resp.status_code}')
        if resp.status_code == 200:
            print(f'   保存成功: {resp.json()}')

        # 3. 读取画像验证
        print('3. 读取画像验证...')
        resp = await client.get('/api/v1/profile', headers=headers)
        if resp.status_code == 200:
            profile = resp.json()
            print(f'   读取成功: name={profile.get("name")}, age={profile.get("age")}')

        # 4. 检查数据库
        print('4. 检查数据库...')
        conn = sqlite3.connect('storage/companion.db')
        row = conn.execute(
            'SELECT name, age, gender FROM elderly_profiles WHERE user_id = ?',
            (user_id,)
        ).fetchone()
        if row:
            print(f'   数据库记录: name={row[0]}, age={row[1]}, gender={row[2]}')
        else:
            print('   数据库中没有找到记录')
        conn.close()

        # 5. 聊天测试
        print('5. 聊天测试...')
        resp = await client.post('/api/v1/chat', json={
            'message': '我叫什么名字？'
        }, headers=headers, timeout=30)
        if resp.status_code == 200:
            chat_data = resp.json()
            print(f'   AI 回复: {chat_data.get("reply")}')
            print(f'   返回的 name: {chat_data.get("name")}')
        else:
            print(f'   聊天失败: {resp.status_code} {resp.text}')

asyncio.run(test())
