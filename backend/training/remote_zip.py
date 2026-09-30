"""Read individual members of a large remote zip via HTTP range requests.

Lets us pull only the frames needed for training crops out of the ~4.5 GB HELMET parts,
instead of downloading every archive in full.
"""
from __future__ import annotations

import struct
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx


@dataclass
class Member:
    name: str
    offset: int  # local header offset
    csize: int
    usize: int
    method: int


class RemoteZip:
    def __init__(self, url: str, timeout: float = 120.0):
        self.source = url
        self.client = httpx.Client(follow_redirects=True, timeout=timeout,
                                   limits=httpx.Limits(max_connections=32, max_keepalive_connections=32))
        self._lock = threading.Lock()
        self._resolve()
        self.members = self._central_directory()

    def _resolve(self) -> None:
        """Follow the redirect to a freshly signed storage URL (they expire after ~1 minute)."""
        r = self.client.get(self.source, headers={"Range": "bytes=0-0"})
        r.raise_for_status()
        self.url = str(r.url)
        self.size = int(r.headers["content-range"].split("/")[1])

    def _get(self, start: int, end: int) -> bytes:
        for attempt in range(6):
            url = self.url
            try:
                r = self.client.get(url, headers={"Range": f"bytes={start}-{end}"})
                if r.status_code in (400, 401, 403):  # expired signature
                    with self._lock:
                        if self.url == url:  # only one thread refreshes
                            self._resolve()
                    continue
                r.raise_for_status()
                return r.content
            except httpx.TransportError:
                time.sleep(1 + attempt)
        raise RuntimeError(f"range {start}-{end} failed after retries")

    def _central_directory(self) -> dict[str, Member]:
        tail = self._get(max(0, self.size - 65536 - 22), self.size - 1)
        eocd = tail.rfind(b"PK\x05\x06")
        cd_size, cd_off = struct.unpack("<II", tail[eocd + 12:eocd + 20])
        loc = tail.rfind(b"PK\x06\x07")  # zip64 locator
        if loc != -1:
            (z64_off,) = struct.unpack("<Q", tail[loc + 8:loc + 16])
            rec = self._get(z64_off, z64_off + 55)
            cd_size, cd_off = struct.unpack("<QQ", rec[40:56])
        cd = self._get(cd_off, cd_off + cd_size - 1)
        out, p = {}, 0
        while cd[p:p + 4] == b"PK\x01\x02":
            method = struct.unpack("<H", cd[p + 10:p + 12])[0]
            csize, usize = struct.unpack("<II", cd[p + 20:p + 28])
            fnlen, exlen, cmlen = struct.unpack("<HHH", cd[p + 28:p + 34])
            (off,) = struct.unpack("<I", cd[p + 42:p + 46])
            name = cd[p + 46:p + 46 + fnlen].decode("utf-8", "replace")
            extra = cd[p + 46 + fnlen:p + 46 + fnlen + exlen]
            i = 0
            while i + 4 <= len(extra):  # zip64 extended info
                hid, hsz = struct.unpack("<HH", extra[i:i + 4])
                if hid == 1:
                    vals = list(struct.unpack("<" + "Q" * (hsz // 8), extra[i + 4:i + 4 + hsz]))
                    if usize == 0xFFFFFFFF:
                        usize = vals.pop(0)
                    if csize == 0xFFFFFFFF:
                        csize = vals.pop(0)
                    if off == 0xFFFFFFFF:
                        off = vals.pop(0)
                i += 4 + hsz
            if not name.endswith("/"):
                out[name] = Member(name, off, csize, usize, method)
            p += 46 + fnlen + exlen + cmlen
        return out

    def read(self, name: str) -> bytes:
        m = self.members[name]
        # local header is 30 bytes + name + extra; fetch a little slack for the variable part
        head = self._get(m.offset, m.offset + 30 + 1024 - 1)
        fnlen, exlen = struct.unpack("<HH", head[26:30])
        start = m.offset + 30 + fnlen + exlen
        body = self._get(start, start + m.csize - 1)
        return body if m.method == 0 else zlib.decompress(body, -15)

    def read_many(self, names: list[str], workers: int = 16):
        """Yield (name, bytes | None); a member that keeps failing yields None instead of raising."""
        def safe(n):
            try:
                return self.read(n)
            except Exception:
                return None

        with ThreadPoolExecutor(workers) as ex:
            yield from zip(names, ex.map(safe, names))
