"""Работа с WireGuard на сервере: ключи, адреса, добавление и удаление клиентов.

Клиент добавляется сразу в работающий интерфейс (`wg set`) и дописывается
в файл настроек сервера, чтобы пережить перезагрузку.
"""
import ipaddress
import os
import re
import subprocess
from dataclasses import dataclass

PEER_MARK = "# vpn-bot tg_id="


@dataclass(frozen=True)
class NewPeer:
    private_key: str
    public_key: str
    preshared_key: str
    ip: str


# --- Чистые функции над текстом файла настроек (их проверяют тесты) ---

def _chunks(text: str) -> list[list[str]]:
    """Режет файл на разделы по строкам «[...]». Наша пометка над [Peer] идёт с ним."""
    chunks: list[list[str]] = [[]]
    for line in text.splitlines():
        if line.strip().startswith("["):
            carry: list[str] = []
            while chunks[-1] and chunks[-1][-1].strip().startswith(PEER_MARK):
                carry.insert(0, chunks[-1].pop())
            chunks.append(carry)
        chunks[-1].append(line)
    return chunks


def _values(chunk: list[str], key: str) -> list[str]:
    found = []
    for line in chunk:
        name, sep, value = line.partition("=")
        if sep and name.strip().lower() == key.lower():
            found.append(value.strip())
    return found


def _section(chunk: list[str]) -> str:
    for line in chunk:
        if line.strip().startswith("["):
            return line.strip().lower()
    return ""


def interface_network(text: str) -> tuple[ipaddress.IPv4Network, ipaddress.IPv4Address]:
    """Сеть VPN и адрес самого сервера из строки Address раздела [Interface]."""
    for chunk in _chunks(text):
        if _section(chunk) == "[interface]":
            for value in _values(chunk, "Address"):
                for part in value.split(","):
                    iface = ipaddress.ip_interface(part.strip())
                    if iface.version == 4:
                        return iface.network, iface.ip
    raise ValueError("В настройках сервера нет IPv4-адреса в [Interface] Address")


def used_ips(text: str) -> set[ipaddress.IPv4Address]:
    used = {interface_network(text)[1]}
    for chunk in _chunks(text):
        if _section(chunk) == "[peer]":
            for value in _values(chunk, "AllowedIPs"):
                for part in value.split(","):
                    net = ipaddress.ip_network(part.strip(), strict=False)
                    if net.version == 4 and net.prefixlen == 32:
                        used.add(net.network_address)
    return used


def free_ip(text: str, also_used: set[str] = frozenset()) -> str:
    network, _ = interface_network(text)
    taken = used_ips(text) | {ipaddress.ip_address(ip) for ip in also_used}
    for host in network.hosts():
        if host not in taken:
            return str(host)
    raise RuntimeError("Свободные адреса в сети VPN закончились")


def add_peer_block(text: str, tg_id: int, public_key: str, preshared_key: str, ip: str) -> str:
    block = (
        f"\n{PEER_MARK}{tg_id}\n"
        "[Peer]\n"
        f"PublicKey = {public_key}\n"
        f"PresharedKey = {preshared_key}\n"
        f"AllowedIPs = {ip}/32\n"
    )
    return text.rstrip("\n") + "\n" + block


def remove_peer_block(text: str, public_key: str) -> str:
    kept = [
        chunk for chunk in _chunks(text)
        if not (_section(chunk) == "[peer]" and public_key in _values(chunk, "PublicKey"))
    ]
    joined = "\n".join(line for chunk in kept for line in chunk)
    return re.sub(r"\n{3,}", "\n\n", joined).rstrip("\n") + "\n"


def client_config(peer: NewPeer, server_public_key: str, endpoint: str,
                  dns: str, mtu: str, allowed_ips: str) -> str:
    lines = [
        "[Interface]",
        f"PrivateKey = {peer.private_key}",
        f"Address = {peer.ip}/32",
        f"DNS = {dns}",
    ]
    if mtu:
        lines.append(f"MTU = {mtu}")
    lines += [
        "",
        "[Peer]",
        f"PublicKey = {server_public_key}",
        f"PresharedKey = {peer.preshared_key}",
        f"AllowedIPs = {allowed_ips}",
        f"Endpoint = {endpoint}",
        "PersistentKeepalive = 25",
    ]
    return "\n".join(lines) + "\n"


# --- Команды на сервере ---

class WireGuard:
    def __init__(self, wg_bin: str, interface: str, config_path: str):
        self.wg_bin = wg_bin
        self.interface = interface
        self.config_path = config_path

    def _run(self, *args: str, stdin: str | None = None) -> str:
        result = subprocess.run(
            [self.wg_bin, *args], input=stdin, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()

    def _read(self) -> str:
        with open(self.config_path, encoding="utf-8") as f:
            return f.read()

    def _write(self, text: str) -> None:
        tmp = self.config_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, self.config_path)

    def server_public_key(self) -> str:
        return self._run("show", self.interface, "public-key")

    def add_peer(self, tg_id: int, also_used: set[str]) -> NewPeer:
        text = self._read()
        ip = free_ip(text, also_used)
        private_key = self._run("genkey")
        public_key = self._run("pubkey", stdin=private_key + "\n")
        preshared_key = self._run("genpsk")
        self._run(
            "set", self.interface, "peer", public_key,
            "preshared-key", "/dev/stdin", "allowed-ips", f"{ip}/32",
            stdin=preshared_key + "\n",
        )
        try:
            self._write(add_peer_block(text, tg_id, public_key, preshared_key, ip))
        except Exception:
            self._run("set", self.interface, "peer", public_key, "remove")
            raise
        return NewPeer(private_key, public_key, preshared_key, ip)

    def remove_peer(self, public_key: str) -> None:
        self._run("set", self.interface, "peer", public_key, "remove")
        self._write(remove_peer_block(self._read(), public_key))
