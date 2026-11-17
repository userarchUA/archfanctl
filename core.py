"""archfanctl core: sensor/fan discovery and control (hwmon + NVIDIA NVML)."""
import glob, os, re, time

CONFIG = "/etc/archfanctl/config.json"
STATUS_DIR = "/run/archfanctl"
STATUS = STATUS_DIR + "/status.json"
HW = "/sys/class/hwmon"

try:
    import pynvml as N
except Exception:
    N = None
_nv_ok = False


def rd(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return None


def rdi(p):
    try:
        return int(rd(p))
    except (TypeError, ValueError):
        return None


def wr(p, v):
    with open(p, "w") as f:
        f.write(str(v))


def san(x):
    return re.sub(r"[:\s]+", "_", x)


# ---------- hwmon ----------
_cache = {"t": 0, "m": {}}


def hwmon_map(force=False):
    if force or time.time() - _cache["t"] > 30:
        m = {}
        for d in sorted(glob.glob(HW + "/hwmon*")):
            name = san(rd(d + "/name") or "unknown")
            dev = san(os.path.basename(os.path.realpath(d + "/device"))) if os.path.exists(d + "/device") else "virt"
            m[(name, dev)] = d
        _cache.update(t=time.time(), m=m)
    return _cache["m"]


def find_hwmon(name, dev):
    d = hwmon_map().get((name, dev)) or hwmon_map(True).get((name, dev))
    if not d:
        raise RuntimeError(f"hwmon {name}/{dev} not found")
    return d


# ---------- NVML ----------
def nv_init():
    global _nv_ok
    if N is None:
        return False
    if not _nv_ok:
        try:
            N.nvmlInit()
            _nv_ok = True
        except Exception:
            return False
    return True


def _s(x):
    return x.decode() if isinstance(x, bytes) else x


def nv_handle(uuid):
    return N.nvmlDeviceGetHandleByUUID(uuid)


# ---------- discovery ----------
def discover():
    fans, temps = [], []
    for (name, dev), d in hwmon_map(True).items():
        for p in sorted(glob.glob(d + "/pwm[0-9]*")):
            m = re.fullmatch(r"pwm(\d+)", os.path.basename(p))
            if not m or not os.path.exists(p + "_enable"):
                continue
            n = m.group(1)
            lab = rd(f"{d}/fan{n}_label")
            fans.append({"id": f"hw:{name}:{dev}:pwm{n}", "label": f"{name} · {lab or 'pwm' + n} ({dev})"})
        for p in sorted(glob.glob(d + "/temp[0-9]*_input")):
            m = re.fullmatch(r"temp(\d+)_input", os.path.basename(p))
            if not m:
                continue
            n = m.group(1)
            lab = rd(f"{d}/temp{n}_label")
            temps.append({"id": f"hw:{name}:{dev}:temp{n}", "label": f"{name} · {lab or 'temp' + n} ({dev})"})
    if nv_init():
        try:
            for i in range(N.nvmlDeviceGetCount()):
                h = N.nvmlDeviceGetHandleByIndex(i)
                uuid, nm = _s(N.nvmlDeviceGetUUID(h)), _s(N.nvmlDeviceGetName(h))
                temps.append({"id": f"nv:{uuid}:temp", "label": f"NVIDIA {nm} · GPU temp"})
                try:
                    nf = N.nvmlDeviceGetNumFans(h)
                except Exception:
                    nf = 1
                for j in range(nf):
                    fans.append({"id": f"nv:{uuid}:fan{j}", "label": f"NVIDIA {nm} · fan {j}"})
        except Exception:
            pass
    return {"fans": fans, "temps": temps}


def read_temp(tid):
    k, *rest = tid.split(":")
    if k == "hw":
        v = rdi(f"{find_hwmon(rest[0], rest[1])}/{rest[2]}_input")
        return None if v is None else v / 1000.0
    if k == "nv" and nv_init():
        return float(N.nvmlDeviceGetTemperature(nv_handle(rest[0]), N.NVML_TEMPERATURE_GPU))
    return None


# ---------- fans ----------
class HwFan:
    def __init__(self, fid):
        _, self.name, self.dev, self.leaf = fid.split(":")
        self.n = self.leaf[3:]
        self.orig = None

    def d(self):
        return find_hwmon(self.name, self.dev)

    def set(self, pct):
        d = self.d()
        en = f"{d}/{self.leaf}_enable"
        if self.orig is None:
            self.orig = rdi(en)
        if rdi(en) != 1:  # (re)assert manual mode, firmware/resume may reset it
            wr(en, 1)
        wr(f"{d}/{self.leaf}", int(round(max(0, min(100, pct)) * 255 / 100)))

    def read(self):
        d = self.d()
        pwm = rdi(f"{d}/{self.leaf}")
        return {"rpm": rdi(f"{d}/fan{self.n}_input"), "pct": None if pwm is None else round(pwm * 100 / 255)}

    def release(self):
        en = f"{self.d()}/{self.leaf}_enable"
        if self.orig not in (None, 1):
            wr(en, self.orig)
        elif rdi(en) == 1:
            wr(en, 2)  # back to automatic control


class NvFan:
    def __init__(self, fid):
        _, self.uuid, leaf = fid.split(":")
        self.i = int(leaf[3:])

    def set(self, pct):
        h = nv_handle(self.uuid)
        try:
            lo, hi = N.nvmlDeviceGetMinMaxFanSpeed(h)
        except Exception:
            lo, hi = 0, 100
        N.nvmlDeviceSetFanSpeed_v2(h, self.i, int(round(max(lo, min(hi, pct)))))

    def read(self):
        return {"rpm": None, "pct": N.nvmlDeviceGetFanSpeed_v2(nv_handle(self.uuid), self.i)}

    def release(self):
        N.nvmlDeviceSetDefaultFanSpeed_v2(nv_handle(self.uuid), self.i)


def make_fan(fid):
    if fid.startswith("hw:"):
        return HwFan(fid)
    if fid.startswith("nv:") and nv_init():
        return NvFan(fid)
    raise RuntimeError(f"unsupported fan {fid}")


# ---------- control logic ----------
def interp(curve, t):
    c = sorted(curve)
    if t <= c[0][0]:
        return float(c[0][1])
    if t >= c[-1][0]:
        return float(c[-1][1])
    for (x0, y0), (x1, y1) in zip(c, c[1:]):
        if x0 <= t <= x1:
            return float(y0) if x1 == x0 else y0 + (y1 - y0) * (t - x0) / (x1 - x0)
    return 100.0


class Controller:
    def __init__(self, cfg):
        self.cfg, self.fan = cfg, make_fan(cfg["fan"])
        self.cur = self.eff = self.temp = None
        self.err = None

    def step(self, dt, read_temp_fn=read_temp):
        c = self.cfg
        ts = []
        for t in c["temps"]:
            try:
                v = read_temp_fn(t)
            except Exception:
                v = None
            if v is not None:
                ts.append(v)
        lo, hi = c.get("min_pct", 20), c.get("max_pct", 100)
        immediate = False
        if not ts:                      # sensor failure -> failsafe full speed
            self.temp, target, immediate = None, 100.0, True
        else:
            self.temp = temp = max(ts)
            if self.eff is None or temp >= self.eff or self.eff - temp > c.get("hyst", 3.0):
                self.eff = temp         # hysteresis: hold speed until temp drops by > hyst
            target = max(lo, min(hi, interp(c["curve"], self.eff)))
            if temp >= c.get("critical", 90.0):
                target, immediate = 100.0, True
        if self.cur is None or immediate:
            self.cur = target
        elif target > self.cur:
            self.cur = min(target, self.cur + c.get("up_rate", 25.0) * dt)
        else:
            self.cur = max(target, self.cur - c.get("down_rate", 5.0) * dt)
        self.fan.set(self.cur)
        self.err = None
