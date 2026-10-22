"""Настройки бота из файла .env (сам .env в git не кладём)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int
    wg_interface: str
    wg_config_path: str
    wg_bin: str
    endpoint: str
    client_dns: str
    client_mtu: str
    client_allowed_ips: str
    max_devices: int
    db_path: str


def _need(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"В .env не задано {name}")
    return value


def load_config() -> Config:
    load_dotenv()
    iface = os.getenv("WG_INTERFACE", "wg0")
    return Config(
        bot_token=_need("BOT_TOKEN"),
        admin_id=int(_need("ADMIN_ID")),
        wg_interface=iface,
        wg_config_path=os.getenv("WG_CONFIG", f"/etc/wireguard/{iface}.conf"),
        wg_bin=os.getenv("WG_BIN", "wg"),
        endpoint=_need("SERVER_ENDPOINT"),
        client_dns=os.getenv("CLIENT_DNS", "1.1.1.1"),
        client_mtu=os.getenv("CLIENT_MTU", ""),
        client_allowed_ips=os.getenv("CLIENT_ALLOWED_IPS", "0.0.0.0/0"),
        max_devices=int(os.getenv("MAX_DEVICES", "3")),
        db_path=os.getenv("DB_PATH", "vpnbot.sqlite3"),
    )
