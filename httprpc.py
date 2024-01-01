import sys
import ssl
import gzip
import time
import json
import uuid
import pickle
import asyncio
import traceback
import urllib.parse
import logging
from logging import critical as log


class Server():
    async def _handler(self, reader, writer):
        peer = None
        count = 1

        while True:
            try:
                peer = writer.get_extra_info('socket').getpeername()
                ctx = dict(ip=peer[0])

                cert = writer.get_extra_info('peercert')
                subject = str(uuid.UUID(cert['subject'][0][0][1]))
                ip_list = [y for x, y in cert['subjectAltName']
                           if 'IP Address' == x]

                if peer[0] in ip_list:
                    ctx['subject'] = subject
            except Exception:
                pass

            try:
                line = await reader.readline()
                p = line.decode().split()[1].strip('/').split('/')

                method = p[0]
                params = {k.lower(): urllib.parse.unquote(v)
                          for k, v in zip(p[1::2], p[2::2])}

                in_gzip = out_gzip = content_type = length = 0
                while True:
                    line = await reader.readline()
                    line = line.strip()
                    if not line:
                        break
                    k, v = line.decode().split(':', maxsplit=1)
                    if 'content-length' == k.strip().lower():
                        length = int(v.strip())
                    if 'content-type' == k.strip().lower():
                        content_type = v.strip().lower()
                    if 'content-encoding' == k.strip().lower():
                        if 'gzip' in v.strip().lower().split():
                            in_gzip = True
                    if 'accept-encoding' == k.strip().lower():
                        if 'gzip' in v.strip().lower().split(', '):
                            out_gzip = True

                if length > 0:
                    octets = await reader.readexactly(length)
                    if length != len(octets):
                        raise Exception('TRUNCATED_MSG_BODY')

                    if in_gzip is True:
                        octets = gzip.decompress(octets)

                    if content_type == 'application/httprpc-python-pickle':
                        params['obj'] = pickle.loads(octets)
                    elif content_type == 'application/json':
                        params['obj'] = json.loads(octets.decode())
                    elif content_type == 'text/plain':
                        params['text'] = octets.decode()
                    else:
                        params['octets'] = octets

            except Exception:
                return writer.close()

            try:
                octets = await self.methods[method](ctx, **params)
                status = content_type = None

                if type(octets) is bytes:
                    content_type = 'application/octet-stream'

                elif type(octets) is str:
                    octets = octets.encode()
                    content_type = 'text/html'

                else:
                    try:
                        octets = json.dumps(octets, indent=4).encode()
                        content_type = 'application/json'
                    except Exception:
                        octets = pickle.dumps(octets)
                        content_type = 'application/httprpc-python-pickle'

                if content_type:
                    status = '200 OK'
            except Exception:
                traceback.print_exc()
                octets = traceback.format_exc().encode()
                status = '500 Internal Server Error'

            try:
                writer.write(f'HTTP/1.1 {status}\n'.encode())
                writer.write(f'content-type: {content_type}\n'.encode())

                if out_gzip is True:
                    octets = gzip.compress(octets)
                    writer.write('content-encoding: gzip\n'.encode())

                writer.write(f'content-length: {len(octets)}\n\n'.encode())
                writer.write(octets)
                await writer.drain()
            except Exception:
                return writer.close()

            log(f'{peer} count({count}) status({status}) '
                f'in_len({length}) out_len({len(octets)}) '
                f'{method}({", ".join(params.keys())})')
            count += 1

    async def run(self, ip, port, methods, cert=None, cacert=None):
        self.methods = methods

        ctx = None
        if cert:
            if not cacert:
                cacert = cert

            ctx = ssl.create_default_context(
                cafile=cacert, purpose=ssl.Purpose.CLIENT_AUTH)
            ctx.load_cert_chain(cert, cert)
            ctx.verify_mode = ssl.CERT_OPTIONAL
            ctx.check_hostname = True

        srv = await asyncio.start_server(self._handler, ip, port, ssl=ctx)
        async with srv:
            return await srv.serve_forever()


def run(port, handlers, cert=None, cacert=None, ip=None):
    asyncio.run(Server().run(ip, port, handlers, cert, cacert))


class Client():
    def __init__(self, cacert, cert, servers):
        servers = [s.split(':') for s in servers.split(',')]

        self.SSL = ssl.create_default_context(
            cafile=cacert, purpose=ssl.Purpose.SERVER_AUTH)
        self.SSL.load_cert_chain(cert, cert)
        self.SSL.verify_mode = ssl.CERT_REQUIRED
        self.SSL.check_hostname = True

        self.conns = {(ip, int(port)): (None, None) for ip, port in servers}
        self.quorum = int(len(self.conns)/2) + 1

    async def server(self, server, resource, octets=b''):
        status = None

        try:
            if self.conns[server][0] is None or self.conns[server][1] is None:
                self.conns[server] = await asyncio.open_connection(
                    server[0], server[1], ssl=self.SSL)

            reader, writer = self.conns[server]

            if type(octets) is bytes:
                content_type = 'application/octet-stream'
            elif type(octets) is str:
                octets = octets.encode()
                content_type = 'text/plain'
            else:
                try:
                    octets = json.dumps(octets, indent=4).encode()
                    content_type = 'application/json'
                except Exception:
                    octets = pickle.dumps(octets)
                    content_type = 'application/httprpc-python-pickle'

            writer.write(f'POST {resource} HTTP/1.1\n'.encode())
            writer.write(f'content-type: {content_type}\n'.encode())
            writer.write(f'content-length: {len(octets)}\n\n'.encode())
            writer.write(octets)
            await writer.drain()

            status = await reader.readline()
            content_type = None

            while True:
                line = await reader.readline()
                line = line.strip()
                if not line:
                    break
                k, v = line.decode().split(':', maxsplit=1)
                if 'content-type' == k.strip().lower():
                    content_type = v.strip().lower()
                if 'content-length' == k.strip().lower():
                    length = int(v.strip())

            octets = await reader.readexactly(length)
            if length != len(octets):
                raise Exception('TRUNCATED_MSG_BODY')

            if status.startswith(b'HTTP/1.1 200 OK'):
                if content_type == 'application/octet-stream':
                    return octets

                if content_type == 'text/html':
                    return octets.decode()

                if content_type == 'application/json':
                    return json.loads(octets.decode())

                if content_type == 'application/httprpc-python-pickle':
                    return pickle.loads(octets)

            raise Exception(octets.decode())
        except Exception:
            if self.conns[server][1] is not None:
                self.conns[server][1].close()

            self.conns[server] = None, None
            raise

    async def cluster(self, resource, octets=b''):
        servers = self.conns.keys()

        return await asyncio.gather(
            *[self.server(s, resource, octets) for s in servers],
            return_exceptions=True)

    def __del__(self):
        for server, (reader, writer) in self.conns.items():
            try:
                writer.close()
            except Exception:
                pass


async def echo(ctx, obj):
    return dict(obj=obj, ctx=ctx, time=time.time())


if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)s %(process)d : %(message)s')

    port = int(sys.argv[1])
    cert = sys.argv[2] if len(sys.argv) > 2 else None
    proto = 'https' if cert else 'http'

    log('''echo '{"value": [1, 2, 3, 4]}' | gzip - | '''
        f'curl -kv --compressed {proto}://localhost:{port}/echo '
        '--data-binary @- '
        '-H "content-type: application/json" '
        '-H "content-encoding: gzip"')

    run(port, dict(echo=echo), cert)
