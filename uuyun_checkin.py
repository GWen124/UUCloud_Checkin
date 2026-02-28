import requests
import os
import time
import subprocess
import json
import re
import sys

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

def log(content):
    """实时输出日志"""
    print(content, flush=True)

def manage_warp(action):
    """
    WARP IP 切换逻辑
    action: 'connect' | 'restart'
    """
    try:
        if action == 'restart':
            log("[Network] 正在断开 WARP...")
            subprocess.run(["sudo", "warp-cli", "disconnect"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
            log("[Network] 正在重新连接 WARP (更换 IP)...")
            subprocess.run(["sudo", "warp-cli", "connect"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif action == 'connect':
            log("[Network] 正在初始化 WARP 连接...")
            subprocess.run(["sudo", "warp-cli", "connect"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 等待连接稳定，GitHub Actions 环境有时候比较慢
        time.sleep(8) 
        
        # 简单检查 (可选)
        try:
            # 这里的 check 是为了确认网络通畅，不记录具体 IP 以保护隐私
            subprocess.run(["curl", "-Is", "https://www.google.com"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log("[Network] 网络连接正常")
        except:
            log("[Network] ⚠️ 警告: 网络似乎未就绪，但在重试中...")

    except Exception as e:
        log(f"[System] WARP 操作异常: {e}")

def get_remaining_traffic(session):
    """
    从用户中心页面提取剩余流量
    """
    try:
        res = session.get(USER_INFO_URL, timeout=15)
        if res.status_code == 200:
            # 尝试匹配常见的 SSPanel 流量显示格式
            # 格式通常为: 剩余流量：10.5GB 或 <div class="bar">10.24 GB</div>
            match = re.search(r'剩余.*?(\d+(\.\d+)?\s*[GM]B)', res.text)
            if match:
                return match.group(1)
            # 备用匹配：匹配带单位的数字
            match_broad = re.search(r'>\s*(\d+(\.\d+)?\s*(GB|MB))\s*<', res.text)
            if match_broad:
                return match_broad.group(1)
    except:
        pass
    return "解析失败"

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
        "code": "",         # 验证码字段
        "remember_me": "week"
    }
    
    try:
        log(f"--- 正在处理: 账户 {account_idx} ---")
        
        # 发送登录请求
        resp = session.post(LOGIN_URL, data=login_data, timeout=20)
        
        try:
            login_json = resp.json()
        except:
            log(f"❌ [账户 {account_idx}] 登录失败: 无法解析响应 (可能是 Cloudflare 质询拦截)")
            return

        if login_json.get('ret') != 1:
            msg = login_json.get('msg', '未知错误')
            log(f"❌ [账户 {account_idx}] 登录失败: {msg}")
            return

        log(f"✅ [账户 {account_idx}] 登录成功")

        # 2. 签到
        session.headers.update({"Referer": USER_INFO_URL})
        checkin_resp = session.post(CHECKIN_URL, json={}, timeout=20)
        
        status_log = ""
        traffic_gained = ""
        
        try:
            c_data = checkin_resp.json()
            ret_code = c_data.get('ret', -1)
            msg = c_data.get('msg', '')
            
            if ret_code == 1:
                status_log = "✅ 签到成功"
                traffic_gained = msg 
            else:
                if "已" in msg or "重复" in msg:
                    status_log = "⚠️ 今日已签到"
                else:
                    status_log = f"❌ 签到失败 ({msg})"
                traffic_gained = "无变动"
        except:
            status_log = f"❌ 签到响应异常 HTTP {checkin_resp.status_code}"

        # 3. 获取剩余流量
        remain = get_remaining_traffic(session)
        
        # 4. 输出最终报告
        log(f"""
=== [账户 {account_idx}] 结果 ===
状态: {status_log}
获得: {traffic_gained}
剩余: {remain}
==========================
""")

    except Exception as e:
        log(f"❌ [账户 {account_idx}] 发生程序异常: {e}")

def main():
    accounts_env = os.environ.get("UUYUN_ACCOUNTS")
    if not accounts_env:
        log("错误：未设置 UUYUN_ACCOUNTS 环境变量")
        return

    # 解析账户
    accounts = []
    for line in accounts_env.split('\n'):
        line = line.strip()
        if not line: continue
        # 兼容逗号分隔
        parts = line.split(',')
        if len(parts) >= 2:
            accounts.append((parts[0].strip(), parts[1].strip()))
    
    log(f"检测到 {len(accounts)} 个账户，开始执行任务...\n")

    for idx, (email, pwd) in enumerate(accounts):
        # --- IP 隔离逻辑 ---
        # 如果是第一个账户，连接 WARP；如果是后续账户，重启 WARP 以切换 IP
        if idx == 0:
            manage_warp('connect')
        else:
            log(f"等待 5 秒后切换 IP...")
            time.sleep(5)
            manage_warp('restart')
            
        run_task(idx + 1, email, pwd)

if __name__ == "__main__":
    main()
