"""HelloAgents智能旅行助手 - 后端应用"""

__version__ = "1.0.0"

# ========== 修复 asyncio subprocess transport GC 时的 RuntimeError ==========
# 放在这里确保无论通过 run.py 还是 uvicorn reload 都能生效
import asyncio.base_subprocess

_original_sub_del = getattr(asyncio.base_subprocess.BaseSubprocessTransport, '__del__', None)

if _original_sub_del is not None:
    def _patched_sub_del(self):
        try:
            _original_sub_del(self)
        except RuntimeError:
            pass

    asyncio.base_subprocess.BaseSubprocessTransport.__del__ = _patched_sub_del

try:
    import asyncio.unix_events
    _orig_pipe_del = getattr(asyncio.unix_events._UnixReadPipeTransport, '__del__', None)
    if _orig_pipe_del is not None:
        def _patched_pipe_del(self):
            try:
                _orig_pipe_del(self)
            except RuntimeError:
                pass
        asyncio.unix_events._UnixReadPipeTransport.__del__ = _patched_pipe_del
except (ImportError, AttributeError):
    pass  # Windows 上没有 unix_events