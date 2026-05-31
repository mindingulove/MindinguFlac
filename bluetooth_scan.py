from __future__ import annotations

import sys
import threading
import time

# --------------------------------------------------------------------------
# Stub for non-macOS
# --------------------------------------------------------------------------
if sys.platform not in ("darwin", "win32"):
    def start_scan() -> None: pass
    def stop_scan() -> None: pass
    def pair_device(address: str) -> str: return "Bluetooth not supported on this platform"
    def get_state() -> dict: return {"scanning": False, "devices": [], "error": ""}

elif sys.platform == "win32":
    import json as _json
    import subprocess as _sp

    _wlock = threading.Lock()
    _wstate: dict = {"scanning": False, "devices": {}, "error": ""}

    # PowerShell: paired BT audio devices from BTHENUM and AudioEndpoint class
    _PS_PAIRED = r"""
try {
    $out = [System.Collections.Generic.List[hashtable]]::new()
    # AudioEndpoint devices with Bluetooth instance IDs
    Get-PnpDevice -Class 'AudioEndpoint' -ErrorAction SilentlyContinue | Where-Object {
        $_.InstanceId -match 'BTHENUM|BTH' -and $_.FriendlyName
    } | ForEach-Object {
        $out.Add(@{ name=$_.FriendlyName; address=$_.InstanceId; paired=$true; connected=($_.Status -eq 'OK') })
    }
    # Fallback: check BTHENUM registry for A2DP/audio class GUIDs
    $audioGuids = @('{6BDD1FC6-810F-11D0-BEC7-08002BE2092F}','{4D36E96C-E325-11CE-BFC1-08002BE10318}')
    $btPath = 'HKLM:\SYSTEM\CurrentControlSet\Enum\BTHENUM'
    if (Test-Path $btPath) {
        Get-ChildItem $btPath -ErrorAction SilentlyContinue | Get-ChildItem -ErrorAction SilentlyContinue | ForEach-Object {
            $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if ($p -and $p.FriendlyName -and ($audioGuids -contains $p.ClassGuid)) {
                $out.Add(@{ name=$p.FriendlyName; address=$_.PSChildName; paired=$true; connected=$false })
            }
        }
    }
    $out | ConvertTo-Json -Compress -Depth 2
} catch { '[]' }
"""

    def _win_scan_thread() -> None:
        try:
            import asyncio
            from bleak import BleakScanner
            async def _scan():
                found = await BleakScanner.discover(timeout=12)
                with _wlock:
                    for d in found:
                        addr = d.address or ""
                        if addr:
                            _wstate["devices"][addr] = {
                                "name": d.name or addr,
                                "address": addr,
                                "paired": False,
                                "connected": False,
                            }
            asyncio.run(_scan())
        except Exception as e:
            with _wlock:
                _wstate["error"] = str(e)
        finally:
            with _wlock:
                _wstate["scanning"] = False

    def start_scan() -> None:
        with _wlock:
            if _wstate["scanning"]:
                return
            _wstate["scanning"] = True
            _wstate["error"] = ""
        threading.Thread(target=_win_scan_thread, daemon=True, name="bt-scan-win").start()

    def stop_scan() -> None:
        with _wlock:
            _wstate["scanning"] = False

    def pair_device(address: str) -> str:
        """On Windows, open Bluetooth settings for the user to complete pairing."""
        try:
            _sp.Popen(["explorer.exe", "ms-settings:bluetooth"])
            return ""
        except Exception as exc:
            return str(exc)

    def get_state() -> dict:
        known: dict[str, dict] = {}
        try:
            r = _sp.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_PAIRED],
                capture_output=True, text=True, timeout=8,
            )
            items = _json.loads(r.stdout.strip() or "[]")
            if isinstance(items, dict):
                items = [items]
            for item in (items or []):
                addr = item.get("address", "")
                if addr:
                    known[addr] = {
                        "name": item.get("name", addr),
                        "address": addr,
                        "paired": True,
                        "connected": bool(item.get("connected")),
                    }
        except Exception:
            pass
        with _wlock:
            for addr, dev in _wstate["devices"].items():
                if addr not in known:
                    known[addr] = dev
            return {
                "scanning": _wstate["scanning"],
                "devices": list(known.values()),
                "error": _wstate["error"],
            }
else:
    from Foundation import NSObject, NSRunLoop, NSDate, NSDefaultRunLoopMode
    from IOBluetooth import IOBluetoothDevice, IOBluetoothDeviceInquiry
    import subprocess as _sp

    _lock = threading.Lock()
    _state: dict = {"scanning": False, "devices": {}, "error": ""}
    _inquiry = None
    _scan_thread: threading.Thread | None = None
    _delegate_ref = None  # prevent GC

    def _set_error(message: str) -> None:
        with _lock:
            _state["error"] = message

    def _bluetooth_error_code(error) -> int:
        try:
            code = error.code() if hasattr(error, "code") else error
            return int(code or 0)
        except Exception:
            return 0

    def _bluetooth_error_message(error) -> str:
        try:
            if hasattr(error, "localizedDescription"):
                return str(error.localizedDescription() or "Scan error")
            return f"Scan error {int(error)}"
        except Exception:
            return "Scan error"

    class _ScanDelegate(NSObject):
        def deviceInquiryDeviceFound_device_(self, sender, device):
            try:
                addr = str(device.getAddressString() or "")
                name = str(device.getName() or device.getNameOrAddress() or addr)
                paired = bool(device.isBRPaired())
                if addr:
                    with _lock:
                        _state["devices"][addr] = {"name": name, "address": addr, "paired": paired}
            except Exception as exc:
                _set_error(f"Bluetooth scan callback failed: {exc}")
            return None

        def deviceInquiryComplete_error_aborted_(self, sender, error, aborted):
            try:
                code = _bluetooth_error_code(error)
                with _lock:
                    _state["scanning"] = False
                    if code:
                        _state["error"] = _bluetooth_error_message(error)
            except Exception as exc:
                _set_error(f"Bluetooth completion callback failed: {exc}")
            return None

        def deviceInquiryStarted_(self, sender):
            try:
                with _lock:
                    _state["scanning"] = True
                    _state["error"] = ""
            except Exception as exc:
                _set_error(f"Bluetooth start callback failed: {exc}")
            return None

    def _scan_loop() -> None:
        global _inquiry, _delegate_ref
        try:
            delegate = _delegate_ref
            _inquiry = IOBluetoothDeviceInquiry.inquiryWithDelegate_(delegate)
            _inquiry.setInquiryLength_(15)
            _inquiry.setUpdateNewDeviceNames_(True)
            result = _inquiry.start()
            if result and result != 0:
                with _lock:
                    _state["error"] = f"Could not start Bluetooth scan (error {result})"
                    _state["scanning"] = False
                return
            loop = NSRunLoop.currentRunLoop()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                loop.runMode_beforeDate_(
                    NSDefaultRunLoopMode,
                    NSDate.dateWithTimeIntervalSinceNow_(0.5),
                )
                with _lock:
                    if not _state["scanning"]:
                        break
            
            # Explicitly stop inquiry and clear delegate before thread exit
            if _inquiry:
                _inquiry.stop()
                _inquiry.setDelegate_(None)
                # Brief pump to handle any pending stop events
                loop.runMode_beforeDate_(NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.1))
                
        except Exception as exc:
            with _lock:
                _state["error"] = f"Bluetooth scan failed: {exc}"
        finally:
            with _lock:
                _state["scanning"] = False
            _inquiry = None
            _delegate_ref = None

    def start_scan() -> None:
        global _scan_thread, _delegate_ref
        with _lock:
            if _state["scanning"]:
                return
            _state["devices"] = {}
            _state["scanning"] = True
            _state["error"] = ""
        
        # Create delegate here to ensure it's alive for the thread
        _delegate_ref = _ScanDelegate.alloc().init()
        _scan_thread = threading.Thread(target=_scan_loop, daemon=True, name="bt-scan")
        _scan_thread.start()

    def stop_scan() -> None:
        # Just set the flag; the loop in _scan_loop will see it and clean up
        with _lock:
            _state["scanning"] = False

    def pair_device(address: str) -> str:
        """Connect or Pair a device. If paired, attempt direct connection. If not, open Settings."""
        try:
            device = IOBluetoothDevice.deviceWithAddressString_(address)
            if not device:
                # If we can't find it by address, it might be a new discovery.
                # Must open settings to pair.
                _open_bluetooth_settings()
                return ""

            is_paired = bool(device.isBRPaired())
            is_connected = bool(device.isConnected())

            if is_paired:
                if is_connected:
                    # Already connected, nothing to do but maybe ensure it's "Active"
                    # for audio, but that's complex.
                    return ""
                
                # Attempt direct connection for paired device
                result = device.openConnection()
                if result == 0: # kIOReturnSuccess
                    # Successfully connected! No need to open settings.
                    return ""
                
                # If connection failed, fallback to opening settings so user can manually fix
                _open_bluetooth_settings()
            else:
                # Not paired, must use System Settings to pair
                _open_bluetooth_settings()
            
            return ""
        except Exception as exc:
            return str(exc)

    def _open_bluetooth_settings() -> None:
        """Helper to open the Bluetooth settings pane using multiple fallbacks."""
        try:
            # macOS 13+ modern URL
            _sp.Popen(["open", "x-apple.systempreferences:com.apple.BluetoothSettings"])
        except Exception:
            try:
                # Older URL
                _sp.Popen(["open", "x-apple.systempreferences:com.apple.Bluetooth"])
            except Exception:
                try:
                    # Absolute path
                    _sp.Popen(["open", "/System/Library/PreferencePanes/Bluetooth.prefPane"])
                except Exception:
                    pass

    def _is_audio(device) -> bool:
        """Return True if device's Bluetooth class-of-device is Audio/Video (major class 4)."""
        try:
            major = (device.classOfDevice() >> 8) & 0x1F
            return major == 4
        except Exception:
            return False

    def get_state() -> dict:
        # Paired devices - audio class only
        known: dict[str, dict] = {}
        try:
            for d in (IOBluetoothDevice.pairedDevices() or []):
                if not _is_audio(d):
                    continue
                addr = d.getAddressString() or ""
                name = d.getName() or d.getNameOrAddress() or addr
                if addr:
                    known[addr] = {
                        "name": name,
                        "address": addr,
                        "paired": True,
                        "connected": bool(d.isConnected()),
                    }
        except Exception:
            pass

        with _lock:
            # Merge freshly scanned devices (filter audio class too)
            for addr, dev in _state["devices"].items():
                if addr not in known:
                    try:
                        d = IOBluetoothDevice.deviceWithAddressString_(addr)
                        if d and not _is_audio(d):
                            continue
                    except Exception:
                        pass
                    known[addr] = {**dev, "connected": False}

            return {
                "scanning": _state["scanning"],
                "devices": list(known.values()),
                "error": _state["error"],
            }
