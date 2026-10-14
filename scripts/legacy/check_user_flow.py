"""检查用户流程：保存画像 -> 聊天"""
import asyncio
import httpx
from app.db import get_conn

async def test_flow():
    # 1. 登录一个测试账号
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        # 登录
        resp = await client.post("/api/v1/auth/login", json={
            "username": "test_profile_u1",
            "password": "123456"
        })
        if resp.status_code != 200:
            print(f"登录失败: {resp.status_code}")
            return

        data = resp.json()
        user_id = data["user_id"]
        token = data["access_token"]
        print(f"登录成功: user_id={user_id}")

        headers = {"Authorization": f"Bearer {token}"}

        # 2. 保存画像
        resp = await client.put("/api/v1/profile", json={
            "name": "张大妈",
            "age": 75,
            "gender": "女",
            "interests": ["唱歌"]
        }, headers=headers)
        print(f"保存画像: {resp.status_code}")
        print(f"保存结果: {resp.json()}")

        # 3. 读取画像验证
        resp = await client.get("/api/v1/profile", headers=headers)
        print(f"读取画像: {resp.status_code}")
        profile_data = resp.json()
        print(f"读取结果: name={profile_data.get('name')}, age={profile_data.get('age')}")

        # 4. 检查数据库
        with get_conn() as conn:
            row = conn.execute(
                "SELECT name, age, gender FROM elderly_profiles WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if row:
                print(f"数据库中的画像: name={row['name']}, age={row['age']}, gender={row['gender']}")
            else:
                print("数据库中没有找到画像")

        # 5. 聊天测试
        resp = await client.post("/api/v1/chat", json={
            "message": "我叫什么名字？"
        }, headers=headers)
        print(f"聊天响应: {resp.status_code}")
        chat_data = resp.json()
        print(f"AI 回复: {chat_data.get('reply')}")
        print(f"返回的 name: {chat_data.get('name')}")

if __name__ == "__main__":
    asyncio.run(test_flow())
