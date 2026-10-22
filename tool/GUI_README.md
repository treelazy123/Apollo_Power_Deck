# Power Deck 上位机使用说明

版本 **0.5.0**。支持功耗曲线、RSSI、DPT 帧接收/统计/记录和 WiFi 文本消息。项目交付与 Apollodeck 接入流程见 [README](../README.md)，字节接口见 [FRAME_PROTOCOL](../FRAME_PROTOCOL.md)。

## 启动与连接

<<<<<<< HEAD
需要 Python 3.10+（含 Tkinter）。**当前项目没有第三方运行依赖，直接运行源码时可以省略 uv。** 在 `tool` 目录运行（macOS 通常将 `python` 换成 `python3`）：

~~~powershell
python -m src.deck_gui
# 自动发现不可用时填写 C6 的实际 IP
python -m src.deck_gui --board 192.168.137.66
~~~

后续开发若需要第三方依赖，建议将依赖记录在 `pyproject.toml` 并提交 `uv.lock`，使用 uv 统一管理虚拟环境和依赖；届时用户可在 `tool` 目录通过 `uv run deck_gui` 自动安装所需依赖并启动。当前已安装 uv 的用户也可以使用该命令。

=======
需要 Python 3.10+（含 Tkinter）及 uv，无第三方运行时依赖。在 `tool` 目录运行：

~~~powershell
uv run deck-gui
# 自动发现不可用时填写 C6 的实际 IP
uv run deck-gui --board 192.168.137.66
# 也可直接使用 Python
python -m src.deck_gui
~~~

>>>>>>> origin/main
GUI 监听 UDP 5005，定期向 C6 UDP 5006 发送 `PDHELLO1`。C6 IP 留空自动发现，也可在界面手动指定。电脑与 C6 接入同一网络，放行防火墙，并避免其他程序占用接收端口。

功耗曲线显示最近 60 s 的电压/电流/功率；RSSI 为 C6 收到热点的信号强度，有效值单位 dBm，缺少有效样本时显示“— dBm”。

当前 format=0x01/0x02/0x03 分别为 6912/9216/14900 B **不透明载荷**，不声明像素布局，因此没有视频预览。接入真实摄像头后，需共同定义像素格式并实现解码，不能仅把载荷换成真实数据就显示图像。

## 记录与离线检查

点击“开始记录”，选择父目录和新的文件夹名，停止记录后检查以下内容：

| 文件 | 内容 |
|---|---|
| `power.csv` | PC 时间、来源、C6 session、功耗序号/时间、电压、电流、功率与 RSSI |
| `depth.csv` | 帧序号、camera_ms、format、载荷长度、C6 时间、驻留/重组耗时与文件名 |
| `frames/*.bin` | 完整 DPT：14 B 头 + 载荷 + 4 B CRC，不含 UDP 头或 SPI 填充 |

当前不生成 PGM，`depth.csv` 的 `pgm_file` 列保留为空。记录不覆盖已有目录；写盘队列有界，磁盘跟不上时查看录制状态中的丢弃数和错误。采集目录可另附传感器型号、数据布局和标定信息。

检查已录制的完整 DPT 文件，在 `tool` 目录执行：

~~~powershell
uv run deck-decode "D:/captures/session/frames/实际文件.bin"
# 或
python -m src.decode_depth "D:/captures/session/frames/实际文件.bin"
~~~

工具检查帧长、类型、格式和 CRC 并输出元数据；三个不透明格式均不支持 PGM 输出。逻辑分析仪抓取的 SPI 数据须先去除尾部填充，不能把带填充的线上数据直接作为录制帧输入。

## 统计含义

| 指标 | 含义 |
|---|---|
| fps / 完整帧 | 成功重组帧率 / 累计数，可能包含重复源帧 |
| invalid | 消息、分片或完整帧解析/校验失败 |
| incomplete | 分片在默认 300 ms 内未收齐 |
| evicted | 待重组池满，提前淘汰未完成帧 |
| 序号缺口 / 估算丢帧 | 根据有效 DPT seq 估算的端到端缺失 |
| 乱序 | 超出近期修正范围的回退序号累计，不是 UDP 分片乱序数 |
| 界面跳过 | GUI 事件队列跳过数据，不等于网络丢包 |
| C6 驻留 / 电脑重组 | C6 校验后至发送的驻留时间 / 首片至重组完成的时间，均非端到端延迟 |

估算丢帧率 = 序号缺口 ÷（已收到的唯一帧数 + 序号缺口）。按来源 IP 和 C6 session 重置，只覆盖首个与最新有效序号之间；近期迟到帧可修正缺口，重复帧不重复计入。该值不能定位具体丢帧环节，需结合 C6 串口统计。

Apollodeck 独立重启而 C6 session 未变时，序号归零可能影响乱序和丢帧估算。seq/camera_ms 都是 uint32：30 fps 下序号约 4.54 年回绕，毫秒时间约 49.71 天回绕。三端时钟未同步，不直接相减计算单向延迟。

## WiFi 文本消息

连接 GUI 后，在“WiFi 消息”输入文本并发送，上限 512 B UTF-8。C6 串口显示 `net_rx: PC message id=... bytes=... text=...`；GUI 收到确认后显示“板端已接收”，2 s 未确认则提示超时，不自动重发。

消息为 `PDMSG1 + uint32 小端 ID + 文本`，确认是 `PDACK1 + 同 ID`，复用 UDP 5006；C6 只接受当前租约对应的 PC IP/端口。确认表示 C6 收到了文本，不表示 Apollodeck 执行了采集指令。

Apollodeck 采集控制、运行时帧格式切换和重新烧录尚未实现，相关控件为预留。

## 分发与维护

<<<<<<< HEAD
### 方式一：直接运行源码（推荐）

准备 Python 3.10+（含 Tkinter），拿到 `tool/` 源码后，在该目录运行：

~~~sh
python -m src.deck_gui
~~~

macOS 通常使用 `python3 -m src.deck_gui`。当前无需安装第三方运行依赖、安装 uv 或执行 `uv build`；后续引入第三方依赖时，可按“启动与连接”一节使用 uv 管理环境并运行。

### 方式二：只发送 whl 安装包

项目的 `pyproject.toml` 已配置好打包和 `deck_gui` 启动入口，无需额外配置。开发者在 `tool` 目录运行：

~~~sh
uv build --wheel
~~~

将生成的 `dist/power_deck_tools-0.5.0-py3-none-any.whl` 发给用户。同一个 whl 可供 Windows 和 macOS 安装，用户仍需准备 uv 和支持 Tkinter 的 Python 3.10+。

用户进入 whl 所在目录，安装一次：

~~~sh
uv tool install --force ./power_deck_tools-0.5.0-py3-none-any.whl
~~~

之后直接运行，无需源码或进入 `tool` 目录：

~~~sh
deck_gui
~~~

如果找不到 `deck_gui`，执行 `uv tool update-shell` 后重新打开终端。参见 [uv 工具安装说明](https://docs.astral.sh/uv/guides/tools/)。

### 源码维护与检查
=======
在 `tool` 目录构建并安装：

~~~powershell
uv build
uv tool install --force .\dist\power_deck_tools-0.5.0-py3-none-any.whl
deck-gui
~~~

也可用 `uv tool install --force .` 安装源码。`uv run deck-gui --help` 可查看启动参数。
>>>>>>> origin/main

`src/deck_gui.py` 负责界面，`src/deck_gui_backend.py` 负责接收、记录和统计，`src/depth_protocol.py` 负责协议与重组，`src/decode_depth.py` 提供离线检查。从仓库根目录运行现有自动化检查：

~~~powershell
python -m unittest discover -s tool/tests -v
~~~
