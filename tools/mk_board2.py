"""把 ART 里的 5G BDF 打成 ath11k 的 board-2.bin 容器。

格式（drivers/net/wireless/ath/ath11k/core.c）：
  magic "QCA-ATH11K-BOARD\0" 补齐到 4 字节
  然后是一串 ath11k_fw_ie { le32 id; le32 len; data[len] }，data 补齐到 4
    id=0 (ATH11K_BD_IE_BOARD)：payload 又是一串 fw_ie
        id=0 = BOARD_NAME（不带结尾 NUL，长度必须与驱动构造的名字完全一致）
        id=1 = BOARD_DATA（裸 BDF）
"""

import hashlib
import os
import struct

ART = "/mnt/c/Users/Landrom/WorkBuddy/test/ax3000/art_dump/art.bin"
OFF_5G = 0x26800
SIZE = 0x20000
OUT = ("/root/ow-main/target/linux/qualcommax/ipq50xx/base-files/"
       "lib/firmware/ath11k/QCN6122/hw1.0/board-2.bin")

MAGIC = b"QCA-ATH11K-BOARD\x00"
IE_BOARD = 0
IE_NAME = 0
IE_DATA = 1

# 驱动构造的名字：bus=<bus>,qmi-chip-id=<chip>,qmi-board-id=<board><variant>
NAMES = [
    "bus=ahb,qmi-chip-id=0,qmi-board-id=255",   # 主名（日志里 board_id 就是 0xff）
    "bus=ahb,qmi-chip-id=0",                    # 兜底名（只按 chip id 找）
]


def pad4(b):
    return b + b"\x00" * ((4 - len(b) % 4) % 4)


def ie(ie_id, payload):
    return pad4(struct.pack("<II", ie_id, len(payload)) + payload)


def main():
    with open(ART, "rb") as fh:
        art = fh.read()

    bdf = bytearray(art[OFF_5G:OFF_5G + SIZE])
    if len(bdf) != SIZE:
        raise SystemExit(f"ART 读取不足：{len(bdf)}")

    print("5G BDF  md5 =", hashlib.md5(bytes(bdf)).hexdigest())
    print("5G BDF  头 4 字节 =", bytes(bdf[:4]).hex())

    # 2.7 固件要求 BDF 偏移 0x45c 为 0x00（2.4 时代那批是 0x03）。
    # 保持 0x03 会让固件在 phyrf_bdf.c:6245 断言 axis_value == ANTENNACHAIN_AXIS_Z。
    old = bytes(bdf[0x45c:0x460])
    if old != b"\x00\x00\x00\x00":
        bdf[0x45c:0x460] = b"\x00\x00\x00\x00"
        print(f"已把 0x45c 从 {old.hex()} 改为 00000000")

    bdf = bytes(bdf)

    body = b""
    for name in NAMES:
        inner = ie(IE_NAME, name.encode()) + ie(IE_DATA, bdf)
        body += ie(IE_BOARD, inner)
        print(f"加入 board 项：{name}  (payload {len(inner)}B)")

    blob = pad4(MAGIC) + body
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as fh:
        fh.write(blob)

    print(f"写出 {OUT}  {len(blob)} 字节")


if __name__ == "__main__":
    main()
