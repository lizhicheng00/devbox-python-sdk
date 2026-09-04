from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any

import httpx

from ._tls import service_ssl_context
from ._version import __version__
from .errors import ProtocolError, raise_connect_error, raise_for_response, transport_error

_CONNECT_RETRY_DELAYS = (0.1, 0.2)
_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)
_CONNECT_HEADERS = {
    "Connect-Protocol-Version": "1",
    "Content-Type": "application/connect+json",
}
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
            verify=service_ssl_context(),
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
        return _response_body(
            self._send(method, path, json_body=json_body, params=params, headers=headers)
        )

    def request_content(
        self,
        method: str,
        path: str,
        content: bytes,
        *,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return _response_body(
            self._send(method, path, content=content, params=params, headers=headers)
        )

    def request_with_headers(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[Any, httpx.Headers]:
        response = self._send(method, path, json_body=json_body, params=params, headers=headers)
        return _response_body(response), response.headers

    def request_bytes(
        self,
        method: str,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return self._send(method, path, params=params, headers=headers).content

    def connect_unary(
        self,
        path: str,
        json_body: object,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        request_headers = {
            "Connect-Protocol-Version": "1",
            "Content-Type": "application/json",
            **dict(headers or {}),
        }
        return _response_body(
            self._send("POST", path, json_body=json_body, headers=request_headers)
        )

    def connect_stream(
        self,
        path: str,
        json_body: object,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[Mapping[str, Any]]:
        request_headers = _connect_headers(timeout, headers)
        try:
            with self._client.stream(
                "POST",
                path,
                content=_connect_frame(json_body),
                headers=request_headers,
                timeout=_stream_timeout(timeout),
            ) as response:
                _reject_redirect(response)
                if response.is_error:
                    response.read()
                    raise_for_response(response)
                _validate_connect_response(response)
                decoder = _ConnectDecoder()
                for chunk in response.iter_bytes():
                    yield from decoder.feed(chunk)
                decoder.finish()
        except Exception as error:
            mapped = transport_error(error)
            if mapped is error:
                raise
            raise mapped from error

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SyncTransport:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        content: bytes | None = None,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        for attempt in range(len(_CONNECT_RETRY_DELAYS) + 1):
            try:
                response = self._client.request(
                    method,
                    path,
                    json=json_body,
                    content=content,
                    params=params,
                    headers=headers,
                )
                _reject_redirect(response)
                if response.is_error:
                    raise_for_response(response)
                return response
            except Exception as error:
                if isinstance(error, _CONNECT_ERRORS) and attempt < len(_CONNECT_RETRY_DELAYS):
                    time.sleep(_CONNECT_RETRY_DELAYS[attempt])
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
            verify=service_ssl_context(),
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
        return _response_body(
            await self._send(method, path, json_body=json_body, params=params, headers=headers)
        )

    async def request_content(
        self,
        method: str,
        path: str,
        content: bytes,
        *,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return _response_body(
            await self._send(method, path, content=content, params=params, headers=headers)
        )

    async def request_with_headers(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[Any, httpx.Headers]:
        response = await self._send(
            method, path, json_body=json_body, params=params, headers=headers
        )
        return _response_body(response), response.headers

    async def request_bytes(
        self,
        method: str,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return (await self._send(method, path, params=params, headers=headers)).content

    async def connect_unary(
        self,
        path: str,
        json_body: object,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        request_headers = {
            "Connect-Protocol-Version": "1",
            "Content-Type": "application/json",
            **dict(headers or {}),
        }
        return _response_body(
            await self._send("POST", path, json_body=json_body, headers=request_headers)
        )

    async def connect_stream(
        self,
        path: str,
        json_body: object,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[Mapping[str, Any]]:
        request_headers = _connect_headers(timeout, headers)
        try:
            async with self._client.stream(
                "POST",
                path,
                content=_connect_frame(json_body),
                headers=request_headers,
                timeout=_stream_timeout(timeout),
            ) as response:
                _reject_redirect(response)
                if response.is_error:
                    await response.aread()
                    raise_for_response(response)
                _validate_connect_response(response)
                decoder = _ConnectDecoder()
                async for chunk in response.aiter_bytes():
                    for event in decoder.feed(chunk):
                        yield event
                decoder.finish()
        except Exception as error:
            mapped = transport_error(error)
            if mapped is error:
                raise
            raise mapped from error

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncTransport:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        content: bytes | None = None,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        for attempt in range(len(_CONNECT_RETRY_DELAYS) + 1):
            try:
                response = await self._client.request(
                    method,
                    path,
                    json=json_body,
                    content=content,
                    params=params,
                    headers=headers,
                )
                _reject_redirect(response)
                if response.is_error:
                    raise_for_response(response)
                return response
            except Exception as error:
                if isinstance(error, _CONNECT_ERRORS) and attempt < len(_CONNECT_RETRY_DELAYS):
                    await asyncio.sleep(_CONNECT_RETRY_DELAYS[attempt])
                    continue
                mapped = transport_error(error)
                if mapped is error:
                    raise
                raise mapped from error
        raise AssertionError("request retry loop did not return")


def _reject_redirect(response: httpx.Response) -> None:
    if response.is_redirect:
        raise ProtocolError("DevBox service returned an unexpected redirect")


class _ConnectDecoder:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._ended = False

    def feed(self, chunk: bytes) -> Iterator[Mapping[str, Any]]:
        if self._ended and chunk:
            raise ProtocolError("EnvD sent data after the Connect stream ended")
        self._buffer.extend(chunk)
        while len(self._buffer) >= 5:
            flags = self._buffer[0]
            size = int.from_bytes(self._buffer[1:5], "big")
            if len(self._buffer) < size + 5:
                return
            data = bytes(self._buffer[5 : size + 5])
            del self._buffer[: size + 5]
            if flags & 1:
                raise ProtocolError("compressed Connect messages are not supported")
            payload = _decode_mapping(data)
            if flags & 2:
                self._ended = True
                error = payload.get("error")
                if isinstance(error, Mapping):
                    raise_connect_error(error)
                if self._buffer:
                    raise ProtocolError("EnvD sent data after the Connect stream ended")
                return
            yield payload

    def finish(self) -> None:
        if self._buffer:
            raise ProtocolError("EnvD returned a truncated Connect stream")
        if not self._ended:
            raise ProtocolError("EnvD closed the Connect stream without a trailer")


def _connect_headers(timeout: float | None, headers: Mapping[str, str] | None) -> dict[str, str]:
    result = {**_CONNECT_HEADERS, **dict(headers or {})}
    normalized_timeout = _stream_timeout(timeout)
    if normalized_timeout:
        result["Connect-Timeout-Ms"] = str(max(1, round(normalized_timeout * 1000)))
    return result


def _connect_frame(value: object) -> bytes:
    data = json.dumps(value, separators=(",", ":")).encode()
    return bytes([0]) + len(data).to_bytes(4, "big") + data


def _stream_timeout(value: float | None) -> float | None:
    if value is not None and value < 0:
        raise ValueError("timeout must be non-negative or None")
    return value if value and value > 0 else None


def _validate_connect_response(response: httpx.Response) -> None:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    if content_type != "application/connect+json":
        raise ProtocolError("EnvD returned an invalid Connect content type")


def _decode_mapping(data: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(data)
    except ValueError as error:
        raise ProtocolError("EnvD returned invalid Connect JSON") from error
    if not isinstance(value, Mapping):
        raise ProtocolError("EnvD returned an invalid Connect message")
    return value


def _response_body(response: httpx.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as error:
        raise ProtocolError("DevBox returned invalid JSON") from error
