# Yandex Music EQ Python

**Independent Windows system-wide 10-band equalizer**, controlled by a small Python/PySide6 GUI and backed by [Equalizer APO](https://sourceforge.net/projects/equalizerapo/). Recreates the Yandex Music web equalizer's band layout, presets and *modeled* Web Audio biquad filter behavior.

> Unofficial project; not affiliated with, endorsed by, or distributed by Yandex. It does not include Yandex frontend source code or bundled audio tracks.

## Scope and limitations

- Ten filters in series: **60 Hz low shelf**, **170, 310, 600, 1000, 3000, 6000, 12000, 14000 Hz peaking**, **16000 Hz high shelf**.
- Q = 1 for peaking filters. Web Audio ignores Q for shelf filters (implemented with shelf slope S = 1).
- Individual gains **-12 to +12 dB**, **0.1 dB** steps. Separate *linear* preamp **0.5 to 1.5**, **0.1** steps.
- **19 presets** extracted as numerical settings from user-provided Yandex Music JS, stored in [`presets.json`](presets.json) beside the Python code. Custom values and app state are stored locally in `settings.json` (ignored by Git).
- Uses Equalizer APO `IIR Order 2` filters with RBJ/Web Audio-style coefficient formulas for **44.1, 48, 88.2, 96, 176.4 and 192 kHz**. For other sample rates, falls back to its built-in LS/PK/HS filters, which may differ from browser DSP.
- **Bit-perfect equivalence to Chrome/Web Audio has not yet been demonstrated**. Differences are possible from DSP implementation, timing, sample rate, clipping, Windows audio effects, and other APO configuration. Comparison against measured browser response is a future validation step.
- Python is only the **GUI/controller**: it cannot intercept arbitrary Windows audio itself. Equalizer APO must be installed and registered on the intended playback endpoint. ASIO and WASAPI exclusive streams can bypass this path.

## Run on Windows 10/11

Requires **Python 3.10+**. Equalizer APO must be enabled for your playback device in its Device Selector; it can be installed directly from this application's first-run prompt on **Windows x64**. A Windows restart may be required.

```powershell
py -m pip install -r requirements.txt
pyw main.pyw
```

Run `py main.pyw` instead if you want to see Python errors in a terminal.

### One-time Equalizer APO connection

1. Start `main.pyw`. If Equalizer APO is missing, the app offers to **download the official x64 v1.4.2 installer from SourceForge**. Only after you confirm, the downloader fetches the file in the background, verifies the **published SHA-256** (`7403be7427bbe1936a40dded082829b6e217fc4f5990fee5cba501f0ae055afa`) and invokes the vendor's **interactive** installer with Windows UAC. A failed download or hash mismatch never runs an installer. On non-x64 systems use the [official SourceForge files](https://sourceforge.net/projects/equalizerapo/files/) manually.
2. **In the vendor's Device Selector, select the actual playback device**, then complete installation and restart Windows if requested. The program cannot reliably perform this hardware choice for you. Relaunch `main.pyw` after installation/restart. If Equalizer APO is found but is not connected (or its managed file is not writable), the app **automatically requests UAC once** to perform setup. You can also click **«Подключить APO»** to retry. Alternatively, from PowerShell run `py setup_apo.py`.
3. Approve the **Windows UAC** prompt. The setup helper creates `EqualizerAPO/config/yandex-music-eq.txt`, appends a scoped `Device: all`, `Stage: post-mix`, `Channel: all` block with `Include: yandex-music-eq.txt` to `config.txt`, and grants **your Windows account Modify permission on the generated file only**. It backs up `config.txt` before the first modification and does not remove other filters. You should inspect any existing filters in Equalizer APO's Configuration Editor so they do not stack unexpectedly.
4. The GUI checks **two independent things**: our `Include` configuration and the Equalizer APO **post-mix registration on the current default playback endpoint** (using a read-only Windows registry check and Qt Multimedia's default device ID). If the Device Selector was cancelled, the status stays **«APO: выберите устройство»** rather than falsely reporting OK. The **«Настроить устройство»** button stays visible even after the include is connected; it opens the vendor's Device Selector for the user to tick the correct device and confirm OK. If the endpoint ID cannot be matched, the status is explicitly **«APO: устройство не проверено»**. Even **«APO: регистрация найдена»** is not confirmation of active sound processing: verify with the vendor's Device Selector test or by measuring/listening to output. The diagnostic textbox shows each transition and setup errors.
5. Toggle the EQ on, adjust bands, and verify the result with music or a test tone using a normal shared-mode Windows audio device. Changes are written automatically after a short pause; closing the GUI does not disable the last selected EQ state.

If the UI says **«конфигурация OK»** but sound still does not change, open **Equalizer APO Configurator**, select the actual Windows playback endpoint (e.g. your USB DAC, not another output), install the APO for that device, and restart Windows if prompted. Check that sound is using shared mode rather than ASIO/WASAPI Exclusive. A UAC prompt only grants permission to configure files; it cannot install the audio-processing endpoint in your place.

If your setup requires custom install paths or ACL restrictions block access, use Equalizer APO's Configuration Editor to manage the include manually. The GUI intentionally does **not** overwrite your whole `config.txt`.

### Where data lives

```text
project/
  main.pyw                 # minimal GUI
  equalizer.py             # validated settings + DSP coefficients / APO config generation
  apo.py                   # Equalizer APO integration
  setup_apo.py             # one-time elevated config setup with status reporting
  installer.py             # opt-in official download, pinned SHA-256 check, UAC launch
  presets.json             # built-in presets; tracked in Git
  settings.json            # auto-created local custom settings; not tracked
  requirements.txt
  tests/
```

The downloaded vendor installer (when requested) is cached in the Windows temporary directory and is never committed to Git. The automatic download pins official x64 version 1.4.2, not an unverified latest installer. The install wizard still requires user input and a system restart or audio service restart. If the first download returns HTML instead of an EXE, or the published checksum does not match, the app discards the untrusted file and retries through official SourceForge mirror hosts. Each candidate must pass the same pinned SHA-256 check; none can bypass verification. If all mirrors fail or block programmatic downloads, the diagnostic area shows the server and error for each attempt and links the official files page for manual installation.

The live **generated** filter file is in the Equalizer APO `config` directory, because its file watcher tracks files there. The original presets remain in the repository root.

## Tests

No hardware or PySide6 needed:

```powershell
py -m unittest discover -s tests -v
```

These cover preset validation, config generation, IIR biquad response at reference frequencies, fallback, settings persistence, and integration-status diagnostics. Windows GUI + APO live-output testing must be performed on a Windows machine.

## Reference

- Equalizer APO [configuration reference](https://sourceforge.net/p/equalizerapo/wiki/Configuration%20reference/) (IIR coefficients, `Include`, expression commands, `sampleRate`).
- User-supplied Yandex Music web JavaScript/HTML, version `4.1726.0` (used to transcribe numeric settings and UI behavior; proprietary source **not** committed).

## Safety / recovery

- Before trying, turn your listening volume down; positive gains can clip and sound louder than expected.
- To bypass this application's audio processing, **turn off the switch** in the GUI. If the GUI is unavailable, comment out `Include: yandex-music-eq.txt` in Equalizer APO's `config.txt`, or remove the managed text file using Administrator permissions.
- If installation interfered with other Equalizer APO settings, restore the timestamped `config.txt.before-yandex-eq-*.bak` file created by setup. The helper changes only one include line and creates the managed file.