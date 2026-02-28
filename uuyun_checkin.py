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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/auth/login",
    "X-Requested-With": "XMLHttpRequest"
}

def log(content):
    print(content, flush=True)

def manage_warp(action):
    """
    WARP IP 切换逻辑 (修复版)
    """
    try:
        # 统一添加 --accept-tos 防止新版客户端报错
        cmd_prefix = ["sudo", "warp-cli", "--accept-tos"]
        
        if action == 'restart':
            log("[Network] 正在切换 IP (重置 WARP)...")
            subprocess.run(cmd_prefix + ["disconnect"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            subprocess.run(cmd_prefix + ["connect"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        elif action == 'connect':
            log("[Network] 正在初始化 WARP 连接...")
            # 先尝试断开，确保状态干净，防止 'Already connected' 报错
            subprocess.run(cmd_prefix + ["disconnect"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
            subprocess.run(cmd_prefix + ["connect"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        time.sleep(5) # 等待连接建立
        
    except subprocess.CalledProcessError as e:
        log(f"[System] WARP 命令执行失败 (代码 {e.returncode})，但这可能不影响后续运行。")
    except Exception as e:
        log(f"[System] WARP 操作异常: {e}")

def get_remaining_traffic(session):
    """
    从用户中心页面提取剩余流量 (增强版)
    """
    try:
        res = session.get(USER_INFO_URL, timeout=15)
        if res.status_code == 200:
            html = res.text
            # 策略1: 针对截图中的卡片布局，通常会有 "剩余流量" 字样
            # 增加对 TB/KB 的支持，使用 re.DOTALL (re.S) 跨行匹配
            # 匹配逻辑: "剩余" -> 任意字符 -> 数字 -> 单位(TB/GB/MB/KB)
            match = re.search(r'剩余.*?>\s*(\d+(\.\d+)?\s*[TGMK]B)', html, re.S)
            if match:
                return match.group(1)
            
            # 策略2: 如果策略1失败，匹配纯文本格式 (例如: 剩余流量: 976.6 TB)
            match_text = re.search(r'剩余.*?(\d+(\.\d+)?\s*[TGMK]B)', html, re.S)
            if match_text:
                return match_text.group(1)

            # 策略3: 盲抓大字号数字 (备用)
            # 截图中的 976.6 TB 非常显眼，通常在某个标签内
            match_broad = re.search(r'>\s*(\d+(\.\d+)?\s*(TB|GB|MB))\s*<', html)
            if match_broad:
                return match_broad.group(1)
                
    except Exception as e:
        return f"提取出错: {str(e)}"
    return "解析失败 (未匹配到格式)"

def run_task(account_idx, email, password):
    session = requests.Session()
    session.headers.update(HEADERS)
    
    # 1. 登录
    login_data = {
        "email": email,
        "passwd": password,
        "code": "",
        "remember_me": "week"
    }
    
    try:
        # log(f"--- 正在处理: 账户 {account_idx} ---") # 减少日志冗余
        resp = session.post(LOGIN_URL, data=login_data, timeout=20)
        
        try:
            login_json = resp.json()
        except:
            log(f"❌ [账户 {account_idx}] 登录失败: 无法解析响应")
            return

        if login_json.get('ret') != 1:
            log(f"❌ [账户 {account_idx}] 登录失败: {login_json.get('msg')}")
            return

        log(f"✅ [账户 {account_idx}] 登录成功")

        # 2. 签到
        session.headers.update({"Referer": USER_INFO_URL})
        checkin_resp = session.post(CHECKIN_URL, json={}, timeout=20)
        
        status_log = ""
        traffic_gained = ""
        
        try:
            c_data = checkin_resp.json()
            if c_data.get('ret') == 1:
                status_log = "✅ 签到成功"
                traffic_gained = c_data.get('msg')
            else:
                msg = c_data.get('msg', '')
                status_log = "⚠️ 今日已签到" if "已" in msg or "重复" in msg else f"❌ 签到失败 ({msg})"
                traffic_gained = "无变动"
        except:
            status_log = "❌ 接口异常"

        # 3. 获取剩余流量
        remain = get_remaining_traffic(session)
        
        # 4. 输出报告
        log(f"""
=== [账户 {account_idx}] 结果 ===
状态: {status_log}
获得: {traffic_gained}
剩余: {remain}
==========================
""")

    except Exception as e:
        log(f"❌ [账户 {account_idx}] 异常: {e}")

def main():
    accounts_env = os.environ.get("UUYUN_ACCOUNTS")
    if not accounts_env:
        log("错误：未设置 UUYUN_ACCOUNTS")
        return

    accounts = []
    for line in accounts_env.split('\n'):
        line = line.strip()
        if not line: continue
        parts = line.split(',')
        if len(parts) >= 2:
            accounts.append((parts[0].strip(), parts[1].strip()))
    
    log(f"检测到 {len(accounts)} 个账户，开始执行任务...\n")

    for idx, (email, pwd) in enumerate(accounts):
        # 第一个账户只连不切，后续账户切换IP
        # 使用 'connect' 会触发先 disconnect 再 connect，解决冲突问题
        if idx == 0:
            manage_warp('connect')
        else:
            manage_warp('restart')
            
        run_task(idx + 1, email, pwd)

if __name__ == "__main__":
    main()
