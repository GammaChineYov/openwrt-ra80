# 小米 AX3000（RA80）刷 OpenWrt 攻关笔记

> 最后更新：2026-11-07 21:35
> 设备当前状态：**原厂系统 1.0.58 正常运行**（可用）

---

## 一、设备信息

| 项 | 值 |
|---|---|
| 型号代码 | `RA80`（v1，非 RA80V2） |
| 型号串 | `Qualcomm Technologies, Inc. IPQ5018/AP-MP02.1` |
| 原厂固件 | `1.0.58 release` |
| SoC | IPQ5018（2×A53 + NPU） |
| RAM / Flash | 256MB / 128MB NAND（ESMT SPI NAND） |
| 5G 射频 | QCN6122 |
| 管理地址 | `192.168.31.1`（原厂） |
| 后台密码 | `12341234` |

### 分区表（`cat /proc/mtd`）

```
mtd0-9    0:SBL1 / MIBIB / BOOTCONFIG / BOOTCONFIG1 / QSEE / QSEE_1 / DEVCFG / DEVCFG_1 / CDT / CDT_1
mtd10     0:APPSBLENV
mtd11-12  0:APPSBL / 0:APPSBL_1        (U-Boot 双份)
mtd13     0:ART                        (射频校准，丢了 WiFi 就废)
mtd14     0:TRAINING
mtd15     bdata
mtd16     crash
mtd17     crash_syslog
mtd18     rootfs      0x02400000 @ 0x00a80000   ← OpenWrt 刷这里
mtd19     rootfs_1    0x02400000 @ 0x02e80000   ← 原厂系统，U-Boot 活动分区
mtd20     overlay     0x01f00000                (原厂 data 卷)
mtd21     rsvd0
```

---

## 二、五条硬约束（这轮踩出来的）

### 1. U-Boot 的 `mtdparts` 只有一个分区，固定在 mtd19

```
0: fs   size=0x02400000  offset=0x02e80000
active partition: nand0,0 - (fs) 0x02400000 @ 0x02e80000
```

`bootmiwifi` 只从 mtd19 加载内核。`flag_boot_rootfs` 似乎不改变这个行为。

### 2. `bootmiwifi` 的 bootargs 是**硬编码**的

```
ubi.mtd=rootfs_1 root=mtd:ubi_rootfs rootfstype=squashfs cnss2.bdf_integrated=0x24 ... rootwait
```

- `nvram set bootargs` → **重启后被覆盖**
- `setenv bootargs` + `saveenv` → 保存成功、`printenv` 显示新值，但 `bootmiwifi` 启动时**仍用旧值**
- 结论：改环境变量无效，只能绕过 `bootmiwifi`

### 3. U-Boot 的 `ubi` 命令是精简版

支持：`ubi part` / `ubi read` / `ubi write`
**不支持**：`ubi rename` / `ubi rm` / `ubi resize` / `ubi ls` / `ubi info`
→ 无法改名或扩容已有卷

### 4. TFTP 有 32MB 上限

TFTP 块号是 16 位（65535 × 512B = 33,553,920B）。36MB 的备份传不完。
→ **解法：切成两块 18MB，分别 `nand write`**

### 5. 手动 `bootm` 会立即 reset

```
IPQ5018# bootm 0x41000000
## Loading kernel from FIT Image at 41000000 ... OK
## Loading fdt from FIT Image at 41000000 ... OK
resetting ...            ← 小米 U-Boot 的安全校验，需要 TZT 预执行
```

---

## 三、已经跑通的流程

### A. 进入 U-Boot

```bash
# 串口桥接持续发回车（serial_bridge.py，COM5 115200 8N1）
printf 'SPAM_ENTER 200' > serial/cmd.txt
# 然后在窗口期内给路由器断电重启
```

成功标志：出现 `IPQ5018#`

### B. 刷写 mtd19（完整固件）

```bash
# 1. 串口命令
setenv serverip 192.168.31.71
tftpboot 0x44000000 <file>            # 单文件 < 32MB
nand erase 0x2e80000 0x2400000
nand write 0x44000000 0x2e80000 <size>

# 2. 大文件（>32MB）切两块
dd if=orig.ubi of=p1.bin bs=1048576 count=18
dd if=orig.ubi of=p2.bin bs=1048576 skip=18
# p1 -> nand write 0x44000000 0x2e80000 0x1200000
# p2 -> nand write 0x44000000 0x4080000 0x1200000
```

### C. 恢复原厂（已验证成功两次）

```bash
nand erase 0x2e80000 0x2400000
tftpboot 0x44000000 p1.bin   → nand write 0x44000000 0x2e80000 0x1200000
tftpboot 0x44000000 p2.bin   → nand write 0x44000000 0x4080000 0x1200000
reset
```

**备份文件**：`xmir-patcher-main/backups/mtd19_rootfs1.bin`（37,748,736B）
**MD5**：`86460c7e5c0151b0d68091489aae094c`

---

## 四、编译配置要点

### 源码

```
WSL: /root/immortalwrt-ax3000   (immortalwrt 24.10, 6.6.137)
参考: /root/ax3000-ref          (crypt0nX 仓库，仅取 DTS)
```

### 关键改动

| 文件 | 改动 |
|---|---|
| `target/linux/qualcommax/image/ipq50xx.mk` | 加 `Device/xiaomi_ax3000` |
| `target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq5018-xiaomi-ax3000.dts` | 自建 DSA 版 DTS |
| `scripts/ubinize-image.sh` | 根卷名 `rootfs` → **`ubi_rootfs`**（匹配 bootmiwifi） |

### 设备包

```make
DEVICE_PACKAGES := \
	ath11k-firmware-ipq5018 \
	ath11k-firmware-qcn6122 \
	kmod-qca-nss-dp \
	kmod-dsa-qca8k
```
（`wpad-openssl` / `kmod-ath11k-ahb` 由 qualcommax 默认包提供，**不要再加 `wpad-basic-wolfssl`，会冲突**）

### 编译环境三个坑

1. **root 用户**：`export FORCE_UNSAFE_CONFIGURE=1`
2. **PATH 污染**：Windows 路径混进 WSL，`find -execdir` 拒绝执行
   → `export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`
3. **代理**：WSL 内 `127.0.0.1:7897` 可用；`ath11k-firmware` 从 `deac-ams.dl.sourceforge.net` 下载最快

---

## 五、当前卡点（唯一剩下的）

### 现象

```
[1.355840] UBI error: cannot open mtd rootfs_1, error -2
[1.358871] UBI error: cannot open mtd rootfs, error -2
[1.370187] Waiting for root device /dev/ubiblock0_1...
```

### 已确认的事实

- ✅ 内核是自编译的：`ARM64 OpenWrt Linux-6.6.137`
- ✅ DTB 是我们自己的：`ARM64 OpenWrt xiaomi_ax3000 device tree blob`
- ✅ **DTB 里分区表完整存在**（反编译确认：`partition@a80000 { label = "rootfs"; }`）
- ✅ UBI 成功挂载新固件：`user volume: 3`、`rootfs_data re-sized to 132 LEBs`
- ❌ 内核里**没有生成 MTD 分区**

### 根因

NAND 被注册成通用 `spi-nand spi0.0` 设备：
```
[1.130159] spi-nand spi0.0: ESMT SPI NAND was found.
[1.130217] spi-nand spi0.0: 128 MiB, block size: 128 KiB, page size: 2048, OOB size: 64
```
但**没有任何分区被创建**。`compatible = "qcom,spi-qpic-snand"` 的节点（`qpic-nand@79b0000`）没有被对应驱动正确接管，DTS 分区表挂在它下面，于是分区没能挂到实际 MTD 设备上。

`CONFIG_MTD_OF_PARTS=y` 已启用，问题在驱动层。

### 修复方向

**方向 A（推荐）**：启用 cmdline 分区
1. 内核配置加 `CONFIG_MTD_CMDLINE_PARTS=y`
2. DTS 的 `bootargs-append` 加 `mtdparts=`
   （已验证：`bootargs-append` 的内容**确实会 append 进内核 cmdline**）
3. mtd-id 待确定，内核日志里设备名是 `spi0.0`，可能是 `mtdparts=spi0.0:...`

**方向 B**：检查 `qcom,spi-qpic-snand` 驱动的 probe 是否成功，可能需要补 patch

**方向 C**：改用 raw NAND 驱动路径（`qcom,ebi2-nandc-bam-v2.1.1`）

---

## 六、文件清单

```
C:\Users\Landrom\WorkBuddy\test\ax3000\
├── NOTES.md                        ← 本文件
├── dts\
│   ├── ipq5018-ax3000.dsa.dts      ← 当前使用的 DTS（DSA 版）
│   ├── device_xiaomi_ax3000.mk     ← 设备定义
│   └── device_lan_only.mk          ← LAN-only 版定义
├── fw-new\
│   ├── owrt.ubi                    ← 最新 OpenWrt 固件（17,563,648B，卷名 ubi_rootfs）
│   ├── orig.ubi                    ← 原厂 mtd19 完整备份（37,748,736B）
│   ├── p1.bin / p2.bin             ← 备份切分（各 18MB，用于 TFTP）
│   └── immortalwrt-...-factory.ubi
├── xmir-patcher-main\
│   ├── connect.py                  ← 开 SSH（密码 12341234）
│   └── backups\                    ← 全部原厂分区备份
├── serial_bridge.py                ← 串口桥接（COM5）
├── serial\
│   ├── cmd.txt                     ← 命令入口
│   └── console.log                 ← 完整串口日志
├── tftpserve2.py                   ← TFTP 服务（UDP 69，需管理员）
├── admin-daemon.ps1                ← 管理员通道（自动设 IP + 命令转发）
├── sshrun.py                       ← SSH 执行命令
├── adm.py                          ← 管理员命令发送
└── build3.sh                       ← 编译脚本（含 PATH/代理/root 修复）
```

---

## 七、常用操作速查

### 开 SSH
```bash
cd xmir-patcher-main
unset http_proxy https_proxy all_proxy          # 必须清代理，否则连不上内网
printf '12341234\n' | python connect.py
```

### 串口桥接
```powershell
Start-Process "C:\Users\Landrom\.global-python\Scripts\python.exe" `
  -ArgumentList "C:\Users\Landrom\WorkBuddy\test\ax3000\serial_bridge.py"
```
命令协议（写 `serial/cmd.txt`）：
- `SPAM_ENTER <秒>` — 持续发回车
- `SEND <文本>` — 发送命令
- `ENTER` / `CTRL_C` / `QUIT`

### 管理员通道
```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\Landrom\WorkBuddy\test\ax3000\admin-daemon.ps1"
```
写 `admin/cmd.txt` 执行，结果读 `admin/out.txt`

### TFTP 服务
```powershell
# 必须有管理员权限（UDP 69）
Start-Process "C:\Users\Landrom\.global-python\Scripts\python.exe" `
  -ArgumentList "C:\Users\Landrom\WorkBuddy\test\ax3000\tftpserve2.py"
```
服务目录：`fw-new\`

---

## 八、血泪教训

1. **U-Boot 网络起不来先查电脑 IP**：U-Boot 不发 DHCP，电脑会掉到 `169.254.x.x`，必须先设静态 `192.168.31.71/24`。这一条卡了近一小时。
2. **改 nvram bootargs 是无效的**，`bootmiwifi` 每次都会覆盖。别在这上面浪费时间。
3. **刷 mtd19 前必须确认恢复路径可用**（TFTP + 备份 + 32MB 分块），否则一次失败就得拆 flash。
4. **串口桥接进程会挂**，表现为"发回车没反应"，先查进程在不在。
5. **PowerShell 5.1 读 UTF-8 无 BOM 的中文脚本会报"字符串缺少终止符"**，脚本一律写纯 ASCII。

---

## 九、突破记录（2026-11-07 22:00）

### 9.1 已经跑通的事实

OpenWrt 已在 mtd19 上**完整启动**（`ImmortalWrt 24.10-SNAPSHOT, r0-9a11bb8`），串口直出 root shell。

关键突破点：**`bootmiwifi` 会把 DTB 的 `chosen/bootargs-append` 拼到硬编码 bootargs 后面**。
实测内核命令行最终为：

```
ubi.mtd=rootfs_1 root=mtd:ubi_rootfs rootfstype=squashfs cnss2.bdf_... rootwait uart_en=1
console=ttyMSM0,115200n8 mtdparts=spi0.0:0x2400000@0x2e80000(rootfs) ubi.mtd=rootfs root=/dev/ubiblock0_1 coherent_pool=2M
```

注意后半段全部来自 DTS 的 `bootargs-append`，**这是唯一能往内核命令行注入参数的口子**（改 nvram 无效）。

### 9.2 NAND 分区问题已解决

之前 `UBI error: cannot open mtd rootfs_1, error -2` 的根因：
内核里**根本没有 MTD 分区**，`qcom,spi-qpic-snand` 没有把 DTS 分区挂上去。

解法（两步都要）：
1. 内核配置 `CONFIG_MTD_CMDLINE_PARTS=y`（写入 `target/linux/qualcommax/config-6.6`）
2. DTS `chosen/bootargs-append` 里加 `mtdparts=spi0.0:0x2400000@0x2e80000(rootfs)`

启动后 `/proc/mtd` 正确出现：
```
mtd0: 02400000 00020000 "rootfs"
```

注意：`mtdparts` 的偏移必须与实际烧写位置一致（我们烧在 mtd19 = `0x2e80000`）。

### 9.3 交换机：DSA qca8k 走不通，必须用 SSDK

DSA 方案（`qca,qca8337` DSA 节点）失败，日志：

```
qca8k 90000.mdio-1:11: Switch id detected ff but expected 13
```

原因不是接线，是**时序冲突**：
- `qca8k` 在 **1.29s** 就 probe（mdio 总线一注册就 probed）
- `qca-ssdk` 到 **17.9s** 才做 `qca_ar8327_gpio_reset: GPIO26 reset switch done`

也就是说 DSA 读 chip id 时交换机还没被正确复位；而且 SSDK 随后又会复位整颗芯片，把 DSA 的 VLAN 配置全部清掉。**两套驱动抢同一颗 QCA8337，DSA 必然失败。**

结论：**改用 SSDK（QSDK 路径）管交换机** —— 恢复原厂 DTS 的 `&ess_instance { ess-switch1@1 {...} }` 节点：

```dts
switch_cpu_bmp = <0x60>;   /* CPU 口 = port 5,6 */
switch_lan_bmp = <0x0e>;   /* LAN = port 1,2,3 */
switch_wan_bmp = <0x10>;   /* port 4 */
```

此时 Linux 侧不出现 lan1/lan2/lan3，三个 LAN 口由交换机**硬件桥接**到 CPU 口（`dp2` = `eth1`）。
所以 OpenWrt 的网络配置应为：

| 逻辑口 | 设备 | 说明 |
|---|---|---|
| lan | `eth1` | 交换机 CPU 口，带 3 个 LAN |
| wan | `eth0` | `dp1`，接 SoC 内置 PHY（phys addr 7） |

### 9.4 WiFi 待解决

`iw dev` 为空，ath11k 报：

```
ath11k c000000.wifi: failed to fetch board data for bus=ahb,qmi-chip-id=0,qmi-board-id=16
ath11k c000000.wifi: failed to fetch board.bin from IPQ5018/hw1.0
ath11k c000000.wifi: qmi failed to fetch board file: -12
```

即缺少 **BDF（board-2.bin）**，与之前判断一致，需要补 `ipq-wifi-xiaomi_ax3000` 包。

---

## 十、串口桥接的坑（已修）

旧版 `serial_bridge.py` 在 `SPAM_ENTER` 期间**完全跳过 cmd.txt 检查**，一旦开始 spam 就无法中断，等于丧失控制。

已修：
- cmd.txt **每轮循环都检查**，spam 期间也检查
- 任何非 SPAM 命令到达时**自动终止 spam**，再执行该命令
- 新增 `SPAM_STOP` 显式停止

设计原则：**任何"长时间自动动作"都必须留一个可被外部抢占的出口。**

---

## 十一、交换机根因（2026-11-07 22:55，子代理检索确认）

### 11.1 `ssdk fal init failed: -26` 的真正含义

`-26` = **`SW_INIT_ERROR`**，不是 errno。

根因：`package/kernel/qca-ssdk/Makefile` 第 51 行默认编译选项是

```make
ISISC_ENABLE=disable MHT_ENABLE=disable
```

**`CHIP_ISISC`（QCA8337/AR8327 这类外挂交换机芯片）的驱动根本没被编译进 `qca-ssdk.ko`。**
DTS 再怎么配对，FAL 层都找不到这个芯片，于是 `fal_init()` 返回 `SW_INIT_ERROR`。

修复：

```bash
sed -i 's/ISISC_ENABLE=disable/ISISC_ENABLE=enable/' package/kernel/qca-ssdk/Makefile
make package/kernel/qca-ssdk/clean && make -j8
```

这正是 `crypt0nX/openwrt-xiaomi-ax3000` 第 2 个提交（Author: Howard2018）做的事，
该提交信息明写「交换机配置好」+「确认有线正常」。之前的失败都是漏了这一步。

### 11.2 SSDK 的节点枚举规则（源码事实）

`src/init/ssdk_dts.c` 的 `ssdk_dt_get_switch_node()`：

1. 先 `of_find_node_by_name(NULL, "ess-instance")` 找到容器节点；
2. 再按 **节点名** 找子节点：`num==0` 找 `ess-switch`，`num==1` 找 `ess-switch1`；
3. `of_device_is_available()` 为假则返回 `SW_DISABLE`；
4. `device_id` 属性决定 `dev_id`。

**关键结论：匹配靠节点名，不是 compatible。** 所以：
- SoC 内置 ESS 必须是 `ess-switch`（dtsi 里 `switch: ess-switch@39c00000`）
- 外挂 QCA8337 必须是 `ess-switch1`（`ess-switch1@1`）
- 两个节点都必须在 `ess-instance` 里，且 `num_devices = <2>`

### 11.3 最终 DTS 结构（三段缺一不可）

```dts
/* 1. MDIO1 总线 + 5 个 PHY，并把复位脚交给 mdio 驱动 */
&mdio1 {
	status = "okay";
	pinctrl-0 = <&mdio1_pins &switch_reset_pins>;
	pinctrl-names = "default";
	phy-reset-gpio = <&tlmm 26 GPIO_ACTIVE_HIGH>;
	ethernet-phy@0 { reg = <0x0>; };
	ethernet-phy@1 { reg = <0x1>; };
	ethernet-phy@2 { reg = <0x2>; };
	ethernet-phy@3 { reg = <0x3>; };
	ethernet-phy@4 { reg = <0x4>; };
};

/* 2. SoC 内置 ESS（dev 0） */
&switch {
	status = "okay";
	compatible = "qcom,ess-switch-ipq50xx";
	device_id = <0>;
	cmnblk_clk = "internal_96MHz";
	reg = <0x39c00000 0x200000>;
	switch_mac_mode = <0x0f>;
	switch_access_mode = "local bus";
	qcom,port_phyinfo { /* port1→mdio0 phy7, port2 forced 1000 */ };
};

/* 3. 外挂 QCA8337（dev 1） */
&ess_instance {
	status = "okay";
	num_devices = <2>;
	ess-switch1@1 {
		compatible = "qcom,ess-switch-qca83xx";
		device_id = <1>;
		switch_access_mode = "mdio";
		mdio-bus = <&mdio1>;
		reset_gpio = <&tlmm 26 GPIO_ACTIVE_HIGH>;
		switch_cpu_bmp = <0x60>;   /* CPU 口 = port5+port6（RA80 实际用 port6） */
		switch_acpu_bmp = <0x60>;
		switch_lan_bmp = <0x0e>;   /* LAN = port1/2/3 */
		switch_wan_bmp = <0x10>;   /* port4 */
		qca,ar8327-initvals = <...>;
		qcom,port_phyinfo { port1..5 → phy 0..4；port6 forced 1000 };
	};
};
```

### 11.4 之前几版为什么失败（复盘）

| 版本 | DTS 写法 | 结果 | 原因 |
|---|---|---|---|
| build #2 | DSA `qca,qca8337` 节点 | `Switch id detected ff` | ① ISISC 没编译 ② DSA 与 SSDK 抢芯片，SSDK 18s 后复位清掉 DSA 配置 |
| owrt4/5 | 只加 `ess-switch1`，无 `&switch` | `fal init failed -26` | ISISC 没编译 + dev0 缺失 |
| owrt6 | 只有 DSA 节点 + bmps | SSDK 只注册 dev0，外挂芯片未识别 | ISISC 没编译 |

**共同根因就一个：`ISISC_ENABLE=disable`。**

---

## 十二、并行研究结论（子代理）

- `-26` = `SW_INIT_ERROR`，出处 `qca-ssdk` Makefile + `fal_init`。
- 上游 `ipq50xx-rax3000q.dts` 里 QCA8337 的 `switch_cpu_bmp` 用的是 `<0x40>`（只 port6），
  但 RA80 那个仓库用 `<0x60>`（port5+6）。**RA80 以仓库值为准**。

---

## 十三、SSDK 版本升级（23:05）

### 13.1 为什么必须换版本

- immortalwrt 24.10 自带 `qca-ssdk 2024.06.13`（codelinaro 源）。
- 参考仓库 `crypt0nX/openwrt-xiaomi-ax3000` 用的是 **`2025-05-30`（openwrt/qca-ssdk, 446db12b）**。
- 两者编译开关其实一致（`ISISC_ENABLE=enable`、`IN_MP_PHY=FALSE`、`IN_QCA803X_PHY=FALSE`、`CHIP_TYPE=MP`），
  差别在 **源码版本**。
- 用 2024.06.13 + ISISC enable 后，`fal_init` 从 `-26`(SW_INIT_ERROR) 变成 `-19`(SW_NOT_SUPPORTED)，
  卡在 `hsl_set_current_chip_type(dev_id, cfg->chip_type)` —— 说明该版本的 hsl 层不认识 CHIP_ISISC。

### 13.2 升级方法（可直接照抄）

改 `package/kernel/qca-ssdk/Makefile` 头部：

```make
PKG_RELEASE:=1
PKG_SOURCE_URL:=https://github.com/openwrt/qca-ssdk.git
PKG_SOURCE_DATE:=2025-05-30
PKG_SOURCE_VERSION:=446db12b1fd3bca2e61e45cb01c4ad52cfddd95b
PKG_MIRROR_HASH:=d7bf3b83b08c61801e3ee3fe6d18da19c8c774e87f94c494c01f80b52d279589
```

### 13.3 关键坑：旧补丁全部对不上

升级后 `make` 会在 **prepare 阶段** 失败，报：

```
Applying .../patches/0003-Revert-qca-ssdk-enable-invoking-fdb-del-function-for.patch
Hunk #1 FAILED at 229.
Patch failed!
```

接着 `0004-SSDK-set-OF-node-for-the-SFP-PHY.patch` 也有多处 FAILED。

处理：**把 `package/kernel/qca-ssdk/patches/` 整个目录移走**（新版已包含这些修复），即可编译通过：

```bash
mv package/kernel/qca-ssdk/patches /root/ssdk_patches_disabled/
mkdir package/kernel/qca-ssdk/patches
make package/kernel/qca-ssdk/clean && make package/kernel/qca-ssdk/compile V=s
```

新版编译通过（约 25s），`qca-ssdk.ko` 内含：
`qca_ar8327_hw_init` / `isisc_init` / `Initializing ISISC Done!!` / `qcom,ess-switch-qca83xx`。

### 13.4 一个必须记住的现象

SSDK 初始化失败会**连带**让 `qca-nss-dp` 加载不了：

```
qca_nss_dp: gave up waiting for init of module qca_ssdk.
qca_nss_dp: Unknown symbol fal_port_autoneg_status_get (err -16)
```

结果是 eth0/eth1 都不存在，设备看起来"没网"。所以 ssdk 必须初始化成功，
不能靠"反正我只用有线"绕过去。

---

## 十四、-19 的真正来源（00:15，插桩定位）

### 14.1 插桩方法（以后照这个来）

在 `build_dir/.../qca-ssdk-*/src/fal/fal_init.c` 里插 `SSDK_ERROR("FALDBG ...")`，
重编 `package/kernel/qca-ssdk/compile` 再出镜像即可。**不用 clean**，改完直接编。

### 14.2 实测输出

```
fal_init[46]: FALDBG hsl_api_init  dev=0 rv=0
fal_init[50]: FALDBG hsl_dev_init  dev=0 rv=0  chip_type=9
fal_init[55]: FALDBG fal_vlan_init dev=0 rv=0
fal_init[60]: FALDBG adpt_init     dev=0 rv=0     ← 内置 ESS 全绿
...
fal_init[46]: FALDBG hsl_api_init  dev=1 rv=0
fal_init[50]: FALDBG hsl_dev_init  dev=1 rv=-19 chip_type=6   ← 外挂交换机
```

`hsl_dev_init` 里的 switch 分支：
`CHIP_ISISC → isisc_init()`，其余分支在未编译时 `rv` 保持 `SW_INIT_ERROR`。

**枚举实际顺序**（`include/init/ssdk_init.h`）：

```
CHIP_ATHENA=0, CHIP_GARUDA=1, CHIP_SHIVA=2, CHIP_HORUS=3,
CHIP_ISIS=4, CHIP_ISISC=5, CHIP_DESS=6, CHIP_HPPE=7,
CHIP_SCOMPHY=8, CHIP_APPE=9, CHIP_MHT=10
```

**所以 `chip_type=6` 是 `CHIP_DESS`，根本不是 ISISC** —— 之前一直以为 6 就是 ISISC，判断错了。

### 14.3 为什么会变成 DESS

`ssdk_init.c` 里 chip_type 的判定：

```c
a_uint8_t chip_ver = 0;
...
if (reg_mode == HSL_REG_MDIO) {
    a_uint32_t phy_id = qca_detect_phyid(dev_id);
    switch (phy_id) {
        case QCA8084_PHY: chip_ver = QCA_VER_MHT; break;
        case F1V4_PHY:    chip_ver = QCA_VER_AR8337; break;
        default: break;
    }
} else { ...读寄存器... }

switch (chip_ver) {
    case QCA_VER_AR8337: cfg->chip_type = CHIP_ISISC; break;
    ...
    case QCA_VER_DESS:   cfg->chip_type = CHIP_DESS;  break;
    default: rv = chip_is_scomphy(dev_id, cfg);
}
```

`chip_ver` 初值 0，**而 `QCA_VER_DESS` 就是 0**。
只要 `qca_detect_phyid()` 没认出 `F1V4_PHY`，就落到 `QCA_VER_DESS`，进而 `CHIP_DESS` → `hsl_dev_init` 返回 -19。

**根因：MDIO 上读不到 QCA8337 的 PHY ID。**
最可能是 **GPIO26 复位极性** —— pinctrl 原来是 `bias-pull-up`（拉高）；
若该板 RESET 为高有效，交换机上电后一直被按在复位里，MDIO 自然读不到。

### 14.4 已应用的修正

`switch-reset-pins` 由

```dts
bias-pull-up;
```

改为

```dts
output-low;
```

并在 `switch_access_mode = "mdio"` 下让 SSDK 自己完成 assert→deassert 复位时序。

---

## 十五、突破：DSA qca8k 终于认出交换机（00:35）

### 15.1 决定性改动（来自并行子代理的 DSA 方案）

1. **把 `ess-switch1` / `&ess_instance` 从 DTS 里整段删掉** —— SSDK 不再抢这颗 QCA8337。
2. 交换机节点改回 `compatible = "qca,qca8337"`，放在 `&mdio1` 下，`reg = <17>`（MDIO 0x11），
   内部口用 **`ethernet-port@N`**（不是 `port@N`）。
3. `reset-gpios` 用 **`GPIO_ACTIVE_LOW`**。

### 15.2 为什么这样就对了（源码依据）

`drivers/net/dsa/qca/qca8k-8xxx.c` 的 `qca8k_sw_probe()`：

```c
priv->reset_gpio = devm_gpiod_get_optional(dev, "reset", GPIOD_OUT_HIGH);
if (priv->reset_gpio) {
    msleep(QCA8K_RESET_WAIT);        // 约 20~50ms
    gpiod_set_value_cansleep(priv->reset_gpio, 0);
    msleep(QCA8K_RESET_WAIT);
}
```

- 驱动自己会在读 chip id **之前**做一次完整复位脉冲，所以不需要外部先复位。
- **必须是 ACTIVE_LOW**：这样 `_HIGH` 阶段 = 拉低=复位有效，随后 `0` = 释放。
  之前用 `GPIO_ACTIVE_HIGH`，等于"释放后又被拉低压住"，所以 `Switch id detected ff`。

### 15.3 实测日志

```
qca8k 90000.mdio-1:11: configuring for fixed/sgmii link mode
qca8k 90000.mdio-1:11: Link is Up - 1Gbps/Full - flow control off
qca8k 90000.mdio-1:11 lan1 (uninitialized): PHY [90000.mdio-1:00] driver [Qualcomm Atheros 8337 internal PHY]
qca8k 90000.mdio-1:11 lan2 (uninitialized): PHY [90000.mdio-1:01] ...
qca8k 90000.mdio-1:11 lan3 (uninitialized): PHY [90000.mdio-1:02] ...
DSA: tree 0 setup
```

`ip link` 出现 `lan1 lan2 lan3`，`lan3=up carrier=1`（电脑插在第三个口）。

### 15.4 仍然卡住的一步：CPU 口不收包

```
eth1:  rx_bytes=0        tx_bytes=46844     ← DSA conduit（dp2）
lan3:  rx_bytes=0        tx_bytes=2260
```

发包正常、**收包为 0**。说明交换机没有把用户口帧送到 CPU 口（或其他方向）。
下一步排查方向（按可能性排序）：

1. `nss-dp` 的 dp2 入向是否依赖 `qca-ssdk` 对内置 ESS（dev0）的初始化 ——
   本版 ssdk 日志出现过 `qca-ssdk module init, no device found!`，说明内置 ESS 没被接管。
2. DSA CPU 口是否需要 `qca,sgmii-enable-pll` 或不同的 `phy-mode`。
3. 是否需要给 CPU 口显式加 `dsa-tag`（qca8k 默认 tag 协议）相关属性。

### 15.5 一个副作用（重要）

`rmmod qca_ssdk` 会直接 **kernel panic**（`Oops: Fatal exception` → 自动重启）。
所以**不要**在运行时卸载 ssdk 做实验。

### 15.6 另一个反复踩的坑

SSDK 初始化失败时，`qca_nss_dp` 会每 30 秒重试一次并打印 `Unknown symbol fal_*`，
**把串口 console 刷死**，导致 `reboot` 命令都不响应，只能断电。
以后遇到"串口发命令没反应"，先看是不是这个原因。

---

## 十六、继续攻 CPU 口（01:30）

### 16.1 试过的三组参数，结果一致

| 版本 | CPU 口 | 节点写法 | 结果 |
|---|---|---|---|
| dsa17 | `ethernet-port@6` | 新式 | `DSA: tree 0 setup`，lan1-3 有，**rx=0** |
| dsa_p0 | `port@0` | 老式（对齐 rax3000q） | 同上，lan3 `Link is Up 1Gbps`，**rx=0** |
| dsa_bmp | `port@0` + ESS 补 `switch_cpu_bmp=0x4 / switch_lan_bmp=0x2` | 老式 | 同上，**rx=0** |

三版共同点：`eth1`（conduit）**tx 有计数、rx 恒 0**，`lan3` 同样 tx 有、rx 0，
且 `rx_errors / rx_dropped / rx_missed_errors` 全为 0 —— **帧根本没到 MAC**。

### 16.2 已排除的原因

- ❌ 交换机没认出来：`qca8k 90000.mdio-1:11` 正常 probe，三个 PHY 都绑上
- ❌ 端口没 up：`lan3 carrier=1`，`Link is Up - 1Gbps/Full`
- ❌ DSA 没建树：`DSA: tree 0 setup`
- ❌ 内置 ESS 没初始化：`ssdk_mp_reset_init: MP reset successfully!` + `Initializing SCOMPHY Done!!`
- ❌ `switch_mac_mode` 写错：上游常量 `MAC_MODE_SGMII_CHANNEL0 = 0xf`，与我们一致
- ❌ `ess-switch` 没启用：上游 rax3000q / ipq5000-ax3000 **都**启用了 `&switch`
- ❌ NSS 固件缺失：本仓库根本没有 `nss-firmware` 包，说明主线 ipq50xx 不需要它

### 16.3 剩下的两个方向

**方向 A：SoC 侧 SGMII 收向没配好**
日志里有 `ssdk_uniphy_reset: ERROR:reset(18) not exist!`（出现 3 次）。
UNIPHY 里含 SGMII PCS，复位项在 DT 里找不到。可以在 `&switch` 里补 `resets`
或改用 `qca-ssdk` 的 `switch_mac_mode` 变体再试。

**方向 B：nss-dp 的 RX 在本内核上就不通**
判断依据：U-Boot 用同一路 `eth1` 能 ping 通（硬件 OK），
Linux 侧 tx 正常、rx 恒 0 且无任何错误计数。
若如此，DSA 路线在 24.10 / 6.6.137 上走不通，
应回到 SSDK 路线（让 ssdk 管交换机），或换 6.12 内核。

### 16.4 一个可以快速判定 A/B 的实验

把网线插到 **WAN 口**（dp1，走内置 GE PHY，不经过 QCA8337），
执行 `ip link set eth0 up` 后看 `/proc/net/dev` 的 eth0 rx 计数：

- eth0 **能收到** → 说明 nss-dp RX 正常，问题在 QCA8337/SGMII 这一段（方向 A）
- eth0 **也收不到** → nss-dp RX 整体不通（方向 B），DSA 这条路当版内核走不通

---

## 十七、WAN 口实测（01:35）

把网线从 lan3 换到 WAN 口后：

```
lan3: Link is Down            ← 拔线瞬间（206s）
eth0 carrier = 0              ← WAN 口没有任何链路
lan1/lan2 carrier = 0
eth0 rx_bytes = 0
```

**WAN 口在 Linux 下完全没链路**。两种解释：

1. WAN 口其实挂在 QCA8337 的 **port4** 上（原厂 DTS 的 `switch_wan_bmp = <0x10>` 正是 bit4），
   而我们的 DTS 把 `port@4` 标成了 `status = "disabled"` → 自然无链路。
2. WAN 口挂 SoC 内置 GE PHY（dp1），但该 PHY 在本内核下没被初始化。

从 `switch_wan_bmp = <0x10>` 看，**第 1 种可能性更大**。

### 下一步（按性价比）

1. 把 DTS 里 `port@4` 的 `status = "disabled"` 去掉、加 `label = "wan"`，
   重刷后看 WAN 口是否拿到 carrier —— 这一步能确定 WAN 到底挂在哪。
2. 若 WAN 也确实在交换机上，则 **三个 LAN + WAN 全部由 QCA8337 承载**，
   唯一剩下的问题就是"交换机 → SoC"这一个方向不通（rx 恒 0）。
   此时应重点查 CPU 口：
   - `ethernet = <&dp2>` 的 SGMII 收向
   - 或改试 `port@5 / ethernet = <&dp1>`（内置 GE PHY 当 CPU 口）
3. 若 WAN 在 dp1 上却拿不到 carrier，则说明内置 GE PHY 未初始化，
   与 `ssdk_uniphy_reset: reset(18) not exist!` 同源，需要补 `resets` 定义。

---

## 十八、端口归属定了 + 方案B（02:10）

### 18.1 U-Boot 的端口输出是硬证据

同一次启动里，网线插不同口，U-Boot 的 `ping` 输出会变：

```
网线在 WAN  →  Port1 Down / Port4 Up 1000M / Port5 Up 1000M
网线在 LAN3 →  Port1 Down / Port3 Up 1000M / Port5 Up 1000M
```

**结论：**

| U-Boot 编号 | 实体 | 说明 |
|---|---|---|
| Port1~4 | 四个网口 | LAN1/LAN2/LAN3/WAN，WAN 是 Port4（对应原厂 `switch_wan_bmp=0x10`） |
| Port5 | 常驻 up 1000M | 不是网口，是交换机与 SoC 之间的链路（PZ-L8 同构：QCA8337 的 phy4 接 IPQ5018 内置 GE PHY） |

并且 **U-Boot 只用 LAN 口就能 ping 通** → 交换机本身、三个 LAN 口、CPU 链路全部硬件正常。

### 18.2 已排除的两条路

- **DSA qca8k**：交换机识别成功（`Switch id detected 13`）、3 个 PHY 绑定、`DSA: tree 0 setup`、`lan3 Link is Up 1Gbps`，
  但 `eth1`（CPU 口）**tx 有计数、rx 恒 0、零错误**。CPU 口试过 port6 / port0 两种写法，结果一致。
- **SSDK**：`ISISC_ENABLE=enable` 且 2025-05-30 版已编入 `isisc_init`，
  但 MDIO 上芯片被识别成 `CHIP_DESS`（`QCA_VER_DESS=0x14`），`hsl_dev_init` 返回 -19。

### 18.3 方案B：不接管交换机

思路：U-Boot 已经把 QCA8337 配成可用状态（三个 LAN 口桥到 CPU 口），
那就**不让 Linux 里任何驱动去碰它**：

- DTS 里删掉 `ethernet-switch@11` 整个节点 → `qca8k` 不会 probe
- 没有 `ess-switch1` / `&ess_instance` → SSDK 不会去复位它
- 保留 `&switch`（内置 ESS dev0），让 dp1/dp2 正常起来
- `&dp2` 仍是 sgmii + fixed-link 1000

**第一版失败**：我把 `switch_reset_pins` 从 `mdio1` 的 `pinctrl-0` 里摘掉了，
结果 GPIO26 变成"无人认领"状态（`/sys/kernel/debug/gpio` 里查不到 `gpio-26`），
交换机被按住/状态丢失，**电脑网卡直接 Disconnected**。

**修正**：保留 pinctrl，把 GPIO26 明确 `output-high`（释放复位电平），
但**不挂任何驱动**去翻转它。这样既不碰交换机，又保证它不在复位里。

### 18.4 一条重要的方法论

之前每次判断"交换机没工作"都靠日志推断。其实有个更直接的观测点：
**电脑网卡的 `Status` / `LinkSpeed`**。
`Disconnected / 0 bps` 就是交换机对应端口没链路，比串口日志快得多。

### 18.5 工具链改造

串口常驻桥接反复自己退出（`.global-python` 的子进程被环境回收），
已改为**一次性调用** `ser.py`：

```bash
python ser.py run <秒> "<命令>"   # 发命令+CR，读指定秒数，追加到 console.log
python ser.py spam <秒>            # 每 60ms 发 CR，抢 U-Boot
python ser.py read <秒>            # 只读
```

没有常驻进程，就不会再出现"监听悄悄死了"。

---

## 十九、突破：LAN 打通了（03:20）

### 19.1 缺失的最后一块拼图

`999-ipq4019-mdio-add-qca-ssdk-support.patch`

来源：`crypt0nX/openwrt-xiaomi-ax3000`，`target/linux/qualcommax/patches-6.12/`

它把 `drivers/net/mdio/mdio-ipq4019.c` 改成 QSDK 风格：

- 在驱动里定义一份与 `qca-ssdk/include/init/ssdk_plat.h` **完全同布局**的 `struct qca_mdio_data`
- `bus->priv` 指向它，并提供 `sw_read` / `sw_write` 回调
- 通过 `PHY 0x10 | r2` + `PHY 0x18` 分页间接读写交换机寄存器

**没有这个补丁，SSDK 对外挂 QCA8337 的所有寄存器读写都是空操作**
（`ssdk_plat.c` 里 `if (mdio_priv && mdio_priv->sw_read)` 恒为假，函数直接返回 SW_FAIL）。
这就是之前所有 SSDK 尝试失败、芯片被误识别成 `CHIP_DESS`、`fal_init` 返回 -19 的真正根因。

补丁在 **kernel 6.6.137 上干净应用**（虽然是 6.12 的补丁），dry-run 无冲突。

### 19.2 最终可用配方（四件套，缺一不可）

**① qca-ssdk**

```make
ISISC_ENABLE=enable          # package/kernel/qca-ssdk/Makefile
PKG_SOURCE_DATE:=2025-05-30  # openwrt/qca-ssdk 446db12b1fd3bca2e61e45cb01c4ad52cfddd95b
```
并把 `package/kernel/qca-ssdk/patches/` 清空（旧补丁对新源码全部对不上）。

**② 内核补丁** `999-ipq4019-mdio-add-qca-ssdk-support.patch`（见 19.1）

**③ DTS**（crypt0nX 原版结构，三段）

```dts
&switch  {                    /* dev0：SoC 内置 ESS */
	status = "okay";
	compatible = "qcom,ess-switch-ipq50xx";
	device_id = <0>;
	cmnblk_clk = "internal_96MHz";
	reg = <0x39c00000 0x200000>;
	switch_mac_mode = <0x0f>;   /* MAC_MODE_SGMII_CHANNEL0 */
	switch_access_mode = "local bus";
	qcom,port_phyinfo {
		port@0 { port_id = <1>; mdiobus = <&mdio0>; phy_address = <7>; phy_dac = <0x10 0x10>; };
		port@1 { port_id = <2>; forced-speed = <1000>; forced-duplex = <1>; };
	};
};

&ess_instance {               /* dev1：外挂 QCA8337 */
	status = "okay";
	num_devices = <2>;
	ess-switch1@1 {
		compatible = "qcom,ess-switch-qca83xx";
		device_id = <1>;
		switch_access_mode = "mdio";
		mdio-bus = <&mdio1>;
		reset_gpio = <&tlmm 26 GPIO_ACTIVE_HIGH>;
		switch_cpu_bmp = <0x60>;
		switch_acpu_bmp = <0x60>;
		switch_lan_bmp = <0x0e>;   /* LAN1/2/3 */
		switch_wan_bmp = <0x10>;   /* WAN = port4 */
		qca,ar8327-initvals = <...>;
		qcom,port_phyinfo { port@1..5 → phy 0..4; port@6 forced 1000; };
	};
};

&tlmm { switch_reset_pins: switch-reset-pins { pins="gpio26"; function="gpio"; output-high; }; };
&mdio1 { status="okay"; pinctrl-0=<&mdio1_pins &switch_reset_pins>;
         phy-reset-gpio=<&tlmm 26 GPIO_ACTIVE_HIGH>; ethernet-phy@0..4 {...}; };
```

**④ `/etc/config/network`**：`br-lan` 的端口必须是 **`eth1`**（dp2），不是 eth0。

### 19.3 成功日志

```
qca_ar8327_gpio_reset[2425]:INFO:GPIO538 reset switch done
regi_init[2496]:INFO:Initializing ISISC Done!!
regi_init[2574]:INFO:qca-ssdk module init succeeded!
nss-dp 39d00000.dp2 eth1: PHY Link up speed: 1000
br-lan: port 1(eth1) entered forwarding state
```

### 19.4 端到端实测

| 项 | 结果 |
|---|---|
| 电脑网卡链路 | 1 Gbps |
| `eth1` 收包 | rx 12403 B / 108 pkt（**不再恒为 0**） |
| IPv4 ARP | `192.168.1.100 lladdr 04:7c:16:0c:b0:92 REACHABLE` |
| ping 网关 | True |
| TCP 80 | True |
| HTTP | 200（LuCI） |
| **DHCP** | **电脑自动获取 192.168.1.116，网关 192.168.1.1** |
| 重启后 | 配置持久，`br-lan` 自动挂上 eth1，依然通则 |

### 19.5 一个和固件无关的坑（重要）

电脑「以太网 11」上有一批**持久化静态路由**（公司网络配置）：

```
192.168.1.0/24  -> 10.26.47.1     ← 直接把 192.168.1.1 打飞
10.32.244.0/24  -> 10.26.47.1
10.19.157.0/24  -> 10.26.47.1
10.16.224.0/24  -> 10.26.47.1
10.103.94.0/24  -> 10.26.47.1
```

只要网线插在这块路由上，ping `192.168.1.1` 就会走 `10.26.47.1` → 全部超时。
排查时一定要看 `Get-NetRoute -PolicyStore PersistentStore`，别怀疑固件。

绕过办法（不动公司配置）：在路由器上临时加 `ip addr add 172.16.9.1/24 dev br-lan`，
电脑配 `172.16.9.100/24` 即可，已验证 ping/TCP80/HTTP 全通。

### 19.6 仍未完成

**WAN 口（交换机 port4）**目前没有对应 netdev。
`ls /sys/class/net` 只有 `eth0`/`eth1`，没有 `eth1.2` 之类。
SSDK 把 WAN 放在独立 VLAN，但没向内核暴露带 tag 的接口。
要让 WAN 可用，需要让 nss-dp 按 VLAN 建 netdev，或改 SSDK 的 VLAN 配置。
**三个 LAN 口 + DHCP + LuCI 已经可用。**

---

## 二十、WAN 打通（04:20）

### 20.1 走过的两条死路

**死路 A：CPU 口拆分。** 把 LAN 限定走交换机 port6、WAN 限定走 port5（port5 → 内置 GE PHY → dp1/eth0）。
结果 eth0 拿到 `100M/full` 链路，但 `rx_errs=268 / rx_pkts=11`，ARP 停在 STALE。
上游 rax3000q 的 DTS 注释早就写明 "dp1 and ge_phy are useless"——PHY-to-PHY 这条路径不可靠。

**死路 B：只建 VLAN 表 + 设 PVID。** 日志显示 VLAN 创建成功，但 `eth1.2` 的 rx 恒为 0。
原因见 20.2 的三点。

### 20.2 WAN 必须做对的四件事（缺一不可）

改 `qca-ssdk/src/init/ssdk_init.c` 的 `ssdk_portvlan_init()`：

**① 打开 802.1Q 模式**

`qca_switch_init()` 初始化时对每个口执行了 `fal_port_1qmode_set(dev_id, i, FAL_1Q_DISABLE)`。
**1Q 模式关闭时 VLAN 表根本不会被查询**，建表等于没建。

```c
fal_port_1qmode_set(dev_id, port, FAL_1Q_FALLBACK);   /* 3 */
```

**② 建 VLAN 表，用 untagged 位图决定打不打 tag**

```c
/* VLAN1 = LAN + CPU6，CPU 口 untagged  -> 内核 eth1（保持原状） */
fal_vlan_create(dev_id, 1);
fal_vlan_member_update(dev_id, 1, lan_bmp | BIT(6), lan_bmp | BIT(6));

/* VLAN2 = WAN + CPU6，CPU 口 tagged    -> 内核 eth1.2 */
fal_vlan_create(dev_id, 2);
fal_vlan_member_update(dev_id, 2, wan_bmp | BIT(6), wan_bmp);
```

**③ PVID 必须 svid + cvid 都写**

AR8337（CHIP_ISISC）**没有** `adpt_port_default_vlantag_set`（那个只有 hppe 有），
`fal_port_default_vlantag_set` 在 ISISC 上是**空调用**，而且返回错误码容易被忽略。

```c
fal_port_default_svid_set(dev_id, port, vid);
fal_port_default_cvid_set(dev_id, port, vid);
```

**④ egress 用 `FAL_EG_UNTOUCHED`**，把"打不打 tag"交给 VLAN 表决定

```c
fal_port_egvlanmode_set(dev_id, port, FAL_EG_UNTOUCHED);
```

端口分配：LAN 口 + CPU6 → PVID 1；WAN 口（port4）→ PVID 2。

### 20.3 内核侧

```bash
uci set network.@device[0].ports=eth1          # br-lan 用 dp2
uci set network.vlan2=device
uci set network.vlan2.name=eth1.2
uci set network.vlan2.type=8021q
uci set network.vlan2.ifname=eth1
uci set network.vlan2.vid=2
uci set network.wan.device=eth1.2
uci set network.wan.proto=dhcp
uci set network.wan6.device=eth1.2
uci commit network
```

`firewall` 的 wan zone 默认已含 `network 'wan'`、`masq='1'`、lan→wan forwarding，
所以 WAN 一拿到地址，LAN 客户端就能 NAT 上网，不用额外配。

### 20.4 实测（双线同时接）

PC 用两条网线同时接路由器的 LAN 口和 WAN 口：

| 侧 | 测试 | 结果 |
|---|---|---|
| LAN（PC 以太网12 → LAN 口） | ping 192.168.1.1 | True |
| LAN | TCP 80（LuCI） | True |
| WAN（PC 以太网11 → WAN 口） | ping 192.168.9.1（eth1.2） | True |
| WAN | TCP 80 | True |

`eth1.2` 计数：`rx 12422 B / 130 pkts`（此前恒为 0）。
**重启后依然双侧全通**（`RA80_VLAN: ... pvid=0 eg=0`，`br-lan: port 1(eth1) entered forwarding state`）。

### 20.5 关键日志

```
RA80_VLAN: 1qmode last=0
RA80_VLAN: vlan1 c=0 m=0 | vlan2 c=0 m=0
RA80_VLAN: lan=vlan1(untag cpu6) wan=vlan2(tag cpu6) pvid=0 eg=0
regi_init[2574]:INFO:Initializing ISISC Done!!
```

全部返回 0 才算成功；任何非 0 会打印 `RA80_VLAN: ... rv=N` 并回退到 port-based 成员表。

### 20.6 一个排查教训

`eth1.2` 有收包但 ping 不通时，先怀疑**防火墙**：
eth1.2 不属于任何 zone，默认 input 策略是 REJECT。
（但 `wan` 接口名一旦挂上 eth1.2 就进 wan zone，正常使用不受影响。）

---

## 二十一、WiFi 现状与 BDF 挖掘（04:50）

### 21.1 为什么现在一点 WiFi 都没有（三层缺失）

**① 驱动栈不全**

```
/lib/modules/6.6.137/: ath.ko  ath11k.ko  ath11k_ahb.ko     ← 只有 AHB（2.4G 内置）
                       缺 ath11k_pci                          ← QCN6122(5G) 走 PCIe 需要它
```

**② BDF（板级数据）全缺**

```bash
ls /lib/firmware        → IPQ5018  qcn6122  regulatory.db
find /lib/firmware -name 'board*'   → 空
```

`ath11k` 没有 `board-2.bin` 就起不了射频。`ipq-wifi` 包存在但**从来没被编进镜像**
（我们的 `DEVICE_PACKAGES` 里没有 `ipq-wifi-*`），而且它本地也没有 RA80 的 BDF。

**③ DTS 没开**

内核 `ipq5018.dtsi` 里 `wifi0`(IPQ5018, 2.4G) / `wifi1`,`wifi2`(QCN6122, 5G) 全部 `status = "disabled"`，
板级 DTS 也没有覆盖。之前为了编译通过，把 wifi 相关节点整段删掉了。

### 21.2 关键突破：从原厂镜像里挖出了 BDF

原厂固件 `orig.ubi`（37,748,736 B）是 UBI 容器，直接 `unsquashfs -o` 会报
`read_block failed / filesystem corruption` —— 因为 UBI 的 LEB 之间有 EC/VID 头交错。

自己写了个最小 UBI 解析器（`ubi_extract.py`）：

- PEB = 128KB（37,748,736 / 131,072 = 288，整除）
- EC header: `UBI#`，`vid_hdr_offset` @16，`data_offset` @20
- VID header: `UBI!`，`vol_id` @8，`lnum` @12
- 按 `lnum` 排序拼接每个卷的 data 区

解析结果：

```
vol_id=0   lnbs=28   bytes=3,555,328      （内核/小卷）
vol_id=1   lnbs=149  bytes=18,919,424     （rootfs，squashfs）
vol_id=0x7FFFFFFF   lnbs=2  bytes=253,952 （UBI 内部 layout 卷）
```

`unsquashfs vol1.bin` 成功解出完整原厂 rootfs。

### 21.3 拿到的资源（已保存到 `ax3000/bdf/`）

```
bdf/ipq5018/bdwlan.bin  bdwlan.b10 b20 b21 b22 b23 b24   各 131072 B   ← 2.4G BDF
bdf/qcn6122/bdwlan.bin  bdwlan.b50 b60 b90 bb0           各 131072 B   ← 5G BDF
bdf/fw_version.txt: WLAN.HK.2.5.r4-00683-QCAHKSWPL_SILICONZ-1.414325.21.570923.3 v1
```

原厂还揭示了 caldata 的来源（不在 rootfs 里，开机脚本从分区导出）：

```
/lib/firmware/IPQ5018/caldata.bin        -> /tmp/IPQ5018/caldata.bin
/lib/firmware/qcn6122/caldata_1.bin      -> /tmp/IPQ5018/qcn6122/caldata_1.bin
```

原厂 DTB 里的 WiFi 保留内存布局（从镜像里的 DTB 字符串块读出来的）：

```
q6_mem_regions@4B000000
q6_ipq5018_data@4C400000      ← 2.4G BDF
m3_dump@4D100000
q6_etr_dump@4D200000
q6_qcn6122_data1@4D300000     ← 5G BDF
m3_dump_qcn6122_1@4E200000
q6_qcn6122_etr_1@4E300000
```

### 21.4 ath11k `board-2.bin` 容器格式（已从内核源码确认）

`drivers/net/wireless/ath/ath11k/core.c: ath11k_core_parse_bd_ie_board()`

```c
struct ath11k_fw_ie { __le32 id; __le32 len; u8 data[]; }
```

- 外层：一个 IE，`id = ATH11K_BD_IE_BOARD (0)`，data 是内层 IE 序列
- 内层：先 `ATH11K_BD_IE_BOARD_NAME (0)`（data = 板名字符串），再 `ATH11K_BD_IE_BOARD_DATA (1)`（data = BDF 原始字节）
- 每个 IE 的 data 按 4 字节对齐

板名由 `ath11k_core_create_board_name()` 生成，形如
`bus=ahb,qmi-chip-id=<X>,qmi-board-id=<Y>`，其中 `Y` 来自 DT 的 `qcom,board_id`。
**所以只要知道运行时打印的 chip-id/board-id，就能自己打包 board-2.bin。**

### 21.5 还差的三步（按顺序）

1. **打 `board-2.bin`**：用 `bdwlan.bin` 按上面的 IE 格式打包，板名用运行时实际请求的值
2. **开 DTS**：参考 `ipq5018-rax3000q.dts` 的写法
   - `&q6v5_wcss { status="okay"; qcom,bootargs_smem=<507>; boot-args=...; }`
   - `q6_wcss_pd1`（resets/clocks/firmware-name）+ `&wifi0 { qcom,rproc=<&q6_wcss_pd1>; qcom,board_id=<X>; qcom,ath11k-fw-memory-mode=<2>; qcom,bdf-addr=<...>; status="okay"; }`
   - `reserved-memory` 补 `tz_apps@4a400000`(0x700000) 和 `q6_mem_regions@4b000000`(0x3000000)
   - 5G 还要 `ath11k_pci` 模块 + PCIe 节点 + `q6_wcss_pd2`
3. **caldata**：找到存 caldata 的 mtd 分区，按原厂方式导出到 `/tmp/IPQ5018/`

已知风险：crypt0nX（同为 RA80）自述 5G 不工作；256MB RAM 跑双频易 OOM。

---

## 二十二、WiFi 攻坚（06:00–07:10）

### 22.1 纠正三个此前的误判

| 之前的说法 | 实际 |
|---|---|
| 5G 需要 `ath11k_pci`，镜像里没有所以 5G 不可能 | **错**。QCN6122 走 `ath11k_ahb`（compatible `qcom,qcn6122-wifi`），`pcic.o` 编在 `ath11k.ko` 里，不需要独立 pci 模块 |
| 启用 WCSS 会抢走 SSDK 的复位/时钟导致 -19 | **错**。逐条比对 `q6v5_wcss` 与 `ess-switch` 的 resets/clocks，集合不相交。hzyitc 的 RA80 固件就是 SSDK + ath11k 双开 |
| wifi3 的 `-22` 是缺 `firmware-name` | **不全**。`q6_alloc_memory_region()` 也要 `memory-region` phandle，缺任一个都是 -EINVAL；两者都必需 |

`-19` = `SW_NOT_SUPPORTED`，真实来源是 SD 层寄存器访问通道未注册：

```c
sw_error_t sd_reg_hdr_get(...) { if (NULL != ssdk_hdr_reg_get) ... else return SW_NOT_SUPPORTED; }
```

### 22.2 已经打通到哪一步

在 `/root/iw-b`（SSDK 只管 dev0、不接管外挂交换机的 DTS）上，WiFi 跑到了 **QMI 阶段**：

```
ath11k c000000.wifi: ipq5018 hw1.0
ath11k c000000.wifi: FW memory mode: 2
remoteproc1: Booting fw image IPQ5018/q6_fw.mdt
remote processor cd00000.remoteproc is now up
remote processor pd-1 is now up
ath11k: chip_id 0x0 chip_family 0x4 board_id 0x24
ath11k: fw_version ... WLAN.HK.2.7.0.1-01744-QCAHKSWPL_SILICONZ-1
```

即：Q6 起来了、QMI 通了、**芯片和 board_id(0x24) 都读对了**。

### 22.3 两个关键细节（值得记）

**① caldata 的文件名是 `cal-ahb-c000000.wifi.bin`**

ath11k 通过 QMI 向用户态要这个文件；原厂/`11-ath11k-caldata` 脚本是从 `0:ART` 分区 dd 出来的。
我们的固件 `/proc/mtd` 只有 `rootfs`（U-Boot 的 `mtdparts=` 覆盖了 DTS 分区表），所以脚本取不到。
**绕过办法**：把 BDF 直接按这个名字放进镜像（QSDK 里 caldata 与 BDF 就是同一份数据）。

放进去之后 `failed to load board data file: -12` 消失。

**② `bdwlan.bin` 与 `bdwlan.b24` 完全相同**（md5 `6d0ce591b70aba07d35cbebb3995e989`），
所以「board_id 0x24 该用 b24」这个担心可以排除，用哪个都行。

### 22.4 现在卡在 WMI

| 固件版本 | 结果 |
|---|---|
| `WLAN.HK.2.7.0.1`（OpenWrt 包自带） | QMI 通、board_id 对 → `failed to receive wmi unified ready event: -110`（超时） |
| `WLAN.HK.2.5.r4`（原厂 rootfs 自带） | `remoteproc1: Failed to load program segments: -110`（段加载就失败） |

两个方向都不通：2.7 能跑起来但 WMI 握不上手；2.5 连段都加载不了。
**最可能的原因**：BDF 是 2.5 时代生成的，与 2.7 固件跨代不配套。

下一步应该是拿一份 **2.7 时代的 BDF**（上游 `ipq-wifi` 里同平台板子的）来试，
如果能握上手，说明就是 BDF 版本问题，再去解决「RA80 专用 BDF」。

### 22.5 有线和无线的互斥（现状）

| 树 | 交换机 | WiFi |
|---|---|---|
| `immortalwrt-ax3000`（主线） | SSDK 管外挂 QCA8337，**有线全通** | 加 reserved-memory 后 SSDK 在 `qca_ar8327_sw_soft_reset` 崩 |
| `iw-b` | 无人管理（无 DSA、无 ess-switch1） | Q6 起来了，**有线不通** |

也就是说：目前**没有一版能同时满足有线和无线**。设备已刷回 `vlan3`（有线全通）。

### 22.6 工具链修复（自己的坑）

1. **`ser.py` 打开 COM5 时必须把 DTR/RTS 拉到无效**，否则这块板子的串口完全没输出。
   这就是"上电了却一个字都没有"的真正原因。
2. 新增 `flow` 模式：**单进程内**先 spam 抢 U-Boot 再依次执行命令，
   不再需要"后台 spam 占着端口、别的命令进不来"。
3. 新增 `sysrq` 模式：一条命令内完成「开 sysrq → 触发重启 → spam 抢 U-Boot → 执行」。

---

## 二十三、WiFi 深挖（08:00–09:10）：Q6 能起来，射频初始化崩

### 23.1 已经打通的链路

```
Q6 起来 → QMI 通 → chip_id/board_id/fw_version 都读对 → BDF+cal 下发 → 射频初始化 ✗ 崩
```

### 23.2 关键源码发现（都在 backports-6.12.61 里）

**① IPQ5018 的 `fixed_bdf_addr = true`**

`ath11k_qmi_assign_target_mem_chunk()` 里：

```c
case BDF_MEM_REGION_TYPE:
    if (of_property_read_u32(dev->of_node, "qcom,bdf-addr", &addr))
        addr = ab->hw_params.bdf_addr;
```

而且 `ath11k_qmi_load_file_target_mem()` 里：

```c
if (ab->hw_params.fixed_bdf_addr) {
    if (type == ATH11K_QMI_FILE_TYPE_CALDATA)
        bdf_addr += ab->hw_params.fw.cal_offset;   /* 128KB */
    memcpy_toio(bdf_addr, temp, len);
}
```

即：**驱动自己把 BDF 写到 `qcom,bdf-addr`，cal 写到 bdf+0x20000**，然后告诉固件"数据不在 QMI 里，去那个地址读"。
所以 BDF 文件内容确实被用上了（我一度怀疑它没被用）。

**② `fw_size = min(board_size, bd.len)`，board_size = 256KB** → 128KB 不会被截断。

**③ `qcom,ath11k-fw-memory-mode` 真的被解析**（core.c `ath11k_init_hw_params`），
mode 2 会额外设置 `num_vdevs=4 / num_peers=32 / coldboot_cal_mm=false`。

### 23.3 cal 到底从哪来（原厂实证）

原厂 `/lib/read_caldata_to_fs.sh`，`ap-mp03.1*`（IPQ5018）分支：

```sh
dd if=${mtdblock} of=${apdk}/IPQ5018/caldata.bin bs=1 count=131072 skip=4096
```

即 **cal = ART 分区 0x1000 起的 128KB**；`bdwlan.bin` 只是通用 BDF。
我们之前把 BDF 当 cal 喂，是错的。

### 23.4 新增的两个工具能力

- **`tftprecv.py`**：U-Boot `tftpput` 的上传接收端。必须回 **OACK(opcode 6)** 而不是 ACK0，
  否则 U-Boot 会一直重发 WRQ。
- **`ctrlc.py`**：`ser.py` 之前把 `CTRL_C` 当字面字符串发，发的是假 Ctrl-C；
  真正的 0x03 才能打断 U-Boot 的 tftp 重试循环。

一次实战：从设备把 **整个 ART 分区（1MB）** 取回本地（`art_dump/art.bin`）。

### 23.5 ART 与 rootfs 里 BDF 的关系

| 文件 | md5 | 0x45c |
|---|---|---|
| ART[0x1000] 128KB | f5d010d9e7d226b49ceafd34c5c0c3ac | 0x03 |
| rootfs `bdwlan.bin`(=`bdwlan.b24`) | 6d0ce591b70aba07d35cbebb3995e989 | 0x03 |
| rootfs `bdwlan.b10` / `b20` | — | **0x00** |
| 上游 2.7 时代 BDF（b3000/ax6000/…） | — | **0x00** |

两者只差 448 字节（逐机校准），所以 ART ≈ BDF + cal。

### 23.6 排除了什么（都试过，全崩）

| 变量 | 试过的值 | 结果 |
|---|---|---|
| BDF 内容 | 原厂 b24 / ART 原始 / 上游 GL-B3000 / 0x45c 改成 0x00 | 全崩 |
| BDF 位置 | 在 U-Boot 里预置到 0x4c400000 再启动 | 全崩（驱动会自己再写一遍） |
| cal 内容 | BDF 冒充 / ART 原始 / B3000 | 全崩 |
| `tz_apps@4a400000` | 补上 7MB | 全崩 |
| carveout | 48MB / 77MB | 全崩 |
| `cold_boot_cal=0` | 模块参数（已验证 sysfs = N） | 全崩 |
| 内存档位 | 2（48MB/77MB）/ 1（48MB） | mode1 崩得更早（QMI 内存请求阶段） |

### 23.7 现在卡在哪

2.7 固件在 `wlan0` 射频初始化时抛异常：

```
Excep :0 Exception detected PName:wlan0 TName:WLAN RT0
PC : 0xb02449a0   BADVA : 0x3a855555
```

即：**Q6 主固件起来了、QMI 通了，但射频（PHY）初始化这一步过不去**，之后 WMI 永远等不到 ready。
缺 BDF 时不会崩（说明是射频初始化触发），任何 BDF/cal 都一样（说明不是数据内容）。

### 23.8 下一步的两条路

1. **继续在这棵树上试**：mode 0 / `qcom,caldb-addr` / 打开 coldboot 校准。
2. **换基线**：immortalwrt-25.12 或 master 的 ipq50xx（kernel 6.12/6.18），
   那里 IPQ5018+QCN6122 是官方支持设备，ath11k 补丁齐；顺带把有线换成 mainline DSA，
   SSDK 那些 VLAN 补丁全部可以扔掉。

### 23.9 后续又试了（09:10–09:50），仍然全崩

| 实验 | 结果 |
|---|---|
| 补 `qcom,m3-dump-addr = <0x4d400000>`（不再丢段） | 警告消失，崩溃点不变 |
| 档位 1 + 77MB（等价 mx6200） | 内存请求阶段崩，`Coldboot Calibration timed out` |
| 档位 1 + `cold_boot_cal=0`（等价上游 0907 补丁 + 512MB 档） | 能走到 BDF 下发，射频初始化仍崩 |
| 档位 1 + 冷启动校准开 + `qcom,caldb-addr = <0x4d200000>` | 进 `wlan mode 7`（冷启动校准）后固件崩，校准超时 |

**上游 0907 补丁**（`cf715a23`）内容确认：只是把 ipq5018 hw params 里的
`coldboot_cal_mm/ftm` 从 `true` 改成 `false`，别的没动。
我们用档位 2 / `cold_boot_cal=0` 都已经等价实现了，所以这条不是我们的拦路虎。

### 23.10 结论（这个基线）

Q6 固件、QMI、BDF/cal 投递都验证通了，**唯独射频初始化过不去**，
且与 BDF/cal 内容、carveout 大小、内存档位、冷启动校准、m3 dump 全部无关。
剩下最可能的解释：**24.10 fork + kernel 6.6 + backports-6.12.61 这套
ipq50xx 补丁不完整**（OpenWrt main 是在 6.12/6.18 上把 IPQ5018+QCN6122 做通的）。

要真拿下 WiFi，建议换基线：OpenWrt 25.12 / main 的 ipq50xx，
把 RA80 的板级 DTS 移植过去（main 里已有 `xiaomi_ax6000`，同 SoC 同 5G 芯片，可直接抄）。
附带好处：有线改走 mainline DSA，SSDK 那些 VLAN 补丁全部可以扔掉。

---

## 二十四、换基线：移植到 OpenWrt main（11:00–）

### 24.1 为什么换

旧基线（24.10 fork + k6.6 + backports-6.12.61）把 WiFi 推到「Q6 起来、QMI 通、BDF/cal 下发成功」，
但固件在**射频初始化**必崩，且与 BDF/cal/内存档位/carveout/冷启动校准/m3dump 全部无关。
main 上同 SoC 的 `ipq5018-mr80x-v2`（IPQ5018+QCN6122+256MB）配置与我们**完全一致**
（mode 2 + bdf 0x4c400000），差别只是它成对带 `wifi1` ——说明是基线补丁完整度问题，不是板子问题。

### 24.2 main 上找到的关键参照

- `ipq5018-mr80x-v2.dts`：256MB 同型机，但 **WiFi 默认 disabled**，注释写明
  「ath11k 占内存太大，256MB 跑 LuCI 会 OOM」。→ 说明是**内存策略**，不是不支持。
- `ipq5018-qcn6122.dtsi`：`q6_region` 48MB；`q6v5_wcss` 的 firmware-name 三元组；
  pd-1/pd-2/pd-3 的完整 smem/interrupts 定义。
- `ipq5018-rax3000q.dts`：同 QCA8337 交换芯片的 **DSA** 写法（`qca,qca8337` @ mdio1 0x11）。

### 24.3 我们的 RA80 板级事实（来自 SSDK 那几轮）

```
LAN1/2/3 = 交换口 1/2/3       WAN = 交换口 4       CPU = 交换口 6 (SGMII → gmac1)
QCA8337 @ mdio1 addr 0x11    PHY: 口N ↔ phy(N-1)
ART @ flash 0x780000 (1MB)   BDF(2.4G)@0x1000 / BDF(5G)@0x26800，各 128KB
分区: 0:SBL1..0:APPSBL_1, 0:ART@0x780000, bdata@0x900000, rootfs@0xa80000, overlay@0x2e80000
复位脚: gpio26(交换芯片, 低有效)  按键: gpio25 reset / gpio23 wps  灯: gpio19/17/22
```

### 24.4 移植动作

1. 新增 `target/linux/qualcommax/dts/ipq5018-xiaomi-ax3000.dts`
   - gmac1 + DSA(qca8337)，CPU 口 6、WAN 口 4、LAN 口 1/2/3
   - wifi0 + wifi1 全开，mode 2，bdf-addr 0x4c400000 / 0x4d100000，m3-dump 0x4df00000
2. `image/ipq50xx.mk` 加 `Device/xiaomi_ax3000`（FitImage + UbiFit，config@mp02.1，IMAGE_SIZE 35MB）
3. `02_network` 登记 `xiaomi,ax3000` → `lan1 lan2 lan3 / wan`
4. 板级固件塞进 `ipq50xx/base-files/lib/firmware/ath11k/`：
   `IPQ5018/hw1.0/board.bin` + `cal-ahb-c000000.wifi.bin`（都来自 ART 0x1000），`QCN6122/hw1.0/board.bin`（ART 0x26800）

### 24.5 预期

- 有线走 mainline DSA（不再需要 SSDK 那套 VLAN 补丁）
- WiFi 用 main 的完整 ipq50xx 补丁集，2.4G 有望直接起来；5G 看 ath11k 是否支持 userpd

---

## 二十五、换基线成功：mainline 上 2.4G 热点跑通（15:00–15:15）

### 25.1 结论先行

**OpenWrt main（kernel 6.18.60）上，RA80 的 2.4G 射频正常工作，能开 WPA2 热点。**

```
phy0-ap0  ESSID: "RA80-Test"  Mode: Master  Channel: 1 (2412 MHz)  HT Mode: HE20
Encryption: WPA-PSK (CCMP)   Tx-Power: 30 dBm   HW Mode(s): 802.11ax/n/g/b
```

旧基线（24.10 fork + k6.6 + backports-6.12.61）里那个「射频初始化必崩」的问题，换基线后**根本不存在**——
所以之前的判断是对的：不是板子问题，是那套 ipq50xx 补丁不完整。

### 25.2 NAND/UBI 读不出来的真因（重要，会误导很久）

现象：U-Boot 能读能写、内核 6.18 读同一段就 `ECC error -74`，`vtbl_check: bad CRC`。

真因：**DTS 里 `nand-ecc-strength = <8>` 与芯片实际能力不符**。

- 芯片：`spi-nand spi0.0: ESMT SPI NAND`，128MiB / 2048+64 / 128KiB
- 驱动表 `drivers/mtd/nand/spi/esmt.c`：`F50L1G41LC` → `NAND_ECCREQ(1, 512)`
  → 片内 ECC 只有 **1bit/512B**
- 我们照抄了 fork（那是另一颗 GigaDevice）的 8bit/512B → 片内 ECC 被绕开，
  单 bit 翻转无人纠正（实测 EC 头里 `0x7fffffff` 变成 `0x7fffef ff`，只翻了一位）
- 内核自己 `ubiformat` 再挂载也失败 —— 因为读写用的是同一套错误配置，仍不自洽

改法（等价于 main 上的 `ipq5018-mr80x-v2.dts`）：

```diff
 	nand@0 {
 		compatible = "spi-nand";
 		reg = <0>;
 		nand-ecc-engine = <&qpic_nand>;
-		nand-ecc-step-size = <512>;
-		nand-ecc-strength = <8>;
 		nand-bus-width = <8>;
```

改完 `ecc_strength=1`，`ubiformat` + `ubiattach` 一次通过：

```
ubi0: attached mtd18 (name "rootfs", size 36 MiB)
ubi0: good PEBs: 288, bad PEBs: 0, corrupted PEBs: 0
```

### 25.3 移植到 main 的关键事实

- 设备 DTS：`target/linux/qualcommax/dts/ipq5018-xiaomi-ax3000.dts`
  - `q6v5_wcss` MPD 三 PD（pd-1/pd-2/pd-3），`q6_region` 48MB
  - `&wifi`（IPQ5018 2.4G）：`fw-memory-mode=2` + `bdf-addr=0x4c400000`
  - `&wifi1`（QCN6122 5G）：`userpd-subsys-name="q6v5_wcss_userpd2"` + `bdf-addr=0x4d100000`
  - 有线：gmac1 + DSA(qca8337 @ mdio1 0x11)，CPU 口 6 / WAN 口 4 / LAN 1-3
  - 分区表放 DTS（main 内核没开 `CONFIG_MTD_CMDLINE_PARTS`，`mtdparts=` 无效）
- 板级固件：`ipq50xx/base-files/lib/firmware/ath11k/`
  - `IPQ5018/hw1.0/board.bin` + `cal-ahb-c000000.wifi.bin`
  - `QCN6122/hw1.0/board.bin` + `cal-ahb-b00a040.wifi.bin`（文件名必须带节点名 b00a040.wifi）

### 25.4 还没解决的

1. **5G（QCN6122）**：cal 名改对后能过 cal，但 `board.bin` 报
   `found invalid board magic` —— QCN6122 不吃裸 ART 块，需要 board-2.bin 容器格式。
2. **持久化**：`sysupgrade -n` 在 initramfs 里没真正写卷（UBI `user volume: 0`），
   设备进 U-Boot `bootmiwifi` 循环。改用 `factory.ubi` 走 U-Boot 直写。
3. **MAC**：目前 `00:03:7f:12:e6:e6`（QCA 默认），应从 ART 读。

### 25.5 5G 崩溃的真凶（已定位，暂禁用）

刷入 fac6 后 2.4G 反而挂了，日志：

```
qcom-q6-mpd cd00000.remoteproc: fatal error received: err_smem_ver.2.1:
Image Variant : IMAGE_VARIANT_STRING=5018.wlanfw2.map_spr_spr_evalQ
phyrf_bdf.c:6245 Assertion axis_value == ANTENNACHAIN_AXIS_Z failed
Thread name : wlan_platform   Process name :wlan1     <-- 注意是 wlan1
```

→ 崩的是 **5G（QCN6122）**，不是 2.4G。QCN6122 的 BDF 是裸 ART 块，
驱动报 `found invalid board magic` 后固件在解析 BDF 时断言，
把 **共用的 Q6（cd00000.remoteproc）一起带崩**，2.4G 才跟着报
`failed to receive wmi unified ready event: -110`。

initramfs 那次之所以 2.4G 能用，是因为当时 5G 的 cal 文件名不对、
在更早的阶段就退出了，没机会崩。

**处置**：`&wifi1 { status = "disabled"; }`，先保 2.4G 稳定。
后续要开 5G，得把 ART 里的 5G BDF 打成 board-2.bin 容器（带 board magic），
不能直接用裸块。

### 25.6 当前实测状态（fac7）

| 项目 | 状态 | 证据 |
|---|---|---|
| 从 flash 启动 | ✅ | UBIFS 挂上 `ubi0:2 rootfs_data`，重启后仍在 |
| LAN | ✅ | lan1/2/3 + br-lan 192.168.1.1，PC ping 通 |
| WAN | ✅ | wan 链路 1Gbps，静态 192.168.9.2 与 PC 双向 ping 通；`ip_forward=1`，`masquerade` 规则在 |
| 2.4G 射频 | ✅ | `phy0` 生成，`iwinfo`: 2412MHz / HE20 / 30dBm |
| 热点 | ✅（待客户端验证） | hostapd `status: ENABLED`, ssid RA80, beacon 100ms, `phy0-ap0` 已桥进 br-lan |
| 5G | ⛔ 暂时禁用 | BDF 需打容器 |
| MAC | 部分 | LAN/WAN 是真实小米 OUI（44:df:65:…），WiFi 仍是 QCA 默认 00:03:7f:… |

### 25.7 5G 攻关成功（关键：BDF 偏移 0x45c）

**三层障碍，逐个拆掉：**

1. **投递路径**：QCN6122 不走 `fixed_bdf_addr`（那是 IPQ5018 独有），
   它走 `ath11k_core_fetch_bdf()` → `board-2.bin` 容器。
   直接喂裸 ART 块会 `found invalid board magic`。

2. **容器格式**（从 `ath11k/core.c` 读出来的）：
   ```
   magic "QCA-ATH11K-BOARD\0"（补齐到 4 字节，即 20 字节）
   然后一串 fw_ie { le32 id; le32 len; data }，data 补齐到 4
     id=0 = BOARD，payload 又是一串 fw_ie：
        id=0 = BOARD_NAME（**不带结尾 NUL**，长度必须与驱动构造的完全一致）
        id=1 = BOARD_DATA（裸 BDF）
   ```
   名字规则（默认 bdf_search）：`bus=<bus>,qmi-chip-id=<chip>,qmi-board-id=<board>`
   实测 5G 侧 `chat_id=0 / board_id=0xff / bus=ahb`，所以主名是
   `bus=ahb,qmi-chip-id=0,qmi-board-id=255`，再补一个兜底名 `bus=ahb,qmi-chip-id=0`。

3. **BDF 内容**：容器做对了之后仍然 `phyrf_bdf.c:6245 Assertion axis_value == ANTENNACHAIN_AXIS_Z`。
   真因是 **BDF 偏移 0x45c 必须是 0x00000000**（2.7 固件要求；2.4 时代那一批是 0x03）。
   改完立刻正常。

**证据链**：ART 0x26800 那块 5G BDF 与原厂 `bdwlan.b60` 只差 300 字节（逐机校准部分），
说明基线正确，缺的只是 0x45c 这个版本标记。

**结果**：
```
phy0  phy1
phy0-ap0  RA80      2412 MHz  HE20  30 dBm   WPA2
phy1-ap0  RA80-5G   5180 MHz  HE80  26 dBm   WPA2   MAC 44:df:65:ef:84:c4（ART 真实 MAC）
```
两路都 `br-lan: port 4/5(phyX-ap0) entered forwarding state`。

工具：`mk_board2.py`（打包 board-2.bin，自动把 0x45c 置 0）。

### 25.8 产品化：LuCI + HE40 + 首启自动配置 + sysupgrade 修复

**① 首启自动配置**：`ipq50xx/base-files/etc/uci-defaults/99-ra80-wifi`
- 双频 SSID/密码/信道/带宽全部预置（2.4G=HE40，5G=HE80）
- MAC 从 `eth0` 推导：2.4G=LAN+2、5G=LAN+1（与 ART 分配一致，换机也不用改脚本）
- 验证：刷完 factory 镜像后**不做任何手工操作**，两路直接起来

**② LuCI**：`CONFIG_PACKAGE_luci=y`（含 mod-admin-full / theme-bootstrap / app-firewall）
- `http://192.168.1.1/` → 200，跳转 `/cgi-bin/luci/`

**③ 按键**：**不需要** `kmod-input-gpio-keys`
- OpenWrt 用自家 `gpio_button_hotplug`（注册名为 gpio-keys）接管 `keys` 节点
- 多装 kmod 会刷 `Driver 'gpio-keys' is already registered` 噪音
- `/etc/rc.button/{reset,wps,power,reboot,failsafe,rfkill}` 齐全，长按 reset 走标准恢复出厂流程

**④ sysupgrade 静默失败的真因**（重要）
`target/linux/qualcommax/ipq50xx/base-files/lib/upgrade/platform.sh` 里
**没有 `xiaomi,ax3000` 分支**，于是落到 `default_do_upgrade` —— 那是非 NAND 的通用路径，
在 UBI 布局上什么都不会写，只打印 `Commencing upgrade` 然后重启，看起来像"升级了但没变"。

修法（与 yuncore/zyxel 同类，单分区 + kernel/rootfs/rootfs_data 三卷）：
```sh
	xiaomi,ax3000)
		CI_UBIPART="rootfs"
		nand_do_upgrade "$1"
		;;
```

**⑤ 镜像尺寸**：加了 LuCI 后 factory 从 0xE80000 → **0xF00000**（15,728,640B）。
U-Boot 刷写长度必须同步改，否则尾部写不全。

### 25.9 两个后发现的坑（都已修）

**① 首启配置不能依赖 `wifi config`**
`wifi config` 按**当时的 phy 枚举顺序**写 `path`，而两个射频谁先注册不稳定。
结果出现过 `radio1.path = c000000.wifi`（2.4G）却配 `channel 36 / HE80`，
hostapd 直接 `Could not determine operating frequency` → `Unable to setup interface`，
两路全哑，且 `wifi restart` 也救不回来（日志里连 hostapd 都不打）。
改法：`uci-defaults` 里**直接写死** `/etc/config/wireless` 的 path/band，
不再走 `wifi config`。修完后 sysupgrade 重启一次就自动恢复，信道正确。

**② sysupgrade 在 256MB 上会 OOM（不是 bug，是内存）**
`nc > /tmp/xxx.bin` 把 15MB 写进 tmpfs（RAM 盘），而双频 ath11k 已吃掉 ~85MB，
`available` 只剩 2~4MB → OOM killer 连环杀 hostapd/netifd/rpcd，甚至触发硬件看门狗。
**正确姿势**：升级前先 `wifi down; rmmod ath11k_ahb; rmmod ath11k`
（能立刻腾出 85MB，available 回到 ~85MB），推镜像再 `sysupgrade`。
反正升级完必重启，不需要无线复活。
注：`rmmod` 后**无法再加载回来**（Q6 会 `start timed out`），只能重启恢复——
所以这个操作只在"马上要升级/重启"时做。

### 25.10 最终验证（sys14，等价 fac14）

| 项 | 结果 |
|---|---|
| 从 flash 启动 + 配置持久 | ✅ 重启后 SSID/信道/MAC 全自动恢复 |
| LAN | ✅ lan1/2/3 + br-lan 192.168.1.1，PC ping 通 |
| WAN | ✅ 1Gbps，DHCP 客户端；静态验证过双向三层可达；`ip_forward=1` + `masquerade` |
| 2.4G | ✅ ch1 / HE40（2x2 40MHz，符合原厂）/ 30dBm / MAC 44:df:65:ef:84:c5 |
| 5G | ✅ ch36 / HE80 / 26dBm / MAC 44:df:65:ef:84:c4 |
| 热点 | ✅ 两路均 WPA2-PSK(CCMP)，已桥进 br-lan |
| LuCI | ✅ 登录 302 → `/cgi-bin/luci/admin/status/overview` 200 |
| 按键 | ✅ `gpio_button_hotplug` 接管，`/etc/rc.button/*` 齐全 |
| sysupgrade | ✅ 修 `platform.sh` 后可正常刷写并重启（`user volume: 4`） |

**内存现状**：MemTotal 183MB，双频起来后 MemFree ≈ 22MB、MemAvailable ≈ 2~4MB。
日常够用，但**任何大文件落 tmpfs 都会 OOM**。要更宽裕只能上 QSDK 的 256M host
mem profile 补丁（减少 ath11k 的 host 侧 ring/peer 分配），属于下一步优化。

---

## 二十六、缺口排查与基础测试（17:20–18:55）

### 26.1 五项缺口

| 缺口 | 处置 | 结果 |
|---|---|---|
| 网关 / 性能仪表板 | 加 `luci-mod-status` | overview / routes / realtime(bandwidth,load,connections) / channel_analysis 全 200 |
| OOM 自愈 | 新增 `ra80-guard` 服务 | 关键进程 `oom_score_adj=-1000`；杀 hostapd 后 30s 自动拉起（实测） |
| 快速连接按键(WPS) | `wpad-basic-mbedtls` → `wpad-mbedtls` | `ubus -v list hostapd.phy0-ap0` 有 3 个 wps 方法；`/etc/rc.button/wps` + `/etc/rc.wps/40-wps_ap` 在位 |
| NSS 加速 | **mainline 无 qca-nss 包**（feeds 里搜不到） | 改开软件 flowtable（`flow_offloading=1`，nft 里有 flowtable） |
| 吞吐测试 | 新增 `iperf3` 包 + 自建测试工具 | 见 26.2 |

**包选择的坑**：`DEFAULT_PACKAGES` 里的 `wpad-basic-mbedtls` 会被 `make defconfig` 反复写回，
`DEVICE_PACKAGES` 里写 `-wpad-basic-mbedtls` 不管用；必须在 `.config` 里写显式的
`# CONFIG_PACKAGE_wpad-basic-mbedtls is not set` 才压得住。

### 26.2 实测数据（sys17）

测试方法：PC 双网卡，WAN 侧 192.168.9.100 → 路由器 WAN 192.168.9.2，
路由器 `firewall redirect` DNAT 5201→`192.168.1.200:5202` 且 lan zone 开 masq。
这样路由器**只做转发、不终止连接**，测的是真实转发能力。

| 场景 | 结果 |
|---|---|
| WAN→LAN 转发 100MB | 270 Mbit/s |
| WAN→LAN 转发 300MB | 281 Mbit/s |
| WAN→LAN 转发 4 流 × 150MB | 281 Mbit/s（**不随流数增长**） |
| 转发时路由器 CPU（600MB/18s） | 总 45%，其中 softirq 43% → 单核软中断打满 |
| 小文件 1MB | 310 Mbit/s，建连 ~19ms |
| 小文件 5MB | 289 Mbit/s，建连 ~22ms |
| IPv6 LAN ping6 | 0% 丢包，0.76–1.54 ms |
| IPv6 吞吐（路由器 wget 拉 PC） | 211 Mbit/s（受 busybox wget 上限） |
| IPv4 LAN（路由器 wget 拉 PC） | 230 Mbit/s（同上，工具上限，非链路上限） |

**结论**：`~280 Mbit/s` 是本机在**无 NSS 硬件加速**下的真实转发天花板，
瓶颈是单核 softirq，与流数无关。想上到千兆必须 NSS offload（qca-nss-dp + ecm），
那是 QSDK 专属，mainline 没有，需要单独移植。

RPS 想摊到多核失败：DSA 用户口不暴露 `queues/rx-*/rps_cpus`（写入无效，读到 0）。

### 26.3 IPv6 现状

- LAN：`fdaa:f977:6e63::/60` ULA，RA + DHCPv6 正常下发，PC 拿到地址
- WAN：需要上游 DHCPv6-PD，本机测试环境没有，未验证
