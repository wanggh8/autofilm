#! /usr/bin/env python3
# -*- coding:utf-8 -*-

import logging
import hmac
import hashlib
import base64
import asyncio
from aiohttp import ClientSession
from pathlib import Path
from typing import Optional

import yaml
from alist import AlistFileSystem, AlistPath


class AutoFilm:
    def __init__(
        self,
        config_path: str,
    ):

        self.base_dir: Path = Path(__file__).parent.absolute()
        config_path = Path(config_path)
        self.config_path: Path = (
            Path(config_path)
            if Path(config_path).is_absolute()
            else self.base_dir / config_path
        )

        self.config_data = {}

        self.video_ext = ("mp4", "mkv", "flv", "avi", "wmv", "ts", "rmvb", "webm")
        self.subtitle_ext = ("ass", "srt", "ssa", "sub")
        self.img_ext = ("png", "jpg")
        self.all_ext = (*self.video_ext, *self.subtitle_ext, *self.img_ext, "nfo")

        try:
            with self.config_path.open(mode="r", encoding="utf-8") as f:
                self.config_data = yaml.safe_load(f)
        except Exception as e:
            logging.critical(
                f"配置文件{config_path}加载失败，程序即将停止，错误信息：{str(e)}"
            )
        else:
            try:
                read_output_dir = Path(self.config_data["Settings"]["output_dir"])
                self.output_dir = (
                    read_output_dir
                    if read_output_dir.is_absolute()
                    else self.base_dir / read_output_dir
                )

                self.library_mode = self.config_data["Settings"]["library_mode"]
                if self.library_mode:
                    self.subtitle: bool = False
                    self.img: bool = False
                    self.nfo: bool = False
                else:
                    self.subtitle: bool = self.config_data["Settings"]["subtitle"]
                    self.img: bool = self.config_data["Settings"]["img"]
                    self.nfo: bool = self.config_data["Settings"]["nfo"]

            except Exception as e:
                logging.error(f"配置文件{self.config_path}读取错误，错误信息：{str(e)}")

            logging.info(f"输出目录：{self.output_dir}".center(50, "="))

    def run(self) -> None:
        try:
            alist_server_list = self.config_data["AlistServerList"]
        except Exception as e:
            logging.error(f"Alist服务器列表读取失败，错误信息：{str(e)}")
        else:
            logging.debug("Alist服务器加载成功")
            for alist_server in alist_server_list:
                try:
                    alist_server_url: str = alist_server["url"]
                    alist_server_username: str = alist_server["username"]
                    alist_server_password: str = alist_server["password"]
                    alist_server_base_path: Optional[str] = alist_server["base_path"]
                    alist_server_token: Optional[str] = alist_server.get("token")
                    if alist_server_url.endswith("/"):
                        alist_server_url = alist_server_url.rstrip("/")
                    if alist_server_base_path == None or alist_server_base_path == "":
                        alist_server_base_path = "/"
                    if not alist_server_base_path.startswith("/"):
                        alist_server_base_path = "/" + alist_server_base_path
                except Exception as e:
                    logging.error(
                        f"Alist服务器{alist_server}配置错误，请检查配置文件：{self.config_path}，错误信息：{str(e)}"
                    )
                else:
                    logging.debug(
                        f"Alist服务器URL：{alist_server_url}，用户名：{alist_server_username}，密码：{alist_server_password}，基本路径：{alist_server_base_path}，token：{alist_server_token}"
                    )
                    asyncio.run(
                        self._processer(
                            alist_server_url,
                            alist_server_username,
                            alist_server_password,
                            alist_server_base_path,
                            alist_server_token,
                        )
                    )

    async def _processer(
        self,
        alist_server_url: str,
        alist_server_username: str,
        alist_server_password: str,
        alist_server_base_path: str,
        alist_server_token: str,
    ) -> None:
        fs = AlistFileSystem.login(
            alist_server_url, alist_server_username, alist_server_password
        )
        fs.chdir(alist_server_base_path)
        async with ClientSession() as session:
            tasks = [
                asyncio.create_task(
                    self._file_process(
                        path, session, alist_server_base_path, alist_server_token
                    )
                )
                for path in fs.rglob("*.*")
            ]
            await asyncio.gather(*tasks)

    async def _file_process(
        self,
        alist_path_cls: AlistPath,
        session: ClientSession,
        base_path: Path,
        token: str,
    ) -> None:
        if not alist_path_cls.name.lower().endswith(self.all_ext):
            return

        file_output_path: Path = (
            self.output_dir / alist_path_cls.name
            if self.library_mode
            else self.output_dir / str(alist_path_cls).replace(base_path, "")
        )

        file_alist_abs_path: str = alist_path_cls.url[
            alist_path_cls.url.index("/d/") + 2 :
        ]

        file_download_url: str = alist_path_cls.url + self._sign(
            secret_key=token, data=file_alist_abs_path
        )

        logging.debug(
            f"正在处理:{alist_path_cls.name}，本地文件目录：{file_output_path}，文件远程路径：{file_alist_abs_path}，下载URL：{file_download_url}"
        )

        if alist_path_cls.name.lower().endswith(self.video_ext):
            file_output_path.parent.mkdir(parents=True, exist_ok=True)
            file_output_path = file_output_path.with_suffix(".strm")
            with file_output_path.open(mode="w", encoding="utf-8") as f:
                f.write(file_download_url)
                logging.debug(
                    f"{file_output_path.name}创建成功，文件本地目录：{file_output_path.parent}"
                )
        elif alist_path_cls.name.lower().endswith(self.img_ext) and self.img:
            file_output_path.parent.mkdir(parents=True, exist_ok=True)
            async with session.get(file_download_url) as resp:
                if resp.status == 200:
                    with file_output_path.open(mode="wb") as f:
                        f.write(await resp.read())
                    logging.debug(
                        f"{file_output_path.name}下载成功，文件本地目录：{file_output_path.parent}"
                    )
        elif alist_path_cls.name.lower().endswith(self.subtitle_ext) and self.subtitle:
            file_output_path.parent.mkdir(parents=True, exist_ok=True)
            async with session.get(file_download_url) as resp:
                if resp.status == 200:
                    with file_output_path.open(mode="wb") as f:
                        f.write(await resp.read())
                    logging.debug(
                        f"{file_output_path.name}下载成功，文件本地目录：{file_output_path.parent}"
                    )
        elif alist_path_cls.name.lower().endswith("nfo") and self.nfo:
            file_output_path.parent.mkdir(parents=True, exist_ok=True)
            async with session.get(file_download_url) as resp:
                if resp.status == 200:
                    with file_output_path.open(mode="wb") as f:
                        f.write(await resp.read())
                    logging.debug(
                        f"{file_output_path.name}下载成功，文件本地目录：{file_output_path.parent}"
                    )

    def _sign(self, secret_key: Optional[str], data: str) -> str:
        if secret_key == "" or secret_key == None:
            return ""
        h = hmac.new(secret_key.encode(), digestmod=hashlib.sha256)
        expire_time_stamp = str(0)
        h.update((data + ":" + expire_time_stamp).encode())
        return f"?sign={base64.urlsafe_b64encode(h.digest()).decode()}:0"
