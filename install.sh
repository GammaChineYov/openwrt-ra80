#!/bin/sh
# 把 RA80 移植应用到一份 OpenWrt mainline 源码树
# 用法: ./install.sh /path/to/openwrt
set -e

TREE=${1:-}
if [ -z "$TREE" ]; then
	echo "用法: $0 <openwrt 源码目录>" >&2
	exit 1
fi
if [ ! -d "$TREE/target/linux/qualcommax" ]; then
	echo "错误: $TREE 看起来不是 OpenWrt 源码树（缺少 target/linux/qualcommax）" >&2
	exit 1
fi

HERE=$(cd "$(dirname "$0")" && pwd)

# 覆盖前先留一份原始 platform.sh，方便回退
if [ -f "$TREE/target/linux/qualcommax/ipq50xx/base-files/lib/upgrade/platform.sh" ]; then
	cp "$TREE/target/linux/qualcommax/ipq50xx/base-files/lib/upgrade/platform.sh" \
	   "$TREE/target/linux/qualcommax/ipq50xx/base-files/lib/upgrade/platform.sh.orig"
fi

cp -R "$HERE/files/." "$TREE/"
chmod 755 "$TREE/target/linux/qualcommax/ipq50xx/base-files/usr/sbin/ra80-guard" 2>/dev/null || true
chmod 755 "$TREE/target/linux/qualcommax/ipq50xx/base-files/etc/init.d/ra80-guard" 2>/dev/null || true
chmod 755 "$TREE/target/linux/qualcommax/ipq50xx/base-files/etc/uci-defaults/"* 2>/dev/null || true

echo "已应用到 $TREE"
echo "下一步：./scripts/feeds update -a && ./scripts/feeds install -a"
echo "        选 Target: qualcommax / ipq50xx / Xiaomi AX3000，然后 make -j\$(nproc)"
