from __future__ import annotations

import logging
import socket
from typing import Mapping

from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from app.logging import log_event

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_pctvbox._tcp.local."


class ServiceAdvertiser:
    def __init__(
        self,
        *,
        port: int,
        name: str = "PC TV Box",
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self._port = port
        self._name = name
        self._properties = dict(properties or {})
        self._zeroconf: AsyncZeroconf | None = None
        self._service_info: AsyncServiceInfo | None = None

    @property
    def is_running(self) -> bool:
        return self._zeroconf is not None

    async def start(self) -> None:
        if self._zeroconf is not None:
            return
        try:
            self._zeroconf = AsyncZeroconf(ip_version=IPVersion.V4Only)
            hostname = socket.gethostname()
            sanitized_hostname = "".join(c for c in hostname if c.isalnum() or c == "-") or "pc"
            instance_name = f"{self._name} ({sanitized_hostname}).{SERVICE_TYPE}"
            props = {
                "version": "1.0.0",
                "name": self._name,
                "https_port": str(self._port),
                "ws_path": "/ws/remote",
                "pair_path": "/api/pair",
                **self._properties,
            }
            props_bytes = {k: v.encode("utf-8") for k, v in props.items()}
            self._service_info = AsyncServiceInfo(
                type_=SERVICE_TYPE,
                name=instance_name,
                port=self._port,
                properties=props_bytes,
                server=f"{sanitized_hostname}.local.",
            )
            await self._zeroconf.async_register_service(self._service_info)
            log_event(
                logger, "mdns_advertiser_started", service_name=instance_name, port=self._port
            )
        except Exception as error:
            log_event(logger, "mdns_advertiser_failed", error=str(error))
            if self._zeroconf is not None:
                try:
                    await self._zeroconf.async_close()
                except Exception:
                    pass
                self._zeroconf = None
                self._service_info = None

    async def stop(self) -> None:
        if self._zeroconf is not None and self._service_info is not None:
            try:
                await self._zeroconf.async_unregister_service(self._service_info)
                await self._zeroconf.async_close()
                log_event(logger, "mdns_advertiser_stopped")
            except Exception as error:
                log_event(logger, "mdns_advertiser_stop_failed", error=str(error))
            finally:
                self._zeroconf = None
                self._service_info = None
