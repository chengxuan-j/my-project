"""回忆录（memoir）领域包。

三条独立管线共享一套数据模型：
- 提取：story_extractor（/chat 落库后异步派发）
- 组织：gap_detector / elicitation / storyboard
- 展示：前端时代轴与故事板（不生成任何画面，状态止于 prompt_ready）

开发计划见 docs/回忆录功能开发计划.md。
"""
