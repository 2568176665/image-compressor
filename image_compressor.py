import concurrent.futures
import glob
import logging
import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from imagemagick_manager import EnsureResult, ImageMagickManager


IMAGE_PATTERNS = (
    "*.jpg",
    "*.jpeg",
    "*.png",
    "*.webp",
    "*.JPG",
    "*.JPEG",
    "*.PNG",
    "*.WEBP",
)


class ImageCompressorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片压缩工具")
        self.root.geometry("650x500")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(8, weight=1)

        logging.basicConfig(
            filename="compression.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            encoding="utf-8",
        )

        self.auto_output_var = tk.BooleanVar(value=True)
        self.input_path_var = tk.StringVar(value=os.path.join(".", "input"))
        self.output_path_var = tk.StringVar()
        self.resize_var = tk.StringVar(value="不使用")
        self.format_var = tk.StringVar(value="jpg")
        self.is_compressing = False
        self.is_runtime_ready = False
        self.magick_path = None
        self.imagemagick_manager = ImageMagickManager()

        self.build_ui()
        self.bind_events()
        self.update_output_path_mode()
        self.start_runtime_check()

    def build_ui(self):
        tk.Label(self.root, text="输入路径:").grid(
            row=0, column=0, padx=10, pady=5, sticky="w"
        )
        self.input_entry = tk.Entry(self.root, textvariable=self.input_path_var)
        self.input_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        tk.Button(self.root, text="选择文件", command=self.select_file, width=10).grid(
            row=0, column=2, padx=2, pady=5
        )
        tk.Button(self.root, text="选择文件夹", command=self.select_folder, width=12).grid(
            row=0, column=3, padx=2, pady=5
        )

        tk.Label(self.root, text="输出路径:").grid(
            row=1, column=0, padx=10, pady=5, sticky="w"
        )

        output_row = tk.Frame(self.root)
        output_row.grid(row=1, column=1, columnspan=3, padx=10, pady=5, sticky="ew")
        output_row.grid_columnconfigure(0, weight=1)

        self.output_entry = tk.Entry(output_row, textvariable=self.output_path_var)
        self.output_entry.grid(row=0, column=0, sticky="ew")

        self.auto_output_check = tk.Checkbutton(
            output_row,
            text="自动 output",
            variable=self.auto_output_var,
            command=self.update_output_path_mode,
        )
        self.auto_output_check.grid(row=0, column=1, padx=(8, 8))

        self.output_button = tk.Button(
            output_row,
            text="选择文件夹",
            command=self.select_output_folder,
            width=12,
        )
        self.output_button.grid(row=0, column=2)

        tk.Label(self.root, text="目标大小 (KB):").grid(
            row=2, column=0, padx=10, pady=5, sticky="w"
        )
        self.size_entry = tk.Entry(self.root, width=15)
        self.size_entry.grid(row=2, column=1, padx=10, pady=5, sticky="w")
        self.size_entry.insert(0, "100")

        tk.Label(self.root, text="Resize:").grid(
            row=3, column=0, padx=10, pady=5, sticky="w"
        )
        resize_combo = ttk.Combobox(
            self.root,
            textvariable=self.resize_var,
            values=["不使用", "640x480", "800x600", "1024x768", "1280x720", "1920x1080"],
            state="readonly",
            width=15,
        )
        resize_combo.grid(row=3, column=1, padx=10, pady=5, sticky="w")
        resize_combo.bind("<<ComboboxSelected>>", self.on_resize_preset_selected)

        size_frame = tk.Frame(self.root)
        size_frame.grid(row=3, column=2, columnspan=2, padx=5, pady=5, sticky="w")
        tk.Label(size_frame, text="宽").pack(side="left")
        self.width_entry = tk.Entry(size_frame, width=8)
        self.width_entry.pack(side="left", padx=(2, 10))
        tk.Label(size_frame, text="高").pack(side="left")
        self.height_entry = tk.Entry(size_frame, width=8)
        self.height_entry.pack(side="left", padx=2)

        tk.Label(self.root, text="输出格式:").grid(
            row=4, column=0, padx=10, pady=5, sticky="w"
        )
        format_combo = ttk.Combobox(
            self.root,
            textvariable=self.format_var,
            values=["jpg", "png", "webp"],
            state="readonly",
            width=15,
        )
        format_combo.grid(row=4, column=1, padx=10, pady=5, sticky="w")

        tk.Label(self.root, text="最大线程数:").grid(
            row=4, column=2, padx=10, pady=5, sticky="w"
        )
        self.max_workers_entry = tk.Entry(self.root, width=10)
        self.max_workers_entry.grid(row=4, column=3, padx=10, pady=5, sticky="w")
        self.max_workers_entry.insert(0, "0")

        self.compress_button = tk.Button(
            self.root,
            text="开始压缩",
            command=self.start_compression,
            bg="#4CAF50",
            fg="white",
            height=2,
        )
        self.compress_button.grid(
            row=5, column=0, columnspan=4, pady=15, sticky="ew", padx=10
        )

        self.progress = ttk.Progressbar(
            self.root, orient="horizontal", mode="determinate"
        )
        self.progress.grid(row=6, column=0, columnspan=4, padx=10, pady=5, sticky="ew")

        tk.Label(self.root, text="日志:").grid(row=7, column=0, padx=10, pady=5, sticky="nw")
        self.log_text = tk.Text(self.root, height=8, state="disabled", wrap="word")
        self.log_text.grid(
            row=8, column=0, columnspan=4, padx=10, pady=5, sticky="nsew"
        )

    def bind_events(self):
        self.input_path_var.trace_add("write", self.on_input_path_changed)

    def on_input_path_changed(self, *_args):
        if self.auto_output_var.get():
            self.sync_output_path()

    def update_output_path_mode(self):
        if self.auto_output_var.get():
            self.sync_output_path()
            self.output_entry.config(state="disabled")
            self.output_button.config(state="disabled")
        else:
            self.output_entry.config(state="normal")
            self.output_button.config(state="normal")

    def sync_output_path(self):
        self.output_path_var.set(self.derive_output_path(self.input_path_var.get()))

    def derive_output_path(self, input_path):
        normalized_path = input_path.strip()
        if not normalized_path:
            return os.path.join(".", "output")

        expanded_path = os.path.expanduser(normalized_path)

        if os.path.isfile(expanded_path):
            base_dir = os.path.dirname(expanded_path)
        elif os.path.isdir(expanded_path):
            base_dir = expanded_path
        else:
            _, extension = os.path.splitext(expanded_path)
            if extension.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                base_dir = os.path.dirname(expanded_path) or "."
            else:
                base_dir = expanded_path

        return os.path.join(base_dir, "output")

    def get_resize_value(self):
        width = self.width_entry.get().strip()
        height = self.height_entry.get().strip()
        if width and height:
            return f"{width}x{height}"
        return None

    def on_resize_preset_selected(self, _event):
        preset = self.resize_var.get()
        if preset != "不使用":
            width, height = preset.split("x")
            self.width_entry.delete(0, tk.END)
            self.width_entry.insert(0, width)
            self.height_entry.delete(0, tk.END)
            self.height_entry.insert(0, height)
        else:
            self.width_entry.delete(0, tk.END)
            self.height_entry.delete(0, tk.END)

    def select_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp")]
        )
        if file_path:
            self.input_path_var.set(file_path)

    def select_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.input_path_var.set(folder_path)

    def select_output_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.output_path_var.set(folder_path)

    def start_compression(self):
        if not self.is_runtime_ready or not self.magick_path:
            messagebox.showwarning("提示", "ImageMagick 尚未准备完成，请稍后再试。")
            return

        logging.info("开始压缩任务")
        self.append_log("开始压缩任务")
        input_path = self.input_entry.get().strip()
        output_path = self.output_entry.get().strip()
        target_size_kb = self.size_entry.get().strip()
        output_format = self.format_var.get()
        resize_value = self.get_resize_value()

        max_workers_str = self.max_workers_entry.get().strip()
        if max_workers_str and max_workers_str != "0":
            try:
                max_workers = int(max_workers_str)
            except ValueError:
                max_workers = os.cpu_count()
        else:
            max_workers = os.cpu_count()

        if not input_path or not output_path or not target_size_kb:
            messagebox.showerror("错误", "请填写所有字段")
            return

        try:
            target_size = int(target_size_kb) * 1024
        except ValueError:
            messagebox.showerror("错误", "目标大小必须是数字")
            return

        image_files = self.collect_image_files(input_path)
        if image_files is None:
            messagebox.showerror("错误", "输入路径无效")
            return

        if not image_files:
            messagebox.showerror("错误", "未找到图片文件")
            return

        if not os.path.exists(output_path):
            os.makedirs(output_path)

        self.progress["maximum"] = len(image_files)
        self.progress["value"] = 0
        self.compress_button.config(state="disabled")
        self.is_compressing = True

        threading.Thread(
            target=self.run_tasks,
            args=(
                image_files,
                output_path,
                target_size,
                output_format,
                resize_value,
                max_workers,
            ),
        ).start()

    def collect_image_files(self, input_path):
        if os.path.isfile(input_path):
            return [input_path]

        if os.path.isdir(input_path):
            image_files = []
            for pattern in IMAGE_PATTERNS:
                image_files.extend(glob.glob(os.path.join(input_path, pattern)))
            return sorted(set(image_files))

        return None

    def start_runtime_check(self):
        existing_path = self.imagemagick_manager.get_magick_path()
        self.magick_path = None
        self.is_runtime_ready = False
        self.compress_button.config(state="disabled")

        if existing_path:
            self.append_log("已找到可用的 ImageMagick，后台检查更新中。")
        else:
            self.append_log("未检测到可用的 ImageMagick，开始后台准备依赖。")

        threading.Thread(target=self.run_runtime_check, daemon=True).start()

    def run_runtime_check(self):
        try:
            result = self.imagemagick_manager.ensure_imagemagick_ready(
                status_callback=self.handle_runtime_status,
            )
        except Exception as error:  # pragma: no cover - defensive fallback
            fallback_path = self.imagemagick_manager.get_magick_path()
            result = EnsureResult(
                magick_path=fallback_path,
                version=None,
                source="unknown" if fallback_path else "none",
                updated=False,
                ready=fallback_path is not None,
                message=f"准备 ImageMagick 时出现未处理错误: {error}",
                fatal=fallback_path is None,
            )
        self.root.after(0, self.finish_runtime_check, result)

    def handle_runtime_status(self, message):
        logging.info(message)
        self.root.after(0, self.append_log, message)

    def finish_runtime_check(self, result):
        self.magick_path = result.magick_path
        self.is_runtime_ready = result.ready and result.magick_path is not None
        self.append_log(result.message)

        if self.is_runtime_ready and not self.is_compressing:
            self.compress_button.config(state="normal")
        else:
            self.compress_button.config(state="disabled")

        if result.fatal:
            messagebox.showerror("错误", result.message)

    def run_tasks(
        self,
        image_files,
        output_path,
        target_size,
        output_format,
        resize_value,
        max_workers,
    ):
        logging.info("开始处理 %s 个文件", len(image_files))
        completed = 0
        total = len(image_files)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self.compress_single,
                    image_file,
                    output_path,
                    target_size,
                    output_format,
                    resize_value,
                )
                for image_file in image_files
            ]

            for future in concurrent.futures.as_completed(futures):
                completed += 1
                try:
                    result = future.result()
                    self.root.after(0, self.update_status, completed, total, result)
                except Exception as error:
                    logging.error("任务错误: %s", error)

        self.root.after(0, self.finish_compression)

    def update_status(self, completed, total, message):
        self.progress["value"] = completed
        self.append_log(f"进度: {completed}/{total} - {message}")

    def append_log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.config(state="disabled")
        self.log_text.see(tk.END)

    def finish_compression(self):
        self.is_compressing = False
        logging.info("所有图片处理完成")
        self.append_log("所有图片处理完成")
        self.compress_button.config(state="normal" if self.is_runtime_ready else "disabled")

    def on_close(self):
        if self.is_compressing:
            messagebox.showwarning(
                "提示", "正在压缩图片，请等待任务完成后再关闭窗口。"
            )
            return
        self.root.destroy()

    def compress_single(
        self, input_file, output_dir, target_size, output_format, resize_value
    ):
        logging.info("开始压缩文件: %s", input_file)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(output_dir, f"{base_name}.{output_format}")
        magick_path = self.magick_path or self.imagemagick_manager.get_magick_path()
        if not magick_path:
            warning_message = "ImageMagick 不可用，无法执行压缩。"
            logging.error(warning_message)
            self.root.after(0, self.append_log, warning_message)
            return f"失败: {base_name} (缺少 ImageMagick)"

        if output_format in ["jpg", "jpeg"]:
            target_kb = target_size // 1024
            cmd = [magick_path, input_file]
            if resize_value:
                cmd.extend(["-resize", resize_value])
            cmd.extend(["-strip", "-define", f"jpeg:extent={target_kb}kb", output_file])
            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if os.path.exists(output_file):
                    actual_size = os.path.getsize(output_file)
                    if actual_size <= target_size:
                        return f"成功: {base_name}"
                    os.remove(output_file)
            except Exception as error:
                logging.error("JPG 极速压缩失败: %s, 错误: %s", input_file, error)

        original_size = os.path.getsize(input_file)
        ratio = target_size / original_size
        if ratio >= 0.8:
            current_quality = 95
        elif ratio >= 0.5:
            current_quality = 80
        elif ratio >= 0.2:
            current_quality = 60
        else:
            current_quality = 40

        low, high = 0, 100
        best_quality = 0

        for _ in range(6):
            cmd = [magick_path, input_file]
            if resize_value:
                cmd.extend(["-resize", resize_value])
            cmd.append("-strip")

            if output_format == "png":
                compression = max(0, min(9, int(9 * (100 - current_quality) / 100)))
                cmd.extend(["-quality", str(compression)])
            else:
                cmd.extend(["-quality", str(current_quality)])

            cmd.append(output_file)

            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                size = os.path.getsize(output_file)

                if size <= target_size:
                    best_quality = current_quality
                    low = current_quality + 1
                else:
                    high = current_quality - 1

                current_quality = (low + high) // 2
                if low > high:
                    break
            except Exception as error:
                logging.error("质量调整失败: %s, 错误: %s", input_file, error)
                break

        if best_quality == 0:
            warning_message = (
                f"警告: {base_name} - 质量已降至最低，无法达到目标大小"
            )
            logging.warning(warning_message)
            self.root.after(0, self.append_log, warning_message)
            return f"失败: {base_name} (无法达到目标)"

        cmd = [magick_path, input_file]
        if resize_value:
            cmd.extend(["-resize", resize_value])
        cmd.append("-strip")

        if output_format == "png":
            compression = max(0, min(9, int(9 * (100 - best_quality) / 100)))
            cmd.extend(["-quality", str(compression)])
        else:
            cmd.extend(["-quality", str(best_quality)])

        cmd.append(output_file)

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as error:
            logging.error("最终生成失败: %s, 错误: %s", input_file, error)
            return f"失败: {base_name} (最终生成失败)"

        result = f"完成: {base_name}"
        logging.info(result)
        return result


if __name__ == "__main__":
    root = tk.Tk()
    app = ImageCompressorApp(root)
    root.mainloop()
