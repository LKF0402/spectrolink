#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 tdlas-mcp 经 cloudflared 暴露为远端直链（实现见 spectrolink_core.tunnel）。

用法：
  HTTPS_PROXY=http://127.0.0.1:7892 python tools/remote_link.py
  或： TDLAS_TOKEN=你的密钥 TDLAS_PORT=8000 python tools/remote_link.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spectrolink_core import tunnel          # noqa: E402

if __name__ == "__main__":
    HERE = os.path.dirname(os.path.abspath(__file__))
    tunnel.run("tdlas", os.path.join(HERE, "tdlas_mcp.py"),
               default_port=8000, env_prefix="TDLAS", near_dir=HERE)
