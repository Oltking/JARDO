"""Background awareness (spec §7.1): what's happening beyond the foreground.

psutil-based snapshots of processes, resource use, and network connections, so
JARVIS knows the machine's state. Read-only — pure perception, no control.
Source: docs/vendor/computer-use/psutil-api-docs.md
"""

from dataclasses import dataclass, field

import psutil


@dataclass
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float
    memory_mb: float


@dataclass
class SystemSnapshot:
    cpu_percent: float
    memory_percent: float
    top_processes: list[ProcessInfo]
    connection_count: int
    listening_ports: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_percent": round(self.memory_percent, 1),
            "top_processes": [
                {"pid": p.pid, "name": p.name, "cpu": round(p.cpu_percent, 1),
                 "mem_mb": round(p.memory_mb, 1)}
                for p in self.top_processes
            ],
            "connection_count": self.connection_count,
            "listening_ports": self.listening_ports,
        }


def snapshot(top_n: int = 5) -> SystemSnapshot:
    procs: list[ProcessInfo] = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
        try:
            info = proc.info
            mem = info.get("memory_info")
            procs.append(ProcessInfo(
                pid=info["pid"],
                name=info.get("name") or "?",
                cpu_percent=info.get("cpu_percent") or 0.0,
                memory_mb=(mem.rss / 1_048_576) if mem else 0.0,
            ))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda p: p.memory_mb, reverse=True)

    listening: list[int] = []
    conn_count = 0
    try:
        conns = psutil.net_connections(kind="inet")
        conn_count = len(conns)
        listening = sorted({
            c.laddr.port for c in conns
            if c.status == psutil.CONN_LISTEN and c.laddr
        })
    except (psutil.AccessDenied, PermissionError):
        # net_connections needs elevated rights on macOS; degrade gracefully.
        pass

    return SystemSnapshot(
        cpu_percent=psutil.cpu_percent(interval=None),
        memory_percent=psutil.virtual_memory().percent,
        top_processes=procs[:top_n],
        connection_count=conn_count,
        listening_ports=listening,
    )
