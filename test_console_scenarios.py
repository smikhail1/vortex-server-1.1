import asyncio
from state_manager import StateManager

async def test_console_logs():
    state = StateManager()
    await state.add_sys_log("TEST", "Console test message")
    dash = await state.get_dashboard_state()
    assert len(dash["system"]["sys_logs"]) > 0
    print("OK: test_console_logs")

if __name__ == "__main__":
    asyncio.run(test_console_logs())
