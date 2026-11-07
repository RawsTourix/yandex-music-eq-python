# Yandex Music EQ Python

**Independent Windows system-wide 10-band equalizer**, controlled by a small Python/PySide6 GUI and backed by [Equalizer APO](https://sourceforge.net/projects/equalizerapo/). Recreates the Yandex Music web equalizer's band layout, presets and *modeled* Web Audio biquad filter behavior.

> Unofficial project; not affiliated with, endorsed by, or distributed by Yandex. It does not include Yandex frontend source code or bundled audio tracks.

## Scope and limitations

- Ten filters in series: **60 Hz low shelf**, **170, 310, 600, 1000, 3000, 6000, 12000, 14000 Hz peaking**, **16000 Hz high shelf**.
- Q = 1 for peaking filters. Web Audio ignores Q for shelf filters (implemented with shelf slope S = 1).
- Individual gains **-12 to +12 dB**, **0.1 dB** steps. Separate *linear* preamp **0.5 to 1.5**, **0.1** steps. The per-control intensity multipliers change processing, not the displayed slider ranges.
- **19 presets** extracted as numerical settings from user-provided Yandex Music JS, stored in [`presets.json`](presets.json) beside the Python code. Custom values and app state are stored locally in `settings.json` (ignored by Git).
- Uses Equalizer APO `IIR Order 2` filters with RBJ/Web Audio-style coefficient formulas for **44.1, 48, 88.2, 96, 176.4 and 192 kHz**. For other sample rates, falls back to its built-in LS/PK/HS filters, which may differ from browser DSP.
- **Bit-perfect equivalence to Chrome/Web Audio has not yet been demonstrated**. Differences are possible from DSP implementation, timing, sample rate, clipping, Windows audio effects, and other APO configuration. Comparison against measured browser response is a future validation step.
- Python is only the **GUI/controller**: it cannot intercept arbitrary Windows audio itself. Equalizer APO must be installed and registered on the intended playback endpoint. ASIO and WASAPI exclusive streams can bypass this path.


## Independent intensity multipliers (experimental)

Instead of a single global multiplier, the GUI has **11 separate compact controls directly below the sliders**: one under the linear preamp ("уровень") and one under each of the ten frequency bands. Click any small `×1` button to open its menu. To fit the narrow band columns, quarter and half are displayed as **`×¼` and `×½`**, with numeric values `×0.25` and `×0.5` in the menu. Each control offers `×0.25`, `×0.5`, `×1`, `×2`, `×4`.

- **Preamp multiplier:** the original linear `preampLinear` is raised to `preampIntensity`. Thus a preamp of 0.5 at ×2 becomes 0.25; a preamp of 1.5 at ×4 becomes 5.0625. This is independent of all band controls.
- **Individual band multiplier ×2/×4:** serially repeats **only that band's original biquad** two or four times, using the same coefficients per copy; it is not substituted by one biquad with doubled/quadrupled gain. With equal multipliers on every band, this is mathematically equivalent to repeated complete linear EQ chains (ignoring possible finite-precision differences).
- **Individual band multiplier ×0.5/×0.25:** approximates a weaker filter by scaling that band's gain in dB while keeping Q and the filter type. It is *not* an exact fractional complex transfer-function power, and can differ in frequency response and phase.
- **Presets stay untouched.** Intensity controls do not modify slider positions and do not switch the preset to Custom. Switching presets preserves all 11 intensity settings.
- **Local storage:** `settings.json` stores `preampIntensity` and a ten-element `bandIntensities` array. Existing v0.1.0 settings default to ×1 everywhere. A previous experimental `settings.json` with the old single `intensity` key migrates that value to all 11 controls on load; the next save uses only the new keys.

**Safety:** ×4 on a +12 dB band can produce a +48 dB rise near its center, potentially much higher when several boosted bands overlap. Multiple independent boosts may clip severely. Lower your playback volume first. The application does not silently add a limiter or change gain to compensate.

Even two separate browser/system EQs are equivalent to the modeled cascade only if their actual DSP implementations and sample-rate conditions agree; that equivalence has not yet been measured.

## Save, reuse, and share your own EQ presets

Create your own named presets directly in the GUI without modifying the built-in Yandex Music `presets.json`. The selector includes your entries marked with **★**.

1. Configure the preamp, all ten bands, and their **eleven individual intensity multipliers**. These values are automatically retained in the current local `settings.json` even before you name the preset.
2. Open the **⋯** menu beside the preset selector and choose **«Сохранить пресет»** (or press **Ctrl+S**). Give your preset a name such as **Super Bass**. The complete configuration is saved in **`user_presets.json`** in the project directory. Select it later from the main dropdown to restore the exact original slider positions and multipliers.
3. For an existing user preset, edit any slider or intensity. The selected preset name gains a **`*`** until you explicitly save changes using **⋯ → «Сохранить изменения»** or **Ctrl+S**. Switching presets with unsaved edits asks whether to save, discard, or cancel.
4. The **⋯** menu contains **Save**, **Save As**, **Rename**, **Delete**, **Export**, **Import**, **Undo**, and **Redo** actions. Built-in presets cannot be renamed or deleted. The separate Save button has been removed so the preset dropdown keeps its width.
5. Export the current configuration as a portable **`.yeq.json`** file, and import such a file on another installation. Import never silently overwrites existing profiles and does not change the currently playing sound; select the newly imported preset in the dropdown to apply it.

## Keyboard shortcuts and audio history

The program keeps a bounded history of the last **100 sound edits**. **Ctrl+Z** undoes a change; **Ctrl+Y** or **Ctrl+Shift+Z** redoes it. Both actions are also available in the **⋯** menu, with disabled states when unavailable.

- Undo/redo covers changes to the preamp slider, each of the ten EQ sliders, all eleven intensity multipliers, the selected preset, and the EQ on/off switch. It restores the Custom preset state and updates Equalizer APO's generated config.
- One continuous mouse drag is **one undo action**, instead of a separate action for every intermediate value. Mouse wheel adjustments are individual steps.
- After undoing, editing another value clears the redo branch. Undo history lives in memory for the current app session, not in the `settings.json` file.
- **Ctrl+S** saves the selected user preset's changes, or opens Save As for a built-in/Custom preset. **Ctrl+Shift+S** always opens Save As. **Ctrl+E** exports the current settings to `.yeq.json`; **Ctrl+O** imports a file.
- Undo/redo handles **live audio edits**, not file operations: exporting, importing, renaming, or saving a user preset is not reverted by Ctrl+Z. Deleting a named preset clears history to avoid resurrecting deleted profile IDs.

User presets save the linear preamp, ten gains in dB, one preamp multiplier, and ten band multipliers. The EQ on/off switch is intentionally *not* part of a preset and retains its current global state. The local user-preset collection and exported `.yeq.json` files are ignored by Git; **back up or copy your exported preset files to preserve them across computers or reinstallations**. An older `settings.json` remains valid, and if a selected user profile is deleted outside the app, the live audio settings are retained as Custom.

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
  settings.json            # auto-created current sound (includes last settings)
  user_presets.json        # local named user presets; not tracked
  *.yeq.json               # portable exported preset files; not tracked
  requirements.txt
  tests/
```

The downloaded vendor installer (when requested) is cached in the Windows temporary directory and is never committed to Git. The automatic download pins official x64 version 1.4.2, not an unverified latest installer. The install wizard still requires user input and a system restart or audio service restart. If the first download returns HTML instead of an EXE, or the published checksum does not match, the app discards the untrusted file and retries through official SourceForge mirror hosts. Each candidate must pass the same pinned SHA-256 check; none can bypass verification. If all mirrors fail or block programmatic downloads, the diagnostic area shows the server and error for each attempt and links the official files page for manual installation.

The live **generated** filter file is in the Equalizer APO `config` directory, because its file watcher tracks files there. The built-in presets remain in the repository root; your named presets live in user_presets.json.

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