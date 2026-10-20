# STM32N6 真实摄像头接入交接说明

更新：2026-10-20。目标为 **N6 SPI 主机 → ESP32-C6 SPI 从机 → WiFi/UDP → PC**。当前模拟已用 F103 主机/C6 从机实现同方向，尚需真实摄像头采集与上板验证。

帧协议统一为 [DPT](FRAME_PROTOCOL.md)：14 B 头 + 载荷 + 4 B CRC；magic=0x01 占 1 B，format 占 1 B。SPI 在 CRC 后补 2 B 零字节，UDP/.bin 不含填充。源端、C6 和 PC 必须匹配配置。

## 帧格式说明

本项目统一使用 DPT，magic=0x01 表示数据类型，format=0x01/0x02/0x03 分别选择 6912/9216/14900 B 不透明载荷，其他值待定。

已检查师兄的 [Apollo SPI 测试工程](https://github.com/Lin-030425/apollo-powerdeck-spi)：N6 主机和简单 C6 从机已具备固定测试字节收发。下一步按 [N6_SPI_ALIGNMENT.md](N6_SPI_ALIGNMENT.md) 统一 CS、DPT 帧长/打包，再接入本项目 WiFi/功耗链路。真实采集是否另有独立工程，需提供对应入口。

## 1. 当前已有的能力

~~~text
真实摄像头 → N6 采集/处理 → DPT 打包 → SPI 主机发送
                                               ↓
C6：SPI 从机 DMA → 长度/CRC 校验 → 完整帧索引队列 → depth_udp
                                                   ↓
INA226 → 功耗样本队列 → power_udp ← net_tx_task → WiFi → PC
PC 发现/文本消息 → net_rx_task（独立 UDP 接收任务）
~~~

- C6 `depth_spi_queue()` / `depth_spi_receive()` 已实现从机描述符提交/取回；最多 3 个缓冲预排队。
- F103 模拟器使用 PA5 SCK、PA7 MOSI、PA6 CS，9 MHz、平均目标 30 fps；可参考它的 DPT 打包和主机事务语义。
- C6 保留 INA226、RSSI、网络发送、电脑发现和文本确认。
- PC 校验三个 DPT 不透明字节格式，显示功耗/帧统计并保存完整帧；当前不解释图像或生成预览。
- **尚待接入/实现**：N6 真实采集与既有 SPI 主机的 DPT 适配、READY、运行时新格式协商、摄像头控制指令、图像重传、源端独立重启 session。

## 2. 分工和编码前要确认的内容

| 开发方 | 工作 |
|---|---|
| N6 | 摄像头初始化、采集/深度算法、像素转换、DPT 与 CRC、SPI 主机 DMA/CS、内存/cache、统计 |
| C6 | 复用从机框架，匹配固定格式/载荷长度；需要时增加新格式、READY、独立重启处理 |
| PC | 匹配格式配置，新格式的解码/预览/保存和唯一帧率统计 |
| 共同 | 电平、接线、完整帧尺寸、单位/状态、CS/就绪时序、启动/复位/背压约定 |


## 3. 接线、CS 与 READY

### 当前三信号线方案（模拟已实现）

| N6 端 | Power Deck | C6 配置 |
|---|---|---|
| PF15 / SPI5_SCK 输出 | SCK | GPIO6 输入 |
| PF11 / SPI5_MOSI 输出 | MOSI | GPIO7 输入 |
| PA3 / SPI5_CS 输出，空闲高 | CS | GPIO4 输入 |
| GND | GND | 共地 |

MOSI 按“主机输出”定义，摄像头数据现在走 MOSI。C6 已按师兄工程配置为 SCK=6、MOSI=7、CS=4，`miso_io_num=-1`；GPIO2/MISO 不连接。若使用之前 F103 的接线，需将 CS 线从 C6 GPIO2 移至 GPIO4。

Power Deck 侧为 3.3 V，逐项核对 N6 VDDIO、电平兼容和供电，不默认任意 N6 引脚可直连。不得使用旧 C6 主机镜像，以免双方驱动 SCK/MOSI。

CS 低时发一整帧，最后一位结束后拉高；不要逐字节产生 CS 脉冲，不加命令/地址/dummy。初始 Mode 0、8 bit、MSB first、低频低帧率验证后再升频。标准 C6 从机以 CS/时钟划分事务，不能直接反用旧 MOSI 高电平请求逻辑。


## 4. N6 需要怎样打包

统一字段表、字节序、格式和 CRC 见 [FRAME_PROTOCOL.md](FRAME_PROTOCOL.md)，不要根据旧模拟文档重建另一套协议。五个头字段为：

~~~text
offset 0:  uint8 magic = 0x01（DPT）
offset 1:  uint8 format
offset 2:  uint32 seq
offset 6:  uint32 camera_ms
offset 10: uint32 payload_bytes
offset 14: payload
随后: uint32 CRC32
CRC 后: 零填充至 SPI 4 B 对齐（当前为 2 B）
~~~

CRC 覆盖头和载荷，不覆盖自身。逐字节写小端；SPI MSB first 与多字节小端并不矛盾。magic/format 为单字节；seq/camera_ms/payload_bytes 为 32 bit 小端。非对齐偏移须按字节读写，不能直接强转结构体。

当前格式：

| format | 完整配置 | payload（B） | F（B） |
|---:|---|---:|---:|
| 1 | 6912 B 不透明字节，无像素定义 | 6912 | 6930 |
| 2 | 9216 B 不透明字节，无像素定义 | 9216 | 9234 |
| 3 | 14900 B 不透明测试字节，无像素宽高 | 14900 | 14918 |

三个配置只定义长度，均为不透明字节，不定义像素、单位或状态。N6 可放入等长真实数据，C6/PC 校验类型、配置、长度和 CRC；不做图像解释。

尺寸、布局或单位变化时**分配新 format 编号**，同步更新 N6/C6/PC 的配置。不能仅改 payload_bytes。当前 1/2/3 都是字节吞吐配置，不是自动预览模式；如需深度/RGB 等像素解释，新增格式号并实现解码/预览。

## 5. 代码修改入口

| 文件 | 作用与 N6 接入修改 |
|---|---|
| [depth_spi.h](main/Inc/depth_spi.h) | C6 14 B 头、固定 payload、F/RX 容量；新格式新增配置分支 |
| [depth_spi.c](main/Src/depth_spi.c) | C6 从机队列、DPT magic/payload/format/CRC 检查；sequence helper 已读偏移 2 |
| [stream_tasks.c](main/Src/stream_tasks.c) | 排队、取回、长度检查、完整帧索引；网络释放后才可复用 |
| [deck_config.h](main/Inc/deck_config.h) | WiFi、DEPTH_TEST_FORMAT、缓冲数量、SCK/MOSI/CS 引脚 |
| [depth_udp.c](main/Src/depth_udp.c) | PDK1 分片可复用；N6 不实现 PDK1/UDP |
| [net_rx.c](main/Src/net_rx.c) | 发现/文本确认，不会自动执行 N6 采集命令 |
| [depth_protocol.py](tool/src/depth_protocol.py) | 新格式在 FRAME_PROFILES 注册；新像素布局另加解码，帧长由配置推导 |
| [deck_gui.py](tool/src/deck_gui.py)、[deck_gui_backend.py](tool/src/deck_gui_backend.py) | 新格式预览/保存、独立重启和唯一采集 fps |
| [main/CMakeLists.txt](main/CMakeLists.txt) | 新增 C6 文件时注册源文件与组件依赖 |

N6 应建自己的 camera_capture、帧打包、spi_frame_tx 等模块，这些只是建议名称。F103 的 SPI1/RCC 复位、DMA1_Channel3、IRQ 和 HAL 完成判断不能逐行搬到 N6。

## 6. DMA、缓存和缓冲所有权

N6 推荐固定池，分离采集、打包和发送占用：

~~~text
FREE → CAPTURING → CAPTURED → PACKING → READY_TO_SEND → SPI_SENDING → FREE
~~~

采集 DMA 不得覆盖打包/发送中的内存。缓冲数取决于原始图、处理结果和 DPT 是否共用内存，不能默认两个就足够。等待 C6 背压时也不能阻塞正在运行的摄像头采集 DMA；用有界队列保留最新完整帧，独立统计发送前丢弃。

cacheable DMA 缓冲需按实际内存属性维护一致性：CPU 写、DMA 读前做适用的 clean；DMA 写、CPU 读需按配置处理失效/屏障。核对 DMA 可访问区域、cache line 对齐和描述符属性，不能仅因 CPU 可读写就认为 DMA 可用。参考 [ST DMA/cache 一致性说明](https://community.st.com/stm32-mpus-61/how-to-maintain-dcache-coherency-for-dma-on-stm32-devices-167548)，具体 API/地址查所用 [N6 官方文档](https://www.st.com/en/microcontrollers-microprocessors/stm32n6-series/documentation.html)。

N6 发送：取完整源帧 → 打包/CRC/cache → 获得接收授权或按约定限速 → CS 低 → DMA 发 W（有效帧 + 尾部填充） → 确认最后一位结束 → CS 高 → 释放发送缓冲。DMA 完成不一定等于 SPI 线上完成，应按具体 N6 HAL/参考手册核对。

C6 所有权：

~~~text
free_q → SPI 描述符排队/接收 → 完成取回/长度和 CRC → ready_q
       → net_tx_task → 最后一片完成或丢弃 → free_q
~~~

实际位数来自 trans_len，要求 W*8。F=14+payload+4，W=align_up(F,4)，当前 CRC 后补 2 B 零字节；RX 容量 W+4 的最后 4 B 保护空间不发送。UDP/.bin 只包含 F 字节；CRC 不覆盖尾部填充。

## 7. 序号、启动与恢复

- seq 按新采集帧递增，重发保持不变。30 次发送同一张图不等于 30 张新采集图。
- N6 在发送前丢弃的帧也保留源序号连续递增，使 PC 缺口能覆盖源端到 PC 的损失；另用 N6 统计定位环节。
- 仅 N6 重启会使 seq 归零，但 C6 session 当前不变，可能持续出现“乱序”。第一版可成组重启；正式支持独立重启要另设计源 boot/session，不能恢复已删除的旧 flags 字段代替它。
- seq/camera_ms 均为 uint32；30 fps 下 seq 约 4.54 年回绕，毫秒 camera_ms 约 49.71 天回绕。按模运算处理回绕，不因此停止录制。
- camera_ms 由 N6 在采集该帧时记录，使用 N6 启动后的 uint32 毫秒计数。采集驱动固定时间戳对应的帧事件，并通过帧元数据传到打包/发送任务；重发保持不变。C6 原样转发，PC 保存到 depth.csv。N6/C6/PC 时钟未同步，不能直接相减当单向延迟。
- N6 超时后停止 DMA/时钟、结束 CS、回收资源，再从新完整事务重试；不从中间字节续传。
- C6 只有取回完成结果后才能复用驱动持有的缓冲；等待结果超时不代表驱动已经自动归还。
- C6/PC 的发送成功/完整帧计数含义不同；没有现成图像可靠重传。无 READY 时启动/复位期间漏帧是需要明确记录的限制。

## 8. 带宽和内存

以下假设 N6 SPI 10 MHz，当前 F103 为 9 MHz：

| format | F（B） | W（B） | 10 MHz 纯线时（含填充） | 有效帧 @30 fps（B/s） | UDP 片/帧 |
|---:|---:|---:|---:|---:|---:|
| 1 | 6930 | 6932 | 5.5456 ms | 207900 | 6 |
| 2 | 9234 | 9236 | 7.3888 ms | 277020 | 8 |
| 3 | 14918 | 14920 | 11.936 ms | 447540 | 13 |

~~~text
F = 14 + payload_bytes + 4
W = align_up(F, 4)
SPI 线时 = 8 * W / SPI_Hz
UDP 分片数 = ceil(F / 1200)
UDP 应用层字节率 = (F + 40 * 分片数) * fps
~~~

还需预留采集/算法/打包/CRC、CS/READY 间隔和调度时间。10 MHz 单线理论 1,250,000 B/s，30 fps 每帧约 41,666 B 已用尽纯线时，实际要留余量。

例如新增 320×240 单通道 u16 配置，载荷 153600 B、有效帧 F=153618 B、SPI W=153620 B，10 MHz 线时约 123 ms，不能跑 30 fps。此例需要新增长度配置；现有格式 1 已无状态字节或像素定义。

C6 512 KB DRAM 不是全部可用于图像。当前 3 个 raw RX 缓冲合计 **44772 B**（3×14924），另有 WiFi/LwIP、描述符、栈与队列。上述大帧若三缓冲，仅有效帧就 460854 B，尚未含 SPI 填充/保护空间，很容易挤占运行内存。

检查 heap/min/dma_block 和每次分配结果。超过预算时先在 N6 降采样/缩小数据，或另设计 SPI 分块/有界缓存；现有 UDP 分片仍以前置完整帧为基础，不能自动解决 C6 大帧内存问题。默认 C6 活跃帧过期 500 ms，PC 重组超时 300 ms；不要仅增大队列来掩盖吞吐不足。

## 9. 联调流程

| 阶段 | 操作 | 通过条件 |
|---|---|---|
| 接口冻结 | 确认型号、图像配置、CS/READY、电平和重启语义 | 三端格式号、payload/F 一致 |
| 已知帧 | 先用 F103 主机验证 C6；再 N6 发已知 DPT，低频约 1 fps | CS/SCK/MOSI 波形与长度、CRC 正确 |
| 单帧采集 | N6 导出一张真实帧，核对单位/状态/行序 | 已知场景和像素可解释 |
| 低帧率真实链路 | 约 5 fps，N6 → C6 → GUI | .bin 与源端数据一致，记录正常；当前无预览 |
| 吞吐提升 | 保持格式，逐步升 SPI 时钟和 fps | 唯一 seq 帧率达到目标，错误和丢帧可定位 |
| 异常恢复 | 截断/CRC 错、源端/C6 分别重启、GUI 断开 | 后续事务能恢复，无缓冲泄漏/卡死 |

建立连接后先记录约 30 秒增量，无需先跑 10～30 分钟。保存同一 seq 的 N6 统计、C6 日志、PC 录制和波形。

| 指标 | 定位 |
|---|---|
| N6 capture/pack/tx/drop | 采集速度、打包成本、发送前丢弃 |
| C6 spi/length/header/crc | 驱动、实际位数、协议配置、完整性；不做像素校验 |
| no_buf / ready_full / pool / ready_peak | 缓冲/队列；pool 含预排队缓冲，3 可能正常 |
| no_wifi / no_receiver / stale / udp | 网络未就绪、租约、过期、发送失败 |
| PC invalid / incomplete / 序号缺口 | 无效数据、分片未齐、完整帧缺失；不能混为同一计数 |
| RSSI | C6 收到热点的信号，不是上行可靠性证明 |

spi_wait_max_us 含等主机停发时间，不是线时；check_max_us 为校验时间。GUI fps 可能包含重复 seq。WiFi 文本消息只是 C6 收到确认，没有真实采集指令语义。

## 10. N6 交付清单

- [ ] N6 工程/板卡/传感器型号、HAL/编译版本、构建烧录方法。
- [ ] N6 主机、C6 从机的引脚/电平图，明确当前 CS=GPIO4、MISO 不使用，是否增加 READY。
- [ ] DPT 单字节 magic/format、源数据布局说明、payload/F/W、SPI mode/时钟、目标唯一 fps。
- [ ] 一个完整 DPT .bin、seq/camera_ms/CRC、像素解释和场景图。
- [ ] DMA/cache/缓冲所有权、CS 完成、背压、超时/复位方案。
- [ ] 独立重启时序号/session 约定，采集/打包/发送/丢帧统计及短时联调记录。
- [ ] C6/PC 配套改动与未完成事项。

源端、C6 和工具升级 DPT 后不要混入旧固件或旧帧。真实采集的最终型号和格式仍需双方补齐；详见 [统一协议](FRAME_PROTOCOL.md)、[F103 联调说明](camera_spi_mock/PROTOCOL.md)、[GUI 使用说明](tool/GUI_README.md)。
