# VPN Sunguard — Telegram-бот

Бот выдаёт настройки VPN на WireGuard.

## Как работает

1. Человек пишет боту `/start` и нажимает «🔑 Получить VPN».
2. Администратору приходит запрос с кнопками «✅ Разрешить» и «❌ Отказать».
3. После «Разрешить» бот сам создаёт настройку на сервере и присылает человеку файл `.conf` и QR-код.
4. Потом человек сам может взять настройку ещё на несколько устройств — всего до 3 (`MAX_DEVICES`).
5. Команда `/users` (только для администратора) — список, кому выдан VPN, и кнопка «🚫 Отключить».

Закрытые ключи клиентов бот не хранит: отправил человеку — и забыл.

## Установка на сервер (Ubuntu/Debian, WireGuard уже работает как `wg0`)

```bash
apt install -y python3-venv
mkdir -p /opt/vpn-bot && cd /opt/vpn-bot
# скопировать сюда папки bot/, deploy/ и файлы requirements.txt, .env.example
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env && nano .env   # вписать токен, свой id, адрес сервера
cp deploy/vpn-bot.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now vpn-bot
journalctl -u vpn-bot -f   # посмотреть, что бот запустился
```

Перед первым запуском сделай копию настроек сервера: `cp /etc/wireguard/wg0.conf /root/wg0.conf.bak`.

Если на сервере стоит AmneziaWG, а не обычный WireGuard, нужно поменять `WG_BIN=awg`,
`WG_INTERFACE` и дописать в настройку клиента параметры Amnezia — это ещё не сделано.

## Проверки

```bash
python -m unittest discover -s tests
```
