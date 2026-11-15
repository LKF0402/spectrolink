"""SpectroLink 共用内核（core）—— 多技术 MCP 的共享物理/数学基座。

分层原则：core 只放「物理量级」的纯函数（无任何技术假设），
技术口径（sigma_tau、2f/1f、QTF 谐振等）一律留在各技术服务器。
"""
from . import hitran
from . import stats

__all__ = ["hitran", "stats"]
