#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ndir-mcp 经 cloudflared 暴露为远端直链（实现见 spectrolink_core.tunnel）。

用法：
  HTTPS_PROXY=http://127.0.0.1:7892 python tools/remote_link.py
  或： NDIR_TOKEN=你的密钥 NDIR_PORT=8005 python tools/remote_link.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spectrolink_core import tunnel          # noqa: E402

if __name__ == "__main__":
    HERE = os.path.dirname(os.path.abspath(__file__))
    tunnel.run("ndir", os.path.join(HERE, "ndir_mcp.py"),
               default_port=8005, env_prefix="NDIR", near_dir=HERE)
