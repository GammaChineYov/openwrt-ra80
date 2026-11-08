# openwrt-ra80

小米 AX3000（**RA80**，IPQ5018 + QCN6122）在 **OpenWrt mainline** 上的设备移植，含若干踩坑修复与实测数据。

> 这台机器 256MB RAM / 128MB ESMT SPI-NAND，原厂固件为双分区布局。
> 本仓库提供的是 **mainline 干净端口**（不用 QSDK、不换 U-Boot），
> 目标是"能正常当路由器用"，不追求跑满千兆——**要千兆请看文末的 NSS 方案**。

## 现状（实测，非纸面）

| 项目 | 状态 | 备注 |
|---|---|---|
| 从 flash 启动 + 配置持久 | ✅ | 重启后 SSID/信道/MAC 自动恢复 |
| LAN | ✅ | lan1/2/3 + br-lan `192.168.1.1`，DSA `qca8337` |
| WAN | ✅ | 1Gbps，DHCP 客户端；`ip_forward` + masquerade 默认开启 |
| 2.4G（IPQ5018 内置） | ✅ | ch1 / HE40 / 30dBm，MAC 取自 ART |
| 5G（QCN6122） | ✅ | ch36 / HE80 / 26dBm，MAC 取自 ART |
| 双频热点 | ✅ | WPA2-PSK，均桥进 br-lan |
| LuCI | ✅ | 含实时带宽/负载/连接、路由表、信道分析 |
| sysupgrade | ✅ | 修复了平台脚本缺分支导致的静默失败 |
| 按键 | ✅ | `gpio_button_hotplug`，长按 reset 恢复出厂 |
| WPS 按键 | ✅ | 需 `wpad-mbedtls`（本仓库默认已选） |
| OOM 自愈 | ✅ | 关键进程 `oom_score_adj=-1000` + 守护自动拉起无线 |

**转发性能：约 280 Mbit/s**（软件转发，单核 softirq 打满）。
这是无 NSS 加速时的架构上限，参数调优无法突破——详见 [docs/NOTES.md](docs/NOTES.md) 第 26 节。

## 三个值得单独说的修复

### 1. NAND 读不出来（`ECC error -74`）

不是镜像问题。DTS 里照抄了别的板子的 `nand-ecc-strength = <8>`，而这台机器的
ESMT `F50L1G41LC` 片内 ECC 只有 **1bit/512B**（驱动表里写死的 `NAND_ECCREQ(1, 512)`）。
强行要 8bit 会绕开片内 ECC，单 bit 翻转无人纠正——实测 EC 头 `0x7fffffff` 变成 `0x7fffef ff`。

删掉那两行即可。

### 2. 5G 固件断言（`phyrf_bdf.c:6245`）

QCN6122 不走 `fixed_bdf_addr`，必须喂 `board-2.bin` **容器**；而且 2.7 固件要求
BDF 偏移 **`0x45c` = 0**（2.4 时代是 `0x03`）。否则固件断言并把共用的 Q6 一起带崩，
表现成 2.4G 报 `failed to receive wmi unified ready event: -110`。

打包工具见 `tools/mk_board2.py`。

### 3. sysupgrade 静默失败

`target/linux/qualcommax/ipq50xx/base-files/lib/upgrade/platform.sh` 里没有
`xiaomi,ax3000` 分支，于是落到 `default_do_upgrade`（非 NAND 的通用路径），
只打印 `Commencing upgrade` 就重启，**什么都没写**。

## 编译

```sh
git clone https://github.com/openwrt/openwrt.git
cd openwrt
git checkout <你用的 main 提交>

# 应用本仓库的移植
/path/to/openwrt-ra80/install.sh /path/to/openwrt

./scripts/feeds update -a && ./scripts/feeds install -a
cp /path/to/openwrt-ra80/config.ipq50xx .config   # 或用 menuconfig 选 Xiaomi AX3000
make defconfig && make -j$(nproc)
```

产物：
- `...-squashfs-factory.ubi` —— U-Boot 直写
- `...-squashfs-sysupgrade.bin` —— 运行中升级

## 刷机

见 [docs/UPGRADE.md](docs/UPGRADE.md)。要点：**升级前必须 `wifi down` + 卸载 ath11k
腾出内存**，否则 15MB 镜像写进 /tmp 会 OOM。

## 板级 BDF 说明

`files/.../lib/firmware/ath11k/` 下的 `board.bin` / `board-2.bin` / `cal-*.bin`
是**从本机 ART 分区导出的**逐机校准数据。换一台机器请用自己的 ART 重新导出：

```sh
dd if=/dev/mtd17 of=/tmp/art.bin          # 0:art
python3 tools/mk_board2.py --art /tmp/art.bin --off 0x26800 --out board-2.bin
```

## 与已有工作的关系（避免重复造轮子）

- **NSS 硬件加速**：[kuncy7/openwrt-nss-edma](https://github.com/kuncy7/openwrt-nss-edma)
  已经打通 IPQ5018 的 NSS（保留上游 `stmmac`，kernel 6.18），实测 ~900 Mbit/s、CPU idle >90%。
  本仓库**不含 NSS**，是"干净 mainline"路线；要千兆请用那棵树。
- **Redmi AX3000 / CR880x**：那棵树已支持；本仓库针对的是 **RA80（小米 AX3000）**，
  分区布局与它们都不同（rootfs 起始 `0x2e80000`，长度 `0x2400000`）。
- 本仓库独有的结论：ESMT 1bit 片内 ECC、QCN6122 board-2.bin 容器 + `0x45c`、
  `platform.sh` 缺分支、以及 OOM/内存实测数据。

## 已知限制

- 转发 ~280 Mbit/s（无 NSS）
- `MemAvailable` 常态只有 2~4MB，任何 >10MB 的 /tmp 写入都会 OOM
- `rmmod ath11k` 后无法重新加载（Q6 `start timed out`），只能重启恢复
- WAN IPv6 需要上游 DHCPv6-PD，未验证

## License

GPL-2.0。设备树与板级脚本按 OpenWrt 惯例发布；BDF 为设备自身校准数据。
