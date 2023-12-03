import sys
import time
import json
import asyncio
import httprpc


async def ping(ctx):
    ctx['time'] = time.time()
    return json.dumps(ctx, sort_keys=True, indent=4).encode()

asyncio.run(httprpc.Server().run(
    sys.argv[1], sys.argv[2], int(sys.argv[3]),
    dict(ping=ping)))
