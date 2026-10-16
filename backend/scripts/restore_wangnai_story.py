# -*- coding: utf-8 -*-
"""恢复王奶奶的「东北插队」故事（昨天实时回忆真实产生，被测试清理误删），
并删除今天探针的测试残留对话。"""
import json
import sqlite3

con = sqlite3.connect("E:/elderly_companion/storage/companion.db")

# 1. 删今天探针的测试残留（id=276，删除条件漏了前缀的那条）
n = con.execute("delete from conversations where id = 276").rowcount

# 2. 从 conversations 原文恢复故事（271-274 是老人真实聊的）
raw = json.dumps(
    [
        {"role": "user", "content": "想当年我在东北插队，零下三十度也下地"},
        {"role": "assistant", "content": "王奶奶，零下三十度，您咋扛过来的？"},
    ],
    ensure_ascii=False,
)
con.execute(
    "insert into life_stories (elderly_user_id, title, summary, raw_dialogue,"
    " time_type, time_value, time_confidence, era_tags, place, people,"
    " emotion_tone, completeness, status, visibility, visibility_locked,"
    " avoid_flag, created_at, updated_at)"
    " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    (
        "e_UfToQjT5ido", "东北插队",
        "老人在东北插队时，寒冬零下三十度仍坚持下地劳动。",
        raw, "era_anchor", "插队", 0.9, '["知青年代"]', "东北", "[]",
        "辛酸", 0.7, "archived", "family", 0, 0,
        "2026-10-15 17:23:09", "2026-10-15 17:23:09",
    ),
)
con.commit()

print("删测试残留 %d 条；恢复故事 1 条" % n)
for r in con.execute(
    "select id, elderly_user_id, title, status, visibility, era_tags, place"
    " from life_stories"
):
    print(" ", r)
print("conversations 总数:", con.execute("select count(*) from conversations").fetchone()[0])
con.close()
