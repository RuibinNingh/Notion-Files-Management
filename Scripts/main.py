from download import Download
from notion import Notion
from upload import Upload


class Main:
    def __init__(self, notion_token: str, max_workers: int = 3):
        self.notion = Notion(notion_token)
        self.downloader = Download(max_workers=max_workers)
        self._probe_id = None
        self.download_list = []
        self.Uploader = None  # type: Upload | None
        self._probe_size_map = {}
    # -------------------------
    # Download
    # -------------------------
    def get_download_list(self, page_id: str):
        """
        发起：拉取 Notion 页面文件列表 + 异步探测 size
        返回：Success + probe_id（前端后续用 probe_id 轮询进度）
        """
        page_data = self.notion.query_page(page_id, True)
        self.download_list = self.notion.get_download_url(page_data)

        urls = [f["url"] for f in self.download_list if f.get("url")]
        if urls:
            self._probe_id = self.downloader.start_probe_sizes(urls, timeout=10, max_retries=3)
            return {
                "status": "success",
                "msg": "下载列表已获取，正在探测文件大小",
                "probe_id": self._probe_id,
                "total": len(urls),
            }
        else:
            self._probe_id = None
            return {
                "status": "success",
                "msg": "下载列表为空",
                "probe_id": None,
                "total": 0,
            }
    def download_list_processing(self, probe_id: str | None = None):
        """
        返回：
        {
        "status": ...,
        "percent": ...,
        "done": ...,
        "total": ...,
        "error": ...,
        }
        同时回写 self.download_list 的 size_mb
        """
        pid = probe_id or self._probe_id
        if not pid:
            return {
                "status": "not_started",
                "percent": 0.0,
                "done": 0,
                "total": 0,
                "error": None,
            }

        progress = self.downloader.get_probe_progress(pid)

        size_map = self.downloader.get_probe_results(pid, partial=True)
        self._probe_size_map = size_map

        if size_map:
            for item in self.download_list:
                url = item.get("url")
                if not url:
                    continue
                probed = size_map.get(url)
                if probed is not None:
                    item["size_mb"] = probed

        return {
            "status": progress.get("status", "probing"),
            "percent": float(progress.get("progress", 0.0)),
            "done": int(progress.get("done", 0)),
            "total": int(progress.get("total", 0)),
            "error": progress.get("errors"),
        }




    def download_notion_files(self, download_list, save_directory: str):
        """
        启动下载任务（批量）
        """
        self.download_list = download_list

        for file_info in self.download_list:
            url = file_info["url"]
            real_name = file_info["real_name"]
            save_path = f"{save_directory}/{real_name}"
            size_mb = file_info.get("size_mb", 0.0)

            # 假设 downloader.download(url, save_path, size=...)
            self.downloader.download(url, save_path, size=size_mb)

        return "Download tasks started"

    def get_download_statuses(self):
        """
        返回下载状态列表
        """
        statuses = []
        for file_info in self.download_list:
            url = file_info["url"]
            name = file_info.get("name")
            real_name = file_info.get("real_name")

            status_info = self.downloader.get_status(url)  # 以 url 为 key

            statuses.append({
                "url": url,
                "name": name,
                "real_name": real_name,
                "status": status_info.get("status", "not_found"),
                "progress": status_info.get("progress", 0),
                "downloaded_mb": status_info.get("downloaded_mb", 0.0),
                "total_mb": status_info.get("total_mb", 0.0),
                "speed_mb_s": status_info.get("speed_mb_s", 0.0),
                "usedTime": status_info.get("usedTime", 0),
                "ETA": status_info.get("ETA", 0),
                "error": status_info.get("error"),
            })
        return statuses

    # -------------------------
    # Upload
    # -------------------------
    def upload_notion_files(self, page_id: str, files_list: list[str], max_workers: int = 3):
        """
        启动上传任务（批量）
        """
        # 懒初始化 uploader（你也可以挪到 __init__）
        self.Uploader = Upload(
            notion_token=self.notion.token,
            max_workers=max_workers,
            rps=3.0,
            burst=4,
            part_size_bytes=15 * 1024 * 1024,
            debug=True,
        )

        ok, fail = 0, 0
        for file_path in files_list:
            ret = self.Uploader.upload_file(file_path, page_id)

            if isinstance(ret, dict) and ret.get("msg") in {"任务已入队", "任务已提交"}:
                ok += 1
            else:
                fail += 1

        if fail > 0:
            return f"Success {ok}, Failed {fail}"
        return "Success"

    def get_upload_statuses(self):
        """
        返回上传状态列表
        """
        """
        上传状态格式:
        [

            {
                "file_path": "C:/path/to/file.ext",
                "status": "uploading",
                "stage": "uploading",
                "progress": 50.0,
                "uploaded_mb": 1.25,
                "total_mb": 2.5,
                "speed_mb_s": 0.5,
                "usedTime": 10,
                "ETA": 10,
                "error": null
            }
        ]
        """
        if not self.Uploader:
            return []

        get_statuses = self.Uploader.list_status()
        statuses = []
        for status in get_statuses:
            statuses.append({
                "file_path": status.get("file_path"),
                "status": status.get("status"),
                "stage": status.get("stage"),
                "progress": status.get("progress", 0),
                "uploaded_mb": status.get("uploaded_mb", 0.0),
                "total_mb": status.get("total_mb", 0.0),
                "speed_mb_s": status.get("speed_mb_s", 0.0),
                "usedTime": status.get("usedTime", 0),
                "ETA": status.get("ETA", 0),
                "error": status.get("error"),
            })
        return statuses

    def shutdown(self):
        """
        释放资源：线程池/Session
        """
        try:
            self.downloader.shutdown()
        except Exception:
            pass

        if self.Uploader:
            try:
                self.Uploader.shutdown(True)
            except Exception:
                pass


if __name__ == "__main__":
    import os
    import time
    from dotenv import load_dotenv

    load_dotenv()
    token = os.getenv("NOTION_TOKEN", "")
    if not token:
        raise RuntimeError("Please set NOTION_TOKEN env var")

    page_id = "2fc644ea-d11a-8010-9665-e5fbaba0fd58"
    save_dir = r"C:/Ruibin_Ningh/program/Notion-Files-Management/Notion-Files-Management/downloads"

    main = Main(notion_token=token, max_workers=3)

    try:
        # 1) 发起：获取下载列表 + 启动 size 探测
        ret = main.get_download_list(page_id=page_id)
        print("[get_download_list]", ret)

        probe_id = ret.get("probe_id")
        if not probe_id:
            print("没有可探测的 url，直接结束。")
            raise SystemExit(0)

        # 2) 轮询：探测进度（直到 done）
        print("\n=== Probing sizes... ===")
        last_print = 0.0
        while True:
            prog = main.download_list_processing(probe_id)
            # prog: {"status","percent","done","total","error"}

            now = time.time()
            if now - last_print >= 1.0:
                err = prog.get("error") or {}
                err_count = len(err) if isinstance(err, dict) else 0
                print(
                    f"[probe] status={prog['status']} "
                    f"{prog['percent']:.2f}% ({prog['done']}/{prog['total']}) "
                    f"errors={err_count}"
                )
                # 如果想看具体错误（会比较长），取消注释：
                # if err_count:
                #     print("[probe-errors]", err)
                last_print = now

            if prog.get("status") == "done":
                break

            time.sleep(0.2)

        print("=== Probe done. ===\n")

        # 3) 开始下载：注意这里传 main.download_list（列表），不是 ret
        print("=== Starting downloads... ===")
        main.download_notion_files(main.download_list, save_directory=save_dir)

        # 4) 轮询：下载进度
        print("\n=== Downloading... ===")
        while True:
            statuses = main.get_download_statuses()

            # 打印总体汇总
            total = len(statuses)
            done = sum(1 for s in statuses if s.get("status") == "completed")
            errn = sum(1 for s in statuses if s.get("status") == "error")
            downloading = sum(1 for s in statuses if s.get("status") == "downloading")
            waiting = sum(1 for s in statuses if s.get("status") == "waiting")

            print(f"[sum] total={total} waiting={waiting} downloading={downloading} done={done} error={errn}")

            # 打印每个文件的状态（你也可以只打印 downloading 的）
            for s in statuses:
                print(
                    f" - {s.get('real_name') or s.get('name')}: "
                    f"status={s.get('status')} "
                    f"prog={s.get('progress', 0)}% "
                    f"speed={s.get('speed_mb_s', 0)}MB/s "
                    f"ETA={s.get('ETA', 0)}s "
                    f"err={s.get('error')}"
                )

            # 结束条件：全部完成或错误（没有 downloading / waiting）
            if done + errn >= total and total > 0:
                print("\n=== All downloads finished. ===")
                break

            time.sleep(1)

    except KeyboardInterrupt:
        print("KeyboardInterrupt -> shutdown")
    finally:
        main.shutdown()
        print("shutdown")
