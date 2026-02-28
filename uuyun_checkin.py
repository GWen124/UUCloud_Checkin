import requests
import os
import time
import subprocess
import json
import re

# === 配置 ===
BASE_URL = "https://www.uuyun.us"
LOGIN_URL = f"{BASE_URL}/auth/login"
CHECKIN_URL = f"{BASE_URL}/user/checkin"
USER_INFO_URL = f"{BASE_URL}/user"

# 伪装浏览器头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/auth/login",
    "X-Requested-With": "XMLHttpRequest"
}

def manage_warp(action):
    """
    WARP IP 切换逻辑
    """
    try:
        print(f"[System] 执行 WARP 操作: {action}...")
        if action == 'restart':
            subprocess.run(["sudo", "warp-cli", "--accept-tos", "disconnect"], check=False, stdout=subprocess.DEVNULL)
            time.sleep(2)
            subprocess.run(["sudo", "warp-cli", "--accept-tos", "connect"], check=True, stdout=subprocess.DEVNULL)
        elif action == 'connect':
            subprocess.run(["sudo", "warp-cli", "--accept-tos", "connect"], check=True, stdout=subprocess.DEVNULL)
        
        time.sleep(5) # 等待连接稳定
    except Exception as e:
        print(f"[System] WARP 操作异常 (可能在本地环境): {e}")

def get_remaining_traffic(session):
    """
    从用户中心页面提取流量信息
    """
    try:
        res = session.get(USER_INFO_URL, timeout=10)
        if res.status_code == 200:
            # 尝试匹配常见的 SSPanel 流量显示格式
            # 格式通常为: 剩余流量：10.5GB 或 <div class="bar">10.24 GB</div>
            match = re.search(r'剩余.*?(\d+(\.\d+)?\s*[GM]B)', res.text)
            if match:
                return match.group(1)
            # 备用匹配
            match_broad = re.search(r'>\s*(\d+(\.\d+)?\s*(GB|MB))\s*<', res.text)
            if match_broad:
                return match_broad.group(1)
    except:
        pass
    return "未知 (无法解析)"

def run_task(account_idx, email, password):
    """
    单个账户的执行流程：登录 -> 签到 -> 查流量
    """
    session = requests.Session()
    session.headers.update(HEADERS)
    
    # 1. 登录
    login_data = {
        "email": email,
        "passwd": password,
        "code": "",         # 验证码字段，通常为空
        "remember_me": "week"
    }
    
    try:
        print(f"[账户 {account_idx}] 正在尝试登录...")
        # 注意：SSPanel 登录通常是 POST 表单数据
        resp = session.post(LOGIN_URL, data=login_data, timeout=15)
        
        try:
            login_json = resp.json()
        except:
            print(f"❌ [账户 {account_idx}] 登录响应解析失败 (可能被防火墙拦截或有验证码)")
            return

        if login_json.get('ret') != 1:
            msg = login_json.get('msg', '未知错误')
            print(f"❌ [账户 {account_idx}] 登录失败: {msg}")
            return

        print(f"✅ [账户 {account_idx}] 登录成功")

        # 2. 签到
        # 签到接口通常需要 json 格式或空数据
        # 更新 Referer 为用户中心
        session.headers.update({"Referer": USER_INFO_URL})
        checkin_resp = session.post(CHECKIN_URL, json={}, timeout=15)
        
        status_log = ""
        traffic_gained = ""
        
        try:
            c_data = checkin_resp.json()
            ret_code = c_data.get('ret', -1)
            msg = c_data.get('msg', '')
            
            if ret_code == 1:
                status_log = "✅ 签到成功"
                traffic_gained = msg # 通常 msg 会包含 "获得了 xx MB"
            else:
                if "已" in msg or "重复" in msg:
                    status_log = "⚠️ 今日已签到"
                else:
                    status_log = f"❌ 签到失败 ({msg})"
                traffic_gained = "无变动"
        except:
            status_log = f"❌ 签到响应解析失败 HTTP {checkin_resp.status_code}"

        # 3. 获取剩余流量
        remain = get_remaining_traffic(session)
        
        # 4. 输出最终日志 (不包含用户名)
        print(f"""
=== [账户 {account_idx}] 报告 ===
状态: {status_log}
本次获得: {traffic_gained}
剩余流量: {remain}
==========================
""")

    except Exception as e:
        print(f"❌ [账户 {account_idx}] 发生异常: {e}")

def main():
    accounts_env = os.environ.get("UUYUN_ACCOUNTS")
    if not accounts_env:
        print("错误：未设置 UUYUN_ACCOUNTS 环境变量")
        return

    # 解析账户
    accounts = []
    for line in accounts_env.split('\n'):
        line = line.strip()
        if not line: continue
        parts = line.split(',')
        if len(parts) >= 2:
            accounts.append((parts[0].strip(), parts[1].strip()))
    
    print(f"检测到 {len(accounts)} 个账户，开始执行任务...\n")

    for idx, (email, pwd) in enumerate(accounts):
        account_num = idx + 1
        
        # --- IP 隔离逻辑 ---
        if idx > 0:
            print(f"正在重置网络环境 (WARP)...")
            manage_warp('restart')
        else:
            manage_warp('connect')
            
        run_task(account_num, email, pwd)
        
        # 账户间冷却时间
        if idx < len(accounts) - 1:
            time.sleep(5)

if __name__ == "__main__":
    main()
