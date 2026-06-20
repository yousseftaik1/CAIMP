"""
Metric collectors using psutil.

Each register_*() function creates observable instruments on the given Meter.
Callbacks are invoked every collection_interval by the SDK reader.
"""

from __future__ import annotations

import logging
from typing import Iterable

import psutil
from opentelemetry.metrics import CallbackOptions, Meter, Observation

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------


def register_cpu_metrics(meter: Meter) -> None:
    # Trigger first sample so subsequent calls return non-zero values
    psutil.cpu_percent(percpu=True)

    def _cpu_utilization(options: CallbackOptions) -> Iterable[Observation]:
        for i, pct in enumerate(psutil.cpu_percent(interval=None, percpu=True)):
            yield Observation(pct / 100.0, {"cpu": str(i)})

    def _cpu_times(options: CallbackOptions) -> Iterable[Observation]:
        times = psutil.cpu_times()
        for state in ("user", "system", "idle", "iowait"):
            val = getattr(times, state, None)
            if val is not None:
                yield Observation(val, {"state": state})

    def _load_average(options: CallbackOptions) -> Iterable[Observation]:
        try:
            l1, l5, l15 = psutil.getloadavg()
            yield Observation(l1, {"period": "1m"})
            yield Observation(l5, {"period": "5m"})
            yield Observation(l15, {"period": "15m"})
        except (AttributeError, OSError):
            pass  # Windows does not support load average

    meter.create_observable_gauge(
        "system.cpu.utilization",
        callbacks=[_cpu_utilization],
        unit="1",
        description="CPU utilization per core (0–1)",
    )
    meter.create_observable_counter(
        "system.cpu.time",
        callbacks=[_cpu_times],
        unit="s",
        description="CPU time by state",
    )
    meter.create_observable_gauge(
        "system.cpu.load_average",
        callbacks=[_load_average],
        unit="1",
        description="System load average (1m/5m/15m)",
    )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def register_memory_metrics(meter: Meter) -> None:
    def _mem_usage(options: CallbackOptions) -> Iterable[Observation]:
        mem = psutil.virtual_memory()
        yield Observation(mem.total, {"state": "total"})
        yield Observation(mem.used, {"state": "used"})
        yield Observation(mem.available, {"state": "available"})
        yield Observation(
            mem.cached if hasattr(mem, "cached") else 0, {"state": "cached"}
        )

    def _mem_utilization(options: CallbackOptions) -> Iterable[Observation]:
        yield Observation(psutil.virtual_memory().percent / 100.0)

    def _swap_usage(options: CallbackOptions) -> Iterable[Observation]:
        swap = psutil.swap_memory()
        yield Observation(swap.total, {"state": "total"})
        yield Observation(swap.used, {"state": "used"})
        yield Observation(swap.free, {"state": "free"})

    meter.create_observable_gauge(
        "system.memory.usage",
        callbacks=[_mem_usage],
        unit="By",
        description="Physical memory by state",
    )
    meter.create_observable_gauge(
        "system.memory.utilization",
        callbacks=[_mem_utilization],
        unit="1",
        description="Memory utilization (0–1)",
    )
    meter.create_observable_gauge(
        "system.memory.swap.usage",
        callbacks=[_swap_usage],
        unit="By",
        description="Swap memory by state",
    )


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------


def register_disk_metrics(meter: Meter) -> None:
    _SKIP_FS = frozenset(("tmpfs", "devtmpfs", "devfs", "squashfs", "overlay"))

    def _disk_usage(options: CallbackOptions) -> Iterable[Observation]:
        for part in psutil.disk_partitions(all=False):
            if part.fstype in _SKIP_FS:
                continue
            try:
                u = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            attrs = {"mountpoint": part.mountpoint, "device": part.device}
            yield Observation(u.total, {**attrs, "state": "total"})
            yield Observation(u.used, {**attrs, "state": "used"})
            yield Observation(u.free, {**attrs, "state": "free"})

    def _disk_utilization(options: CallbackOptions) -> Iterable[Observation]:
        for part in psutil.disk_partitions(all=False):
            if part.fstype in _SKIP_FS:
                continue
            try:
                u = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            yield Observation(u.percent / 100.0, {"mountpoint": part.mountpoint})

    def _disk_io(options: CallbackOptions) -> Iterable[Observation]:
        try:
            counters = psutil.disk_io_counters(perdisk=True)
        except Exception:
            return
        for disk, c in (counters or {}).items():
            attrs = {"device": disk}
            yield Observation(c.read_bytes, {**attrs, "direction": "read"})
            yield Observation(c.write_bytes, {**attrs, "direction": "write"})

    meter.create_observable_gauge(
        "system.filesystem.usage",
        callbacks=[_disk_usage],
        unit="By",
        description="Disk usage per mount point",
    )
    meter.create_observable_gauge(
        "system.filesystem.utilization",
        callbacks=[_disk_utilization],
        unit="1",
        description="Disk utilization per mount point (0–1)",
    )
    meter.create_observable_counter(
        "system.disk.io",
        callbacks=[_disk_io],
        unit="By",
        description="Disk I/O bytes per device",
    )


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def register_network_metrics(meter: Meter) -> None:
    _SKIP_IFACES = frozenset(("lo", "loopback"))

    def _net_io(options: CallbackOptions) -> Iterable[Observation]:
        try:
            counters = psutil.net_io_counters(pernic=True)
        except Exception:
            return
        for iface, c in (counters or {}).items():
            if iface.lower() in _SKIP_IFACES:
                continue
            attrs = {"interface": iface}
            yield Observation(c.bytes_sent, {**attrs, "direction": "transmit"})
            yield Observation(c.bytes_recv, {**attrs, "direction": "receive"})
            yield Observation(
                c.packets_sent, {**attrs, "direction": "transmit", "type": "packets"}
            )
            yield Observation(
                c.packets_recv, {**attrs, "direction": "receive", "type": "packets"}
            )
            yield Observation(
                c.errout, {**attrs, "direction": "transmit", "type": "errors"}
            )
            yield Observation(
                c.errin, {**attrs, "direction": "receive", "type": "errors"}
            )
            yield Observation(
                c.dropout, {**attrs, "direction": "transmit", "type": "dropped"}
            )
            yield Observation(
                c.dropin, {**attrs, "direction": "receive", "type": "dropped"}
            )

    meter.create_observable_counter(
        "system.network.io",
        callbacks=[_net_io],
        unit="By",
        description="Network I/O bytes/packets/errors per interface",
    )


# ---------------------------------------------------------------------------
# System / process
# ---------------------------------------------------------------------------


def register_system_metrics(meter: Meter) -> None:
    def _open_fds(options: CallbackOptions) -> Iterable[Observation]:
        try:
            yield Observation(psutil.Process().num_fds())
        except (AttributeError, psutil.AccessDenied, psutil.NoSuchProcess):
            pass

    def _process_count(options: CallbackOptions) -> Iterable[Observation]:
        yield Observation(len(psutil.pids()))

    def _boot_time(options: CallbackOptions) -> Iterable[Observation]:
        yield Observation(psutil.boot_time())

    meter.create_observable_gauge(
        "process.open_file_descriptors",
        callbacks=[_open_fds],
        unit="{fd}",
        description="Number of open file descriptors by the agent process",
    )
    meter.create_observable_gauge(
        "system.process.count",
        callbacks=[_process_count],
        unit="{process}",
        description="Total number of running processes",
    )
    meter.create_observable_gauge(
        "system.uptime",
        callbacks=[_boot_time],
        unit="s",
        description="System boot time (Unix epoch)",
    )


# ---------------------------------------------------------------------------
# Register all
# ---------------------------------------------------------------------------


def register_all(meter: Meter) -> None:
    register_cpu_metrics(meter)
    register_memory_metrics(meter)
    register_disk_metrics(meter)
    register_network_metrics(meter)
    register_system_metrics(meter)
    log.info("All metric collectors registered")
