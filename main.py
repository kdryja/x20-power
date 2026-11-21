"""X20 Power: charge limit, Travel Mode and per-game TDP for the ROG Xbox Ally X20 (board RC74XA).

Findings on BIOS RC74XA.303 (2026-11-21), judged by charging behaviour:

* Charge limit (WMI 0x00120057). The standard charge_control_end_threshold
  write never reaches the EC. A limit takes effect only when the value is
  written first with bit 7 set and then as a plain value. The EC ignores the
  number and holds at 80%. 0x64 (100) removes the limit.
* Travel Mode (Armoury Crate's 65 W charging cap) is WMI 0x00090034: DEVS writes
  EC bit TRED (1/0), DSTS reads TRSA. Found by diffing Windows reads with Travel
  Mode on/off/on. The EC keeps it across reboots.
* TDP goes through asus-armoury (ppt_pl1_spl / ppt_pl2_sppt / ppt_pl3_fppt), the
  same way SimpleDeckyTDP does it: all three get the chosen value, clamped to
  each attribute's firmware range. Platform profile follows the TDP
  (quiet < 13 W, balanced < 20 W, performance otherwise).
"""
import asyncio
import glob
import json
import os

import decky

DBG = "/sys/kernel/debug/asus-nb-wmi"
CHARGE_DEV = 0x00120057
LIMIT_ON = (0xD0, 0x50)   # 0x80|80, then plain 80
LIMIT_OFF = (0x64,)       # 100 = no limit
TRAVEL_DEV = 0x00090034
BAT = "/sys/class/power_supply/BAT1"
AC_ONLINE = "/sys/class/power_supply/ACAD/online"
ARMOURY = "/sys/class/firmware-attributes/asus-armoury/attributes"
SPL, SPPT, FPPT = "ppt_pl1_spl", "ppt_pl2_sppt", "ppt_pl3_fppt"
FALLBACK_RANGES = {SPL: (7, 35), SPPT: (13, 45), FPPT: (19, 55)}   # RC74XA.303
PLATFORM_PROFILE = "/sys/firmware/acpi/platform_profile"
BATTERY_DEFAULT_TDP = 15
SETTINGS = os.path.join(os.environ.get("DECKY_PLUGIN_SETTINGS_DIR", "/tmp/x20-power"), "settings.json")

_wmi_lock = asyncio.Lock()        # debugfs dev_id/ctrl_param are shared state
_settings_lock = asyncio.Lock()   # load-modify-save of settings.json
_tdp_lock = asyncio.Lock()


# ---------- small helpers ----------

def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _write(path, value):
    with open(path, "w") as f:
        f.write(f"{value}\n")


def _int(path, default=0):
    try:
        return int(_read(path, str(default)))
    except (TypeError, ValueError):
        return default


def _load():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(settings):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=1, sort_keys=True)
    os.replace(tmp, SETTINGS)


async def _modify(change):
    async with _settings_lock:
        settings = _load()
        change(settings)
        _save(settings)
        return settings


# ---------- asus-nb-wmi debugfs ----------

def _devs(dev_id, value):
    _write(f"{DBG}/dev_id", f"0x{dev_id:08x}")
    _write(f"{DBG}/ctrl_param", f"0x{value:x}")
    return _read(f"{DBG}/devs", "")


def _dsts(dev_id):
    """Return the DSTS value, or None when the read fails."""
    try:
        _write(f"{DBG}/dev_id", f"0x{dev_id:08x}")
        text = _read(f"{DBG}/dsts", "")   # e.g. "DSTS(0x90034) = 0x10001"
        return int(text.rsplit("=", 1)[1].strip(), 16)
    except (OSError, ValueError, IndexError):
        return None


def _travel_mode():
    value = _dsts(TRAVEL_DEV)
    if value is None or not value & 0x10000:   # bit 16 = "device present"
        return None
    return bool(value & 1)


# ---------- power readings ----------

def _charger_watts():
    watts = None
    for port in glob.glob("/sys/class/power_supply/ucsi-source-psy-*"):
        if _read(f"{port}/online") != "1":
            continue
        v = _int(f"{port}/voltage_now")
        i = _int(f"{port}/current_now")
        watts = max(watts or 0, round(v * i / 1e12))
    return watts


def _apu_watts():
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        if _read(f"{hwmon}/name") != "amdgpu":
            continue
        for name in ("power1_average", "power1_input"):
            value = _read(f"{hwmon}/{name}")
            if value and value.isdigit():
                return round(int(value) / 1e6, 1)
    return None


# ---------- TDP ----------

def _tdp_supported():
    return all(os.path.exists(f"{ARMOURY}/{a}/current_value") for a in (SPL, SPPT, FPPT))


def _range(attr):
    lo = _int(f"{ARMOURY}/{attr}/min_value", -1)
    hi = _int(f"{ARMOURY}/{attr}/max_value", -1)
    return (lo, hi) if 0 < lo <= hi else FALLBACK_RANGES[attr]


def _clamp(value, bounds):
    return max(bounds[0], min(bounds[1], value))


def _source():
    return "ac" if _read(AC_ONLINE) == "1" else "battery"


def _platform_profile_for(tdp):
    choices = (_read(f"{PLATFORM_PROFILE}_choices", "") or "").split()
    want = "quiet" if tdp < 13 else "balanced" if tdp < 20 else "performance"
    return want if want in choices else None


def _tdp_for(settings, game_id, source):
    """Returns (watts, game_has_own_value)."""
    profiles = settings.get("tdp_profiles", {})
    own = profiles.get(game_id, {}).get(source)
    if isinstance(own, int):
        return own, game_id != "default"
    default = profiles.get("default", {}).get(source)
    if isinstance(default, int):
        return default, False
    return (_range(SPL)[1] if source == "ac" else BATTERY_DEFAULT_TDP), False


def _import_simpledeckytdp(settings):
    """One-time import of SimpleDeckyTDP's per-game TDP values. Returns the count."""
    if settings.get("sdtdp_imported"):
        return 0
    settings["sdtdp_imported"] = True
    path = os.path.join(os.path.dirname(os.path.dirname(SETTINGS)), "SimpleDeckyTDP", "settings.json")
    try:
        with open(path) as f:
            src = json.load(f)
    except (OSError, ValueError):
        return 0
    # With maxTdpOnAcPower on, SimpleDeckyTDP forced max TDP on AC, so its stored AC values were not in effect.
    import_ac = not (src.get("advanced") or {}).get("maxTdpOnAcPower")
    profiles = settings.setdefault("tdp_profiles", {})
    count = 0
    for key, profile in (src.get("tdpProfiles") or {}).items():
        tdp = (profile or {}).get("tdp")
        if not isinstance(tdp, (int, float)):
            continue
        source = "battery"
        if key.endswith("-ac-power"):
            if not import_ac:
                continue
            key, source = key[: -len("-ac-power")], "ac"
        profiles.setdefault(key, {}).setdefault(source, int(tdp))
        count += 1
    return count


class Plugin:
    game_id = "default"
    game_name = ""
    applied = None
    ac_task = None

    # ----- state for the panel -----

    async def get_state(self):
        settings = _load()
        async with _wmi_lock:
            travel = _travel_mode()
        source = _source()
        tdp, own = _tdp_for(settings, self.game_id, source)
        spl_lo, spl_hi = _range(SPL)
        return {
            "charge_limit": settings.get("charge_limit"),
            "travel_mode": travel,
            "debugfs": os.path.isdir(DBG),
            "capacity": _read(f"{BAT}/capacity"),
            "status": _read(f"{BAT}/status"),
            "current_ma": _int(f"{BAT}/current_now") // 1000,
            "charger_w": _charger_watts(),
            "tdp": {
                "supported": _tdp_supported(),
                "game_id": self.game_id,
                "game_name": self.game_name,
                "source": source,
                "value": tdp,
                "own": own,
                "min": spl_lo,
                "max": spl_hi,
                "limits": {a: _int(f"{ARMOURY}/{a}/current_value") for a in (SPL, SPPT, FPPT)},
                "platform_profile": _read(PLATFORM_PROFILE),
                "apu_w": _apu_watts(),
            },
        }

    # ----- charge limit / Travel Mode -----

    async def set_charge_limit(self, enabled):
        enabled = bool(enabled)
        async with _wmi_lock:
            for value in (LIMIT_ON if enabled else LIMIT_OFF):
                result = _devs(CHARGE_DEV, value)
                decky.logger.info(f"DEVS 0x{CHARGE_DEV:08x} 0x{value:x}: {result}")
        await _modify(lambda s: s.__setitem__("charge_limit", enabled))
        return await self.get_state()

    async def set_travel_mode(self, enabled):
        value = 1 if enabled else 0
        async with _wmi_lock:
            result = _devs(TRAVEL_DEV, value)
            decky.logger.info(f"DEVS 0x{TRAVEL_DEV:08x} {value}: {result}")
        return await self.get_state()

    async def reapply(self):
        settings = _load()
        if "charge_limit" in settings:
            decky.logger.info(f"re-applying charge_limit={settings['charge_limit']}")
            await self.set_charge_limit(settings["charge_limit"])
        return await self.get_state()

    # ----- TDP -----

    async def _apply_tdp(self, force=False):
        if not _tdp_supported():
            return
        source = _source()
        tdp, _ = _tdp_for(_load(), self.game_id, source)
        key = (tdp, source, self.game_id)
        if not force and key == self.applied:
            return
        async with _tdp_lock:
            values = {a: _clamp(tdp, _range(a)) for a in (SPL, SPPT, FPPT)}
            profile = _platform_profile_for(tdp)
            try:
                for attr in (FPPT, SPPT, SPL):
                    _write(f"{ARMOURY}/{attr}/current_value", values[attr])
                    await asyncio.sleep(0.1)
                if profile and _read(PLATFORM_PROFILE) != profile:
                    _write(PLATFORM_PROFILE, profile)
            except OSError as e:
                decky.logger.error(f"TDP {tdp} W failed: {e}")
                return
            self.applied = key
            decky.logger.info(
                f"TDP {tdp} W ({source}, game {self.game_id} {self.game_name!r}): "
                f"spl {values[SPL]} sppt {values[SPPT]} fppt {values[FPPT]}, profile {profile}")

    async def set_game(self, game_id, game_name=""):
        game_id = str(game_id or "default")
        if game_id != self.game_id:
            self.game_id, self.game_name = game_id, str(game_name or "")
            await self._apply_tdp()
        return await self.get_state()

    async def set_tdp(self, watts):
        watts = _clamp(int(watts), _range(SPL))
        game_id, source = self.game_id, _source()
        await _modify(lambda s: s.setdefault("tdp_profiles", {}).setdefault(game_id, {}).__setitem__(source, watts))
        await self._apply_tdp(force=True)
        return await self.get_state()

    async def resume(self):
        await self.reapply()
        await self._apply_tdp(force=True)
        return await self.get_state()

    async def _watch_ac(self):
        last = _source()
        while True:
            await asyncio.sleep(2)
            try:
                current = _source()
                if current != last:
                    last = current
                    decky.logger.info(f"power source -> {current}")
                    await self._apply_tdp()
            except Exception as e:
                decky.logger.error(f"AC watch: {e}")

    # ----- lifecycle -----

    async def _main(self):
        try:
            async with _settings_lock:
                settings = _load()
                if not settings.get("sdtdp_imported"):
                    count = _import_simpledeckytdp(settings)
                    _save(settings)
                    decky.logger.info(f"imported {count} SimpleDeckyTDP TDP values")
        except Exception as e:
            decky.logger.error(f"SimpleDeckyTDP import failed: {e}")
        for _ in range(30):
            if os.path.isdir(DBG):
                break
            await asyncio.sleep(1)
        try:
            await self.reapply()
        except Exception as e:   # keep the loader running if debugfs is missing
            decky.logger.error(f"re-apply at start failed: {e}")
        try:
            await self._apply_tdp(force=True)
        except Exception as e:
            decky.logger.error(f"TDP at start failed: {e}")
        Plugin.ac_task = asyncio.get_event_loop().create_task(self._watch_ac())

    async def _unload(self):
        if Plugin.ac_task:
            Plugin.ac_task.cancel()
