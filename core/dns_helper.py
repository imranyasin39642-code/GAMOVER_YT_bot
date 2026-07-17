import asyncio
import aiohttp
from typing import List, Dict, Any, Optional
from aiohttp.resolver import AbstractResolver, DefaultResolver

DOH_SERVERS = [
    "https://8.8.8.8/resolve",          # Google DoH
    "https://1.1.1.1/dns-query",        # Cloudflare DoH
    "https://45.90.28.0/dns-query",     # NextDNS DoH
]

DOH_HEADERS = {
    "Accept": "application/dns-json",
}

async def _query_single_doh(session: aiohttp.ClientSession, endpoint: str, hostname: str) -> Optional[str]:
    try:
        async with session.get(
            endpoint,
            params={"name": hostname, "type": "A"},
            headers=DOH_HEADERS,
            timeout=aiohttp.ClientTimeout(total=4)
        ) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                answers = data.get("Answer", [])
                for ans in answers:
                    if ans.get("type") == 1:  # A record
                        ip = ans.get("data", "").strip()
                        if ip:
                            return ip
    except Exception:
        pass
    return None

async def resolve_dns_doh(hostname: str) -> Optional[str]:
    connector = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                asyncio.create_task(_query_single_doh(session, endpoint, hostname))
                for endpoint in DOH_SERVERS
            ]
            for coro in asyncio.as_completed(tasks):
                try:
                    result = await coro
                    if result:
                        for t in tasks:
                            if not t.done():
                                t.cancel()
                        return result
                except Exception:
                    pass
    except Exception as e:
        print(f"[DoH] Session error resolving {hostname}: {e}")
    finally:
        try:
            await connector.close()
        except Exception:
            pass
    return None


class DoHResolver(AbstractResolver):
    def __init__(self):
        self.fallback = DefaultResolver()
        self._cache: Dict[str, str] = {}

    async def resolve(self, hostname: str, port: int = 0, family: int = 0) -> List[Dict[str, Any]]:
        import re
        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", hostname):
            return await self.fallback.resolve(hostname, port, family)

        if hostname in self._cache:
            ip = self._cache[hostname]
            return [{"hostname": hostname, "host": ip, "port": port, "family": family, "proto": 0, "flags": 0}]

        ip = await resolve_dns_doh(hostname)
        if ip:
            self._cache[hostname] = ip
            return [{"hostname": hostname, "host": ip, "port": port, "family": family, "proto": 0, "flags": 0}]

        try:
            return await self.fallback.resolve(hostname, port, family)
        except Exception as e:
            print(f"[DoH] System DNS also failed for {hostname}: {e}")
            raise

    async def close(self) -> None:
        await self.fallback.close()


def get_doh_connector() -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(resolver=DoHResolver(), ssl=False)
