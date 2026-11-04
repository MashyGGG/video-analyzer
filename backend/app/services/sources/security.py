import ipaddress
import re
import socket
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

PLATFORMS = {
    "douyin": ("douyin.com",),
    "tiktok": ("tiktok.com",),
    "bilibili": ("bilibili.com", "b23.tv"),
    "youtube": ("youtube.com", "youtu.be"),
}
EGRESS_DOMAINS = tuple(d for group in PLATFORMS.values() for d in group) + (
    "douyinvod.com",
    "bytecdn.cn",
    "ibytedtos.com",
    "tiktokcdn.com",
    "tiktokv.com",
    "bilivideo.com",
    "hdslb.com",
    "googlevideo.com",
    "ytimg.com",
    "bytedance.com",
)


class SourceError(Exception):
    def __init__(self, code: str, retryable: bool = False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


def matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def hostname(host: str) -> str:
    if not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", host) or len(host) > 253:
        raise SourceError("SOURCE_UNSAFE")
    return host


def extract(text: str) -> tuple[str, str, str]:
    urls = re.findall(r"https?://[^\s<>\"'，。！；）]+", text)
    if len(urls) != 1:
        raise SourceError("SOURCE_UNSUPPORTED")
    try:
        parsed = urlsplit(urls[0])
        host = hostname(parsed.hostname or "")
        if parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password:
            raise SourceError("SOURCE_UNSAFE")
        if parsed.fragment or "\\" in urls[0] or any(ord(c) < 33 for c in urls[0]):
            raise SourceError("SOURCE_UNSAFE")
        platform = next((p for p, domains in PLATFORMS.items() if matches(host, domains)), None)
        if platform is None:
            raise SourceError("SOURCE_UNSUPPORTED")
        # Strip tracking/credentials; retain only platform resource identifiers.
        query = parse_qs(parsed.query)
        allowed = {k: v[0] for k, v in query.items() if k in ("v", "bvid", "modal_id")}
        url = urlunsplit(("https", host, parsed.path or "/", urlencode(allowed), ""))
        resource = allowed.get("v", allowed.get("modal_id", parsed.path.rstrip("/").rsplit("/", 1)[-1]))
        if not resource or len(resource) > 200 or not re.fullmatch(r"[A-Za-z0-9_-]+", resource):
            raise SourceError("SOURCE_UNSUPPORTED")
        return url, platform, resource
    except ValueError:
        raise SourceError("SOURCE_UNSAFE") from None


def public_addresses(host: str, port: int) -> list[tuple[int, tuple]]:
    hostname(host)
    if port != 443 or not matches(host, EGRESS_DOMAINS):
        raise SourceError("SOURCE_UNSAFE")
    records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    result: list[tuple[int, tuple]] = []
    for family, _, _, _, address in records:
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global or ip.is_multicast or ip.is_unspecified or getattr(ip, "ipv4_mapped", None):
            raise SourceError("SOURCE_UNSAFE")
        # Translation/tunnel ranges can embed a private IPv4 target on other deployments.
        if isinstance(ip, ipaddress.IPv6Address) and (
            ip.sixtofour is not None
            or ip.teredo is not None
            or ip in ipaddress.ip_network("64:ff9b::/96")
            or ip in ipaddress.ip_network("64:ff9b:1::/48")
        ):
            raise SourceError("SOURCE_UNSAFE")
        if str(ip) == "168.63.129.16":  # Azure platform virtual IP, despite global classification.
            raise SourceError("SOURCE_UNSAFE")
        result.append((family, address))
    if not result:
        raise SourceError("SOURCE_EXPIRED")
    return result


def connect_public(host: str, port: int) -> socket.socket:
    # One DNS lookup; connect numeric sockaddr, never call create_connection(host).
    addresses = public_addresses(host, port)
    family, address = addresses[0]
    target = socket.socket(family, socket.SOCK_STREAM)
    try:
        target.settimeout(8)
        target.connect(address)
        if target.getpeername()[0] != address[0]:
            raise SourceError("SOURCE_UNSAFE")
        return target
    except BaseException:
        target.close()
        raise
