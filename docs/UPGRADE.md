# RA80 刷机与升级

> 适用于小米 AX3000（RA80）。分区：`rootfs` = mtd18，起始 `0x2e80000`，长度 `0x2400000`（36MB）。
> 串口 115200 8N1，U-Boot 不会坏，最坏情况能救回来。

## 一、升级前必须腾内存（最容易忽略）

双频 ath11k 起来后 `MemAvailable` 只有 2~4MB，**把 15MB 镜像写进 `/tmp` 必然 OOM**
（会连环杀 hostapd/netifd/rpcd，甚至触发硬件看门狗）。

```sh
wifi down
rmmod ath11k_ahb
rmmod ath11k
free -m            # available 应回到 ~85MB
```

⚠️ `rmmod` 之后无线加载不回来（Q6 会 `start timed out`），只能靠重启。
所以只在"马上要升级/重启"时做。

## 二、运行中升级（sysupgrade）

镜像要先进路由器。HTTP 在很多环境下会被安全软件掐断，用裸 TCP 推最稳：

```sh
# PC 侧（把 push.py 指向你的镜像）
python push.py     # 监听 0.0.0.0:9000

# 路由器侧
nc <PC的LAN地址> 9000 > /tmp/sysupgrade.bin
md5sum /tmp/sysupgrade.bin      # 必须与本地一致
sysupgrade -n /tmp/sysupgrade.bin
```

成功的标志：日志出现 `ubi0: user volume: 4` 与 `mount_root: switching to ubifs overlay`。

## 三、U-Boot 直写（系统进不去时）

1. PC 起 TFTP 服务，目录里放 `factory.ubi`
2. 串口连续回车打断 autoboot
3. 逐条执行（**每次 reset 后环境会丢，IP 要重设**）：

```
setenv ipaddr 192.168.137.1
setenv serverip 192.168.137.205
setenv ethact eth1
ping 192.168.137.205
tftpboot 0x44000000 factory.ubi
nand erase 0x2e80000 0x2400000
nand write 0x44000000 0x2e80000 0x<镜像字节数>
reset
```

⚠️ `nand write` 的长度必须等于镜像实际字节数（`printf '0x%X' $(stat -c %s factory.ubi)`）。
加包会让镜像变长，长度写小了就是尾部没写全、起不来。

## 四、刷后验收

```sh
uptime                              # 确认真重启了
iwinfo | grep -E "ESSID|Channel:"   # 两路都要有具体信道；Channel 0 表示 hostapd 没起来
ls /sys/class/ieee80211/            # 期望 phy0 phy1
uci get network.wan.proto           # dhcp
free -m                             # MemFree 约 20MB
```

浏览器打开 `http://192.168.1.1`，用 `root` + **空密码** 登录。

## 五、常见假故障

| 现象 | 真相 |
|---|---|
| `Channel: 0 (unknown GHz)` | wireless 配置里 `path` 指错射频，hostapd 算不出频率 |
| `Unable to setup interface` | 同上 |
| 串口长时间无输出但能 ping 通 | 控制台只是空闲，发条命令就有回显 |
| LuCI 直接访问返回 403 | 没登录，不是坏了 |
| 升级后配置全丢 | 用了 `-n`；本镜像靠 `/etc/uci-defaults/99-ra80-wifi` 首启自动生成 |
