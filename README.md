# Power Deck

采集 INA226 功耗与摄像头帧，经 ESP32-C6 WiFi/UDP 发往电脑。当前链路为 **STM32F103 SPI 主机 → ESP32-C6 SPI 从机 → PC**；F103 仍产生合成载荷，真实 STM32N6 采集尚未接入。

图像协议已统一为 **DPT：14 B 帧头 + 载荷 + 4 B CRC32**，SPI 在 CRC 后另补 2 B 零字节。F103、C6 和上位机必须一起更新。字段/格式配置的统一定义见 [FRAME_PROTOCOL.md](FRAME_PROTOCOL.md)，N6 开发交接见 [N6_CAMERA_INTEGRATION.md](N6_CAMERA_INTEGRATION.md)。

## 系统结构

~~~text
INA226 ─I2C→ power_sample_task → 功耗队列 → power_udp ─┐
                                                     ├→ WiFi/UDP → deck_gui
F103 主机 ─SPI→ depth_rx_task → 完整帧队列 → depth_udp ─┘
                    ↑                        │
                    └──── 空闲帧索引队列 ────┘
PC ─UDP 5006→ net_rx_task：发现、连接租约、文本消息/确认
~~~

- `power_sample_task` 每 100 ms 采样，功耗 JSON 包含电压、电流、功率及 `rssi_dbm` / `rssi_valid`。
- `depth_rx_task` 提前提交从机 DMA 缓冲，取回事务后检查实际位数、DPT 和 CRC。
- `net_tx_task` 在功耗样本和深度分片间调度；通过线程安全快照取得 PC 地址。
- `depth_udp` 发送 PDK1 分片；`net_rx_task` 独立监听 UDP 5006。
- PC 监听 UDP 5005，定期发送 `PDHELLO1`；C6 按其源 IP/端口单播，租约 5 秒。

## 仓库内容

| 路径 | 内容 |
|---|---|
| main/ | C6 SPI 从机、WiFi、INA226、FreeRTOS 任务、UDP 模块 |
| camera_spi_mock/ | F103 SPI 主机模拟器、CubeMX/CMake、抓帧工具 |
| tool/ | GUI、协议解析、UDP 收发与录制 |
| [FRAME_PROTOCOL.md](FRAME_PROTOCOL.md) | DPT 固定头、格式配置、CRC、兼容规则 |
| [camera_spi_mock/PROTOCOL.md](camera_spi_mock/PROTOCOL.md) | F103 接线、时序、DMA、统计与构建 |
| [tool/GUI_README.md](tool/GUI_README.md) | GUI 安装/运行、消息、保存、测试 |
| [N6_CAMERA_INTEGRATION.md](N6_CAMERA_INTEGRATION.md) | 真实 N6 主机采集接入流程与注意事项 |
| [N6_SPI_ALIGNMENT.md](N6_SPI_ALIGNMENT.md) | 师兄 Apollo SPI 工程与本项目的差异、修改分工和联调清单 |
| [BENCHMARK_MODES.md](BENCHMARK_MODES.md) | 当前载荷规模与历史镜像说明 |
| bench_artifacts/ | **旧帧格式 / C6 主机 / F103 从机镜像，不能与当前工程混用** |

## 硬件与接线

| Power Deck / C6 | Apollo N6 | F103C8T6 模拟器 | 当前用途 |
|---|---|---|---|
| SCK / GPIO6 | PF15 / SPI5_SCK | PA5 / SPI1_SCK | STM32 输出时钟，C6 输入 |
| MOSI / GPIO7 | PF11 / SPI5_MOSI | PA7 / SPI1_MOSI | STM32 发送数据，C6 接收 |
| CS / GPIO4 | PA3 / SPI5_CS | PA6 / CAM_CS | 低有效片选 |
| GND | GND | GND | 共地 |

C6 引脚已与师兄 Apollo 工程统一为 SCK=6、MOSI=7、CS=4。原 GPIO2/MISO 不再连接；旧 F103 接线需将 PA6 的 CS 线从 C6 GPIO2 移到 GPIO4。F103 为 Half-Duplex Master、单线 TX DMA；C6 为 RX-only 从机，SPI Mode 0、8 bit、MSB first、3.3 V 电平。

当前 APB2 72 MHz / 8 产生 SPI **9 MHz**，F103 用 33/33/34 ms 节拍实现平均目标 **30 fps**。一个 CS 事务传一帧，结束最后一位后拉高 CS；没有旧 MOSI 请求和 dummy 数据。C6 预排队最多 3 个缓冲，但**没有 READY**，重启或缓冲耗尽仍可能漏收，实际帧率需上板验证。

两端先更新再联机；禁止旧 C6 主机固件与新 F103 主机固件同时驱动 SCK/MOSI。

INA226：C6 GPIO19 SDA、GPIO18 SCL，I2C 100 kHz，地址 0x40；当前按 10 mΩ 分流电阻、1 mA 电流 LSB 配置。找不到 INA226 时功耗采样关闭，深度链路仍启动。RSSI 表示 C6 收到热点的信号，不是 PC 测得的上行信号强度。

## 当前格式和配置

默认格式 3。三个格式都是不透明字节，仅载荷长度不同，不定义宽高/单位。帧头按顺序为 1 B magic、1 B format、4 B seq、4 B camera_ms、4 B payload_bytes：

| format | 不透明载荷（B） | 有效帧 F（B） | SPI 线长 W（B） | UDP 分片 | 预览 |
|---:|---:|---:|---:|---:|---|
| 0x01 | 6912 | 6930 | 6932 | 6 | 仅 .bin |
| 0x02 | 9216 | 9234 | 9236 | 8 | 仅 .bin |
| 0x03 | 14900 | 14918 | 14920 | 13 | 仅 .bin |

| 项目 | 配置位置 |
|---|---|
| F103 格式、帧率、启动等待 | camera_spi_mock/Core/Inc/camera_mock.h：CAM_TEST_FORMAT、CAM_TARGET_FPS |
| F103 SPI 分频 | CubeMX 或 Core/Src/main.c 的 MX_SPI1_Init() |
| C6 WiFi、格式、缓冲、引脚 | main/Inc/deck_config.h：SSID/密码、DEPTH_TEST_FORMAT、DEPTH_FRAME_COUNT |
| C6 载荷尺寸/头长 | main/Inc/depth_spi.h |
| PC 格式配置 | tool/src/depth_protocol.py：FRAME_PROFILES |

切换 1/2/3 时修改两端相同格式号，重新构建/烧录；PC 识别表内格式。新增分辨率、单位或布局要分配新格式号并修改三端配置，不能仅改变 payload_bytes。N6 真实数据可按等长字节打包，但三个格式均不做图像解释；需要预览时新增明确像素格式。magic=0x01 表示 DPT，format 为单字节编号；其他类型/配置待定。

有效帧 F=14+payload+4；SPI 线长 W=align_up(F,4)，当前在 CRC 后补 2 B 零字节。C6 RX 容量 W+4 的最后 4 B 是不发送的保护空间。UDP/.bin 只包含 F 字节。C6 不再分配整帧零数据 TX 缓冲。PDK1 外层仍是 40 B 头 + 最多 1200 B DPT 切片。

## 构建与烧录

### ESP32-C6

使用已配置 ESP-IDF 5.5.5 的 VS Code 扩展：

1. 打开根目录，目标选择 ESP32-C6。
2. 编辑 `main/Inc/deck_config.h` 中热点 SSID/密码，电脑热点使用 2.4 GHz。
3. 需要调整 SDK 参数时使用 SDK Configuration Editor。
4. Build Project → Flash Device → Monitor Device，选择实际串口。

输出 `build/Power_Deck.bin`；使用正常完整烧录流程，app 偏移为 0x10000。当前代码是 SPI 从机；旧 bench_artifacts 的主机固件不能使用。

### STM32F103C8T6

需要 CMake 3.22+、Ninja、GNU Arm 工具链。提供 Debug/Release presets：

~~~powershell
cd camera_spi_mock
cmake --preset Debug
cmake --build --preset Debug
~~~

生成 `build/Debug/camera_spi_mock.elf` 和同名 .bin；Release 同理。可用 STM32CubeIDE/ST-Link，Flash 起始 0x08000000。CubeMX .ioc 已同步为主机、PA6 CS、仅 TX DMA。

调试器观察 `g_camera_stats` 的 generated/started/completed、错误、超时、打包/发送耗时和 spi_hz，详细含义见 [模拟器说明](camera_spi_mock/PROTOCOL.md)。

## 电脑上位机

Python 3.10+、包含 Tkinter 的 Python，以及 uv；运行时仅依赖标准库。在 tool 目录：

~~~powershell
uv run deck-gui
# 指定当前 C6 IP 时
uv run deck-gui --board 192.168.137.66
~~~

C6 IP 留空自动发现；广播受限时填写 IP。Windows 防火墙允许 UDP 5005。GUI 显示最近 60 秒功耗曲线、RSSI 和帧统计；三个格式均不提供图像预览。按“开始记录”选择父目录/文件夹名，保存 power.csv、depth.csv、完整 DPT .bin，三种格式均只保存 .bin，不生成 .pgm。

GUI WiFi 消息支持最多 512 B UTF-8 文本：PDMSG1 发往 UDP 5006，C6 打印后回 PDACK1；2 秒未确认提示超时。当前只传文本，不执行开始采集/格式切换等设备指令；“帧类型/重新烧录”仍为预留界面。接收任务栈 3072 B、优先级 4，由 stream_tasks_start 创建。

PC 工具已更新为 0.5.0，仅接收 DPT。已录制的旧帧格式 需要旧工具查看，本次不做自动转换。

## 统计与验证

- C6：`depth_err_detail spi/length/header/crc`，以及 drop_reason、send_err、last_rx_bits、heap/min/dma_block。
- `spi_wait_max_us` 包含等待主机空闲/停发，`check_max_us` 是帧校验耗时；都不能直接当端到端延迟。
- `pool` 包含预排队的 SPI 缓冲，3 可能正常；`no_buf` 是无已排队事务且无空闲帧时的耗尽事件，不是漏帧总数。
- drop_reason 区分 ready_full/no_wifi/no_receiver/stale/udp。启动前 no_wifi/no_receiver 的累计增长需与连接后的增量区分。
- GUI `invalid` 为无效数据，`incomplete` 为分片重组超时。“序号缺口/估算丢帧”基于有效 DPT seq，不能单独区分源端/C6/WiFi 丢帧。
- GUI fps 可能包含重复采集帧，真实采集率还要检查唯一 seq。独立重启源端会使序号归零，初次联调建议成组重启。

在根目录：

~~~powershell
python -m unittest discover -s tool/tests -v
python -m unittest discover -s camera_spi_mock/tools -v
~~~

覆盖 DPT、旧协议拒收、UDP 重组、实际 PC 接收/录制、RSSI、任意载荷字节和 CLI 拒绝 PGM。构建/软件测试不能证明硬件帧率；真实 N6 接入时还需确认摄像头布局、单位、DMA/cache、CS 和启动恢复，参见交接文档。
