import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

import wg  # noqa: E402

SERVER = """[Interface]
Address = 10.8.0.1/24
ListenPort = 51820
PrivateKey = SERVERPRIV

[Peer]
PublicKey = OLD1
AllowedIPs = 10.8.0.2/32
"""


class WgTextTest(unittest.TestCase):
    def test_free_ip_skips_server_and_peers(self):
        self.assertEqual(wg.free_ip(SERVER), "10.8.0.3")
        self.assertEqual(wg.free_ip(SERVER, {"10.8.0.3"}), "10.8.0.4")

    def test_add_then_remove_keeps_other_peers(self):
        text = wg.add_peer_block(SERVER, 42, "NEWKEY", "PSK", "10.8.0.3")
        self.assertIn("# vpn-bot tg_id=42\n[Peer]\nPublicKey = NEWKEY", text)
        self.assertEqual(wg.free_ip(text), "10.8.0.4")
        back = wg.remove_peer_block(text, "NEWKEY")
        self.assertNotIn("NEWKEY", back)
        self.assertNotIn("tg_id=42", back)
        self.assertIn("PublicKey = OLD1", back)
        self.assertEqual(back, SERVER)

    def test_remove_old_peer(self):
        back = wg.remove_peer_block(SERVER, "OLD1")
        self.assertNotIn("OLD1", back)
        self.assertIn("ListenPort = 51820", back)

    def test_client_config(self):
        peer = wg.NewPeer("PRIV", "PUB", "PSK", "10.8.0.3")
        text = wg.client_config(peer, "SRVPUB", "1.2.3.4:51820", "1.1.1.1", "", "0.0.0.0/0")
        self.assertIn("Address = 10.8.0.3/32", text)
        self.assertIn("Endpoint = 1.2.3.4:51820", text)
        self.assertNotIn("MTU", text)


if __name__ == "__main__":
    unittest.main()
