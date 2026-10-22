# Power Deck 项目交付文档

更新：2026-10-20。目标链路为 **Apollodeck（STM32N6，SPI 主机）→ ESP32-C6 SPI 从机 → WiFi/UDP → 电脑上位机**，同时采集和回传 INA226 功耗数据。

## 1. 交付范围与当前状态

| 部分 | 当前能力 / 待完成事项 |
|---|---|
| Power Deck / C6 | SPI 从机 DMA 接收、DPT 长度/帧头/CRC 校验、功耗采样、RSSI、UDP 单播、电脑发现与文本消息确认 |
| 电脑上位机 | 电压/电流/功率曲线、RSSI、帧率及丢帧估算、自定义目录记录、完整帧保存 |
| Apollodeck | 工程位于 `fireware/apollo_spi_master/`；目前发送 14900 B 固定字节，**尚未按 DPT 打包，也尚未接入真实摄像头采集** |
| 图像显示 | 当前三种 format 仅定义不透明字节长度，没有像素布局，**不能显示视频**；接入真实数据后需补充像素定义和解码 |
| 控制功能 | WiFi 文本消息可发送并确认；Apollodeck 采集控制、运行时格式切换和上位机重新烧录尚未实现 |

**现有 Apollodeck 原始字节流不能直接通过 C6 校验。** 默认 C6 要求 14920 B 的 SPI 事务，包含 DPT 头、14900 B 载荷、CRC 和填充。Apollodeck 接口适配与真实采集的任务见第 6 节。

<<<<<<< HEAD
=======
交付时记录三端使用的提交号、固件版本、接线和 format。构建通过不代表真实摄像头链路已验收。
>>>>>>> origin/main

## 2. 工程目录与代码入口

~~~text
Power_Deck/
├─ README.md                  交付范围、部署、任务分工与联调
├─ FRAME_PROTOCOL.md          DPT / PDK1 字节级协议
├─ fireware/
│  ├─ power_deck/             ESP32-C6，ESP-IDF 工程
│  │  ├─ CMakeLists.txt
│  │  ├─ sdkconfig
│  │  └─ main/
│  │     ├─ main.c
│  │     ├─ Inc/
│  │     └─ Src/
│  └─ apollo_spi_master/      Apollodeck 固件（STM32N6）
└─ tool/                     Python 上位机
   ├─ GUI_README.md           使用、记录与统计说明
   ├─ src/
   └─ tests/
~~~

| 修改入口 | 作用 |
|---|---|
| [deck_config.h](fireware/power_deck/main/Inc/deck_config.h) | WiFi、格式选择、SPI 引脚、帧池和功耗队列大小 |
| [depth_spi.h](fireware/power_deck/main/Inc/depth_spi.h)、[depth_spi.c](fireware/power_deck/main/Src/depth_spi.c) | DPT 尺寸、SPI 从机描述符、帧头及 CRC 校验 |
| [stream_tasks.c](fireware/power_deck/main/Src/stream_tasks.c) | 任务、缓冲所有权、网络调度、丢弃原因和运行统计 |
| [power_udp.c](fireware/power_deck/main/Src/power_udp.c)、[depth_udp.c](fireware/power_deck/main/Src/depth_udp.c) | 分别发送功耗 JSON 和图像帧 UDP 分片 |
| [net_rx.c](fireware/power_deck/main/Src/net_rx.c) | 电脑发现、接收端租约、文本消息及确认 |
| [depth_protocol.py](tool/src/depth_protocol.py) | PC 的 DPT 校验、格式表和 PDK1 重组 |
| [deck_gui_backend.py](tool/src/deck_gui_backend.py)、[deck_gui.py](tool/src/deck_gui.py) | 网络、记录、序号统计及界面 |

## 3. 硬件接口与数据流

### 接线

| Apollodeck / SPI5 主机 | Power Deck / C6 从机 | 作用 |
|---|---|---|
| PF15 / SCK | GPIO6 / SCK | Apollodeck 输出时钟 |
| PF11 / MOSI | GPIO7 / MOSI | Apollodeck 向 C6 发送数据 |
| PA3 / CS | GPIO4 / CS | 低有效，一次事务发送完整帧 |
| GND | GND | 共地 |

SPI 使用 Mode 0、8 bit、MSB first；MISO 不使用。Power Deck 为 3.3 V 电平，连接前核对 Apollodeck 对应 VDDIO。CS 空闲高，发完整帧的最后一位后再拉高；没有命令、地址或 dummy 前缀。当前没有 READY 信号，启动、复位或缓存耗尽时可能漏帧。

<<<<<<< HEAD
Apollodeck 当前运行配置约 6.25 MHz、30 ms 发送周期，周期对应约 33.3 次/s；时钟和周期由 Apollodeck 控制。
=======
Apollodeck 当前运行配置约 6.25 MHz、30 ms 发送周期，周期对应约 33.3 次/s；时钟和周期由 Apollodeck 控制。目标 30 fps 应按平均 33.33 ms 调度，不能仅修改 C6 的配置来提高源端帧率。
>>>>>>> origin/main

INA226：C6 GPIO19/SDA、GPIO18/SCL，I2C 100 kHz，地址 0x40；当前按 10 mΩ 分流电阻和 1 mA 电流 LSB 配置。传感器初始化失败时，图像接收链路仍启动。

### 任务与缓存

~~~text
INA226 → power_sample_task → power_q → power_udp ─┐
                                                ├→ net_tx_task → WiFi → PC
Apollodeck → SPI → depth_rx_task → ready_q → depth_udp ───┘
               ↑                         │
               └──────── free_q ←────────┘
PC → UDP 5006 → net_rx_task（发现、租约、文本确认）
~~~

| C6 任务 | 优先级 | 栈分配（B） | 工作 |
|---|---:|---:|---|
| depth_rx_task | 6 | 4096 | 提交/取回 SPI DMA，校验后只传帧索引 |
| power_sample_task | 5 | 3072 | 每 100 ms 采样功耗与 RSSI |
| net_tx_task | 4 | 5120 | 调度功耗与帧分片，发送完成或丢弃后释放帧 |
| net_rx_task | 4 | 3072 | 独立处理 UDP 接收，不阻塞发送任务 |
| stats_task | 2 | 3072 | 每约 1 s 打印运行统计 |

`power_q` 默认容纳 32 个功耗样本；`free_q` 和 `ready_q` 只保存索引，帧池默认 3 个。默认 format=3 时，每帧 DMA RX 容量 14924 B，三帧共 **44772 B**。512 KB DRAM 还要供 WiFi、LwIP、堆、栈等使用，不能全部分给图像。

缓冲所有权固定为：`free → SPI 排队/接收 → 校验 → ready → 网络发送或丢弃 → free`。SPI 驱动持有的缓冲不能读写；网络尚未释放的缓冲不能重新提交给 SPI。等待接收结果出错不代表驱动已经归还描述符。

## 4. 传输配置

DPT 的完整字段、CRC、SPI 对齐和 UDP 外层见 [FRAME_PROTOCOL.md](FRAME_PROTOCOL.md)。概要为：

~~~text
magic(1 B) → format(1 B) → seq(4 B) → camera_ms(4 B) → payload_bytes(4 B)
→ payload → CRC32(4 B) → SPI 尾部零填充
~~~

| format | 载荷（B） | 有效帧 F（B） | SPI 线长 W（B） | UDP 分片/帧 |
|---:|---:|---:|---:|---:|
| 0x01 | 6912 | 6930 | 6932 | 6 |
| 0x02 | 9216 | 9234 | 9236 | 8 |
| 0x03（默认） | 14900 | 14918 | 14920 | 13 |

三种格式都不声明宽高、像素类型或单位。C6 由 `DEPTH_TEST_FORMAT` 选择一种固定长度；PC 可识别表内三种格式，不能仅凭 `payload_bytes` 接收任意长度。源端打包格式必须与 C6 一致；切换时同步修改并烧录两端。当前 Apollodeck 工程尚无对应的 DPT format 配置。

有效帧 `F = 14 + payload_bytes + 4`；SPI 线长 `W = align_up(F, 4)`。当前都补 2 B 零；C6 再预留 4 B 不上线路的保护空间。UDP 和录制的 `.bin` 只保存 F 字节。

format=3、30 fps 时，有效帧数据约 447540 B/s；加入 PDK1 头后约 463140 B/s，尚未包含 UDP/IP/WiFi 开销。6.25 MHz 下每帧纯 SPI 线时约 19.10 ms，剩余时间还要容纳采集、打包、CRC 与调度。增大真实图像尺寸前，重新核算帧长、帧池和带宽。

## 5. 构建、部署与上位机

### C6

<<<<<<< HEAD
**C6 建议单独用一个 VS Code 窗口打开 `fireware/power_deck` 文件夹**（实际目录名为 `power_deck`），按以下步骤操作：

1. 烧录前修改工程内的 `main/Inc/deck_config.h`（[仓库内链接](fireware/power_deck/main/Inc/deck_config.h)），设置热点 SSID、密码及 format。电脑热点使用 2.4 GHz。当前 `sdkconfig` 已配置目标为 `esp32c6`；首次配置或目标不符时，通过 `ESP-IDF: Set Espressif Device Target` 选择 `esp32c6`。


~~~powershell
idf.py --version
idf.py build
idf.py -p COM5 flash monitor
~~~

`COM5` 仅为示例，请替换为设备管理器中 C6 的实际串口；监视器可按 `Ctrl+]` 退出。也可以通过命令面板运行 `ESP-IDF: Build your Project`、`ESP-IDF: Select Port to Use`、`ESP-IDF: Flash your Project` 和 `ESP-IDF: Monitor your Device`。


### PC

需要 Python 3.10+（含 Tkinter）。当前没有第三方运行依赖，直接运行源码时可以省略 uv。另开终端，从仓库根目录运行（macOS 通常将 `python` 换成 `python3`）：

~~~powershell
cd tool
python -m src.deck_gui
# 自动发现不可用时指定 C6 串口显示的 IP
python -m src.deck_gui --board 192.168.137.66
~~~

后续开发若引入第三方依赖，建议用 uv 统一管理虚拟环境和依赖，在 `tool` 目录通过 `uv run deck_gui` 安装依赖并启动；当前已安装 uv 时也可使用此命令。

=======
在已配置 **ESP-IDF 5.5.5** 的终端中，从仓库根目录进入实际工程：

~~~powershell
cd fireware/power_deck
idf.py build
idf.py -p COM实际端口 flash monitor
~~~

首次配置新工程时确认目标为 `esp32c6`。烧录前修改 [deck_config.h](fireware/power_deck/main/Inc/deck_config.h) 中的热点 SSID、密码及 format。电脑热点使用 2.4 GHz。VS Code ESP-IDF 扩展也应以 `fireware/power_deck` 为工程目录。

构建输出在 `fireware/power_deck/build/`，使用 ESP-IDF 完整烧录流程。Apollodeck 使用 STM32CubeIDE 构建和调试，工程位于 `fireware/apollo_spi_master/`；接口适配任务见第 6 节。

### PC

需要 Python 3.10+（含 Tkinter）和 uv，无第三方运行时依赖。另开终端，从仓库根目录运行：

~~~powershell
cd tool
uv run deck-gui
# 自动发现不可用时指定 C6 串口显示的 IP
uv run deck-gui --board 192.168.137.66
~~~

>>>>>>> origin/main
PC 默认监听 UDP 5005，向 C6 UDP 5006 发送 `PDHELLO1`；C6 按来源 IP/端口单播回传，租约 5 s。放行防火墙并避免多个接收程序争用端口。RSSI 表示 C6 收到热点的信号强度。

“开始记录”可选择父目录和新文件夹名，保存 `power.csv`、`depth.csv` 和 `frames/*.bin`。`.bin` 是完整 DPT 头、载荷及 CRC，非纯像素；当前不生成预览或 PGM。详细操作、统计和离线检查见 [上位机说明](tool/GUI_README.md)。

<<<<<<< HEAD
## 6. 接入任务
=======
## 6. Apollodeck 开发人员接入任务
>>>>>>> origin/main

按以下顺序推进，避免同时改变物理接口、协议和采集逻辑：

| 阶段 | Apollodeck 侧工作 | 配套工作与通过条件 |
|---|---|---|
<<<<<<< HEAD
| 1. 适配 DPT | 在 `FSBL/Core/Src/main.c` 的发送入口打包头和 CRC；发送缓冲及长度覆盖 W，CS 包围整帧 | 当前 14900 B 固定数据只能放在 payload 区，线上须发送 14920 B；C6 `depth ok` 增长、错误无新增 |
| 2. 打通回传 | 先降低发送频率，启动 C6 并确认 SPI 接收就绪后再启动 Apollodeck | PC 保存的同一 seq 的 payload 与源端逐字节一致，功耗/RSSI 同时正常 |
| 3. 接入真实采集 | 传感器初始化、采集/算法、真实 payload、采集时间与序号 | 提供一帧源数据、布局说明、场景说明及对应 DPT `.bin` |
| 4. 解释图像 | 约定像素类型、宽高、行序、通道、单位及无效值；需要解释图像时分配新 format | 同步 C6 长度配置、PC `FRAME_PROFILES` 及解码/预览；现有不透明格式不能直接显示视频 |
| 5. 提升吞吐与恢复 | 核对采集/打包/发送耗时，逐步达到目标唯一帧率，处理发送超时/重启 | 比较源端、C6 和 PC 的计数增量；验证错误帧丢弃、GUI 断开重连及恢复 |
=======
| 1. 冻结接口 | 确认板卡/传感器、引脚电平、SPI 时钟、format、采集帧长与时间戳事件 | 双方记录提交号、接线和 F/W；默认先用 format=3 |
| 2. 适配 DPT | 在 `FSBL/Core/Src/main.c` 的发送入口打包头和 CRC；发送缓冲及长度覆盖 W，CS 包围整帧 | 当前 14900 B 固定数据只能放在 payload 区，线上须发送 14920 B；C6 `depth ok` 增长、错误无新增 |
| 3. 打通回传 | 先降低发送频率，启动 C6 并确认 SPI 接收就绪后再启动 Apollodeck | PC 保存的同一 seq 的 payload 与源端逐字节一致，功耗/RSSI 同时正常 |
| 4. 接入真实采集 | 传感器初始化、采集/算法、真实 payload、采集时间与序号 | 提供一帧源数据、布局说明、场景说明及对应 DPT `.bin` |
| 5. 解释图像 | 约定像素类型、宽高、行序、通道、单位及无效值；需要解释图像时分配新 format | 同步 C6 长度配置、PC `FRAME_PROFILES` 及解码/预览；现有不透明格式不能直接显示视频 |
| 6. 提升吞吐与恢复 | 核对采集/打包/发送耗时，逐步达到目标唯一帧率，处理发送超时/重启 | 比较源端、C6 和 PC 的计数增量；验证错误帧丢弃、GUI 断开重连及恢复 |
>>>>>>> origin/main

Apollodeck 当前参数入口为 [spi_link_config.h](fireware/apollo_spi_master/FSBL/Core/Inc/spi_link_config.h)，发送入口为 [main.c](fireware/apollo_spi_master/FSBL/Core/Src/main.c)。目前 `SPI_TEST_FRAME_SIZE=14900`、`SPI_TEST_PERIOD_MS=30`；仅改变长度不能完成 DPT 接入，还必须生成全部字段、CRC 和填充。现有 `image_buffer_checksum` 是本地累加和，不能替代协议 CRC32。

真实采集接入须遵守以下约定：

- **序号和时间戳**：每个新采集帧递增 seq，包括后续发送前被丢弃的帧；重发同一帧保持 seq 和 camera_ms。camera_ms 由 Apollodeck 在约定的采集事件记录，以帧元数据传到发送任务，不能改用发包时刻。
- **缓冲和 DMA/cache**：分离采集、处理与发送的所有权；发送期间不得覆盖载荷。改为 DMA 后，核对 Apollodeck 的 DMA 可访问内存、缓存属性与一致性维护；确认最后一位发送结束后再结束 CS 和释放缓冲。
- **背压与容量**：使用有界队列，记录源端丢帧。当前无 READY，延时不能保证 C6 一直可接收；若需就绪握手，由双方共同定义。UDP 分片不能解决 C6 接收整帧所需的内存。
- **重启与计时**：Apollodeck 独立重启会让 seq 归零，而 C6 session 不变，可能干扰 PC 丢帧估算；当前联调可成组重启，正式支持需补充源端 session 设计。三端时钟未同步，不直接相减计算单向延迟。

交付真实采集版本时，附构建/烧录方法、板卡与传感器型号、数据布局、完整 `.bin` 样本、采集/打包/发送/丢帧统计，以及三端相同 seq 的联调记录。

## 7. 运行诊断与验收

C6 串口的 `stream` 标签每约 1 s 输出累计计数。先确认 WiFi 已获得 IP、PC 已建立租约，再比较连接后约 30 s 的**增量**；启动前 no_wifi/no_receiver 的历史累计不代表连接后仍在丢帧。

| 指标 | 含义 / 排查方向 |
|---|---|
| power ok/err/drop/tx | 有效样本 / 采样错误 / 队列或发送环节丢弃 / 本地发送成功 |
| depth ok/err/no_buf/drop/tx | 校验有效 / 驱动或帧校验错误 / 无已排队事务且无空闲缓冲的耗尽事件 / 有效帧被主动丢弃 / 所有分片本地发送成功 |
| depth_err_detail spi/length/header/crc | SPI 驱动错误 / 实际位数不符 / 类型、格式、长度字段或填充不符 / CRC 不符 |
| ready_full/no_wifi/no_receiver/stale/udp | 完整帧队列满 / 网络未就绪 / 无接收端 / 帧龄超过 500 ms / UDP 发送失败 |
| send_err / last_send_errno | socket 初始化或发送错误累计 / 最近错误码；12 为 ENOMEM，通常是发送资源暂时不足 |
| pool / peak / power_q_peak / ready_peak | 当前占用帧数（含 SPI 预排队）/ 占用峰值 / 功耗队列峰值 / 完整帧队列峰值；pool=3 本身不代表异常 |
| spi_wait_max_us / check_max_us | 等待 SPI 完成的最大耗时（含主机空闲）/ 帧校验最大耗时；均非端到端延迟 |
| heap / min / dma_block / stacks | 当前空闲堆 / 历史最小空闲堆 / DMA 最大连续空闲块 / 功耗、SPI、发送三个任务的历史最小剩余栈；单位 B |
| peer_expired / peer_wifi_lost | 因接收端租约过期 / WiFi 断开而清除接收端的次数 |
| last_drop seq/age_ms/offset | 最近丢弃帧的序号 / 校验后驻留毫秒数 / 下一个待发送分片在 DPT 内的字节偏移 |
| PC invalid / incomplete / evicted | 解析或校验失败 / 分片重组超时 / 重组池满而提前淘汰 |
| PC 序号缺口 / 乱序 | 基于有效帧 seq 估算缺帧 / 超出近期修正范围的回退序号；不是 UDP 分片乱序计数 |

`err` 是坏帧或驱动错误，`drop` 是已有效接收的帧没能全部发出，`no_buf` 是缓存耗尽事件而非精确丢帧数。三者均发生在 C6，但不能互相替代。`tx` 只说明 C6 本地发送成功，PC 是否收到仍要看完整帧、序号和重组统计。

验收记录至少包含：三端版本、format/payload/F/W、实际 SCK/帧率、Apollodeck 采集/发送/丢弃数、C6 错误及丢弃原因增量、PC 完整帧/invalid/incomplete/序号缺口、堆与栈余量，以及一组可对应的源数据和录制文件。真实 30 fps 应核对新采集的唯一序号，不能靠重复发送同一张图验收。

上位机自动化检查在仓库根目录运行：

~~~powershell
python -m unittest discover -s tool/tests -v
~~~

协议和软件检查通过后，仍需实物验证 CS 波形、接收位数、源数据一致性与异常恢复。字节协议以 [FRAME_PROTOCOL.md](FRAME_PROTOCOL.md) 为准，上位机操作以 [tool/GUI_README.md](tool/GUI_README.md) 为准。
