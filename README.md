# caonima

some hacks for https://github.com/sb-child/nima

have fun!

## [autorotate](./autorotate.py)

现在你笔记本的niri屏幕会跟随重力旋转了，而且只发生在平板模式。

**依赖项(Fedora软件包)**:

- `python3-pydbus` 脚本强依赖
- `python3-gobject` 脚本强依赖
- `iio-sensor-proxy` 通常预装

**依赖项(systemd系统服务)**:

- `iio-sensor-proxy.service` 通常默认开着
- `laptop-sensor-daemon.service` [我的项目](https://github.com/sb-child/laptop-sensor-daemon)

**依赖项(内核模块)**:

- `hp-wmi` 如果惠普Flip没输出事件, 这是补丁 [我的项目](https://github.com/sb-child/laptop-sensor-daemon/blob/main/patch/README.md)

**本体**:

- `cnm-autorotate.service` systemd用户服务, [一键部署](#caoniman)

## [pw-set](./pw-set.py)

打玩音游看黄片，叫床声卡成魔鬼哦哦哦哦，搞的声卡都不知道设置什么采样率。

我提供了非常方便的解决方案:

```bash
./pw-set.py -r 44100 -q 32
```

**依赖项(Fedora软件包)**:

- `python3` 脚本解释器
- `pipewire` 被控制的

## [modemctl](./modemctl.py)

当你插入移远的Rx500U模块，它会亲切的弹窗告诉你现在怎么样了。

**部署**:

```bash
RP=$(realpath modemctl.py) sed "s@{script_path}@$RP@g" cnm-modemctl.service | sudo tee /etc/systemd/system/cnm-modemctl.service
sudo systemctl daemon-reload
sudo systemctl enable cnm-modemctl.service
sudo systemctl restart cnm-modemctl.service
```

## [fuck-pipewire-pulse](./fuck-pipewire-pulse.py)

有个关于 `pipewire-pulse` 与蓝牙音频设备的死锁还没有找到问题源头，这是 workaround。

**依赖项(Fedora软件包)**:

- `python3` 脚本解释器
- `pipewire` 被控制的
- `bluetoothctl` 被控制的

**依赖项(systemd系统服务)**:

- `bluetooth.service` 通常默认开着

**依赖项(systemd用户服务)**:

- `pipewire.service` 被控制的

**本体**:

- `cnm-fuck-pipewire-pulse.service` systemd用户服务, [一键部署](#caoniman)

## [fuck-phira](./fuck-phira.py)

因为pipewire不太聪明, 没有及时把采样率开到phira开的384k, 这是 workaround。

我不理解为什么phira把主音源采样率锁在384k, 但游玩音源采样率可以自己调。

**依赖项(Fedora软件包)**:

- `python3` 脚本解释器
- `pipewire` 被控制的

**依赖项(systemd用户服务)**:

- `pipewire.service` 被控制的

**本体**:

- `cnm-fuck-phira.service` systemd用户服务, [一键部署](#caoniman)

## [qmiset](./qmiset.py)

Quectel QMI 模块每次开关都好麻烦，所以我提供了非常方便的解决方案:

```bash
sudo ./qmiset.py up
sudo ./qmiset.py down
```

**依赖项(Fedora软件包)**:

- `python3` 脚本解释器
- `libqmi-utils` 提供 `qmi-network`
- `busybox` 提供 `udhcpc`

## [spawn-me-first](./spawn-me-first.py)

这是给niri `spawn` 的，因为我要偷一些环境变量给别的脚本用。

你要知道即使niri死了，用户服务还活着。我不想注销登录之后因为没有同步新的环境变量导致服务全崩了。

**依赖项**:

- `niri` 不然呢

**部署**:

在 `~/.config/niri/config.kdl` 加上这个配置:

```
spawn-at-startup "/path/to/spawn-me-first.py"
```

## [caoniman](./caoniman.py)

大多数这里的服务都可以通过运行这个脚本一键部署。

**支持的服务**:

- `autorotate` [这里](#autorotate)
- `fuck-pipewire-pulse` [这里](#fuck-pipewire-pulse)
- `fuck-phira` [这里](#fuck-phira)

**部署**:

```bash
# 部署所有支持的服务
./caoniman.py
```

## [nima](https://github.com/sb-child/nima)

我fork的[niri](https://github.com/niri-wm/niri)。

你要知道niri对数位板和触摸屏的支持，就跟别的窗管一个样...

但是我要用触摸屏和数位板。
