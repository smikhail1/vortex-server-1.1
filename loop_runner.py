import asyncio
from typing import Awaitable, Callable, Optional


async def run_forever(
    name: str,
    coro_factory: Callable[[], Awaitable[None]],
    logger=None,
    delay_on_error: float = 2.0,
) -> None:
    while True:
        try:
            await coro_factory()
        except asyncio.CancelledError:
            if logger:
                logger.warning("LOOP", f"{name} cancelled", {})
            raise
        except Exception as exc:
            if logger:
                logger.error("LOOP", f"{name} crashed", {
                    "error": str(exc),
                    "restart_after_sec": delay_on_error,
                })
            await asyncio.sleep(delay_on_error)


def create_task(coro: Awaitable[None], name: Optional[str] = None) -> asyncio.Task:
    try:
        return asyncio.create_task(coro, name=name)
    except TypeError:
        return asyncio.create_task(coro)