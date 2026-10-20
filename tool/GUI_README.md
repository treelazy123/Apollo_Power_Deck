# Power Deck 上位机 GUI

当前版本 **0.5.0**，支持 DPT 数据帧、PDK1 UDP 分片、功耗 JSON/RSSI 和文本消息。需要 Python 3.10+、Tkinter 和 uv；无第三方运行时依赖。帧定义见 [DPT 协议](../FRAME_PROTOCOL.md)。

## 启动

在 tool 目录：

~~~powershell
uv run deck-gui
uv run deck-gui --board 192.168.137.66
# 也可用 Python
python -m src.deck_gui
~~~

C6 IP 留空自动发现，也可手动输入。GUI 监听 UDP 5005、向 C6 UDP 5006 发送 PDHELLO1。Windows 防火墙需放行；广播不可用时指定 IP。避免同时运行多个争用 UDP 5005 的接收程序。

## 协议与显示

DPT 有效帧为 14 B 头 + 载荷 + 4 B CRC；头是 `<BBIII`，依次为 1 B magic=0x01、1 B format、4 B seq、4 B camera_ms、4 B payload_bytes。FRAME_PROFILES 只定义三个载荷长度；width/height=0、pixels=None。

| format | 布局 | 有效帧 F（B） | 显示/保存 |
|---:|---|---:|---|
| 1 | 6912 B 不透明字节 | 6930 | 仅 .bin，无预览 |
| 2 | 9216 B 不透明字节 | 9234 | 仅 .bin，无预览 |
| 3 | 14900 B 不透明测试载荷，无图像宽高 | 14918 | 仅 .bin |

PDK1 外层保持 40 B 头、最多 1200 B 片段，传输并重组有效帧 F；SPI CRC 后的 2 B 填充不进入 UDP 或 .bin。旧录制文件和旧 bench_artifacts 镜像不自动兼容，升级须同步源端、C6 和 PC。

功耗曲线显示最近 60 秒电压/电流/功率；WiFi RSSI 卡片显示 C6 收到热点的信号强度（dBm）。功耗包没提供有效 RSSI 时显示“— dBm”。RSSI 不等于 PC 测得的 C6 上行强度。

## 记录与复核

“开始记录”可自选父目录和文件夹名，在新目录保存：

- power.csv：电脑时间、板端地址、C6 session、功耗 seq/timestamp_ms、电压/电流/功率与 rssi_dbm/rssi_valid。
- depth.csv：seq、camera_ms、format、payload_size、C6 时间、重组耗时和文件名。
- frames/*.bin：完整 DPT（头+载荷+CRC），无 PDK1 头；不是仅传感器 payload。
- 三种格式均不生成 .pgm。depth.csv 的 pgm_file 列为兼容既有 CSV 表头而保留，始终为空。

当前帧不声明真实/合成来源；如需记录真实/合成来源、传感器型号、标定等，随采集目录提供说明。不要根据帧头猜来源。

记录目录不会覆盖已有目录。后台写盘有有界队列，磁盘跟不上时会丢弃待记录项，应检查录制状态。

## 统计含义

| 指标 | 含义 |
|---|---|
| fps / 完整帧 | 成功重组的帧率/累计数，可能包含重复源帧 |
| invalid | 消息/分片/帧解析或校验失败 |
| incomplete | 某帧分片在默认 300 ms 内未收齐 |
| 序号缺口 / 估算丢帧 | 按有效 DPT seq 估算端到端缺失，不能定位到具体环节 |
| 乱序 | 超出近期修正范围的异常回退序号累计，不是 UDP 分片乱序数 |
| 界面跳过 | 网络事件入 GUI 队列时被跳过，不等于网络丢包 |

估算丢帧率 = 序号缺口 ÷（已收到帧数 + 序号缺口）；按源 IP 和 C6 session 重新统计，只覆盖首个与最新有效序号之间，近期迟到帧可修正。N6/F103 独立重启而 C6 session 未变时，估算可能受干扰。

seq/camera_ms 均为 uint32：30 fps 下序号约 4.54 年回绕，毫秒计时约 49.71 天回绕；不会因此自动停止记录。camera_ms、C6 时间和 PC 时间未同步。“C6 驻留”从 C6 校验后开始，“电脑重组”从首片到完整帧，都不是完整摄像头到 PC 的延迟。

## WiFi 消息

1. 源端、C6 及工具使用当前 DPT 版本，并先连接 GUI。
2. “WiFi 消息”输入文本，点发送或 Enter，上限 512 B UTF-8。
3. C6 串口打印 `net_rx: PC message id=... bytes=... text=...`。
4. GUI 收到确认后显示“板端已接收”；2 秒未确认提示超时，不自动重发。

“已发送”仅表示 PC 发出数据报，“板端已接收”表示 C6 文本处理确认，不表示 N6 执行采集指令。数据包为 PDMSG1（6 B）+ uint32 小端 ID + 文本，确认 PDACK1 + 同 ID；与发现复用 UDP 5006，返回 PC 接收端口。C6 仅接受当前租约对应的 PC IP/端口。

当前未实现 N6 采集控制、运行时帧格式切换或重新烧录；相关按钮为预留。

## 安装与分发

~~~powershell
uv build
uv tool install --force .\dist\power_deck_tools-0.5.0-py3-none-any.whl
deck-gui
~~~

也可复制源码后 `uv tool install --force .`。不要继续使用缓存的旧版 旧帧格式 工具。进入 tool 目录运行 `uv run deck-gui --help` 查看参数。

## 源文件与测试

- src/deck_gui.py：界面、功耗曲线、预览和操作。
- src/deck_gui_backend.py：UDP、文本确认、统计和记录。
- src/depth_protocol.py：共享 DPT 载荷配置/帧校验与 PDK1 重组。
- tests/test_frame_protocol.py：协议、UDP 与录制回归。
- ../camera_spi_mock/tools/decode_depth.py：复用同一解析器的 .bin 元数据工具；三个格式均拒绝 PGM 输出。

根目录执行：

~~~powershell
python -m unittest discover -s tool/tests -v
python -m unittest discover -s camera_spi_mock/tools -v
~~~
