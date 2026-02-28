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
    WARP IP 切换逻辑
    """
    try:
        cmd_prefix = ["sudo", "warp-cli", "--accept-tos"]
        
        if action == 'restart':
            log("[Network] 正在切换 IP (重置 WARP)...")
            subprocess.run(cmd_prefix + ["disconnect"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            subprocess.run(cmd_prefix + ["connect"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        elif action == 'connect':
            log("[Network] 正在初始化 WARP 连接...")
            subprocess.run(cmd_prefix + ["disconnect"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
            subprocess.run(cmd_prefix + ["connect"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        time.sleep(5)
        
    except Exception as e:
        log(f"[System] WARP 操作异常: {e}")

def convert_to_mb(value_str):
    """辅助函数：将流量字符串转换为 MB 以便比较大小"""
    value_str = value_str.upper()
    try:
        if 'TB' in value_str:
            return float(re.findall(r"[\d\.]+", value_str)[0]) * 1024 * 1024
        elif 'GB' in value_str:
            return float(re.findall(r"[\d\.]+", value_str)[0]) * 1024
        elif 'MB' in value_str:
            return float(re.findall(r"[\d\.]+", value_str)[0])
        elif 'KB' in value_str:
            return float(re.findall(r"[\d\.]+", value_str)[0]) / 1024
    except:
        return 0
    return 0

def get_remaining_traffic(session):
    """
    从用户中心页面提取剩余流量 (终极增强版)
    """
    try:
        res = session.get(USER_INFO_URL, timeout=15)
        # 强制设置编码，防止中文匹配乱码
        res.encoding = 'utf-8' 
        
        if res.status_code == 200:
            html = res.text
            
            # --- 方案 1: 精准匹配 "剩余" 字样 ---
            # 扩大匹配范围，忽略换行符
            match = re.search(r'剩余.*?>\s*(\d+(?:\.\d+)?\s*[TGMK]B)', html, re.S)
            if match:
                return match.group(1)

            # --- 方案 2: 暴力扫描所有流量格式，取最大值 ---
            # 既然你的剩余流量高达 976.6 TB，它一定是页面上最大的那个数字
            all_traffic = re.findall(r'(\d+(?:\.\d+)?\s*[TGMK]B)', html)
            if all_traffic:
                # 排除掉明显是年份的数字 (如 2026 MB 这种误判，虽不常见但以防万一)
                valid_traffic = [t for t in all_traffic if "202" not in t] 
                if valid_traffic:
                    # 找出数值最大的那个
                    max_traffic = max(valid_traffic, key=convert_to_mb)
                    return f"{max_traffic} (自动识别最大值)"
            
            # --- 调试信息: 如果还是失败，打印页面关键部分 ---
            if "剩余" in html:
                idx = html.find("剩余")
                # 打印 "剩余" 后面 200 个字符，看看网页结构到底长啥样
                snippet = html[idx:idx+200].replace('\n', ' ').replace('\r', '')
                return f"解析失败. 页面片段: {snippet}..."
            else:
                return "解析失败. 页面中未找到 '剩余' 二字 (可能是动态渲染或登录失效)"

    except Exception as e:
        return f"提取出错: {str(e)}"
    return "解析失败 (未知原因)"

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
        if idx == 0:
            manage_warp('connect')
        else:
            manage_warp('restart')
            
        run_task(idx + 1, email, pwd)

if __name__ == "__main__":
    main()
