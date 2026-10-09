from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BlockRule:
    first: str
    last: str
    label: str = "Blocked"

    def as_dict(self) -> dict[str, str]:
        return {"first": self.first, "last": self.last, "label": self.label}


_RANGE_RE = re.compile(
    r"(?P<first>(?:\d{1,3}\.){3}\d{1,3})\s*-\s*(?P<last>(?:\d{1,3}\.){3}\d{1,3})"
)


def parse_blocklist(text: str) -> list[BlockRule]:
    """Parse PeerGuardian, eMule, CIDR, range, and single IPv4 entries."""
    rules: list[BlockRule] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.startswith(("#", ";", "//")):
            continue

        match = _RANGE_RE.search(line)
        label = "Blocked"
        try:
            if match:
                first_ip = ipaddress.IPv4Address(match.group("first"))
                last_ip = ipaddress.IPv4Address(match.group("last"))
                prefix = line[: match.start()].rstrip(" :,-")
                label = prefix or label
            elif "/" in line:
                token = line.split()[0]
                network = ipaddress.IPv4Network(token, strict=False)
                first_ip, last_ip = network.network_address, network.broadcast_address
                label = "CIDR"
            else:
                token = line.split()[0]
                first_ip = last_ip = ipaddress.IPv4Address(token)
                label = "Manual"
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
            continue

        if int(first_ip) > int(last_ip):
            first_ip, last_ip = last_ip, first_ip
        key = (str(first_ip), str(last_ip))
        if key not in seen:
            seen.add(key)
            rules.append(BlockRule(*key, label=label[:160]))
    return rules

