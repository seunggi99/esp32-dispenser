import asyncio

_pending: dict[int, asyncio.Future] = {}
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def wait_for_result(command_id: int) -> asyncio.Future:
    future = asyncio.get_running_loop().create_future()
    _pending[command_id] = future
    return future


def cancel_wait(command_id: int) -> None:
    _pending.pop(command_id, None)


def notify_result(command_id: int, reported) -> None:
    future = _pending.pop(command_id, None)
    if future is None or _loop is None:
        return
    _loop.call_soon_threadsafe(_resolve, future, reported)


def _resolve(future: asyncio.Future, reported) -> None:
    if not future.done():
        future.set_result(reported)
