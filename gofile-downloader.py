#! /usr/bin/env python3


from os import chdir, getcwd, getenv, listdir, mkdir, path, rmdir
from sys import exit, stdout, stderr
from typing import Any, TextIO
from requests import get, post
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from platform import system
from hashlib import sha256
from shutil import move
from time import perf_counter


NEW_LINE: str = "\n" if system() != "Windows" else "\r\n"


def _print(msg: str, error: bool = False) -> None:
    """
    Print a message.

    :param msg: a string to be printed.
    :param error: if the error stream output should be used instead of the standard output.
    :return:
    """

    output: TextIO = stderr if error else stdout
    output.write(msg)
    output.flush()


def die(msg: str) -> None:
    """
    Display a message of error and exit.

    :param msg: a string to be printed.
    :return:
    """

    _print(f"{msg}{NEW_LINE}", True)
    exit(-1)


# increase max_workers for parallel downloads
# defaults to 5 download at time
class Main:
    def __init__(self, url: str, password: str | None = None, max_workers: int = 5) -> None:
        root_dir: str | None = getenv("GF_DOWNLOADDIR")

        if root_dir and path.exists(root_dir):
            chdir(root_dir)

        self._lock: Lock = Lock()
        self._message: str = " "
        self._root_dir: str = root_dir if root_dir else getcwd()
        self._max_workers: int = max_workers
        token: str | None = getenv("GF_TOKEN")
        self._token: str = token if token else self._getToken()

        self._parseUrlOrFile(url, password)


    def _threadedDownloads(self, content_dir: str, files_link_list: list[dict[str, str]]) -> None:
        """
        _threadedDownloads

        Parallelize the downloads.

        "param content_dir": cotent directory.
        :param files_link_list: list of files in the format {"path": "", "filename": "", "link": ""}
        :return:
        """

        chdir(content_dir)

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            for item in files_link_list:
                executor.submit(self._downloadContent, item)

        chdir(self._root_dir)


    def _createDir(self, dirname: str) -> None:
        """
        _createDir

        creates a directory where the files will be saved if doesn't exist and change to it.

        :param dirname: name of the directory to be created.
        :return:
        """

        current_dir: str = getcwd()
        filepath: str = path.join(current_dir, dirname)

        try:
            mkdir(path.join(filepath))
        # if the directory already exist is safe to do nothing
        except FileExistsError:
            pass


    @staticmethod
    def _getToken() -> str:
        """
        _getToken

        Gets the access token of account created.

        :return: The access token of an account. Or exit if account creation fail.
        """

        user_agent: str | None = getenv("GF_USERAGENT")
        headers: dict[str, str] = {
            "User-Agent": user_agent if user_agent else "Mozilla/5.0",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": "*/*",
            "Connection": "keep-alive",
        }

        create_account_response: dict[Any, Any] = post("https://api.gofile.io/accounts", headers=headers).json()

        if create_account_response["status"] != "ok":
            die("Account creation failed!")

        return create_account_response["data"]["token"]


    def _downloadContent(self, file_info: dict[str, str], chunk_size: int = 16384) -> None:
        """
        _downloadContent

        Requests the contents of the file and writes it.

        :param file_info: a dictionary with information about a file to be downloaded.
        :param chunk_size: the number of bytes it should read into memory.
        :return:
        """

        filepath: str = path.join(file_info["path"], file_info["filename"])
        if path.exists(filepath):
            if path.getsize(filepath) > 0:
                _print(f"{filepath} already exist, skipping.{NEW_LINE}")

                return

        tmp_file: str =  f"{filepath}.part"
        url: str = file_info["link"]
        user_agent: str | None = getenv("GF_USERAGENT")

        headers: dict[str, str] = {
            "Cookie": f"accountToken={self._token}",
            "Accept-Encoding": "gzip, deflate, br",
            "User-Agent": user_agent if user_agent else "Mozilla/5.0",
            "Accept": "*/*",
            "Referer": f"{url}{("/" if not url.endswith("/") else "")}",
            "Origin": url,
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache"
        }

        # check for partial download and resume from last byte
        part_size: int = 0
        if path.isfile(tmp_file):
            part_size = int(path.getsize(tmp_file))
            headers["Range"] = f"bytes={part_size}-"

        has_size: str | None = None
        status_code: int | None = None

        try:
            with get(url, headers=headers, stream=True, timeout=(9, 27)) as response_handler:
                status_code = response_handler.status_code

                if ((response_handler.status_code in (403, 404, 405, 500)) or
                    (part_size == 0 and response_handler.status_code != 200) or
                    (part_size > 0 and response_handler.status_code != 206)):
                    _print(
                        f"Couldn't download the file from {url}."
                        f"{NEW_LINE}"
                        f"Status code: {status_code}"
                        f"{NEW_LINE}"
                    )

                    return

                content_lenth: str | None = response_handler.headers.get('Content-Length')
                has_size = content_lenth if part_size == 0 \
                    else content_lenth.split("/")[-1] if content_lenth else None

                if not has_size:
                    _print(
                        f"Couldn't find the file size from {url}."
                        f"{NEW_LINE}"
                        f"Status code: {status_code}"
                        f"{NEW_LINE}"
                    )

                    return

                with open(tmp_file, 'ab') as handler:
                    total_size: float = float(has_size)

                    start_time: float = perf_counter()
                    for i, chunk in enumerate(response_handler.iter_content(chunk_size=chunk_size)):
                        progress: float = (part_size + (i * len(chunk))) / total_size * 100

                        handler.write(chunk)

                        rate: float = (i * len(chunk)) / (perf_counter()-start_time)
                        unit: str = "B/s"
                        if rate < (1024):
                            unit = "B/s"
                        elif rate < (1024*1024):
                            rate /= 1024
                            unit = "KB/s"
                        elif rate < (1024*1024*1024):
                            rate /= (1024 * 1024)
                            unit = "MB/s"
                        elif rate < (1024*1024*1024*1024):
                            rate /= (1024 * 1024 * 1024)
                            unit = "GB/s"

                        # thread safe update the self._message, so no output interleaves
                        with self._lock:
                            _print(f"\r{" " * len(self._message)}")

                            self._message = f"\rDownloading {file_info['filename']}: {part_size + i * len(chunk)}" \
                            f" of {has_size} {round(progress, 1)}% {round(rate, 1)}{unit}"

                            _print(self._message)
        finally:
            with self._lock:
                if has_size and path.getsize(tmp_file) == int(has_size):
                    _print(f"\r{" " * len(self._message)}")
                    _print(f"\rDownloading {file_info['filename']}: "
                        f"{path.getsize(tmp_file)} of {has_size} Done!"
                        f"{NEW_LINE}"
                    )
                    move(tmp_file, filepath)


    def _parseLinks(
        self,
        _id: str,
        files_link_list: list[dict[str, str]],
        password: str | None = None
    ) -> None:
        """
        _parseLinks

        Parses for possible links recursively and populate a list with file's info.

        :param _id: url to the content.
        :param files_link_list: list of files that will be populated in the format {"path": "", "filename": "", "link": ""}
        :param password: content's password.
        :return:
        """

        url: str = f"https://api.gofile.io/contents/{_id}?wt=4fd6sg89d7s6&cache=true"

        if password:
            url = f"{url}&password={password}"

        user_agent: str | None = getenv("GF_USERAGENT")

        headers: dict[str, str] = {
            "User-Agent": user_agent if user_agent else "Mozilla/5.0",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Authorization": f"Bearer {self._token}",
        }

        response: dict[Any, Any] = get(url, headers=headers).json()

        if response["status"] != "ok":
            _print(f"Failed to get a link as response from the {url}.{NEW_LINE}")
            return

        data: dict[Any, Any] = response["data"]

        if "password" in data and "passwordStatus" in data and data["passwordStatus"] != "passwordOk":
            _print(f"Password protected link. Please provide the password.{NEW_LINE}")
            return

        if data["type"] == "folder":
            self._createDir(data["name"])
            chdir(data["name"])

            for child_id in data["children"]:
                child: dict[Any, Any] = data["children"][child_id]

                if child["type"] == "folder":
                    self._parseLinks(child["id"],files_link_list, password)
                else:
                    files_link_list.append(
                        {
                            "path": getcwd(),
                            "filename": child["name"],
                            "link": child["link"]
                        }
                    )

            chdir(path.pardir)
        else:
            files_link_list.append(
                {
                    "path": getcwd(),
                    "filename": data["name"],
                    "link": data["link"]
                }
            )


    def _download(self, url: str, password: str | None = None) -> None:
        """
        _download

        Requests to start downloading files.

        :param url: url of the content.
        :param password: content's password.
        :return:
        """

        try:
            if not url.split("/")[-2] == "d":
                _print(f"The url probably doesn't have an id in it: {url}.{NEW_LINE}")
                return

            content_id: str = url.split("/")[-1]
        except IndexError:
            _print(f"{url} doesn't seem a valid url.{NEW_LINE}")
            return

        content_dir: str = path.join(self._root_dir, content_id)
        _password: str | None = sha256(password.encode()).hexdigest() if password else password
        files_link_list: list[dict[str, str]] = []

        self._createDir(content_dir)
        chdir(content_id)
        self._parseLinks(content_id, files_link_list, _password)

        # removes the root content directory if there's no file or subdirectory
        if not listdir(content_dir) and not files_link_list:
            rmdir(content_dir)
            return

        self._threadedDownloads(content_dir, files_link_list)


    def _parseUrlOrFile(self, url_or_file: str, _password: str | None = None) -> None:
        """
        _parseUrlOrFile

        Parses a file or a url for possible links.

        :param url_or_file: a filename with urls to be downloaded or a single url.
        :param password: password to be used across all links, if not provided a per link password may be used.
        :return:
        """

        if not (path.exists(url_or_file) and path.isfile(url_or_file)):
            self._download(url_or_file, _password)
            return

        with open(url_or_file, "r") as f:
            lines: list[str] = f.readlines()

        for line in lines:
            line_splitted: list[str] = line.split(" ")
            url: str = line_splitted[0].strip()
            password: str | None = _password if _password else line_splitted[1].strip() \
                if len(line_splitted) > 1 else _password

            self._download(url, password)


if __name__ == '__main__':
    try:
        from sys import argv

        url: str | None = None
        password: str | None = None
        argc: int = len(argv)

        if argc > 1:
            url = argv[1]

            if argc > 2:
                password = argv[2]

            # Run
            _print(f"Starting, please wait...{NEW_LINE}")
            Main(url=url, password=password)
        else:
            die(f"Usage:"
                f"{NEW_LINE}"
                f"python gofile-downloader.py https://gofile.io/d/contentid"
                f"{NEW_LINE}"
                f"python gofile-downloader.py https://gofile.io/d/contentid password"
            )
    except KeyboardInterrupt:
        exit(1)

