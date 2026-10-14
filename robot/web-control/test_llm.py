"""测试 qwen3.8-flash 的陪聊+函数调用准确性。"""
import json, httpx

URL = "https://llm-p3vxs7hqk42wx4oq.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
KEY = "sk-ws-H.PRMYMER.33v1.MEYCIQDqw92ZLP_mnB-gJMLEeEYzHhbE2IXREDVxsoGB_x5FhgIhAMkeM25WzAoYLNKkzVElrorOjOb9w1GCiv8yl7_eZgVV"
ACTIONS = ["前进","后退","左转","右转","鞠躬","摇摆","握手","戳戳","伸懒腰","前跳","收腿"]
SYS = "你是一只可爱的机器狗,能陪用户聊天。当用户表达动作意图时调用robot_action,把多个连续动作按用户说的顺序放进actions列表。纯聊天时正常温暖回复,不调工具。"
TOOLS = [{"type":"function","function":{"name":"robot_action","description":"控制机器狗做一个或一连串动作",
    "parameters":{"type":"object","properties":{"actions":{"type":"array","items":{"type":"object",
    "properties":{"action":{"type":"string","enum":ACTIONS}},"required":["action"]}}},"required":["actions"]}}}]

tests = ["先向前走然后握个手", "转个圈再鞠个躬", "往前走两步", "你好呀今天心情怎么样", "累不累啊"]
client = httpx.Client(proxy="http://127.0.0.1:7890", timeout=40)
for q in tests:
    r = client.post(URL, headers={"Authorization": f"Bearer {KEY}"}, json={
        "model": "qwen3.8-flash",
        "messages": [{"role":"system","content":SYS},{"role":"user","content":q}],
        "tools": TOOLS,
    })
    m = r.json()["choices"][0]["message"]
    tc = m.get("tool_calls")
    if tc:
        args = json.loads(tc[0]["function"]["arguments"])
        acts = "→".join(a["action"] for a in args.get("actions", []))
        print(f"[{q}] 动作: {acts}")
    else:
        print(f"[{q}] 闲聊: {(m.get('content') or '')[:50]}")
