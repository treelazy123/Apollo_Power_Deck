# DPT 与 PDK1 传输协议

本文定义 Apollodeck → C6 → PC 的字节接口。交付范围、配置入口、接线与接入流程见 [README.md](README.md)。Apollodeck 为 SPI 主机，C6 为 SPI 从机；C6 校验 DPT 后使用 PDK1/UDP 回传。本文是协议约定，当前 Apollodeck 工程的适配状态见 README。

## 1. DPT 布局

~~~text
F = 14 B 帧头 + payload_bytes B 载荷 + 4 B CRC32
W = align_up(F, 4)                 SPI 线上字节数
RX_capacity = W + 4               C6 DMA 接收容量，保护字不发送
~~~

| 字节偏移 | 长度 | 字段 | 定义 |
|---:|---:|---|---|
| 0 | 1 B | magic | SPI 数据类型；数值 0x01 表示 DPT，其余待定、当前拒收 |
| 1 | 1 B | format | 载荷配置编号，见下表；不是 ASCII 数字 |
| 2 | 4 B | seq | uint32 小端，新采集帧递增，同帧重发保持不变 |
| 6 | 4 B | camera_ms | uint32 小端，Apollodeck 记录的该帧采集时间，相对 Apollodeck 启动的毫秒计数 |
| 10 | 4 B | payload_bytes | uint32 小端，仅载荷长度，不含头、CRC 或填充 |
| 14 | payload_bytes | payload | 不透明字节 |
| 14 + payload_bytes | 4 B | CRC32 | uint32 小端，覆盖帧头和载荷 |
| F | W − F | SPI 填充 | 当前三种 format 都为两个零字节，仅 SPI 发送 |

帧头恰为 14 B，Python 表示为 `struct.Struct("<BBIII")`。C 端按字节写小端，不能直接发送普通结构体或将偏移 2/6/10 强转为 uint32 指针。SPI MSB first 是字节内位顺序，不改变小端整数的字节顺序。

### magic 与 format

magic 只占一个字节，`frame[0] = 0x01` 表示整帧属于 DPT；三个 format 都使用这个 magic。format 是紧随其后的一个字节，`frame[1] = 0x03` 表示配置 3，不是 ASCII `'3'`，也不存放 14900。

| format | payload（B） | 有效帧 F（B） | SPI W（B） | C6 RX 容量（B） | 预期接收位数 | UDP 分片数 |
|---:|---:|---:|---:|---:|---:|---:|
| 0x01 | 6912 | 6930 | 6932 | 6936 | 55456 | 6 |
| 0x02 | 9216 | 9234 | 9236 | 9240 | 73888 | 8 |
| 0x03 | 14900 | 14918 | 14920 | 14924 | 119360 | 13 |

其他编号尚未定义，当前拒收。三个格式**只定义长度**，不定义 u16、float、宽高、行序、通道、单位或无效值。PC 当前返回 `width=height=0`、`pixels=None`；仅保存完整帧，不生成视频或 PGM。真实数据可作为等长字节透传；需像素解释时另约定 format 并实现解码。

C6 默认 `DEPTH_TEST_FORMAT=3`，只接收编译时选择的配置；PC 的 `FRAME_PROFILES` 可识别表内三种配置。源端必须匹配，不支持运行时协商。新增格式时同步修改源端、C6 的长度/缓冲配置与 PC 格式表，不能只改 payload_bytes。

### 字节示例

format=1、seq=0x01020304、camera_ms=0x05060708 时，帧头为：

~~~text
01 01 04 03 02 01 08 07 06 05 00 1B 00 00
│  │  └─seq────┘ └─camera_ms┘ └─6912────┘
│  └─format
└─magic
~~~

默认配置 3：payload_bytes 的线上字节为 `34 3A 00 00`；载荷占偏移 14～14913，CRC 占 14914～14917，SPI 填充占 14918～14919。

## 2. CRC32

使用 CRC-32/ISO-HDLC：反射多项式 `0xEDB88320`，初值 `0xFFFFFFFF`，最终异或 `0xFFFFFFFF`，等价于 `zlib.crc32(header + payload)`。测试向量 `123456789` 的结果为 `0xCBF43926`。

CRC 覆盖偏移 0 至 `14 + payload_bytes - 1`，不包含 CRC 自身、SPI 填充、RX 保护空间或 UDP 头。修改任何头字段或载荷后重新计算；CRC 结果按小端追加。使用 Apollodeck 硬件 CRC 时须匹配反射、输入顺序、初值和最终异或；本地累加和不能代替 CRC32。

## 3. SPI 事务与接收校验

SPI Mode 0、8 bit、MSB first。接线为 Apollodeck PF15→C6 GPIO6/SCK、PF11→GPIO7/MOSI、PA3→GPIO4/CS，并共地；MISO 不使用。

一次 CS 低电平发送完整 W 字节，第一个字节为 magic，没有命令/地址/dummy 前缀。最后一位结束后再拉高 CS。CRC 后补零至 4 B 对齐；填充不计入 payload_bytes。C6 RX 容量 W+4 中最后 4 B 是保护空间，**Apollodeck 不发送这 4 B**。

C6 先检查实际 `trans_len == W * 8`，再检查 magic、format、payload_bytes 和零填充，最后检查 CRC。分别计入 `length`、`header`、`crc` 错误；驱动 API 失败计入 `spi`。只有校验通过的帧进入网络队列。

缓冲从 SPI 驱动取回完成结果后才能读取，从网络任务释放后才能重新排队。CS 不代表 C6 已就绪或 PC 已收到；当前无 READY，启动/复位/缓冲耗尽可能漏帧。

## 4. PDK1 UDP 外层

Apollodeck 只发送 DPT，不负责 PDK1。C6 将 F 字节有效帧切为最多 1200 B 的片段，每片添加 40 B PDK1 头；多字节整数均为小端。

| 偏移 | 长度 | 字段 | 定义 |
|---:|---:|---|---|
| 0 | 4 B | magic | ASCII `PDK1` |
| 4 | 1 B | version | 1 |
| 5 | 1 B | kind | 2，图像帧 |
| 6 | 2 B | header_bytes | 40 |
| 8 | 4 B | session | C6 启动时生成的会话标识 |
| 12 | 4 B | seq | 与 DPT 偏移 2 的 seq 相同 |
| 16 | 4 B | total | F，不含 SPI 填充 |
| 20 | 4 B | offset | 片段在完整 DPT 内的字节偏移 |
| 24 | 2 B | length | 本片有效字节数，最大 1200 |
| 26 | 2 B | index | 从 0 开始的分片索引 |
| 28 | 2 B | count | `ceil(F / 1200)` |
| 30 | 2 B | reserved | 0 |
| 32 | 4 B | rx_ms | C6 完成帧校验后的毫秒计时 |
| 36 | 4 B | queue_ms | 本片发送前，该帧从 rx_ms 起的驻留毫秒数 |
| 40 | length | data | 完整 DPT 的一段，包含头/载荷/CRC 的相应部分 |

Python 表示为 `struct.Struct("<4sBBHIIIIHHHHII")`。PC 按来源、session、seq 和 rx_ms 重组并再次校验 DPT，内外 seq 必须一致。默认重组超时 300 ms，最多 16 个待重组帧；C6 活跃帧龄超过 500 ms 会主动丢弃。当前没有图像重传。

PC 默认监听 UDP 5005，以 `PDHELLO1` 向 C6 UDP 5006 注册，C6 单播到其源 IP/端口，租约 5 s。功耗使用独立 JSON 数据报，发现和文本确认不嵌入 DPT；用户操作见 [上位机说明](tool/GUI_README.md)。

## 5. 录制、时间与序号

`frames/*.bin` 保存完整 F 字节（头+载荷+CRC），不含 PDK1、SPI 填充或 RX 保护字。逻辑分析仪导出的 W 字节需先去掉末尾填充再交给 `deck-decode`。`depth.csv` 保存 seq、camera_ms、format、C6 计时与重组耗时，保留的 pgm_file 列始终为空。

camera_ms 由 Apollodeck 在固定的采集事件记录，随该帧传递到打包/发送任务；重发保持不变，C6 原样转发。新采集帧递增 seq，源端发送前丢弃的帧也保留采集序号递增，便于 PC 估算缺帧。

seq 与 camera_ms 均为 uint32：30 fps 下 seq 约 4.54 年回绕，毫秒时间约 49.71 天回绕。三端时钟未同步，不能直接相减计算单向延迟；C6 驻留从校验后计，PC 重组从首片计，都不包含完整采集链路。

PC 按来源 IP/C6 session 估算序号缺口；只能覆盖首个与最新有效序号之间，不能单独定位源端、C6 或 WiFi 丢帧。Apollodeck 独立重启但 C6 session 不变可能被视为异常回退；当前需记录此限制或成组重启，独立恢复需要另设计源端会话标识。
