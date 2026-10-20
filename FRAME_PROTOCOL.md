# DPT 摄像头帧协议

本项目统一使用 DPT 数据帧，不再按版本编号命名。摄像头侧为 SPI 主机，ESP32-C6 为从机；C6 校验后使用 PDK1/UDP 分片回传电脑。

## 1. 14 B 帧头

~~~text
有效帧 F = 14 B 帧头 + payload_bytes B 载荷 + 4 B CRC32
SPI 线长 W = align_up(F, 4)
当前三个格式均在 CRC 后补 2 B 零字节，W = F + 2
~~~

字段顺序固定为 magic、format、seq、camera_ms、payload_bytes。magic/format 各 1 B；seq、camera_ms、payload_bytes 均为 uint32 小端。SPI MSB first 表示字节内位顺序，不改变小端整数的字节顺序。

| 偏移 | 长度 | 字段 | 当前定义 |
|---:|---:|---|---|
| 0 | 1 B | magic | SPI 数据类型，0x01 表示 DPT，其他待定 |
| 1 | 1 B | format | 0x01 / 0x02 / 0x03 对应下表 |
| 2 | 4 B | seq | uint32 帧序号；新帧递增，重试保持不变 |
| 6 | 4 B | camera_ms | N6 记录的该帧采集时间戳，uint32，单位 ms，相对 N6 启动计时 |
| 10 | 4 B | payload_bytes | 仅载荷长度，不含头、CRC 或 SPI 填充 |
| 14 | payload_bytes | payload | 不透明字节 |
| 14 + payload_bytes | 4 B | CRC32 | 小端，覆盖帧头与载荷 |
| F | W - F | SPI 填充 | 当前为 00 00，仅用于 SPI 对齐 |

Python 帧头为 `struct.Struct("<BBIII")`，恰好 14 B。C 端逐字段按字节读写，不能直接发送普通结构体或把偏移 2/6/10 强转成 uint32 指针，以免产生填充或非对齐访问。

### 1.1 magic：SPI 数据类型

magic 只占偏移 0 的一个字节。`0x01` 表示本项目 DPT 数据，其他数值待定，当前接收端拒收。三个 format 都用同一个 magic。

~~~c
frame[0] = 0x01;  /* 一个数值字节 */
~~~


### 1.2 format：载荷配置

format 只占偏移 1 的一个字节，当前三个值均表示不透明载荷，只区分固定长度：

| format | 线上字节 | payload（B） | 有效帧 F（B） | SPI 线长 W（B） | PC 行为 |
|---:|---|---:|---:|---:|---|
| 0x01 | 01 | 6912 | 6930 | 6932 | 仅 .bin，无预览 |
| 0x02 | 02 | 9216 | 9234 | 9236 | 仅 .bin，无预览 |
| 0x03 | 03 | 14900 | 14918 | 14920 | 仅 .bin，无预览 |
| 其他 | 待定 | 未定义 | 未定义 | 未定义 | 当前拒收 |

例如配置 3，写 `frame[1] = 0x03`，并在偏移 10 写入小端 uint32 数值 14900（`34 3A 00 00`）。不能把 format 写成 ASCII“3”，也不能用载荷长度替代编号。

这些编号不声明 u16、float32、分辨率、通道、单位或状态码。任意载荷字节均允许，CRC 仍检查完整性。PC 返回 width/height=0、pixels=None，不生成视频或 PGM。真实数据可作为等长字节替换载荷；需要像素解码时另约定新的配置编号。

## 2. 配置与示例

源端 `CAM_TEST_FORMAT` 与 C6 `DEPTH_TEST_FORMAT` 必须一致，默认 3。C6 只接收编译时选定的一种配置，PC 的 FRAME_PROFILES 可识别上述三种配置；不支持运行时自动协商或仅凭 payload_bytes 接收任意长度。

| 端 | 修改入口 |
|---|---|
| F103 | [camera_mock.h](camera_spi_mock/Core/Inc/camera_mock.h)、[camera_mock.c](camera_spi_mock/Core/Src/camera_mock.c) |
| C6 | [deck_config.h](main/Inc/deck_config.h)、[depth_spi.h](main/Inc/depth_spi.h)、[depth_spi.c](main/Src/depth_spi.c) |
| PC | [depth_protocol.py](tool/src/depth_protocol.py) 的 FRAME_PROFILES |

format=1、seq=0x01020304、camera_ms=0x05060708 时，14 B 头为：

~~~text
01  01  04 03 02 01  08 07 06 05  00 1B 00 00
magic format seq         camera_ms    payload_bytes
~~~

默认配置 3 的 SPI 事务为：

~~~text
偏移 0：       01                     magic = DPT
偏移 1：       03                     format = 3
偏移 2～5：    seq（uint32 小端）
偏移 6～9：    camera_ms（uint32 小端）
偏移 10～13：  34 3A 00 00            payload_bytes = 14900
偏移 14～14913：14900 B 载荷
偏移 14914～14917：CRC32（小端）
偏移 14918～14919：00 00               SPI 填充
~~~


## 3. CRC32

CRC-32/ISO-HDLC：反射多项式 0xEDB88320、初值 0xFFFFFFFF、最终异或 0xFFFFFFFF，等同 `zlib.crc32(header + payload)`；测试向量 `123456789` 对应 0xCBF43926。

CRC 覆盖偏移 0 至 `14 + payload_bytes - 1`，不包含 CRC 自身、SPI 填充、RX 保护空间或 UDP 头。修改头或载荷后必须重算 CRC。N6 硬件 CRC 的反射、字节序和初值等需与上述定义一致；测试数据的简单累加和不能代替 CRC32。

## 4. SPI 长度、对齐与缓冲

- 一个 CS 低电平事务承载 W 字节，第一字节是 magic，无命令/地址/dummy 前缀。最后一位发完后拉高 CS。
- SPI Mode 0、8 bit、MSB first；主机控制 SCK。C6 接线为 GPIO6/SCK、GPIO7/MOSI、GPIO4/CS，MISO 不使用，共地。
- CRC 后追加零字节把 SPI 线长补到 4 B 倍数，当前三个格式都补 2 B。这不是帧头字段，也不增加 payload_bytes。
- C6 分配 W+4 字节的 DMA RX 容量，其中最后 4 B 是不发送的保护空间；要求 trans_len=W×8。长度不符先记 length 错误，不访问未收齐的数据。
- 长度正确后，magic、format、payload_bytes 或 SPI 填充不符记 header 错误；CRC 不符记 crc 错误。仅有效帧进入网络队列。
- 只有从驱动取回完成描述符后才能读取接收缓冲；网络发送或丢弃并释放后才能重新排队。
- CS 不表示已就绪或 PC 已收到；当前没有 READY，启动、重启和缓冲耗尽时仍可能漏帧。

采用尾部填充以满足 [ESP-IDF 5.5.5 C6 SPI 从机的 DMA 对齐要求](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32c6/api-reference/peripherals/spi_slave.html#restrictions-and-known-issues)。

| format | F（B） | W（B） | RX 容量 W+4（B） | SPI 预期位数 |
|---:|---:|---:|---:|---:|
| 1 | 6930 | 6932 | 6936 | 55456 |
| 2 | 9234 | 9236 | 9240 | 73888 |
| 3 | 14918 | 14920 | 14924 | 119360 |

## 5. UDP 与电脑记录

PDK1 外层保持 40 B 头、每片最多 1200 B；外层 version=1、kind=2 不变。C6 只切分 F 字节，丢开 CRC 后的 SPI 填充。PDK1 seq 取帧内偏移 2 的 uint32 seq，total=F；三种配置的分片数依次为 6、8、13。

~~~text
源端：DPT 有效帧 + SPI 填充 → SPI
C6：长度/类型/配置/CRC 校验 → 仅有效帧 F → PDK1/UDP
PC：重组 PDK1 → 校验 DPT → 显示帧统计并记录
~~~

`frames/*.bin` 保存 F 字节的完整有效帧（头+载荷+CRC），不含 PDK1、SPI 填充或 RX 保护空间。PGM 不生成，depth.csv 的 pgm_file 列保留为空。抓帧工具的输入也是该 .bin；逻辑分析仪导出的 W 字节 SPI 事务需先去掉末尾填充再使用 .bin 工具。

UDP 没有现成的图像重传。C6 tx 表示本地全部分片发送成功，PC incomplete 表示重组超时，两者不保证等价。PC 默认重组超时 300 ms、最多 16 个待重组帧；C6 活跃帧龄超过 500 ms 会丢弃。

## 6. 时间与序号

真实摄像头链路中，camera_ms 由 N6 在采集该帧时记录，来自 N6 启动后的毫秒计数。采集驱动应选定并固定帧时间戳对应的事件，在采集记录中注明；采集、处理和发送任务通过帧元数据传递同一个时间戳，重发保持不变。C6 原样转发该字段，PC 将其写入 depth.csv。N6 接入真实采集时需在对应采集事件中实现赋值。

新采集帧递增 seq，重发保持 seq；GUI fps 是完成重组帧率，验证真实采集率还需检查唯一序号。N6/F103、C6、PC 的时钟未同步，不能直接相减当作端到端延迟。

C6 驻留统计从校验后开始，PC 重组统计从首个分片开始。仅源端重启使 seq 归零但 C6 session 不变时，丢帧/乱序估算可能受影响；联调可成组重启，正式支持独立重启需另设计源端 session。数据来源、传感器型号等在采集记录中说明。

## 7. 升级和测试

源端、C6、PC 成套更新；bench_artifacts 是旧帧格式/旧主从镜像，不能混用，也不自动转换旧录制文件。当前工具版本为 0.5.0。

~~~powershell
python -m unittest discover -s tool/tests -v
python -m unittest discover -s camera_spi_mock/tools -v
~~~

覆盖 14 B 帧头、单字节类型/配置、三种长度、无效类型、长度/CRC 错误、SPI 填充与 UDP 数据区分、分片重组、实际 UDP 接收和功耗/RSSI/完整帧保存。固件构建与主机测试不代替上板波形及帧率验证。
