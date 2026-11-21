# X20 Power

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for the **ASUS ROG Xbox Ally X20** (board RC74XA) on Linux. It adds three things to the Quick Access menu:

- **TDP per game.** Separate values on battery and on the charger, applied when the running game changes, when you plug in or unplug, and after sleep.
- **Charge limit.** 80% or off. That is all the X20 firmware supports (see below).
- **Travel Mode.** Armoury Crate's 65 W charging cap, toggled from Linux.

It was written for one device and tested on that device only:
- CachyOS (handheld edition) with the `linux-ogc` 7.3.4 kernel
- BIOS RC74XA.303
- Decky Loader 3.3.1

Use at your own risk.

## Status

| Feature | How far it's verified |
|---|---|
| Charge limit on/off | By charging behaviour: holds at 80% and resumes charging when switched off. Holding through sleep and after a reboot isn't confirmed yet. |
| Travel Mode | The switch is confirmed in Windows, and in Linux its status follows the toggle. The effect on charging power isn't confirmed (needs a >65 W charger). |
| TDP | By power draw: in Hades II, APU power held flat at about 10 W with a 10 W setting and rose to 22–25 W at 20 W. The limits follow the slider, power source and running game. A light, frame-capped game (Spelunky 2 at about 8 W) didn't drop to a 7 W setting within 6 minutes. |

## Why the standard Linux charge limit doesn't work on the X20

On the X20, writing `/sys/class/power_supply/BAT1/charge_control_end_threshold` (what upower, Steam and most Decky plugins use) does nothing. The file just echoes the last value written, and the battery still charges to 100%.

The reason is in the X20's ACPI tables. The WMI handler for device `0x00120057` stores the value in EC RAM. It only sends the EC its "apply" command (`ECMD 0xA3`) when bit 7 of the *previous* write was set. The Linux driver only sends 0–100, so the apply command is never sent. By comparison, the 2024 ROG Ally X (RC72LA) tables pass the value straight to the EC, which is why the same setting works on older models.

All of this was tested by watching `charge_now` and `current_now`, not by reading the setting back:

| Sent through asus-nb-wmi debugfs (`0x00120057`) | Result |
|---|---|
| plain `90` (what the kernel does) | no effect, charges to 100% |
| `0xDA` or `0xDF` (bit 7 set) | stops charging |
| `0xDA` then `0x5A` (flag, then plain 90) | charges from 78%, **stops at 80%** |
| `0xDF` then `0x5F` (flag, then plain 95) | stays at 80%, also after unplugging and replugging |
| `0x64` (100) | limit off, charging resumes within seconds |

So the EC ignores the number and only does **80% or no limit**, which matches Armoury Crate SE offering only an 80% option on this model. X20 Power sends `0xD0` then `0x50` for "on" and `0x64` for "off". With the value at 80, the firmware's `_BST` reports the hold properly ("Not charging").

## Travel Mode

Travel Mode is WMI device `0x00090034`:
- `DEVS` writes EC bit `TRED` (ERAM offset 0xA1, bit 2).
- `DSTS` reads `TRSA` (0xA1, bit 6).

It was found by reading every side-effect-free WMI getter in Windows while toggling Travel Mode on, off and on again in Armoury Crate (see [docs/travel-mode-reads.txt](docs/travel-mode-reads.txt)). The setting persists across reboots. From Linux, the status follows the toggle. **Its effect on charging power has not been verified yet**: that needs a charger above 65 W.

## TDP

TDP goes through the kernel's `asus-armoury` firmware attributes, the same way [SimpleDeckyTDP](https://github.com/aarron-lee/SimpleDeckyTDP) does it on ROG Ally devices. The chosen value is written to `ppt_pl3_fppt`, `ppt_pl2_sppt` and `ppt_pl1_spl`, each clamped to the range the firmware reports:

| Attribute | X20 range |
|---|---|
| `ppt_pl1_spl` (sustained) | 7–35 W |
| `ppt_pl2_sppt` (slow) | 13–45 W |
| `ppt_pl3_fppt` (fast) | 19–55 W |

The slider covers the SPL range. The platform profile follows the TDP: `quiet` below 13 W, `balanced` below 20 W, `performance` otherwise.

- Moving the slider saves the value for the current game and power source.
- Games without their own value use the default.
- With no value set, the default is 15 W on battery and the maximum on the charger.

On first start, X20 Power imports the per-game battery TDP values from SimpleDeckyTDP's settings, if they're there. It also imports SimpleDeckyTDP's charger values, unless its "max TDP on AC" option was on: in that case SimpleDeckyTDP never applied them. Uninstall SimpleDeckyTDP afterwards, or the two will fight over TDP.

## Requirements

- A kernel with `asus-armoury` (`/sys/class/firmware-attributes/asus-armoury/`).
- `asus-nb-wmi` with debugfs (`CONFIG_DEBUG_FS=y`; `/sys/kernel/debug/asus-nb-wmi/` must exist). The plugin runs as root (`"flags": ["root"]`).
- Decky Loader 3.x.

## Install

```bash
git clone https://github.com/kdryja/x20-power.git
cd x20-power
sudo ./install.sh
```

`install.sh` copies the plugin to `~/homebrew/plugins/x20-power` and restarts Decky. To uninstall, use Decky's plugin settings.

## Notes for hacking on it

- The frontend (`dist/index.js`) is hand-written, so there's no Node build step. It uses the globals Decky provides (`window.SP_REACT`, `window.DFL`) and the loader API connection used by `@decky/api`. `package.json` must keep `"type": "module"`. Without it, Decky loads the file as a legacy script and fails with "Unexpected token export".
- `tools/cdp_compile.py` syntax-checks `dist/index.js` in Steam's own JS engine. It compiles but doesn't run the file, through the CEF debug port Decky enables. Run it on the device: `python3 tools/cdp_compile.py dist/index.js`.
- `tools/x20-wmi-read.ps1` is the read-only Windows script used to find Travel Mode. Run it in an elevated PowerShell.
- The debugfs interface is meant for debugging, not as a stable API. The proper fix is for the kernel's `asus-wmi` driver to learn the X20's charge-limit sequence.

Not affiliated with ASUS or Microsoft.
