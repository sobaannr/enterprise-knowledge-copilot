import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_protocol_has_no_approval_tool():
    async def check():
        params = StdioServerParameters(command=sys.executable, args=["-m", "copilot.mcp_server"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                result = await client.list_tools()
                names = {tool.name for tool in result.tools}
                assert names == {
                    "search_knowledge",
                    "answer_knowledge",
                    "list_incidents",
                    "prepare_followups",
                    "get_analysis",
                }

    asyncio.run(check())
