import sys
import time
import json
import httprpc


async def obj(ctx):
    ctx['time'] = time.time()
    return ctx


async def html(ctx):
    return str(await obj(ctx))


async def octets(ctx):
    return json.dumps(await obj(ctx), sort_keys=True, indent=4).encode()


async def echo(ctx, octets):
    return octets


httprpc.run(int(sys.argv[1]),
            dict(obj=obj, html=html, octets=octets, echo=echo),
            sys.argv[2] if len(sys.argv) > 2 else None)
