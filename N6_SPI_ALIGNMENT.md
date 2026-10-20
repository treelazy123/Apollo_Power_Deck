# Apollo N6 与 Power Deck SPI 对接清单

更新：2026-10-20。用途：把师兄已验证的 N6→C6 SPI 测试接入本项目的功耗、WiFi 和上位机链路。

本次只读检查了 [师兄仓库 main 分支](https://github.com/Lin-030425/apollo-powerdeck-spi/tree/main) 的 README、协议/构建文档、两端配置、N6 main.c/spi.c 和 C6 spi_slave_receiver.c。未在本地编译该仓库，也未做实物验证。main 分支会更新，开始联合修改前双方应记录各自提交号。

## 1. 两边现在有什么不同

| 项目 | 师兄 SPI 测试工程 | 本项目 |
|---|---|---|
| 主从 | STM32N657 SPI5 主机，C6 SPI2 从机 | 摄像头侧主机，C6 SPI2 从机 |
| SCK/MOSI | PF15→GPIO6，PF11→GPIO7 | C6 GPIO6/7，一致 |
| CS | N6 PA3→C6 GPIO4 | 已统一为 C6 GPIO4；GPIO2/MISO 不连接 |
| Mode/位宽/位序 | Mode 0、8 bit、MSB first | 一致 |
| SPI 内容 | 整帧重复 00 01 10 11 | DPT：14 B 头 + 载荷 + 4 B CRC + 2 B SPI 填充 |
| 当前 SPI 总长 | 14900 B | 默认 format=3，SPI 线长 14920 B |
| N6 发送 | 阻塞 HAL_SPI_Transmit，约 6.25 MHz，30 ms 周期（约 33.3 fps） | 时钟/周期由源端控制，原模拟目标平均 30 fps |
| C6 校验 | 接收位数、固定字节模式 | 接收位数、DPT 帧头/配置、CRC，不解释载荷 |
| C6 后续处理 | 校验后清空并立即重新排队 | 完整帧交给网络任务，发送或丢弃后才能释放 |
| ESP-IDF | 仓库文档标明验证版本 v6.1 | 当前项目构建环境 v5.5.5 |
| READY | 无 | 无 |

依据：[N6 测试入口](https://github.com/Lin-030425/apollo-powerdeck-spi/blob/main/firmware/apollo_spi_master/FSBL/Core/Src/main.c)、[C6 接收入口](https://github.com/Lin-030425/apollo-powerdeck-spi/blob/main/firmware/powerdeck_spi_slave/main/spi_slave_receiver.c)、[两端测试参数](https://github.com/Lin-030425/apollo-powerdeck-spi/blob/main/docs/protocol.md)、[构建环境](https://github.com/Lin-030425/apollo-powerdeck-spi/blob/main/docs/build-and-flash.md)。

师兄当前的固定字节测试没有本项目帧头，不能直接交给当前校验器。当前统一使用 DPT：magic=0x01 占 1 B，format 占 1 B，其他类型/配置待定。

## 2. 先确认这三个接口决定

1. **CS 已按师兄工程统一。** 本项目 `DEPTH_GPIO_CS=4`，N6 PA3 接 C6 GPIO4；SCK/MOSI 仍为 PF15→GPIO6、PF11→GPIO7。GPIO2/MISO 不连接；旧 F103 模拟器 PA6 的 CS 线也需移到 C6 GPIO4。修改后应重新烧录 C6，并按此接线。
2. **首轮使用默认 format=3。** payload=14900 B，有效帧 F=14918 B，SPI 线长 W=14920 B。原 14900 B 固定字节可作为载荷，但须另加 14 B 头、4 B CRC 和 2 B 尾部零填充。
3. **先保留已验证的 N6 阻塞发送和约 6.25 MHz。** 第一轮降到约 5 fps，接通后再改为平均 30 fps。30 ms 周期对应约 33.3 fps；30 fps 可用 33/33/34 ms 节拍。暂不同时改 DMA、时钟和真实摄像头采集。

14900 B 现在就是默认配置 3 的载荷长度；N6 的发送缓冲和 SPI_TEST_FRAME_SIZE 必须覆盖线长 W=14920 B，不能仍只发 14900 B。

## 3. 双方分别改什么

| 负责人 | 代码入口 | 第一轮工作 |
|---|---|---|
| 师兄/N6 | 外部仓库 FSBL/Core/Inc/spi_link_config.h | SPI 发送长度改为 14920，保留已验证 SPI 分频，先降低发送频率 |
| 师兄/N6 | 外部仓库 FSBL/Core/Src/main.c | 把整帧固定模式改为 DPT 打包；补 seq、camera_ms、payload_bytes、format 和 CRC；保留 CS 包围一次完整发送 |
| 你/C6 | 本项目 main/Inc/deck_config.h | CS 已统一为 GPIO4；核对热点和 format=3，保留现有三缓冲和任务 |
| 你/C6 | main/Inc/depth_spi.h、main/Src/depth_spi.c | 首轮沿用当前 DPT 长度/CRC 校验；不要改成固定模式校验 |
| 你/C6 | main/Src/stream_tasks.c | 保留 free→SPI→ready→网络→free 所有权流程，观察错误和 drop 增量 |
| 你/PC | tool/src/depth_protocol.py、GUI | 默认 format=3 已支持；验证完整帧、序号、.bin 保存与功耗/RSSI |
| 双方 | 本清单与联调记录 | 记录版本、接线、配置和同一帧的结果，之后再接真实采集 |

本项目作为 C6 联调主工程，师兄的简单 C6 工程保留作物理链路对照。不要直接合并两个 app_main 或让两套驱动同时初始化 SPI2。师兄工程收到数据后立即重排队的做法适合当前本地校验；加入 WiFi 转发后必须等网络任务释放，避免 SPI 覆盖尚未发完的帧。

N6 的载荷可以继续使用 00 01 10 11 循环，但只填在 payload 区，不能覆盖头和 CRC。每个新帧更新序号、时间和 CRC；当前测试帧的 image_buffer_checksum 只是本地累加和，不能代替线上 CRC32。

真实采集接入后，camera_ms 由 N6 的采集事件记录，使用相对 N6 启动的 uint32 毫秒计数，并随该帧传入打包函数；重发保持该值。固定字节测试尚无真实采集事件时，可以用测试帧生成时间验证字段传输，真实采集时应替换为实际采集时间。

DPT 打包依照 [FRAME_PROTOCOL.md](FRAME_PROTOCOL.md)：

~~~text
0   uint8 magic = 0x01（DPT）
1   uint8 format = 0x03
2   uint32 seq
6   uint32 camera_ms
10  uint32 payload_bytes = 14900
14  payload[14900]
14914 uint32 CRC32
14918 两个零字节（SPI 填充）
有效帧 F=14918 B；SPI 线长 W=14920 B
~~~

magic/format 各 1 B 且相邻，seq/camera_ms/payload_bytes 均为 uint32 小端；CRC 覆盖头和载荷，不含自身或 SPI 填充；CRC-32/ISO-HDLC 与 zlib.crc32 一致。N6 先完成完整帧再拉低 CS，发送 W 字节后结束 CS。C6 RX 容量为 W+4，最后 4 B 保护空间不发送；网络/.bin 只保留 F。

## 4. 联调按这个顺序推进

| 步骤 | 操作 | 通过条件 |
|---|---|---|
| 复现原工程 | 如双方还没共同确认过，先用师兄原 N6+C6 测试工程和原接线 | 约 14900 B 固定测试帧，原测试 errors 增量为 0；已有共同记录可跳过 |
| 冻结接口 | 使用 CS=GPIO4，确认 format=3、SPI 14920 B、Mode 0、6.25 MHz 和帧周期 | 双方配置/接线一致，记录提交号 |
| 接通 DPT | N6 发送已知载荷，换成本项目 C6；先 C6 启动并准备接收，再启动 N6 | C6 depth ok 增长，spi/length/header/crc 错误增量为 0 |
| 接通 WiFi/PC | 约 5 fps 完成发现和单播，录制约 30 秒 | PC invalid/incomplete 增量可解释；.bin 的 payload 与源端已知字节一致 |
| 达到 30 fps | 保持载荷/频率，调整源端节拍 | N6 新序号约 30/s，C6/PC 增量相符；统计连接后的 drop/no_buf，而非只看累计值 |
| 换真实采集 | 确认传感器输出和实际帧长后替换 payload，必要时新增格式 | 同一 seq 的源端数据与 PC .bin 逐字节一致；预览需要另定义像素格式 |
| 异常恢复 | PC 断开、源端/C6 重启、错误 CRC | 不转发坏帧，恢复后继续收帧；独立源端重启的序号统计限制需记录 |

约 6.25 MHz 下发送 14920 B 的纯线时约 19.10 ms，30 fps 周期约 33.33 ms，打包/CRC、CS 间隔和调度仍需占用剩余时间，不能仅由线时保证最终帧率。

首轮没有 READY。启动延时只能缓解启动顺序问题，网络忙碌或 C6 重启仍可能漏帧。若联调显示缓冲来不及提交，再共同定义 READY/背压。源端独立重启导致 seq 归零而 C6 session 不变，也需按现有交接说明记录。

真实采集要与当前固定数据测试分开确认。已检查的 N6 SPI 测试入口尚在发送合成固定字节；是否另有采集/算法工程，需要师兄提供入口和一帧样本。转 DMA 时再核对 N6 cache、DMA 可访问内存及完成时序；本次阻塞发送阶段不直接套用 DMA 缓存处理。

## 5. 需要交付的文档与记录

不用重新写一套总说明。维护以下三份即可：

| 文档 | 用途 |
|---|---|
| 本清单 | 已有代码差异、最终接口选择、双方修改分工、联调顺序 |
| [FRAME_PROTOCOL.md](FRAME_PROTOCOL.md) | 唯一的字节级协议，N6 按此生成 DPT |
| [N6_CAMERA_INTEGRATION.md](N6_CAMERA_INTEGRATION.md) | 真实采集的内存/cache/所有权及后续接入注意事项 |

每轮联调在记录中填：日期、两端提交号/固件、ESP-IDF 版本、接线/CS、format/payload/F/W、SCK/周期、N6 发送数、C6 ok/err/no_buf/drop/tx 增量、PC 完整帧/invalid/incomplete/序号缺口，以及结论和遗留问题。附一帧完整 .bin 和对应源端数据/校验值。

第一阶段交付目标：**N6 DPT 测试帧 → 本项目 C6 → WiFi → PC 完整保存，同时继续接收 INA226 功耗/RSSI。** 真实摄像头采集、图像预览和 N6 采集指令在这一链路接通后逐项推进。
