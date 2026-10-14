"""启动脚本：python run.py 即可运行。"""
import os

import uvicorn

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    # 监听 0.0.0.0：允许局域网内其它设备（老人平板 / 家属手机）访问后端
    print("老人情感陪伴 AI Demo 启动中... 本机 http://127.0.0.1:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
