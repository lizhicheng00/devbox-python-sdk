from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any

import httpx

from ._version import __version__
from .errors import ProtocolError, raise_for_response, transport_error

_IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}
QueryParams = Mapping[str, str | int | float | bool | None]


class SyncTransport:
    def __init__(
        self,
        base_url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        request_headers = {"User-Agent": f"devbox-python/{__version__}", **headers}
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=request_headers,
            timeout=timeout,
            transport=transport,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = self._send(method, path, json_body, params, headers)
        return _response_body(response)

    def request_with_headers(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[Any, httpx.Headers]:
        response = self._send(method, path, json_body, params, headers)
        return _response_body(response), response.headers

    def request_bytes(
        self,
        method: str,
        path: str,
        *,
        params: QueryParams | None = None,
    ) -> bytes:
        return self._send(method, path, None, params, None).content

    def iter_events(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
    ) -> Iterator[Mapping[str, Any]]:
        try:
            with self._client.stream(method, path, json=json_body) as response:
                if response.is_error:
                    response.read()
                    raise_for_response(response)
                for line in response.iter_lines():
                    if not line:
                        continue
                    yield _decode_event(line)
        except Exception as error:
            mapped = transport_error(error)
            if mapped is error:
                raise
            raise mapped from error

    def close(self) -> None:
        self._client.close()

    def _send(
        self,
        method: str,
        path: str,
        json_body: object | None,
        params: QueryParams | None,
        headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        attempts = 2 if method.upper() in _IDEMPOTENT_METHODS else 1
        for attempt in range(attempts):
            try:
                response = self._client.request(
                    method, path, json=json_body, params=params, headers=headers
                )
                if response.status_code >= 500 and attempt + 1 < attempts:
                    time.sleep(0.1)
                    continue
                if response.is_error:
                    raise_for_response(response)
                return response
            except Exception as error:
                if isinstance(error, httpx.TransportError) and attempt + 1 < attempts:
                    time.sleep(0.1)
                    continue
                mapped = transport_error(error)
                if mapped is error:
                    raise
                raise mapped from error
        raise AssertionError("request retry loop did not return")


class AsyncTransport:
    def __init__(
        self,
        base_url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        request_headers = {"User-Agent": f"devbox-python/{__version__}", **headers}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=request_headers,
            timeout=timeout,
            transport=transport,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = await self._send(method, path, json_body, params, headers)
        return _response_body(response)

    async def request_with_headers(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[Any, httpx.Headers]:
        response = await self._send(method, path, json_body, params, headers)
        return _response_body(response), response.headers

    async def request_bytes(
        self,
        method: str,
        path: str,
        *,
        params: QueryParams | None = None,
    ) -> bytes:
        return (await self._send(method, path, None, params, None)).content

    async def iter_events(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
    ) -> AsyncIterator[Mapping[str, Any]]:
        try:
            async with self._client.stream(method, path, json=json_body) as response:
                if response.is_error:
                    await response.aread()
                    raise_for_response(response)
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    yield _decode_event(line)
        except Exception as error:
            mapped = transport_error(error)
            if mapped is error:
                raise
            raise mapped from error

    async def close(self) -> None:
        await self._client.aclose()

    async def _send(
        self,
        method: str,
        path: str,
        json_body: object | None,
        params: QueryParams | None,
        headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        attempts = 2 if method.upper() in _IDEMPOTENT_METHODS else 1
        for attempt in range(attempts):
            try:
                response = await self._client.request(
                    method, path, json=json_body, params=params, headers=headers
                )
                if response.status_code >= 500 and attempt + 1 < attempts:
                    await asyncio.sleep(0.1)
                    continue
                if response.is_error:
                    raise_for_response(response)
                return response
            except Exception as error:
                if isinstance(error, httpx.TransportError) and attempt + 1 < attempts:
                    await asyncio.sleep(0.1)
                    continue
                mapped = transport_error(error)
                if mapped is error:
                    raise
                raise mapped from error
        raise AssertionError("request retry loop did not return")


def _decode_event(line: str) -> Mapping[str, Any]:
    if line.startswith("data:"):
        line = line[5:].strip()
    try:
        value = json.loads(line)
    except ValueError as error:
        raise ProtocolError("DevBox returned an invalid stream event") from error
    if not isinstance(value, Mapping):
        raise ProtocolError("DevBox returned an invalid stream event")
    return value


def _response_body(response: httpx.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as error:
        raise ProtocolError("DevBox returned invalid JSON") from error
