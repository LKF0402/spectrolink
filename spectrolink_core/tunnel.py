#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把某个 MCP server 经 cloudflared 隧道暴露为远端可直链 URL（安全默认）。

六个技术共用这一份实现，各 server 的 ``tools/remote_link.py`` 只是薄封装。

设计要点（隐私 / 安全）：
  · MCP HTTP 服务器仅监听 127.0.0.1 —— 隧道在本地连接，外部无法直连本机端口
  · 强制 Bearer token：取自 ``<前缀>_TOKEN``，缺省随机生成；不落库、不进仓库
  · cloudflared 把 http://127.0.0.1:PORT 映射为公网 https URL（不出防火墙端口）
  · 经代理出网时自动用 ``<前缀>_TUNNEL_PROXY`` / HTTPS_PROXY / HTTP_PROXY，
    并切到 http2 协议以兼容 HTTP 代理

环境变量（``<前缀>`` 默认由技术名大写推导，如 tdlas → TDLAS）：
  <前缀>_PORT          本地端口，默认 8000
  <前缀>_TOKEN         Bearer 密钥
  <前缀>_TUNNEL_PROXY  cloudflared 出网代理（优先于 HTTPS_PROXY）
"""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import time

_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def settings(tech, default_port=8000, env_prefix=None):
    """解析本次运行的端口/密钥/代理（纯函数，便于离线自测）。"""
    prefix = (env_prefix or tech).upper()
    port = int(os.environ.get(f"{prefix}_PORT", str(default_port)))
    token = os.environ.get(f"{prefix}_TOKEN") or secrets.token_hex(16)
    proxy = (os.environ.get(f"{prefix}_TUNNEL_PROXY")
             or os.environ.get("HTTPS_PROXY")
             or os.environ.get("HTTP_PROXY") or "")
    return {"tech": tech.lower(), "prefix": prefix, "port": port,
            "token": token, "proxy": proxy}


def find_cloudflared(near_dir):
    """先找 PATH，再看脚本同目录下的 cloudflared.exe。"""
    from shutil import which
    for name in ("cloudflared", "cloudflared.exe"):
        if which(name):
            return name
    local = os.path.join(near_dir, "cloudflared.exe")
    return local if os.path.exists(local) else None


def run(tech, mcp_script, default_port=8000, env_prefix=None, near_dir=None):
    """起本地 MCP HTTP → 起隧道 → 打印直链与客户端配置。"""
    cfg = settings(tech, default_port, env_prefix)
    port, token, proxy = cfg["port"], cfg["token"], cfg["proxy"]
    here = near_dir or os.path.dirname(os.path.abspath(__file__))

    srv = subprocess.Popen(
        [sys.executable, mcp_script, "--http", "--host", "127.0.0.1",
         "--port", str(port), "--token", token],
        stderr=subprocess.PIPE, text=True)
    time.sleep(1.5)
    if srv.poll() is not None:
        print("[remote_link] MCP 服务器启动失败：", srv.stderr.read(), file=sys.stderr)
        sys.exit(1)
    print(f"[remote_link] {cfg['tech']} MCP 已起：127.0.0.1:{port}（仅本地）；token 前缀 {token[:8]}…")

    cf = find_cloudflared(here)
    if not cf or not os.path.exists(cf):
        print("[remote_link] 未找到 cloudflared，请先安装：", file=sys.stderr)
        print("  Windows: winget install Cloudflare.cloudflared", file=sys.stderr)
        print("  或下载 cloudflared-windows-amd64.exe 放到 tools/ 下", file=sys.stderr)
        srv.terminate()
        sys.exit(2)

    env = dict(os.environ)
    cmd = [cf, "tunnel", "--url", f"http://127.0.0.1:{port}"]
    if proxy:
        env["HTTPS_PROXY"] = proxy
        env["HTTP_PROXY"] = proxy
        cmd += ["--protocol", "http2"]          # HTTP 代理只能代理 TCP，强制 http2
    print(f"[remote_link] 启动 cloudflared 隧道（代理={proxy or '直连'}）…")
    tunnel = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=env)

    url = None
    try:
        for line in tunnel.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            m = _URL_RE.search(line)
            if m:
                url = m.group(0)
                break
    except (OSError, ValueError, TypeError):     # 管道被关闭/解码失败：按"未解析到 URL"处理
        pass

    if not url:
        print("[remote_link] 未从 cloudflared 输出解析到 URL（代理/网络问题？）", file=sys.stderr)
        srv.terminate()
        tunnel.terminate()
        sys.exit(3)

    print("\n" + "=" * 64)
    print("远端直链已就绪")
    print(f"  MCP URL : {url}/mcp")
    print(f"  Bearer  : {token}   ← 仅本次隧道有效（进程退出即失效）")
    print("  ⚠ 以下含完整 token：不要重定向到日志、不要提交进仓库（stdout 一旦落盘就留下凭据）")
    print("  客户端配置：")
    print(f'  {{ "mcpServers": {{ "{cfg["tech"]}": {{ "type": "http",')
    print(f'    "url": "{url}/mcp",')
    print(f'    "headers": {{ "Authorization": "Bearer {token}" }} }} }} }}')
    print("=" * 64)
    print("按 Ctrl+C 停止（会同时关闭本地服务器与隧道）。")

    try:
        tunnel.wait()
    except KeyboardInterrupt:
        pass
    finally:
        srv.terminate()
        tunnel.terminate()
