"""检查画像数据的保存和读取"""
import sqlite3
from app.profile.elderly_profile import ProfileStore

def check_db():
    conn = sqlite3.connect('storage/companion.db')

    # 检查 elderly_profiles 表
    print('=== elderly_profiles 表 ===')
    rows = conn.execute('SELECT user_id, name, age, gender, interests FROM elderly_profiles LIMIT 5').fetchall()
    for r in rows:
        print(f'  user_id={r[0]}, name={r[1]}, age={r[2]}, gender={r[3]}, interests={r[4]}')

    # 检查 users 表
    print('\n=== users 表 ===')
    rows = conn.execute('SELECT user_id, profile FROM users LIMIT 5').fetchall()
    import json
    for r in rows:
        p = json.loads(r[1])
        print(f'  user_id={r[0]}, name={p.get("name")}, age={p.get("age")}')

    conn.close()

def test_profile_store():
    print('\n=== 测试 ProfileStore ===')
    store = ProfileStore()

    # 测试读取一个已知用户
    test_user_id = 'e_UfToQjT5ido'  # 从之前的日志看到这个用户
    profile = store.get(test_user_id)
    print(f'用户 {test_user_id} 的画像:')
    print(f'  name: {profile.name}')
    print(f'  age: {profile.age}')
    print(f'  gender: {profile.gender}')
    print(f'  interests: {profile.interests}')

if __name__ == '__main__':
    check_db()
    test_profile_store()
