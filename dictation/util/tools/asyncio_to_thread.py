# coding: utf-8
"""
Run blocking functions in a thread

A compatible asyncio.to_thread (it does not exist in Python 3.8).
Runs blocking functions safely from async code.
"""

import functools
import contextvars
from asyncio import events
from typing import Any, Callable, TypeVar

__all__ = ('to_thread',)

T = TypeVar('T')


async def to_thread(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """
    Run a function asynchronously in a separate thread

    Turns a blocking function into a coroutine that runs in the thread pool executor.
    The current contextvars.Context is carried over to the new thread.

    Args:
        func: the function to run
        *args: positional arguments for the function
        **kwargs: keyword arguments for the function

    Returns:
        The function's return value

    Example:
        >>> result = await to_thread(blocking_io_function, arg1, arg2)
    """
    loop = events.get_running_loop()
    ctx = contextvars.copy_context()
    func_call = functools.partial(ctx.run, func, *args, **kwargs)
    return await loop.run_in_executor(None, func_call)
